"""صفحه‌ی تارگت‌گذاری خودکار."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from components.rtl import page_setup  # noqa: E402
from components.state import get_bundle  # noqa: E402
from mktcore.config import get_settings  # noqa: E402
from mktcore.locale_fa import format_number_fa  # noqa: E402

page_setup("تارگت‌گذاری", "🎯")
st.title("🎯 تارگت‌گذاری خودکار فروش")

cur = get_settings().mkt_currency
col_a, col_b = st.columns(2)
horizon = col_a.slider("افق تارگت (ماه):", 3, 18, 6)
uplift = col_b.slider("رشد سناریوی متعادل (٪):", 0, 50, 10) / 100

bundle = get_bundle(horizon=horizon, balanced_uplift=uplift)
tp = bundle.targets
if tp is None:
    st.warning("داده برای تارگت‌گذاری کافی نیست.")
    st.stop()

st.metric("مجموع پیش‌بینی پایه", f"{format_number_fa(tp.forecast_total)} {cur}")

cols = st.columns(len(tp.scenarios))
for col, sc in zip(cols, tp.scenarios.values(), strict=True):
    col.metric(
        f"سناریوی {sc.name_fa}",
        f"{format_number_fa(sc.total)} {cur}",
        delta=f"{sc.uplift_vs_forecast*100:.1f}٪ نسبت به پیش‌بینی",
    )

st.divider()
for sc in tp.scenarios.values():
    with st.expander(f"جزئیات سناریوی {sc.name_fa}"):
        st.write(sc.rationale)
        tbl = pd.DataFrame({"دوره": list(sc.per_period.keys()),
                            "هدف": list(sc.per_period.values())})
        st.dataframe(tbl, use_container_width=True, hide_index=True)

st.success(f"سناریوی پیشنهادی پیش‌فرض: **{tp.scenarios[tp.recommended].name_fa}** "
           "(در صفحه‌ی استراتژی، مدل با دلیل سناریوی نهایی را توصیه می‌کند).")
