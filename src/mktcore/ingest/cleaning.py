"""پاک‌سازی داده‌ی نگاشت‌شده: نوع‌ها، تاریخ‌های ترکیبی/جلالی، ارز، تکراری‌ها."""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from ..locale_fa import normalize_digits
from .schema import ColumnRole, standard_column

_DATE = standard_column(ColumnRole.DATE)
_REVENUE = standard_column(ColumnRole.REVENUE)
_QUANTITY = standard_column(ColumnRole.QUANTITY)
_UNIT_PRICE = standard_column(ColumnRole.UNIT_PRICE)
_COST = standard_column(ColumnRole.COST)
_DISCOUNT = standard_column(ColumnRole.DISCOUNT)
_ORDER_ID = standard_column(ColumnRole.ORDER_ID)

_NUMERIC_COLS = (_REVENUE, _QUANTITY, _UNIT_PRICE, _COST, _DISCOUNT)


def _to_number(value: object) -> float:
    """تبدیل یک مقدار (احتمالاً فارسی/ارزی) به عدد اعشاری یا NaN."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return np.nan
    if isinstance(value, (int, float)):
        return float(value)
    s = normalize_digits(str(value)).strip()
    s = s.replace(",", "")
    s = re.sub(r"[^\d.\-]", "", s)
    if s in ("", "-", ".", "-."):
        return np.nan
    try:
        return float(s)
    except ValueError:
        return np.nan


def _parse_jalali(value: str) -> pd.Timestamp | None:
    """تجزیه‌ی رشته‌ی تاریخ جلالی به Timestamp میلادی."""
    m = re.match(r"^\s*(1[34]\d{2})[/\-.](\d{1,2})[/\-.](\d{1,2})", value)
    if not m:
        return None
    try:
        import jdatetime

        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        g = jdatetime.date(y, mo, d).togregorian()
        return pd.Timestamp(g)
    except Exception:
        return None


def _parse_one_date(value: object) -> pd.Timestamp | None:
    """تجزیه‌ی یک مقدار تاریخ؛ ابتدا جلالی (الگوی 13xx/14xx) سپس میلادی."""
    v = normalize_digits(str(value)).strip()
    if not v:
        return None
    jal = _parse_jalali(v)
    if jal is not None:
        return jal
    ts = pd.to_datetime(v, errors="coerce", dayfirst=False)
    return None if pd.isna(ts) else pd.Timestamp(ts)


def _parse_dates(series: pd.Series) -> pd.Series:
    """تجزیه‌ی ستون تاریخ با پشتیبانی از فرمت‌های ترکیبی، میلادی و جلالی متنی.

    تجزیه عنصر-به-عنصر است تا فرمت‌های متفاوت در یک ستون و تاریخ جلالی
    (که در غیر این صورت ممکن است میلادی تفسیر شود) درست مدیریت شوند.
    """
    return pd.to_datetime(series.map(_parse_one_date), errors="coerce")


def clean_frame(df: pd.DataFrame) -> pd.DataFrame:
    """پاک‌سازی DataFrame استانداردشده.

    - تبدیل ستون‌های عددی (با رقم فارسی و جداکننده)
    - تجزیه‌ی تاریخ (میلادی/جلالی)
    - مشتق REVENUE از QUANTITY×UNIT_PRICE در صورت نبود
    - حذف ردیف‌های بدون تاریخ یا درآمد معتبر
    - حذف سفارش‌های کاملاً تکراری
    """
    out = df.copy()

    # تاریخ
    if _DATE in out.columns:
        out[_DATE] = _parse_dates(out[_DATE])

    # اعداد: تبدیل به عدد و سپس تضمین نوع عددی (جلوگیری از مقایسه‌ی str با int)
    for col in _NUMERIC_COLS:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col].map(_to_number), errors="coerce")

    # مشتق درآمد در صورت نبود مقدار ولی وجود تعداد و قیمت واحد
    if _REVENUE in out.columns and _QUANTITY in out.columns and _UNIT_PRICE in out.columns:
        need = out[_REVENUE].isna() & out[_QUANTITY].notna() & out[_UNIT_PRICE].notna()
        disc = out[_DISCOUNT] if _DISCOUNT in out.columns else 0.0
        out.loc[need, _REVENUE] = (
            out.loc[need, _QUANTITY] * out.loc[need, _UNIT_PRICE] * (1 - (disc if isinstance(disc, float) else out.loc[need, _DISCOUNT].fillna(0)))
        )
    elif _REVENUE not in out.columns and _QUANTITY in out.columns and _UNIT_PRICE in out.columns:
        out[_REVENUE] = out[_QUANTITY] * out[_UNIT_PRICE]

    # حذف ردیف‌های بدون تاریخ یا درآمد معتبر
    before = len(out)
    if _DATE in out.columns:
        out = out[out[_DATE].notna()]
    if _REVENUE in out.columns:
        out = out[out[_REVENUE].notna() & (out[_REVENUE] >= 0)]
    out.attrs["dropped_invalid_rows"] = before - len(out)

    # حذف ردیف‌های کاملاً تکراری (نه بر اساس order_id؛ هر سفارش می‌تواند چند قلم داشته باشد)
    dup_before = len(out)
    out = out.drop_duplicates()
    out.attrs["dropped_duplicate_rows"] = dup_before - len(out)

    out = out.sort_values(_DATE).reset_index(drop=True) if _DATE in out.columns else out.reset_index(drop=True)
    return out


__all__ = ["clean_frame"]
