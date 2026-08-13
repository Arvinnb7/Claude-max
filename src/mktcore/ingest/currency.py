"""تبدیل واحد پول (تومان/ریال) روی ستون‌های مبلغی دیتافریم پاک‌شده.

واحد پول در تحلیل صرفاً برچسب نمایشی است؛ این ماژول تنها نقطه‌ای است که
تبدیل عددی انجام می‌دهد: یک بار، بعد از پاک‌سازی و قبل از تحلیل، تا همه‌ی
پایین‌دست (KPI، پیش‌بینی، تارگت، پیامک، خروجی اکسل) در واحد نمایش باشند.
"""

from __future__ import annotations

import pandas as pd

CURRENCIES = ("تومان", "ریال")

# تنها منبع حقیقت نسبت واحدها. صحیح (نه float) است تا لایه‌ی ماندگاری بتواند
# مبالغ را بدون اتلاف دقت به ریالِ عدد صحیح تبدیل کند.
_RIAL_PER_UNIT = {"ریال": 1, "تومان": 10}

# ستون‌های استاندارد مبلغی که همیشه تبدیل می‌شوند. quantity شمارشی است و
# discount ممکن است نسبت باشد؛ هر دو از این فهرست بیرون‌اند.
MONETARY_COLUMNS = ("revenue", "cost", "unit_price", "gross_amount")

# ستون تخفیف فقط وقتی مبلغی است تبدیل می‌شود (نسبتی بی‌واحد است).
_DISCOUNT_COLUMN = "discount"


def rial_per_unit(currency: str) -> int:
    """چند ریال در یک واحدِ داده‌شده است؟ (تومان → ۱۰، ریال → ۱)

    مرزِ نوشتن در جداول canonical از این تابع استفاده می‌کند تا مبلغِ واحدِ
    نمایش را به ریالِ عدد صحیح تبدیل کند.
    """
    if currency not in _RIAL_PER_UNIT:
        raise ValueError(
            f"واحد پول نامعتبر است: «{currency}» — فقط «تومان» یا «ریال» مجاز است."
        )
    return _RIAL_PER_UNIT[currency]


def conversion_factor(file_currency: str, display_currency: str) -> float:
    """ضریب تبدیل مبالغ از واحد فایل به واحد نمایش (ریال→تومان = ۰٫۱)."""
    for name, value in (("واحد فایل", file_currency), ("واحد نمایش", display_currency)):
        if value not in _RIAL_PER_UNIT:
            raise ValueError(
                f"{name} نامعتبر است: «{value}» — فقط «تومان» یا «ریال» مجاز است."
            )
    return _RIAL_PER_UNIT[file_currency] / _RIAL_PER_UNIT[display_currency]


def _columns_to_convert(df: pd.DataFrame) -> tuple[str, ...]:
    """ستون‌های مبلغی این فریم، با احتساب تخفیفِ مبلغی.

    تفسیر «مبلغی/نسبتی» یک بار در پاک‌سازی تعیین و در `attrs` ثبت شده است؛
    اگر مبلغی باشد باید مثل بقیه‌ی مبالغ تبدیل شود، وگرنه `discount_total`
    در KPI به‌اندازه‌ی نسبت واحدها (ده برابر) غلط می‌شود.
    """
    cols = MONETARY_COLUMNS
    if df.attrs.get("discount_is_amount") and _DISCOUNT_COLUMN in df.columns:
        cols = (*cols, _DISCOUNT_COLUMN)
    return cols


def convert_monetary_columns(df: pd.DataFrame, factor: float) -> pd.DataFrame:
    """اعمال ضریب تبدیل روی ستون‌های مبلغی؛ با ضریب ۱ همان df برمی‌گردد.

    ردیف‌های برگشت (attrs) هم تبدیل می‌شوند تا KPI خالص هم‌واحد بماند؛
    آرتیفکت ممیزی exclusions عمداً با مبلغ اصلی فایل می‌ماند.
    """
    if factor == 1.0:
        return df
    columns = _columns_to_convert(df)
    out = df.copy()
    for col in columns:
        if col in out.columns:
            out[col] = out[col] * factor

    from .cleaning import SideFrame, get_returns

    returns = get_returns(df)
    if len(returns):
        ret = returns.copy()
        for col in columns:
            if col in ret.columns:
                ret[col] = ret[col] * factor
        out.attrs["returns_df"] = SideFrame(ret)
        out.attrs["returns_total"] = float(df.attrs.get("returns_total", 0.0)) * factor
    return out


__all__ = [
    "CURRENCIES",
    "MONETARY_COLUMNS",
    "conversion_factor",
    "convert_monetary_columns",
    "rial_per_unit",
]
