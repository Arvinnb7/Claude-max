"""صفحه‌ی استراتژی مارکتینگ با هوش مصنوعی (Claude)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from components.rtl import page_setup  # noqa: E402
from components.state import get_bundle, set_value  # noqa: E402
from mktcore.ai.client import api_key_available  # noqa: E402
from mktcore.ai.strategist import generate_strategy  # noqa: E402
from mktcore.config import get_settings  # noqa: E402

page_setup("استراتژی هوش مصنوعی", "🧠")
st.title("🧠 استراتژی مارکتینگ (تحلیل مدیر مارکتینگ سنیور)")

settings = get_settings()
horizon = st.slider("افق تحلیل (ماه):", 3, 18, 6)
bundle = get_bundle(horizon=horizon)

if not api_key_available():
    st.error(
        "کلید API انتروپیک تنظیم نشده است. مقدار `ANTHROPIC_API_KEY` را در فایل `.env` "
        "یا متغیر محیطی قرار دهید تا استراتژی هوش مصنوعی تولید شود."
    )
    st.info("بخش‌های تحلیل آماری، پیش‌بینی و تارگت بدون نیاز به کلید کار می‌کنند.")
    st.stop()

st.caption(f"مدل: {settings.mkt_model} — سطح تلاش: {settings.mkt_effort}")

if st.button("✨ تولید استراتژی", type="primary"):
    with st.spinner("مدیر مارکتینگ هوشمند در حال تحلیل داده‌ها و تدوین استراتژی است…"):
        try:
            report = generate_strategy(bundle)
            set_value("strategy_report", report)
        except Exception as e:  # نمایش خطای کاربرپسند
            st.error(f"خطا در تولید استراتژی: {e}")
            st.stop()

report = st.session_state.get("strategy_report")
if report is None:
    st.info("برای دریافت تحلیل و استراتژی، دکمه‌ی «تولید استراتژی» را بزنید.")
    st.stop()

st.subheader("خلاصه‌ی مدیریتی")
st.write(report.executive_summary)

if report.factor_analysis:
    st.subheader("تحلیل عوامل مؤثر بر فروش")
    for f in report.factor_analysis:
        st.markdown(f"**{f.factor}:** {f.finding}  \n_تأثیر: {f.impact}_")

st.subheader("توجیه تارگت")
st.write(report.target_rationale)

if report.recommendations:
    st.subheader("توصیه‌های عملیاتی اولویت‌بندی‌شده")
    rec_tbl = pd.DataFrame(
        [
            {"عنوان": r.title, "اولویت": r.priority, "اثر مورد انتظار": r.expected_impact, "تلاش": r.effort}
            for r in report.recommendations
        ]
    )
    st.dataframe(rec_tbl, use_container_width=True, hide_index=True)
    for r in report.recommendations:
        with st.expander(f"{r.title} (اولویت: {r.priority})"):
            st.write(r.rationale)

if report.risks:
    st.subheader("ریسک‌ها و نکات احتیاطی")
    for risk in report.risks:
        st.write("⚠️", risk)
