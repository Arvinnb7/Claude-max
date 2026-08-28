"""ارزش عمر مشتری بر پایه‌ی **سود ناخالص** — چندافقی و با بازه (§۱۹).

## نسبتش با CLV موجود

`next_purchase._clv_12m` سر جایش می‌ماند و یک ریال هم تغییر نمی‌کند. آن عدد
**درآمدی** است و همه‌جا (حالت «ویژه»، فهرست اقدام، اکسل، Customer 360) به همان
شکل مصرف می‌شود. این ماژول عددِ **سودی** را کنارش می‌گذارد، نه به‌جایش.

## چرا همان قرارداد تنزیل تکرار می‌شود

`_clv_12m` افتِ زنده‌بودن را **پیش از** انباشتِ ماه اول اعمال می‌کند، یعنی در
عمل سیزده بار افت می‌دهد نه دوازده بار. اگر اینجا فرمولِ «تمیز» می‌نوشتیم، دو
عددِ کنار هم در UI با هم جور درنمی‌آمدند و کاربر نمی‌توانست بفهمد اختلاف از
«درآمد در برابر سود» است یا از «فرمولِ متفاوت». پس قرارداد عیناً تکرار می‌شود و
یک تست پینش می‌کند: با دادن درآمدِ سرانه به‌جای سودِ سرانه، خروجی ۳۶۵ روزه باید
همان `_clv_12m` شود.

## چرا بازه اجباری است

§۱۹ می‌گوید CLV باید «accompanied by uncertainty» باشد. عددِ تک، تصمیمِ خرج‌کردن
را روی رقمی بنا می‌کند که خودش یک تخمین است؛ با بازه، تصمیم‌گیرنده می‌داند
کجای طیف ایستاده. بازه از دو منبع می‌آید: پراکندگیِ تعداد خرید (پواسون) و
پراکندگیِ سودِ هر سفارشِ همان مشتری.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# قرارداد تنزیل و افتِ زنده‌بودن عمداً از همان ماژول خوانده می‌شود تا اگر روزی
# عوض شد، این دو عدد از هم جدا نیفتند.
from .next_purchase import _ALIVE_PI, _CLV_DISCOUNT_MONTHLY

CLV_MODEL_VERSION = 1
CLV_HORIZONS_DAYS: tuple[int, ...] = (90, 180, 365)
CLV_DISCOUNT_MONTHLY = _CLV_DISCOUNT_MONTHLY

BASIS_GROSS_PROFIT = "gross_profit"
BASIS_BLOCKED = "blocked"

CONFIDENCE_HIGH = "بالا"
CONFIDENCE_MEDIUM = "متوسط"
CONFIDENCE_LOW = "کم (نمونه ناکافی)"

# زیر این تعداد سفارش، پراکندگیِ سودِ هر سفارش قابل‌تخمین نیست.
_MIN_ORDERS_FOR_SPREAD = 4
# ضریبِ بازه‌ی ۸۰٪ (دو دنباله‌ی ۱۰٪) — همان سطحی که سنجه‌های دیگر گزارش می‌کنند.
_Z_80 = 1.2815515655446004


@dataclass(frozen=True)
class HorizonCLV:
    """CLV یک افق. `value_rial` خالی یعنی محاسبه نشد — نه صفر."""

    horizon_days: int
    basis: str
    value_rial: int | None
    low_rial: int | None
    high_rial: int | None
    confidence_fa: str
    blocked_reason_fa: str | None
    model_version: int
    as_of: str

    def to_dict(self) -> dict:
        return {
            "horizon_days": self.horizon_days,
            "basis": self.basis,
            "value_rial": self.value_rial,
            "low_rial": self.low_rial,
            "high_rial": self.high_rial,
            "confidence_fa": self.confidence_fa,
            "blocked_reason_fa": self.blocked_reason_fa,
            "model_version": self.model_version,
            "as_of": self.as_of,
        }


def gross_profit_per_order_rial(
    *, gross_profit_rial: int | None, n_orders: int | None,
) -> int | None:
    """سودِ سرانه‌ی هر سفارش. پوشش ناقص ⇒ `None`.

    ورودی عمداً «سودِ کلِ مشتری» است نه فهرست خطوط: قاعده‌ی پوششِ کامل قبلاً در
    لایه‌ی ویژگی اعمال شده و آنجا سودِ مشتریِ ناقص‌پوشش اصلاً `None` است.
    """
    if gross_profit_rial is None or not n_orders:
        return None
    return int(round(gross_profit_rial / n_orders))


def horizon_clv(
    *,
    gp_per_order_rial: int | None,
    mu_days: float | None,
    p_alive: float | None,
    n_orders: int | None,
    as_of: str,
    profit_cv: float | None = None,
    horizons: tuple[int, ...] = CLV_HORIZONS_DAYS,
    blocked_reason_fa: str | None = None,
) -> list[HorizonCLV]:
    """CLV سودمحور برای هر افق، با بازه.

    نبودِ سود یا نبودِ آهنگ خرید ⇒ هر سه افق «محاسبه نشد» با دلیل صریح.
    """
    reason = blocked_reason_fa
    if gp_per_order_rial is None:
        reason = reason or (
            "سودِ این مشتری محاسبه‌شدنی نیست، چون بهای تمام‌شده‌ی همه‌ی خطوطش "
            "ثبت نشده است. عددِ ناقص بدتر از نبودِ عدد است."
        )
    elif mu_days is None or mu_days <= 0:
        reason = reason or (
            "آهنگ خرید این مشتری معلوم نیست (کمتر از دو خرید دارد)، پس تعداد "
            "خریدِ آینده قابل تخمین نیست."
        )

    if reason:
        return [
            HorizonCLV(
                horizon_days=days, basis=BASIS_BLOCKED, value_rial=None,
                low_rial=None, high_rial=None, confidence_fa=CONFIDENCE_LOW,
                blocked_reason_fa=reason, model_version=CLV_MODEL_VERSION, as_of=as_of,
            )
            for days in horizons
        ]

    confidence = _confidence(n_orders)
    return [
        _one_horizon(
            days=days, gp_per_order_rial=int(gp_per_order_rial), mu_days=float(mu_days),
            p_alive=p_alive, n_orders=n_orders, profit_cv=profit_cv,
            confidence=confidence, as_of=as_of,
        )
        for days in horizons
    ]


def _one_horizon(
    *,
    days: int,
    gp_per_order_rial: int,
    mu_days: float,
    p_alive: float | None,
    n_orders: int | None,
    profit_cv: float | None,
    confidence: str,
    as_of: str,
) -> HorizonCLV:
    months = max(1, int(round(days / 30)))
    orders_per_month = 30.0 / mu_days
    alive = 1.0 if p_alive is None else float(p_alive)

    total = 0.0
    for month in range(1, months + 1):
        # افت **پیش از** انباشت — همان ترتیبی که `_clv_12m` دارد.
        alive *= _ALIVE_PI ** (30.0 / mu_days)
        total += (
            orders_per_month * gp_per_order_rial * alive
            / ((1.0 + CLV_DISCOUNT_MONTHLY) ** month)
        )

    low, high = _band(
        total, days=days, mu_days=mu_days, n_orders=n_orders, profit_cv=profit_cv,
    )
    return HorizonCLV(
        horizon_days=days, basis=BASIS_GROSS_PROFIT, value_rial=int(round(total)),
        low_rial=int(round(low)), high_rial=int(round(high)),
        confidence_fa=confidence, blocked_reason_fa=None,
        model_version=CLV_MODEL_VERSION, as_of=as_of,
    )


def _band(
    point: float, *, days: int, mu_days: float, n_orders: int | None,
    profit_cv: float | None,
) -> tuple[float, float]:
    """بازه‌ی ۸۰٪ — از پراکندگیِ تعدادِ خرید، و در صورت امکان سودِ هر خرید.

    پواسون انتخاب شده چون فرآیند خرید در همین سیستم از قبل با همان توزیع مدل
    شده (`next_purchase.window_components`) و افزودنِ فرضِ تازه، عددی می‌ساخت که
    با بقیه‌ی سیستم ناسازگار باشد.
    """
    expected_orders = max(days / mu_days, 1e-9)
    spread = _Z_80 * math.sqrt(expected_orders) / expected_orders
    low_factor = max(0.0, 1.0 - spread)
    high_factor = 1.0 + spread

    if profit_cv and n_orders and n_orders >= _MIN_ORDERS_FOR_SPREAD:
        # خطای معیارِ میانگینِ سودِ هر سفارش: با تعداد سفارش کم می‌شود.
        profit_spread = _Z_80 * float(profit_cv) / math.sqrt(float(n_orders))
        low_factor *= max(0.0, 1.0 - profit_spread)
        high_factor *= 1.0 + profit_spread

    return point * low_factor, point * high_factor


def _confidence(n_orders: int | None) -> str:
    """همان سه‌سطحیِ `next_purchase.value_confidence` تا واژگان یکی بماند."""
    count = int(n_orders or 0)
    if count >= _MIN_ORDERS_FOR_SPREAD:
        return CONFIDENCE_HIGH
    if count >= 2:
        return CONFIDENCE_MEDIUM
    return CONFIDENCE_LOW


__all__ = [
    "BASIS_BLOCKED",
    "BASIS_GROSS_PROFIT",
    "CLV_DISCOUNT_MONTHLY",
    "CLV_HORIZONS_DAYS",
    "CLV_MODEL_VERSION",
    "CONFIDENCE_HIGH",
    "CONFIDENCE_LOW",
    "CONFIDENCE_MEDIUM",
    "HorizonCLV",
    "gross_profit_per_order_rial",
    "horizon_clv",
]
