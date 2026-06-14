"""فیکسچرهای مشترک تست."""

from __future__ import annotations

import pandas as pd
import pytest

from mktcore.synthetic import generate_synthetic_sales


@pytest.fixture(scope="session")
def raw_sales() -> pd.DataFrame:
    """داده‌ی فروش خام مصنوعی (ستون‌های فارسی)."""
    return generate_synthetic_sales(seed=7, days=540)


@pytest.fixture
def messy_frame() -> pd.DataFrame:
    """داده‌ی کثیف: رقم فارسی، تاریخ جلالی، جداکننده‌ی ارز، تکراری، درآمد گم‌شده."""
    return pd.DataFrame(
        {
            "تاریخ": ["1403/01/05", "1403/01/06", "1403/01/06", "2024-03-28"],
            "شماره سفارش": ["A-1", "A-2", "A-2", "A-3"],
            "کد مشتری": ["C1", "C2", "C2", "C3"],
            "نام محصول": ["الف", "ب", "ب", "ج"],
            "تعداد": ["۲", "۱", "۱", "۳"],
            "قیمت واحد": ["۱٬۲۰۰٬۰۰۰", "۸۰۰,۰۰۰", "۸۰۰,۰۰۰", "۵۰۰۰۰۰"],
            "مبلغ کل": ["۲٬۴۰۰٬۰۰۰", "", "", "۱٬۵۰۰٬۰۰۰"],
        }
    )
