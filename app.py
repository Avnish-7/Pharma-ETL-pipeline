"""Streamlit dashboard. Run:  streamlit run app.py   (after python src/etl.py)"""
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

DB_PATH = Path(__file__).parent / "data" / "db" / "pharma.db"

st.set_page_config(page_title="Pharma Territory Analytics", layout="wide")


@st.cache_data
def query(sql: str, params: tuple = ()) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql_query(sql, conn, params=params)


if not DB_PATH.exists():
    st.error("Warehouse not found. Run `python src/generate_data.py` then `python src/etl.py` first.")
    st.stop()

# ---------- Sidebar filters ----------
st.sidebar.header("Filters")
months = query("SELECT DISTINCT month FROM fact_sales ORDER BY month")["month"].tolist()
start, end = st.sidebar.select_slider("Month range", options=months, value=(months[0], months[-1]))
regions = query("SELECT DISTINCT region FROM dim_territory ORDER BY region")["region"].tolist()
sel_regions = st.sidebar.multiselect("Region", regions, default=regions)
areas = query("SELECT DISTINCT therapeutic_area FROM dim_product ORDER BY 1")["therapeutic_area"].tolist()
sel_areas = st.sidebar.multiselect("Therapeutic area", areas, default=areas)

if not sel_regions or not sel_areas:
    st.warning("Select at least one region and one therapeutic area.")
    st.stop()

# Product filter needs line-level data, so aggregate from fact_sales directly
ph_r = ",".join("?" * len(sel_regions))
ph_a = ",".join("?" * len(sel_areas))
df = query(
    f"""
    SELECT t.territory_id, t.territory_name, t.region, t.rep_name, s.month, p.therapeutic_area,
           p.product_name, SUM(s.units) AS units, SUM(s.revenue) AS revenue
    FROM fact_sales s
    JOIN dim_territory t ON t.territory_id = s.territory_id
    JOIN dim_product p   ON p.product_id   = s.product_id
    WHERE s.month BETWEEN ? AND ? AND t.region IN ({ph_r}) AND p.therapeutic_area IN ({ph_a})
    GROUP BY t.territory_id, s.month, p.product_id
    """,
    (start, end, *sel_regions, *sel_areas),
)
targets = query(
    f"""SELECT g.territory_id, g.month, g.target_revenue FROM fact_target g
        JOIN dim_territory t ON t.territory_id = g.territory_id
        WHERE g.month BETWEEN ? AND ? AND t.region IN ({ph_r})""",
    (start, end, *sel_regions),
)

st.title("Pharma Sales Territory Analytics")
if df.empty:
    st.info("No data for the selected filters.")
    st.stop()

# ---------- KPIs ----------
total_rev, total_units = df["revenue"].sum(), df["units"].sum()
# Target is set at territory-month level (all products), so attainment is only meaningful
# when every therapeutic area is selected.
all_areas = set(sel_areas) == set(areas)
total_target = targets["target_revenue"].sum()
c1, c2, c3, c4 = st.columns(4)
c1.metric("Revenue", f"₹{total_rev:,.0f}")
c2.metric("Units sold", f"{total_units:,.0f}")
c3.metric("Active territories", df["territory_id"].nunique())
c4.metric("Target attainment", f"{total_rev / total_target:.1%}" if all_areas and total_target else "n/a",
          help="Shown only when all therapeutic areas are selected (targets are territory-level).")

# ---------- Tabs ----------
tab_rank, tab_trend, tab_compare, tab_quality = st.tabs(
    ["Territory ranking", "Trends", "Compare territories", "Data quality"])

by_terr = df.groupby(["territory_id", "territory_name", "region", "rep_name"], as_index=False)[
    ["revenue", "units"]].sum()
if all_areas:
    by_terr = by_terr.merge(
        targets.groupby("territory_id", as_index=False)["target_revenue"].sum(), on="territory_id", how="left")
    by_terr["attainment_%"] = (by_terr["revenue"] / by_terr["target_revenue"] * 100).round(1)
by_terr = by_terr.sort_values("revenue", ascending=False)

with tab_rank:
    left, right = st.columns([3, 2])
    left.subheader("Revenue by territory")
    left.bar_chart(by_terr.set_index("territory_name")["revenue"])
    right.subheader("Leaderboard")
    right.dataframe(by_terr.drop(columns=["territory_id"]), hide_index=True, width="stretch")
    st.subheader("Revenue by region")
    st.bar_chart(df.groupby("region")["revenue"].sum())

with tab_trend:
    monthly = df.groupby(["month", "region"], as_index=False)["revenue"].sum().pivot(
        index="month", columns="region", values="revenue")
    st.subheader("Monthly revenue by region")
    st.line_chart(monthly)
    total_m = df.groupby("month")["revenue"].sum()
    mom = (total_m.pct_change() * 100).round(1).rename("MoM growth %")
    st.subheader("Month-over-month growth")
    st.bar_chart(mom.dropna())
    st.subheader("Revenue by product")
    st.bar_chart(df.groupby("product_name")["revenue"].sum().sort_values(ascending=False))

with tab_compare:
    names = by_terr["territory_name"].tolist()
    picks = st.multiselect("Pick 2-4 territories", names, default=names[:2], max_selections=4)
    if len(picks) < 2:
        st.info("Select at least two territories to compare.")
    else:
        sub = df[df["territory_name"].isin(picks)]
        st.line_chart(sub.groupby(["month", "territory_name"])["revenue"].sum().unstack())
        summary = by_terr[by_terr["territory_name"].isin(picks)].set_index("territory_name").drop(
            columns=["territory_id"])
        st.dataframe(summary, width="stretch")
        mix = sub.groupby(["territory_name", "therapeutic_area"])["revenue"].sum().unstack(fill_value=0)
        st.subheader("Therapeutic-area mix")
        st.bar_chart(mix)

with tab_quality:
    run = query("SELECT * FROM etl_run ORDER BY run_at DESC LIMIT 1")
    if not run.empty:
        r = run.iloc[0]
        q1, q2, q3 = st.columns(3)
        q1.metric("Rows read", f"{r.rows_read:,}")
        q2.metric("Rows loaded", f"{r.rows_loaded:,}")
        q3.metric("Rows rejected", f"{r.rows_rejected:,}")
    st.subheader("Rejections by reason")
    st.dataframe(query("SELECT reason, COUNT(*) AS rows FROM rejected_rows GROUP BY reason ORDER BY rows DESC"),
                 hide_index=True)
