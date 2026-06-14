"""صفحه‌ی خروجی گزارش: Markdown و PDF فارسی."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from components.rtl import page_setup  # noqa: E402
from components.state import get_bundle  # noqa: E402
from mktcore.reporting.markdown_report import build_markdown  # noqa: E402
from mktcore.reporting.pdf_report import build_pdf, weasyprint_available  # noqa: E402

page_setup("خروجی گزارش", "📄")
st.title("📄 خروجی گزارش")

bundle = get_bundle()
strategy = st.session_state.get("strategy_report")

if strategy is None:
    st.info("برای گنجاندن بخش استراتژی، ابتدا در صفحه‌ی «استراتژی هوش مصنوعی» گزارش را تولید کنید. "
            "گزارش بدون آن هم شامل تحلیل آماری، پیش‌بینی و تارگت خواهد بود.")

md = build_markdown(bundle, strategy)

st.subheader("پیش‌نمایش گزارش")
st.markdown(md)

st.divider()
col1, col2 = st.columns(2)

with col1:
    st.download_button(
        "⬇️ دانلود Markdown",
        data=md.encode("utf-8"),
        file_name="marketing_report.md",
        mime="text/markdown",
    )

with col2:
    if weasyprint_available():
        try:
            pdf_bytes = build_pdf(bundle, strategy)
            st.download_button(
                "⬇️ دانلود PDF",
                data=pdf_bytes,
                file_name="marketing_report.pdf",
                mime="application/pdf",
            )
        except Exception as e:
            st.warning(f"تولید PDF ناموفق بود: {e}")
    else:
        st.caption("برای خروجی PDF، گروه اختیاری نصب شود: `pip install '.[pdf]'` "
                   "و کتابخانه‌های سیستمی pango/cairo.")
