# Pharma Sales Territory Analytics Pipeline

End-to-end Python + SQLite ETL pipeline that cleans and consolidates multi-region pharma sales data,
plus an interactive Streamlit dashboard for territory-level performance tracking and comparison.

**Stack:** Python, pandas, SQLite, Streamlit

## Architecture

    data/raw/*.csv  ──►  src/etl.py  ──►  data/db/pharma.db  ──►  app.py (Streamlit)
    (4 regional sales        extract → transform → load          filters, KPIs, ranking,
     files, 2 schemas,       (validation, dedup, reject log)      trends, comparison, DQ tab
     masters, targets)

Warehouse (star schema): `dim_territory`, `dim_product`, `fact_sales`, `fact_target`,
`rejected_rows`, `etl_run`, and view `v_territory_monthly`.

## Run

    pip install -r requirements.txt
    python src/generate_data.py    # synthetic raw data with injected quality issues
    python src/etl.py              # builds data/db/pharma.db
    streamlit run app.py
    pytest

## ETL rules
- Two regional schemas (different headers, ISO vs dd/mm/yyyy dates) mapped to one schema
- Territory / product codes trimmed and upper-cased
- Rejected (and logged with a reason): duplicate txn_id, unparseable date, missing or
  non-positive units, unknown territory, unknown product
- Revenue = units × product unit price; rebuilt from scratch on every run (idempotent)

## Dashboard
Filters (month range, region, therapeutic area) · KPIs incl. target attainment · territory
leaderboard · regional/product trends & MoM growth · side-by-side territory comparison ·
data-quality tab showing rows read / loaded / rejected.

## Swapping in real data
Replace files in `data/raw/` keeping the column names above, then re-run `etl.py`.
