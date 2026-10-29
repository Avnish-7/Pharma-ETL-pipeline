"""ETL: raw CSVs -> cleaned SQLite warehouse.

Run:  python src/etl.py
Reads data/raw/*.csv, writes data/db/pharma.db (rebuilt on every run, so it is idempotent).
"""
import logging
import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
DB_PATH = ROOT / "data" / "db" / "pharma.db"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("etl")

# Different regional systems use different headers -> map everything to one schema
COLUMN_MAP = {
    "TransactionID": "txn_id", "SaleDate": "sale_date", "Territory": "territory_id",
    "ProductCode": "product_id", "Qty": "units",
}

SCHEMA = """
DROP VIEW  IF EXISTS v_territory_monthly;
DROP TABLE IF EXISTS fact_sales;
DROP TABLE IF EXISTS fact_target;
DROP TABLE IF EXISTS dim_territory;
DROP TABLE IF EXISTS dim_product;
DROP TABLE IF EXISTS rejected_rows;
DROP TABLE IF EXISTS etl_run;

CREATE TABLE dim_territory (
    territory_id TEXT PRIMARY KEY, territory_name TEXT NOT NULL,
    region TEXT NOT NULL, rep_name TEXT
);
CREATE TABLE dim_product (
    product_id TEXT PRIMARY KEY, product_name TEXT NOT NULL,
    therapeutic_area TEXT, unit_price REAL NOT NULL
);
CREATE TABLE fact_sales (
    txn_id TEXT PRIMARY KEY, sale_date TEXT NOT NULL, month TEXT NOT NULL,
    territory_id TEXT NOT NULL REFERENCES dim_territory(territory_id),
    product_id   TEXT NOT NULL REFERENCES dim_product(product_id),
    units INTEGER NOT NULL CHECK (units > 0), revenue REAL NOT NULL
);
CREATE TABLE fact_target (
    territory_id TEXT NOT NULL REFERENCES dim_territory(territory_id),
    month TEXT NOT NULL, target_revenue REAL NOT NULL,
    PRIMARY KEY (territory_id, month)
);
CREATE TABLE rejected_rows (source_file TEXT, txn_id TEXT, reason TEXT);
CREATE TABLE etl_run (run_at TEXT, rows_read INTEGER, rows_loaded INTEGER, rows_rejected INTEGER);

CREATE INDEX idx_sales_terr_month ON fact_sales(territory_id, month);

CREATE VIEW v_territory_monthly AS
SELECT t.territory_id, t.territory_name, t.region, t.rep_name, s.month,
       SUM(s.revenue) AS revenue, SUM(s.units) AS units,
       COALESCE(g.target_revenue, 0) AS target_revenue
FROM fact_sales s
JOIN dim_territory t ON t.territory_id = s.territory_id
LEFT JOIN fact_target g ON g.territory_id = s.territory_id AND g.month = s.month
GROUP BY t.territory_id, s.month;
"""


# ---------- Extract ----------
def extract_sales() -> pd.DataFrame:
    frames = []
    for path in sorted(RAW.glob("sales_*.csv")):
        df = pd.read_csv(path, dtype=str).rename(columns=COLUMN_MAP)
        df["source_file"] = path.name
        frames.append(df)
        log.info("extracted %-18s %6d rows", path.name, len(df))
    return pd.concat(frames, ignore_index=True)


# ---------- Transform ----------
def parse_dates(s: pd.Series) -> pd.Series:
    """Source systems mix ISO (yyyy-mm-dd) and dd/mm/yyyy. Try both explicitly."""
    iso = pd.to_datetime(s, format="%Y-%m-%d", errors="coerce")
    dmy = pd.to_datetime(s, format="%d/%m/%Y", errors="coerce")
    return iso.fillna(dmy)


def transform_sales(df: pd.DataFrame, valid_territories: set, valid_products: set, prices: dict):
    rejected = []

    def reject(mask, reason):
        if mask.any():
            rejected.append(df.loc[mask, ["source_file", "txn_id"]].assign(reason=reason))
        return df[~mask]

    df = df.copy()
    df["territory_id"] = df["territory_id"].str.strip().str.upper()
    df["product_id"] = df["product_id"].str.strip().str.upper()
    df["sale_date"] = parse_dates(df["sale_date"])
    df["units"] = pd.to_numeric(df["units"], errors="coerce")

    df = reject(df.duplicated(subset=["txn_id"], keep="first"), "duplicate txn_id")
    df = reject(df["sale_date"].isna(), "unparseable date")
    df = reject(df["units"].isna(), "missing units")
    df = reject(df["units"] <= 0, "non-positive units")
    df = reject(~df["territory_id"].isin(valid_territories), "unknown territory")
    df = reject(~df["product_id"].isin(valid_products), "unknown product")

    df["units"] = df["units"].astype(int)
    df["revenue"] = df["units"] * df["product_id"].map(prices)
    df["month"] = df["sale_date"].dt.strftime("%Y-%m")
    df["sale_date"] = df["sale_date"].dt.strftime("%Y-%m-%d")
    rej = pd.concat(rejected, ignore_index=True) if rejected else pd.DataFrame(
        columns=["source_file", "txn_id", "reason"])
    return df[["txn_id", "sale_date", "month", "territory_id", "product_id", "units", "revenue"]], rej


# ---------- Load ----------
def run() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    territories = pd.read_csv(RAW / "territories.csv")
    products = pd.read_csv(RAW / "products.csv")
    targets = pd.read_csv(RAW / "targets.csv")

    raw_sales = extract_sales()
    clean, rejected = transform_sales(
        raw_sales,
        set(territories["territory_id"]),
        set(products["product_id"]),
        dict(zip(products["product_id"], products["unit_price"])),
    )
    log.info("transform: %d kept, %d rejected", len(clean), len(rejected))
    if len(rejected):
        log.info("rejections by reason:\n%s", rejected["reason"].value_counts().to_string())

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(SCHEMA)
        territories.to_sql("dim_territory", conn, if_exists="append", index=False)
        products.to_sql("dim_product", conn, if_exists="append", index=False)
        clean.to_sql("fact_sales", conn, if_exists="append", index=False)
        targets.to_sql("fact_target", conn, if_exists="append", index=False)
        rejected.to_sql("rejected_rows", conn, if_exists="append", index=False)
        conn.execute(
            "INSERT INTO etl_run VALUES (datetime('now'), ?, ?, ?)",
            (len(raw_sales), len(clean), len(rejected)),
        )
    log.info("loaded warehouse -> %s", DB_PATH)


if __name__ == "__main__":
    run()
