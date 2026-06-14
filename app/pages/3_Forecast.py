"""صفحه‌ی پیش‌بینی فروش."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from components import charts  # noqa: E402
from components.rtl import page_setup  # noqa: E402
from components.state import get_bundle  # noqa: E402
from mktcore.config import get_settings  # noqa: E402
from mktcore.locale_fa import format_number_fa  # noqa: E402

page_setup("پیش‌بینی فروش", "🔮")
st.title("🔮 پیش‌بینی فروش")

cur = get_settings().mkt_currency
horizon = st.slider("افق پیش‌بینی (ماه):", min_value=3, max_value=18, value=6)
bundle = get_bundle(horizon=horizon)
fc = bundle.forecast

if fc is None:
    st.warning("داده برای پیش‌بینی کافی نیست.")
    st.stop()

st.caption(f"مدل انتخاب‌شده: **{fc.model_name}**")
if fc.backtest_metrics:
    cols = st.columns(len(fc.backtest_metrics))
    for col, (name, val) in zip(cols, fc.backtest_metrics.items(), strict=False):
        col.metric(name, f"{val:.1f}" + ("٪" if name == "MAPE" else ""))

st.plotly_chart(
    charts.forecast_chart(fc.history, fc.yhat, fc.lower, fc.upper),
    use_container_width=True,
)

st.metric(f"مجموع پیش‌بینی {fc.horizon} دوره", f"{format_number_fa(fc.total_forecast)} {cur}")

import pandas as pd  # noqa: E402

tbl = pd.DataFrame(
    {
        "دوره": [str(d.date()) for d in fc.yhat.index],
        "پیش‌بینی": fc.yhat.round().astype(int).values,
        "کف اطمینان": fc.lower.round().astype(int).values,
        "سقف اطمینان": fc.upper.round().astype(int).values,
    }
)
st.dataframe(tbl, use_container_width=True, hide_index=True)
