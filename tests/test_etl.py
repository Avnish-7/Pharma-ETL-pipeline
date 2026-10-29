import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from etl import parse_dates, transform_sales  # noqa: E402

PRICES = {"P01": 100.0}


def _df(rows):
    return pd.DataFrame(rows, columns=["txn_id", "sale_date", "territory_id", "product_id", "units", "source_file"])


def test_parse_dates_handles_both_formats():
    out = parse_dates(pd.Series(["2024-03-05", "05/03/2024", "garbage"]))
    assert out.iloc[0] == out.iloc[1] == pd.Timestamp("2024-03-05")
    assert pd.isna(out.iloc[2])


def test_transform_cleans_and_rejects():
    df = _df([
        ["T1", "2024-01-10", " n01 ", "P01", "5", "a.csv"],   # good, needs normalising
        ["T1", "2024-01-10", "N01", "P01", "5", "a.csv"],     # duplicate txn_id
        ["T2", "2024-01-11", "N01", "P01", "-3", "a.csv"],    # negative units
        ["T3", "2024-01-12", "N01", "P01", None, "a.csv"],    # missing units
        ["T4", "2024-01-13", "X99", "P01", "2", "a.csv"],     # unknown territory
    ])
    clean, rej = transform_sales(df, {"N01"}, {"P01"}, PRICES)
    assert list(clean["txn_id"]) == ["T1"]
    assert clean.iloc[0]["territory_id"] == "N01" and clean.iloc[0]["revenue"] == 500.0
    assert set(rej["reason"]) == {"duplicate txn_id", "non-positive units", "missing units", "unknown territory"}
