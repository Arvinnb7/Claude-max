"""پاک‌سازی داده‌ی نگاشت‌شده: نوع‌ها، تاریخ‌های ترکیبی/جلالی، ارز، تکراری‌ها."""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from ..locale_fa import normalize_digits
from .schema import SOURCE_ROW, ColumnRole, standard_column

_DATE = standard_column(ColumnRole.DATE)
_REVENUE = standard_column(ColumnRole.REVENUE)
_QUANTITY = standard_column(ColumnRole.QUANTITY)
_UNIT_PRICE = standard_column(ColumnRole.UNIT_PRICE)
_COST = standard_column(ColumnRole.COST)
_DISCOUNT = standard_column(ColumnRole.DISCOUNT)
_ORDER_ID = standard_column(ColumnRole.ORDER_ID)

_NUMERIC_COLS = (_REVENUE, _QUANTITY, _UNIT_PRICE, _COST, _DISCOUNT)
# ستون‌هایی که باید برچسب رشته‌ای یکدست داشته باشند (جلوگیری از مخلوط str/float)
_LABEL_COLS = tuple(
    standard_column(r) for r in (
        ColumnRole.CUSTOMER_ID, ColumnRole.PRODUCT, ColumnRole.ORDER_ID,
        ColumnRole.SALESPERSON, ColumnRole.BRANCH, ColumnRole.CHANNEL,
        ColumnRole.REGION, ColumnRole.CATEGORY, ColumnRole.EMAIL, ColumnRole.PHONE,
    )
)
# ستون‌های مبلغی که ممکن است با «قرارداد علامت منفی» حسابداری ذخیره شده باشند
_SIGN_COLS = (_REVENUE, _UNIT_PRICE, _QUANTITY, _COST)


class SideFrame:
    """پوشش DataFrame برای نگهداری در df.attrs.

    pandas 3 هنگام concat مقادیر attrs را با == مقایسه می‌کند و DataFrame خام
    خطای «truth value ambiguous» می‌دهد؛ این پوشش برابری هویتی دارد.
    """

    __slots__ = ("df",)

    def __init__(self, df: pd.DataFrame) -> None:
        self.df = df

    def __eq__(self, other: object) -> bool:
        return self is other

    def __hash__(self) -> int:
        return id(self)


def get_exclusions(df: pd.DataFrame) -> pd.DataFrame:
    """ردیف‌های حذف‌شده در پاک‌سازی (با ستون «دلیل»)؛ خالی اگر موجود نباشد."""
    side = df.attrs.get("exclusions_df")
    return side.df if isinstance(side, SideFrame) else pd.DataFrame()


def get_returns(df: pd.DataFrame) -> pd.DataFrame:
    """ردیف‌های برگشت از فروش (revenue منفی، جدا از فریم اصلی)؛ خالی اگر نباشد.

    فریم اصلی فقط رویداد خرید مثبت دارد (تحلیل رفتاری روی خرید درست است)؛
    خالص‌سازی مالی در لایه‌ی KPI با همین فریم انجام می‌شود.
    """
    side = df.attrs.get("returns_df")
    return side.df if isinstance(side, SideFrame) else pd.DataFrame()


def _clean_label(x: object) -> object:
    """تبدیل برچسب به رشته‌ی تمیز یا NaN (برای یکدست‌سازی ستون‌های شناسه/متنی)."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return np.nan
    s = str(x).strip()
    if s == "" or s.lower() in ("nan", "none", "null", "<na>"):
        return np.nan
    return s


def _to_number(value: object) -> float:
    """تبدیل یک مقدار (احتمالاً فارسی/ارزی) به عدد اعشاری یا NaN.

    پرانتز حسابداری «(1,250)» طبق قرارداد دفترداری به معنی عدد منفی است.
    """
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return np.nan
    if isinstance(value, (int, float)):
        return float(value)
    s = normalize_digits(str(value)).strip()
    paren_negative = s.startswith("(") and s.endswith(")")
    if paren_negative:
        s = s[1:-1]
    s = s.replace(",", "")
    s = re.sub(r"[^\d.\-]", "", s)
    if s in ("", "-", ".", "-."):
        return np.nan
    try:
        num = float(s)
    except ValueError:
        return np.nan
    return -num if paren_negative and num > 0 else num


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

    # نرمال‌سازی «قرارداد علامت منفی» حسابداری: اگر یک ستون مبلغی عمدتاً منفی باشد
    # (خروجی نرم‌افزارهای حسابداری ایرانی)، علامتش برگردانده می‌شود تا فروش مثبت شود.
    sign_flipped: list[str] = []
    for col in _SIGN_COLS:
        if col in out.columns:
            s = out[col].dropna()
            if len(s) >= 10 and (s < 0).mean() > 0.6:
                out[col] = -out[col]
                sign_flipped.append(col)
    out.attrs["sign_flipped"] = sign_flipped

    # یکدست‌سازی ستون‌های برچسبی به رشته (یا NaN) تا مخلوط str/float رخ ندهد
    for col in _LABEL_COLS:
        if col in out.columns:
            out[col] = out[col].map(_clean_label)

    # مشتق درآمد در صورت نبود مقدار ولی وجود تعداد و قیمت واحد
    if _REVENUE in out.columns and _QUANTITY in out.columns and _UNIT_PRICE in out.columns:
        need = out[_REVENUE].isna() & out[_QUANTITY].notna() & out[_UNIT_PRICE].notna()
        disc = out[_DISCOUNT] if _DISCOUNT in out.columns else 0.0
        out.loc[need, _REVENUE] = (
            out.loc[need, _QUANTITY] * out.loc[need, _UNIT_PRICE] * (1 - (disc if isinstance(disc, float) else out.loc[need, _DISCOUNT].fillna(0)))
        )
    elif _REVENUE not in out.columns and _QUANTITY in out.columns and _UNIT_PRICE in out.columns:
        out[_REVENUE] = out[_QUANTITY] * out[_UNIT_PRICE]

    # حذف ردیف‌های بدون تاریخ یا درآمد معتبر — با ثبت ممیزی (شماره ردیف + دلیل)
    exclusions: list[pd.DataFrame] = []

    def _exclude(mask: pd.Series, reason: str) -> None:
        if mask.any():
            part = out.loc[mask].copy()
            part["دلیل"] = reason
            exclusions.append(part)

    before = len(out)
    if _DATE in out.columns:
        _exclude(out[_DATE].isna(), "تاریخ نامعتبر")
        out = out[out[_DATE].notna()]
    returns = pd.DataFrame(columns=out.columns)
    if _REVENUE in out.columns:
        _exclude(out[_REVENUE].isna(), "مبلغ نامعتبر")
        out = out[out[_REVENUE].notna()]
        # ردیف‌های منفی = برگشت از فروش؛ حذف نمی‌شوند بلکه جدا نگه داشته می‌شوند
        # تا در فروش خالص لحاظ شوند (پیش‌تر بی‌صدا حذف می‌شدند = بیش‌برآورد فروش)
        neg_share = float((out[_REVENUE] < 0).mean()) if len(out) else 0.0
        if 0.4 < neg_share <= 0.6:
            # نه اقلیت برگشتی نه اکثریت حسابداری — قرارداد علامت مشکوک است
            out.attrs["ambiguous_sign"] = True
        ret_mask = out[_REVENUE] < 0
        returns = out[ret_mask].copy()
        out = out[~ret_mask]
    out.attrs["dropped_invalid_rows"] = before - len(out) - len(returns)

    # حذف ردیف‌های کاملاً تکراری (نه بر اساس order_id؛ هر سفارش می‌تواند چند قلم داشته باشد)
    # ستون فنی source_row از تعریف «تکرار» خارج است وگرنه هیچ تکراری پیدا نمی‌شد
    dup_before = len(out)
    dup_subset = [c for c in out.columns if c != SOURCE_ROW]
    dup_mask = out.duplicated(subset=dup_subset) if SOURCE_ROW in out.columns else out.duplicated()
    _exclude(dup_mask, "ردیف تکراری")
    out = out[~dup_mask]
    out.attrs["dropped_duplicate_rows"] = dup_before - len(out)

    if exclusions:
        excl = pd.concat(exclusions, ignore_index=True)
    else:
        excl = pd.DataFrame(columns=[*out.columns, "دلیل"])
    out.attrs["exclusions_df"] = SideFrame(excl)
    out.attrs["returns_df"] = SideFrame(returns.reset_index(drop=True))
    out.attrs["n_returns"] = int(len(returns))
    out.attrs["returns_total"] = float(-returns[_REVENUE].sum()) if len(returns) else 0.0

    out = out.sort_values(_DATE).reset_index(drop=True) if _DATE in out.columns else out.reset_index(drop=True)
    return out


__all__ = ["clean_frame", "get_exclusions", "get_returns", "SideFrame"]
