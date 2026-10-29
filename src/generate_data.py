"""Generate messy, multi-source pharma sales data so the ETL has real work to do.

Run:  python src/generate_data.py
Writes CSVs into data/raw/. Deterministic (fixed seed).
"""
from pathlib import Path

import numpy as np
import pandas as pd

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"
rng = np.random.default_rng(42)

TERRITORIES = [
    ("N01", "Delhi Central", "North", "Rohit Verma"),
    ("N02", "Chandigarh", "North", "Neha Kapoor"),
    ("N03", "Lucknow", "North", "Amit Tiwari"),
    ("S01", "Chennai", "South", "Karthik Raman"),
    ("S02", "Bengaluru", "South", "Divya Nair"),
    ("S03", "Hyderabad", "South", "Suresh Reddy"),
    ("E01", "Kolkata", "East", "Subhajit Das"),
    ("E02", "Bhubaneswar", "East", "Priya Mohanty"),
    ("E03", "Guwahati", "East", "Rahul Bora"),
    ("W01", "Mumbai", "West", "Sneha Kulkarni"),
    ("W02", "Pune", "West", "Aditya Joshi"),
    ("W03", "Ahmedabad", "West", "Hardik Patel"),
]

PRODUCTS = [
    ("P01", "CardioSafe 10mg", "Cardiology", 120.0),
    ("P02", "GlucoBal 500mg", "Diabetes", 85.0),
    ("P03", "NeuroCalm 25mg", "Neurology", 210.0),
    ("P04", "RespiClear Inhaler", "Respiratory", 340.0),
    ("P05", "OncoGuard 50mg", "Oncology", 980.0),
    ("P06", "DermaSoothe Cream", "Dermatology", 150.0),
]

MONTHS = pd.period_range("2024-01", "2025-12", freq="M")
# Region-level seasonality / growth so the dashboard shows real patterns
REGION_GROWTH = {"North": 0.012, "South": 0.020, "East": 0.006, "West": 0.015}
TERRITORY_SIZE = {t[0]: rng.uniform(0.6, 1.5) for t in TERRITORIES}


def build_sales() -> pd.DataFrame:
    rows, txn = [], 1
    for tid, _, region, _ in TERRITORIES:
        for pid, _, _, _ in PRODUCTS:
            base = rng.uniform(40, 160) * TERRITORY_SIZE[tid]
            for i, m in enumerate(MONTHS):
                season = 1 + 0.15 * np.sin(2 * np.pi * (m.month - 1) / 12)
                trend = (1 + REGION_GROWTH[region]) ** i
                for _ in range(rng.integers(1, 4)):
                    day = int(rng.integers(1, 28))
                    units = max(1, int(rng.normal(base * season * trend / 2, base / 8)))
                    rows.append((f"T{txn:06d}", m.to_timestamp().replace(day=day), tid, pid, units))
                    txn += 1
    return pd.DataFrame(rows, columns=["txn_id", "sale_date", "territory_id", "product_id", "units"])


def inject_dirt(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    n = len(df)
    # nulls and negatives in units
    df.loc[rng.choice(n, int(n * 0.010), replace=False), "units"] = np.nan
    df.loc[rng.choice(n, int(n * 0.005), replace=False), "units"] = -5
    df["territory_id"] = df["territory_id"].astype(object)
    # inconsistent territory formatting
    idx = rng.choice(n, int(n * 0.015), replace=False)
    df.loc[idx, "territory_id"] = df.loc[idx, "territory_id"].str.lower().map(lambda s: f" {s} ")
    # unknown territory codes
    df.loc[rng.choice(n, int(n * 0.005), replace=False), "territory_id"] = "X99"
    # exact duplicate rows
    df = pd.concat([df, df.sample(int(n * 0.02), random_state=1)], ignore_index=True)
    return df.sample(frac=1, random_state=7).reset_index(drop=True)


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    sales = inject_dirt(build_sales())
    regions = {t[0]: t[2] for t in TERRITORIES}
    clean_key = sales["territory_id"].astype(str).str.strip().str.upper()
    sales["_region"] = clean_key.map(regions).fillna("North")  # X99 lands in North file

    for region, part in sales.groupby("_region"):
        part = part.drop(columns="_region")
        if region in ("North", "East"):  # Schema A: ISO dates, snake_case headers
            part = part.assign(sale_date=part["sale_date"].dt.strftime("%Y-%m-%d"))
        else:  # Schema B: dd/mm/yyyy dates, different column names
            part = part.assign(sale_date=part["sale_date"].dt.strftime("%d/%m/%Y"))
            part = part.rename(columns={
                "txn_id": "TransactionID", "sale_date": "SaleDate",
                "territory_id": "Territory", "product_id": "ProductCode", "units": "Qty",
            })
        part.to_csv(RAW / f"sales_{region.lower()}.csv", index=False)

    pd.DataFrame(TERRITORIES, columns=["territory_id", "territory_name", "region", "rep_name"]) \
        .to_csv(RAW / "territories.csv", index=False)
    pd.DataFrame(PRODUCTS, columns=["product_id", "product_name", "therapeutic_area", "unit_price"]) \
        .to_csv(RAW / "products.csv", index=False)

    # Monthly revenue targets per territory (roughly 5% above a noisy baseline)
    rev = build_sales().merge(pd.DataFrame(PRODUCTS, columns=["product_id", "n", "a", "unit_price"]), on="product_id")
    rev["revenue"] = rev["units"] * rev["unit_price"]
    rev["month"] = rev["sale_date"].dt.to_period("M").dt.to_timestamp()
    tgt = rev.groupby(["territory_id", "month"], as_index=False)["revenue"].sum()
    tgt["target_revenue"] = (tgt["revenue"] * rng.uniform(0.92, 1.12, len(tgt))).round(0)
    tgt["month"] = tgt["month"].dt.strftime("%Y-%m")
    tgt[["territory_id", "month", "target_revenue"]].to_csv(RAW / "targets.csv", index=False)
    print(f"Wrote raw files to {RAW}")


if __name__ == "__main__":
    main()
