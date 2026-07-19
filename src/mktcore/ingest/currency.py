"""تبدیل واحد پول (تومان/ریال) روی ستون‌های مبلغی دیتافریم پاک‌شده.

واحد پول در تحلیل صرفاً برچسب نمایشی است؛ این ماژول تنها نقطه‌ای است که
تبدیل عددی انجام می‌دهد: یک بار، بعد از پاک‌سازی و قبل از تحلیل، تا همه‌ی
پایین‌دست (KPI، پیش‌بینی، تارگت، پیامک، خروجی اکسل) در واحد نمایش باشند.
"""

from __future__ import annotations

import pandas as pd

CURRENCIES = ("تومان", "ریال")

_RIAL_PER_UNIT = {"ریال": 1.0, "تومان": 10.0}

# ستون‌های استاندارد مبلغی. discount نسبت است (نه مبلغ) و quantity شمارشی —
# هرگز تبدیل نمی‌شوند.
MONETARY_COLUMNS = ("revenue", "cost", "unit_price", "gross_amount")


def conversion_factor(file_currency: str, display_currency: str) -> float:
    """ضریب تبدیل مبالغ از واحد فایل به واحد نمایش (ریال→تومان = ۰٫۱)."""
    for name, value in (("واحد فایل", file_currency), ("واحد نمایش", display_currency)):
        if value not in _RIAL_PER_UNIT:
            raise ValueError(
                f"{name} نامعتبر است: «{value}» — فقط «تومان» یا «ریال» مجاز است."
            )
    return _RIAL_PER_UNIT[file_currency] / _RIAL_PER_UNIT[display_currency]


def convert_monetary_columns(df: pd.DataFrame, factor: float) -> pd.DataFrame:
    """اعمال ضریب تبدیل روی ستون‌های مبلغی؛ با ضریب ۱ همان df برمی‌گردد.

    ردیف‌های برگشت (attrs) هم تبدیل می‌شوند تا KPI خالص هم‌واحد بماند؛
    آرتیفکت ممیزی exclusions عمداً با مبلغ اصلی فایل می‌ماند.
    """
    if factor == 1.0:
        return df
    out = df.copy()
    for col in MONETARY_COLUMNS:
        if col in out.columns:
            out[col] = out[col] * factor

    from .cleaning import SideFrame, get_returns

    returns = get_returns(df)
    if len(returns):
        ret = returns.copy()
        for col in MONETARY_COLUMNS:
            if col in ret.columns:
                ret[col] = ret[col] * factor
        out.attrs["returns_df"] = SideFrame(ret)
        out.attrs["returns_total"] = float(df.attrs.get("returns_total", 0.0)) * factor
    return out


__all__ = ["CURRENCIES", "MONETARY_COLUMNS", "conversion_factor", "convert_monetary_columns"]
