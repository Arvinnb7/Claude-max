"""مدیریت وضعیت مشترک بین صفحات Streamlit."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st


def get(key: str, default: Any = None) -> Any:
    return st.session_state.get(key, default)


def set_value(key: str, value: Any) -> None:
    st.session_state[key] = value


def has_clean_data() -> bool:
    df = st.session_state.get("clean_df")
    return isinstance(df, pd.DataFrame) and not df.empty


def require_data() -> pd.DataFrame:
    """بازگرداندن داده‌ی پاک‌شده یا نمایش راهنما و توقف صفحه."""
    if not has_clean_data():
        st.warning("ابتدا در صفحه‌ی «خانه» داده را بارگذاری و نگاشت کنید.")
        st.stop()
    return st.session_state["clean_df"]


@st.cache_data(show_spinner="در حال اجرای تحلیل…")
def cached_analysis(df_token: str, horizon: int, balanced_uplift: float):
    """اجرای تحلیل با کش بر اساس امضای داده (df_token) و پارامترها."""
    from mktcore.pipeline import run_analysis

    df = st.session_state["clean_df"]
    return run_analysis(df, horizon=horizon, balanced_uplift=balanced_uplift)


def get_bundle(horizon: int = 6, balanced_uplift: float = 0.10):
    """دریافت MetricsBundle با کش؛ امضای داده برای ابطال کش استفاده می‌شود."""
    df = require_data()
    token = st.session_state.get("data_token", str(len(df)))
    return cached_analysis(token, horizon, balanced_uplift)
