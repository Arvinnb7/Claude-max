"""صفحه‌ی نمای کلی شاخص‌های کلیدی عملکرد."""

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

page_setup("شاخص‌های کلیدی", "📈")
st.title("📈 شاخص‌های کلیدی عملکرد")

cur = get_settings().mkt_currency
bundle = get_bundle()
k = bundle.kpis


def _pct(v):
    return "—" if v is None else f"{v*100:.1f}٪"


c1, c2, c3, c4 = st.columns(4)
c1.metric("درآمد کل", f"{format_number_fa(k.total_revenue)} {cur}")
c2.metric("تعداد سفارش", format_number_fa(k.n_orders))
c3.metric("تعداد مشتری", format_number_fa(k.n_customers))
c4.metric("میانگین ارزش سفارش", f"{format_number_fa(k.aov)} {cur}")

c5, c6, c7, c8 = st.columns(4)
c5.metric("رشد ماهانه", _pct(k.mom_growth))
c6.metric("رشد سالانه", _pct(k.yoy_growth))
c7.metric("نرخ مشتری تکراری", _pct(k.repeat_rate))
c8.metric("حاشیه‌ی سود ناخالص", _pct(k.gross_margin))

for flag in k.flags:
    st.info(flag)

st.divider()

t = bundle.trends
if not t.daily.empty:
    st.plotly_chart(charts.revenue_trend(t.daily, t.moving_avg_30), use_container_width=True)
if not t.monthly.empty:
    st.plotly_chart(charts.monthly_bar(t.monthly), use_container_width=True)

# فصلی‌بودن
seas = bundle.seasonality
if seas.weekday_index:
    st.subheader("الگوی فصلی")
    peak = max(seas.weekday_index, key=seas.weekday_index.get)
    st.write(f"قوی‌ترین روز هفته از نظر فروش: **{peak}**")
    if seas.seasonality_strength is not None:
        st.write(f"قدرت فصلی‌بودن: **{seas.seasonality_strength:.2f}** (۰ تا ۱)")
