"""تزریق استایل RTL و فونت فارسی به صفحات Streamlit."""

from __future__ import annotations

import streamlit as st

_RTL_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;600;700&display=swap');

html, body, [class*="css"], .stApp, .stMarkdown, .stDataFrame, button, input, textarea, select {
    font-family: 'Vazirmatn', Tahoma, sans-serif !important;
}
.stApp { direction: rtl; }
section.main > div { direction: rtl; text-align: right; }
h1, h2, h3, h4, h5, p, label, span, div { direction: rtl; }
[data-testid="stMetricValue"], [data-testid="stMetricLabel"] { direction: rtl; text-align: right; }
[data-testid="stSidebar"] { direction: rtl; text-align: right; }
.stDataFrame { direction: rtl; }
table { direction: rtl; }
</style>
"""


def apply_rtl() -> None:
    """اعمال جهت راست‌به‌چپ و فونت فارسی روی صفحه‌ی جاری."""
    st.markdown(_RTL_CSS, unsafe_allow_html=True)


def page_setup(title: str, icon: str = "📊") -> None:
    """پیکربندی استاندارد هر صفحه: عنوان، جهت RTL."""
    st.set_page_config(page_title=title, page_icon=icon, layout="wide")
    apply_rtl()
