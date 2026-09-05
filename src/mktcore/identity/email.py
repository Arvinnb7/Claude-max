"""نرمال‌سازیِ ایمیل به‌عنوان کلیدِ هویت (§۹.۱ بند ۲).

همان قاعده‌ی این لایه: فقط تطبیقِ قطعی. ایمیل حروفِ کوچک و بدونِ فاصله‌ی اضافه؛
چیزی که شکلِ ایمیل ندارد `None` می‌شود — نه «حدس»، نه کلید.
"""

from __future__ import annotations

import re

from mktcore.locale_fa import normalize_digits

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


def normalize_email(raw: object) -> str | None:
    """`" Ali.R@Example.COM "` → `"ali.r@example.com"`؛ نامعتبر → `None`."""
    if raw is None:
        return None
    if isinstance(raw, float) and raw != raw:  # NaN
        return None
    text = normalize_digits(str(raw)).strip().lower()
    if not text or text in {"nan", "none", "null"}:
        return None
    return text if _EMAIL.fullmatch(text) else None


__all__ = ["normalize_email"]
