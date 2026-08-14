"""تعیین حالت چرخه‌ی عمر — تابع خالص، بدون دیتابیس و بدون I/O.

## چرا آستانه‌ی سراسری غلط است

«۶۰ روز خرید نکرده» برای مشتریِ هفتگیِ نانوایی فاجعه است و برای مشتریِ سالانه‌ی
لوازم خانگی کاملاً عادی. هر قاعده‌ی ۳۰/۶۰/۹۰ روزه، یکی از این دو را اشتباه
برچسب می‌زند. پس اینجا آستانه‌ها **مضربی از فاصله‌ی خرید خودِ مشتری‌اند**:

```
تأخیر نسبی = روزهای بی‌خریدی ÷ فاصله‌ی معمول خرید همان مشتری
```

مشتری با آهنگ ۳۰ روزه و ۴۵ روز بی‌خریدی → تأخیر نسبی ۱.۵ → «در حال لغزش».
مشتری با آهنگ ۹۰ روزه و همان ۴۵ روز → تأخیر نسبی ۰.۵ → هنوز سر وقت است.

## تنها ثابت‌های سراسری

پنج عدد زیر تنها پارامترهای غیرشخصی‌اند و عمداً کم و مستندند. بقیه‌ی
قضاوت‌ها از داده‌ی خود مشتری می‌آید.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ------------------------------------------------------------------ حالت‌ها
STATE_PROSPECT = "prospect"
STATE_NEW = "new"
STATE_ACTIVATED = "activated"
STATE_GROWING = "growing"
STATE_ESTABLISHED = "established"
STATE_LOYAL = "loyal"
STATE_VIP = "vip"
STATE_SLIPPING = "slipping"
STATE_AT_RISK = "at_risk"
STATE_DORMANT = "dormant"
STATE_LOST = "lost"
STATE_REACTIVATED = "reactivated"

LIFECYCLE_STATES: tuple[str, ...] = (
    STATE_PROSPECT, STATE_NEW, STATE_ACTIVATED, STATE_GROWING,
    STATE_ESTABLISHED, STATE_LOYAL, STATE_VIP, STATE_SLIPPING,
    STATE_AT_RISK, STATE_DORMANT, STATE_LOST, STATE_REACTIVATED,
)

STATE_LABELS_FA: dict[str, str] = {
    STATE_PROSPECT: "بالقوه",
    STATE_NEW: "تازه‌وارد",
    STATE_ACTIVATED: "فعال‌شده",
    STATE_GROWING: "در حال رشد",
    STATE_ESTABLISHED: "تثبیت‌شده",
    STATE_LOYAL: "وفادار",
    STATE_VIP: "ویژه",
    STATE_SLIPPING: "در حال لغزش",
    STATE_AT_RISK: "در خطر ریزش",
    STATE_DORMANT: "خفته",
    STATE_LOST: "ازدست‌رفته",
    STATE_REACTIVATED: "بازگشته",
}

# حالت‌هایی که «رفتنی» محسوب می‌شوند؛ بازگشت از این‌ها یعنی احیا
_LAPSED_STATES = frozenset({STATE_SLIPPING, STATE_AT_RISK, STATE_DORMANT, STATE_LOST})

# ------------------------------------------------------- ثابت‌های سراسری (۵)
# تأخیر نسبی: چند برابر آهنگ خرید خودِ مشتری گذشته است.
SLIPPING_RATIO = 1.0    # از آهنگش گذشته ولی هنوز کمی
AT_RISK_RATIO = 1.5     # به‌طور معنادار عقب افتاده
DORMANT_RATIO = 3.0     # مدت طولانی نیامده
LOST_RATIO = 5.0        # بازگشت بعید است
# احتمال فعال‌بودن (sBG) که پایین‌تر از آن، مشتری ازدست‌رفته حساب می‌شود
LOST_ALIVE_PROBABILITY = 0.05

# آستانه‌های شمارشیِ سفارش — نه زمانی، پس شخصی‌سازی معنا ندارد
_ACTIVATED_ORDERS = 2
_ESTABLISHED_ORDERS = 3
_LOYAL_ORDERS = 5

# چرا «وفادار» شرط طول عمر جدا ندارد: با n خرید، طول عمر تقریباً (n−۱) برابر
# فاصله‌ی خرید است، پس هر شرطی روی نسبتِ طول‌عمر/فاصله چیزی جز همان شمار
# سفارش نمی‌گوید. آنچه واقعاً وفاداری را از انفجارِ یک‌باره جدا می‌کند این است
# که مشتری **آهنگ شخصی شناخته‌شده** داشته باشد و هنوز سر وقت باشد — و هر دو
# پیش از این نقطه بررسی شده‌اند.


@dataclass(frozen=True)
class LifecycleInput:
    """ورودی قضاوت — همه از `customer_features` که از قبل نوشته می‌شود.

    هیچ‌کدام محاسبه‌ی تازه لازم ندارند؛ این ماژول فقط تفسیر می‌کند.
    """

    n_orders: int | None = None
    recency_days: int | None = None
    tenure_days: int | None = None
    avg_gap_days: float | None = None
    p_alive: float | None = None
    clv_rial: int | None = None
    # میانه‌ی آهنگ خرید کل جامعه — تنها برای مشتری‌ای که هنوز آهنگ شخصی ندارد
    population_gap_days: float | None = None
    # آستانه‌ی ویژه‌بودن: ارزش آینده‌ی دهک بالا (از بیرون داده می‌شود چون
    # به توزیع کل مشتریان بستگی دارد، نه به خود مشتری)
    vip_clv_threshold_rial: int | None = None
    # آیا در آخرین عکسِ ثبت‌شده، حالتش «رفتنی» بود؟ (برای تشخیص احیا)
    previous_state: str | None = None
    # آیا از آن عکس تا حالا خریدی ثبت شده است؟
    purchased_since_previous: bool = False


@dataclass(frozen=True)
class LifecycleVerdict:
    """حالت + دلیل خوانا + پایه‌ی قضاوت.

    `basis` می‌گوید آهنگ خرید از خودِ مشتری آمده یا از میانه‌ی جامعه — تا در
    UI معلوم باشد این قضاوت چقدر شخصی است.
    """

    state: str
    reason_fa: str
    basis: str  # personal | population | count_only
    overdue_ratio: float | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def label_fa(self) -> str:
        return STATE_LABELS_FA.get(self.state, self.state)


def _effective_gap(data: LifecycleInput) -> tuple[float | None, str]:
    """آهنگ خرید مؤثر و پایه‌اش.

    آهنگ شخصی فقط وقتی معنا دارد که مشتری **دست‌کم دو خرید** کرده باشد؛ با یک
    خرید هیچ فاصله‌ای وجود ندارد که میانگین گرفته شود.
    """
    orders = data.n_orders or 0
    if data.avg_gap_days and data.avg_gap_days > 0 and orders >= 2:
        return float(data.avg_gap_days), "personal"
    if data.population_gap_days and data.population_gap_days > 0:
        return float(data.population_gap_days), "population"
    return None, "count_only"


def _overdue_ratio(data: LifecycleInput, gap: float | None) -> float | None:
    if gap is None or data.recency_days is None:
        return None
    return float(data.recency_days) / gap


def _is_growing(data: LifecycleInput, gap: float | None) -> bool:
    """رشد = خرید با آهنگی تندتر از آنچه طول عمرش نشان می‌دهد.

    بدون سری زمانی کامل، این نزدیک‌ترین سنجه‌ی صادقانه است: مشتری‌ای که در
    طول عمرش سفارش‌های بیشتری از حد انتظارِ آهنگش جا داده، در حال رشد است.
    """
    if gap is None or not data.tenure_days or not data.n_orders:
        return False
    expected = data.tenure_days / gap
    return data.n_orders >= max(_ESTABLISHED_ORDERS, expected * 1.2)


def classify_lifecycle(data: LifecycleInput) -> LifecycleVerdict:
    """تعیین حالت چرخه‌ی عمر.

    ترتیب بررسی عمدی است: **وضعیت رفتن مقدم بر وضعیت رشد است**. مشتریِ وفاداری
    که سه برابر آهنگش نیامده، «خفته» است نه «وفادار» — وگرنه برچسبِ خوش‌بینانه
    جلوی اقدام نجات را می‌گیرد.
    """
    orders = data.n_orders or 0
    gap, basis = _effective_gap(data)
    ratio = _overdue_ratio(data, gap)
    tags: list[str] = []

    if orders <= 0:
        return LifecycleVerdict(
            STATE_PROSPECT, "هنوز خریدی از این مشتری ثبت نشده است.", basis, ratio,
        )

    # ۱) احیا: پیش از هر قضاوت دیگری، چون داستانش مهم‌تر است
    if (data.previous_state in _LAPSED_STATES and data.purchased_since_previous
            and (ratio is None or ratio <= SLIPPING_RATIO)):
        previous_fa = STATE_LABELS_FA.get(data.previous_state, data.previous_state)
        return LifecycleVerdict(
            STATE_REACTIVATED,
            f"پیش‌تر «{previous_fa}» بود و دوباره خرید کرده است.",
            basis, ratio, ("returning",),
        )

    # ۲) ازدست‌رفته: احتمال بازگشت عملاً صفر
    if data.p_alive is not None and data.p_alive < LOST_ALIVE_PROBABILITY:
        return LifecycleVerdict(
            STATE_LOST,
            f"احتمال فعال‌بودن به {round(data.p_alive * 100, 1)}٪ رسیده است.",
            basis, ratio,
        )
    if ratio is not None and ratio > LOST_RATIO:
        return LifecycleVerdict(
            STATE_LOST,
            f"بیش از {LOST_RATIO:g} برابر فاصله‌ی معمول خریدش گذشته است.",
            basis, ratio,
        )

    # ۳) حالت‌های عقب‌افتادگی، از شدید به خفیف
    if ratio is not None and ratio > DORMANT_RATIO:
        return LifecycleVerdict(
            STATE_DORMANT,
            f"{_ratio_text(ratio)} برابر فاصله‌ی معمول خریدش گذشته است.",
            basis, ratio,
        )
    if ratio is not None and ratio > AT_RISK_RATIO:
        return LifecycleVerdict(
            STATE_AT_RISK,
            f"{_ratio_text(ratio)} برابر فاصله‌ی معمول خریدش گذشته و هنوز ارزش دارد.",
            basis, ratio, ("worth_saving",),
        )
    if ratio is not None and ratio > SLIPPING_RATIO:
        return LifecycleVerdict(
            STATE_SLIPPING,
            f"کمی از فاصله‌ی معمول خریدش ({_days_text(gap)}) گذشته است.",
            basis, ratio,
        )

    # ۴) مشتریِ سر وقت — حالا کیفیت رابطه سنجیده می‌شود
    if (data.vip_clv_threshold_rial and data.clv_rial
            and data.clv_rial >= data.vip_clv_threshold_rial):
        return LifecycleVerdict(
            STATE_VIP,
            "ارزش مورد انتظار آینده‌اش در بالاترین گروه است.",
            basis, ratio, ("high_future_value",),
        )
    # وفاداری فقط وقتی ادعا می‌شود که آهنگ خرید **شخصی** شناخته شده باشد؛
    # با تکیه بر میانه‌ی جامعه، «منظم بودن» ادعای اثبات‌نشده است.
    if orders >= _LOYAL_ORDERS and basis == "personal":
        return LifecycleVerdict(
            STATE_LOYAL,
            f"{orders} خرید با آهنگ منظمِ حدود {_days_text(gap)}.",
            basis, ratio,
        )
    if _is_growing(data, gap):
        tags.append("accelerating")
        return LifecycleVerdict(
            STATE_GROWING,
            "آهنگ خریدش از روند طول عمرش تندتر است.",
            basis, ratio, tuple(tags),
        )
    if orders >= _ESTABLISHED_ORDERS:
        return LifecycleVerdict(
            STATE_ESTABLISHED, f"{orders} خرید با الگوی پایدار.", basis, ratio,
        )
    if orders >= _ACTIVATED_ORDERS:
        return LifecycleVerdict(
            STATE_ACTIVATED,
            "خرید دومش را انجام داده — از تک‌خرید عبور کرده است.",
            basis, ratio,
        )
    return LifecycleVerdict(
        STATE_NEW, "تنها یک خرید ثبت شده است.", basis, ratio,
    )


def _ratio_text(ratio: float) -> str:
    return f"{ratio:.1f}".rstrip("0").rstrip(".")


def _days_text(gap: float | None) -> str:
    return "—" if gap is None else f"{round(gap)} روز"


def population_gap(gaps: list[float]) -> float | None:
    """میانه‌ی آهنگ خرید جامعه — تکیه‌گاه مشتریانِ بدون آهنگ شخصی.

    میانه است نه میانگین: چند مشتریِ روزانه یا چندساله نباید معیار بقیه را
    جابه‌جا کنند.
    """
    valid = sorted(g for g in gaps if g and g > 0)
    if not valid:
        return None
    mid = len(valid) // 2
    if len(valid) % 2:
        return valid[mid]
    return (valid[mid - 1] + valid[mid]) / 2


def vip_threshold(clv_values: list[int], *, top_fraction: float = 0.1) -> int | None:
    """آستانه‌ی «ویژه» = صدکِ بالای ارزش آینده.

    سند تصریح می‌کند ویژه‌بودن به **ارزش آینده** است، نه درآمد گذشته؛ پس مبنا
    `clv` است. آستانه از توزیع همین کسب‌وکار می‌آید، نه از عددی جهانی.
    """
    valid = sorted(v for v in clv_values if v and v > 0)
    if len(valid) < 10:  # با کمتر از ده مشتری، «دهک بالا» معنا ندارد
        return None
    index = max(0, min(len(valid) - 1, int(len(valid) * (1 - top_fraction))))
    return valid[index]


__all__ = [
    "AT_RISK_RATIO",
    "DORMANT_RATIO",
    "LIFECYCLE_STATES",
    "LOST_ALIVE_PROBABILITY",
    "LOST_RATIO",
    "SLIPPING_RATIO",
    "STATE_LABELS_FA",
    "LifecycleInput",
    "LifecycleVerdict",
    "classify_lifecycle",
    "population_gap",
    "vip_threshold",
]
