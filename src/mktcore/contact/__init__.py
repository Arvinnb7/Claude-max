"""مجوز تماس: چه کسی حق دارد پیام بگیرد.

دو لایه، مثل `uplift/`:

* `permission.py` — تصمیم به‌صورت تابع خالص، بدون I/O و بدون دیتابیس.
* `register.py` — دفترِ انصراف روی دیتابیس و ساختنِ دروازه از داده‌ی واقعی.

این جداسازی عمدی است: منطقِ تصمیم بدون دیتابیس آزمودنی می‌ماند، و لایه‌ی
دیتابیس هرگز خطا به بالا پرت نمی‌کند (نبودِ دفتر نباید ارسال را بخواباند —
ولی «بررسی نشد» صریح گزارش می‌شود، نه «قبول»).
"""

from .permission import (
    DEFAULT_FATIGUE_WINDOW_DAYS,
    REASON_CONSENT,
    REASON_CONTROL,
    REASON_FATIGUE,
    REASON_LABELS_FA,
    ContactGate,
    GateResult,
)

__all__ = [
    "DEFAULT_FATIGUE_WINDOW_DAYS",
    "REASON_CONSENT",
    "REASON_CONTROL",
    "REASON_FATIGUE",
    "REASON_LABELS_FA",
    "ContactGate",
    "GateResult",
]
