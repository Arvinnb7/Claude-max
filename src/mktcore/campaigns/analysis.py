"""سنجش اثر کمپین — با بازه‌ی اطمینان و مرزِ صریحِ «نمی‌دانیم».

## چرا «نرخ تبدیل گروه تماس‌شده» عدد بی‌معنایی است

اگر به ۱۰۰ مشتری تماس بگیرید و ۲۰ نفر خرید کنند، ۲۰٪ نرخ تبدیل نیست؛ نرخ
تبدیل **مشاهده‌شده** است. شاید ۱۸ نفرشان به‌هرحال می‌خریدند. آنچه ارزش دارد
تفاوت با گروهی است که تماس نگرفته‌ایم:

```
اثر افزوده = نرخ گروه آزمایش − نرخ گروه کنترل
```

## چرا بازه‌ی اطمینان اجباری است

با ۲۰ نفر کنترل، «۵٪ اثر» و «۵٪ نویز» از هم قابل‌تشخیص نیستند. گزارش‌کردن عدد
بدون بازه، تصمیم‌گیرنده را به اقدام روی نویز تشویق می‌کند. پس هر عددی که
بازه‌اش صفر را در بر بگیرد، **اثر اثبات‌شده اعلام نمی‌شود**.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# کمینه‌ی اندازه‌ی گروه کنترل برای هر ادعای علّی. زیر این عدد، حتی اثرهای بزرگ
# هم از نویز قابل‌تشخیص نیستند.
MIN_CONTROL_SIZE = 30
MIN_TREATMENT_SIZE = 30
# سطح اطمینان بازه (۹۵٪)
_Z = 1.959963985

VERDICT_PROVEN = "proven"
VERDICT_INCONCLUSIVE = "inconclusive"
VERDICT_ATTRIBUTION_ONLY = "attribution_only"
VERDICT_NOT_READY = "not_ready"

VERDICT_LABELS_FA = {
    VERDICT_PROVEN: "اثر اثبات‌شده",
    VERDICT_INCONCLUSIVE: "شواهد کافی نیست",
    VERDICT_ATTRIBUTION_ONLY: "فقط انتساب (بدون گروه کنترل)",
    VERDICT_NOT_READY: "هنوز نتیجه‌ای ثبت نشده",
}


@dataclass
class ArmStats:
    """آمار یک بازو. همه‌ی مبالغ ریالِ صحیح‌اند."""

    arm: str
    size: int = 0
    converters: int = 0
    orders: int = 0
    revenue_rial: int = 0
    # `None` یعنی پوششِ بها کامل نبود — نه اینکه بها صفر بوده.
    cost_rial: int | None = None

    @property
    def gross_profit_rial(self) -> int | None:
        """درآمد − بها. `None` وقتی بها کامل نیست."""
        if self.cost_rial is None:
            return None
        return self.revenue_rial - self.cost_rial

    @property
    def profit_per_customer(self) -> float | None:
        profit = self.gross_profit_rial
        if profit is None or not self.size:
            return None
        return profit / self.size

    @property
    def conversion_rate(self) -> float:
        return self.converters / self.size if self.size else 0.0

    @property
    def revenue_per_customer(self) -> float:
        return self.revenue_rial / self.size if self.size else 0.0


@dataclass
class CampaignReport:
    """گزارش اثر — همیشه با حکم صریح درباره‌ی اعتبار خودش."""

    treatment: ArmStats
    control: ArmStats
    verdict: str
    verdict_reason_fa: str
    absolute_lift: float | None = None          # اختلاف نرخ تبدیل
    relative_lift: float | None = None          # اثر نسبی
    lift_ci: tuple[float, float] | None = None  # بازه‌ی اطمینان اثر مطلق
    incremental_orders: float | None = None
    incremental_revenue_rial: int | None = None
    incremental_revenue_ci: tuple[int, int] | None = None
    blocked_metrics: dict[str, str] = field(default_factory=dict)
    # قدرت تفکیکِ این کمپین: کوچک‌ترین اثری که با این اندازه دیدنی است
    detectable_effect: float | None = None
    power_note_fa: str | None = None
    # هزینه‌ی واقعیِ ثبت‌شده‌ی تماس. `None` یعنی ارسالی از داخل سیستم نبوده.
    contact_cost_rial: int | None = None
    # هزینه‌ی هر سفارشِ **افزوده**. فقط وقتی معنا دارد که اثر اثبات شده باشد،
    # چون تقسیم بر عددی که خودش اثبات‌نشده است، عددِ اثبات‌نشده می‌دهد.
    cost_per_incremental_order_rial: int | None = None
    # سود ناخالص افزوده — شمالِ‌ستاره‌ی سند (§۴). `None` تا وقتی پوششِ بها در
    # **هر دو** بازو کامل نباشد؛ جمعِ ناقص سود را بیشتر از واقع نشان می‌دهد.
    incremental_gross_profit_rial: int | None = None
    gross_profit_note_fa: str | None = None
    # تفاوتِ **مشاهده‌شده** بین دو بازو — همیشه با نامِ خودش. برای حکمِ غیرعلّی
    # (inconclusive) عددِ «افزوده» None می‌ماند و فقط این‌ها پر می‌شوند؛ وگرنه
    # همان عدد با برچسبِ «افزوده» به مصرف‌کننده‌ی API می‌رسد (§۳.۶، §۲۳.۱).
    observed_orders_diff: float | None = None
    observed_revenue_diff_rial: int | None = None
    observed_revenue_diff_ci: tuple[int, int] | None = None
    observed_gross_profit_diff_rial: int | None = None
    causal_note_fa: str | None = None

    @property
    def is_causal(self) -> bool:
        return self.verdict == VERDICT_PROVEN

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "verdict_label": VERDICT_LABELS_FA[self.verdict],
            "verdict_reason_fa": self.verdict_reason_fa,
            "is_causal": self.is_causal,
            "arms": {
                "treatment": _arm_dict(self.treatment),
                "control": _arm_dict(self.control),
            },
            "absolute_lift": self.absolute_lift,
            "relative_lift": self.relative_lift,
            "lift_ci": list(self.lift_ci) if self.lift_ci else None,
            "incremental_orders": self.incremental_orders,
            "incremental_revenue_rial": self.incremental_revenue_rial,
            "incremental_revenue_ci": (
                list(self.incremental_revenue_ci) if self.incremental_revenue_ci else None
            ),
            "blocked_metrics": self.blocked_metrics,
            "detectable_effect": self.detectable_effect,
            "power_note_fa": self.power_note_fa,
            "contact_cost_rial": self.contact_cost_rial,
            "incremental_gross_profit_rial": self.incremental_gross_profit_rial,
            "gross_profit_note_fa": self.gross_profit_note_fa,
            "cost_per_incremental_order_rial": self.cost_per_incremental_order_rial,
            "observed_difference": {
                "orders": self.observed_orders_diff,
                "revenue_rial": self.observed_revenue_diff_rial,
                "revenue_ci": (
                    list(self.observed_revenue_diff_ci)
                    if self.observed_revenue_diff_ci else None
                ),
                "gross_profit_rial": self.observed_gross_profit_diff_rial,
            },
            "causal_note_fa": self.causal_note_fa,
        }


def _arm_dict(stats: ArmStats) -> dict:
    return {
        "size": stats.size,
        "converters": stats.converters,
        "orders": stats.orders,
        "revenue_rial": stats.revenue_rial,
        "conversion_rate": round(stats.conversion_rate, 4),
        "revenue_per_customer_rial": round(stats.revenue_per_customer),
        # `None` یعنی پوششِ بها کامل نبود — نه اینکه بها صفر بوده.
        "cost_rial": stats.cost_rial,
        "gross_profit_rial": stats.gross_profit_rial,
        "profit_per_customer_rial": (
            None if stats.profit_per_customer is None
            else round(stats.profit_per_customer)
        ),
    }


# سنجه‌هایی که با زیرساخت فعلی محاسبه‌شدنی نیستند — صریح، نه غایب
_BLOCKED_METRICS = {
    # دلیلِ قبلی «کانال خروجی اکسل بازخورد ندارد» بود؛ حالا کانال دومی هم هست
    # (ارسال مستقیم) و آن هم مسدود است — ولی به دلیلِ متفاوت: پنل شناسه‌ی پیام
    # را برمی‌گرداند (و ذخیره می‌شود) ولی هیچ webhookی برای دریافت وضعیت تحویل
    # وصل نشده است.
    "delivered": "وضعیت تحویل نیازمند webhook از پنل پیامکی است که هنوز وصل نشده.",
    "viewed_clicked": "پیامک بازخورد مشاهده یا کلیک ندارد؛ این سنجه کانالِ دیگری می‌خواهد.",
    "incremental_gross_profit": (
        "سود افزوده تا وقتی گزارش نمی‌شود که بهای تمام‌شده‌ی همه‌ی خطوطِ پنجره‌ی "
        "سنجش در هر دو گروه موجود باشد. با پوشش کامل، این انسداد خودبه‌خود "
        "برداشته می‌شود."
    ),
    "cost_per_incremental_order": "هزینه‌ی تماس در سیستم ثبت نمی‌شود.",
}


def minimum_detectable_effect(t: ArmStats, c: ArmStats) -> float | None:
    """کوچک‌ترین اثری که با **این اندازه‌ی گروه‌ها** قابل تشخیص است.

    چرا لازم است: یک کمپین با گروه کنترل ۸۰ نفره نمی‌تواند اثر ۵ واحد درصدی را
    از نوفه جدا کند — حتی اگر آن اثر واقعاً وجود داشته باشد. بدون این عدد،
    «شواهد کافی نیست» مبهم است؛ با آن، معنایش روشن می‌شود: «برای دیدن اثری
    کوچک‌تر از این، گروه بزرگ‌تری لازم است».

    مبنا: نرخ تبدیلِ مشاهده‌شده‌ی گروه کنترل (یا ۰٫۵ در بدترین حالت اگر صفر
    باشد — بیشترین واریانس، پس محافظه‌کارانه‌ترین تخمین).
    """
    if not t.size or not c.size:
        return None
    p = c.conversion_rate or 0.5
    variance = p * (1 - p)
    if variance <= 0:  # نرخ صفر یا صد → واریانس صفر، تخمین بی‌معنا
        variance = 0.25
    return _Z * math.sqrt(variance / t.size + variance / c.size)


def required_control_size(target_effect: float, baseline_rate: float = 0.3,
                          *, holdout_pct: int = 10) -> int | None:
    """اندازه‌ی گروه کنترلِ لازم برای تشخیص اثری به‌اندازه‌ی `target_effect`.

    برای پاسخ به پرسش عملی «کمپین بعدی را چند نفره ببندم؟».
    """
    if target_effect <= 0 or not 0 < holdout_pct < 100:
        return None
    variance = baseline_rate * (1 - baseline_rate)
    ratio = (100 - holdout_pct) / holdout_pct  # اندازه‌ی آزمایش به کنترل
    return math.ceil(variance * (1 + 1 / ratio) * (_Z / target_effect) ** 2)


def achievable_effect(total_size: int, baseline_rate: float = 0.3,
                      *, holdout_pct: int = 10) -> float | None:
    """معکوسِ `required_control_size`: با **این** تعداد نفر، چه اثری دیدنی است؟

    `required_control_size` به پرسشِ «برای دیدن اثر ۵ واحد درصد چند نفر لازم
    است؟» پاسخ می‌دهد. ولی وقتی تعداد مشتریانِ در دسترس محدود است، پرسشِ عملی
    برعکس می‌شود: «من فقط ۳۰۰ نفر در این گروه دارم؛ با آن‌ها چه چیزی را
    می‌توانم اثبات کنم؟»

    بدون این عدد، توصیه‌ی «کمپین ۹۰۰ نفره ببند» برای کسی که ۳۰۰ نفر دارد بی‌مصرف
    است و هیچ راهنمایی‌ای نمی‌دهد.
    """
    if total_size <= 0 or not 0 < holdout_pct < 100:
        return None
    control = total_size * holdout_pct / 100
    if control < 1:
        return None
    ratio = (100 - holdout_pct) / holdout_pct
    variance = baseline_rate * (1 - baseline_rate)
    if variance <= 0:
        variance = 0.25
    return _Z * math.sqrt(variance * (1 + 1 / ratio) / control)


def _diff_ci(t: ArmStats, c: ArmStats) -> tuple[float, float]:
    """بازه‌ی اطمینان اختلاف دو نسبت (تقریب Wald با اصلاح پیوستگی)."""
    p1, n1 = t.conversion_rate, t.size
    p2, n2 = c.conversion_rate, c.size
    se = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2) if n1 and n2 else 0.0
    diff = p1 - p2
    margin = _Z * se
    return (diff - margin, diff + margin)


def _revenue_diff_ci(t: ArmStats, c: ArmStats) -> tuple[float, float]:
    """بازه‌ی اطمینان اختلاف درآمد سرانه.

    بدون داشتن واریانس فردی، از تقریب پواسنیِ درآمد استفاده می‌شود: برای
    توزیع‌های راست‌کج (که درآمد همیشه هست) محافظه‌کارانه‌تر از تقریب نرمال است.
    """
    diff = t.revenue_per_customer - c.revenue_per_customer
    if not t.size or not c.size:
        return (diff, diff)
    var = (
        (t.revenue_per_customer ** 2) / max(t.converters, 1) / t.size
        + (c.revenue_per_customer ** 2) / max(c.converters, 1) / c.size
    )
    margin = _Z * math.sqrt(max(var, 0.0))
    return (diff - margin, diff + margin)


def _power_note(mde: float | None, holdout_pct: int = 10) -> str | None:
    """جمله‌ی قدرت تفکیک: «چه چیزی را نمی‌توانستیم ببینیم، و چه اندازه‌ای لازم بود»."""
    if mde is None:
        return None
    needed = required_control_size(0.05, holdout_pct=holdout_pct)
    text = (
        f"با این اندازه‌ی گروه‌ها، تنها اثرهای بزرگ‌تر از "
        f"{round(mde * 100, 1)} واحد درصد قابل تشخیص‌اند."
    )
    if mde > 0.05 and needed:
        text += (
            f" برای دیدن اثری در حد ۵ واحد درصد، گروه کنترل باید حدود "
            f"{needed} نفر باشد."
        )
    return text


def analyze_campaign(
    treatment: ArmStats,
    control: ArmStats,
    *,
    contact_cost_rial: int | None = None,
) -> CampaignReport:
    """ساخت گزارش اثر با حکم صریح درباره‌ی اعتبارش.

    `contact_cost_rial` هزینه‌ی **واقعیِ ثبت‌شده‌ی** تماس است (از دفتر ارسال).
    `None` یعنی هیچ ارسالی از داخل سیستم انجام نشده — مثلاً کانال، خروجی اکسل
    بوده — و در آن حالت «هزینه به‌ازای سفارش افزوده» مسدود می‌ماند.
    """
    report = _verdict(treatment, control, contact_cost_rial=contact_cost_rial)
    _attach_gross_profit(report, treatment, control)
    if contact_cost_rial is None:
        return report

    report.contact_cost_rial = int(contact_cost_rial)
    # تقسیم بر سفارشِ افزوده تنها وقتی معنا دارد که خودِ آن عدد اثبات شده باشد.
    # وگرنه «هزینه‌ی هر سفارش افزوده» عددی است که مخرجش ممکن است نوفه باشد.
    orders = report.incremental_orders
    if report.is_causal and orders and orders > 0:
        report.cost_per_incremental_order_rial = round(int(contact_cost_rial) / orders)
    return report


def _attach_gross_profit(
    report: CampaignReport, treatment: ArmStats, control: ArmStats,
) -> None:
    """سود ناخالص افزوده — فقط وقتی پوششِ بها در **هر دو** بازو کامل است.

    فرمول همان فرمولِ درآمد افزوده است، با سود به‌جای درآمد:

        سود افزوده = (سودِ سرانه‌ی آزمایش − سودِ سرانه‌ی کنترل) × اندازه‌ی آزمایش

    اگر یکی از دو بازو پوششِ ناقص داشته باشد، عدد **گزارش نمی‌شود**. جمعِ ناقصِ
    بها سود را بیشتر از واقع نشان می‌دهد و هیچ نشانه‌ای هم همراهش نیست — همان
    چیزی که سند «a partial number is worse than no number» می‌نامد.
    """
    if not treatment.size or not control.size:
        # دلیلِ واقعی اینجا بها نیست: یکی از دو گروه هنوز عضوِ سنجیده‌شده ندارد
        # (مثلاً گروه آزمایش هنوز تماس نگرفته). گفتنِ «بها ثبت نشده» اینجا
        # کاربر را دنبال مشکلی می‌فرستد که وجود ندارد.
        report.gross_profit_note_fa = (
            "سود افزوده محاسبه نشد: یکی از دو گروه هنوز عضوِ سنجیده‌شده ندارد. "
            "تا وقتی گروه آزمایش تماس نگرفته، مقایسه‌ای در کار نیست."
        )
        return

    treatment_profit = treatment.profit_per_customer
    control_profit = control.profit_per_customer
    if treatment_profit is None or control_profit is None:
        report.gross_profit_note_fa = (
            "سود افزوده محاسبه نشد: بهای تمام‌شده برای همه‌ی خطوطِ پنجره‌ی سنجش "
            "در هر دو گروه ثبت نشده است. عددِ ناقص بدتر از نبودِ عدد است."
        )
        return

    diff = round((treatment_profit - control_profit) * treatment.size)
    report.observed_gross_profit_diff_rial = diff
    # انسدادِ «پوشش بها» برداشته می‌شود (پوشش کامل است) — جدا از حکمِ علّی، تا
    # پیامِ «بها ناقص است» با «اثر اثبات نشده» قاطی نشود.
    report.blocked_metrics.pop("incremental_gross_profit", None)
    if report.is_causal:
        report.incremental_gross_profit_rial = diff
        report.gross_profit_note_fa = (
            "سود افزوده از تفاضل سودِ سرانه‌ی دو گروه محاسبه شد؛ بهای تمام‌شده برای "
            "همه‌ی اعضا موجود بود."
        )
    else:
        report.gross_profit_note_fa = (
            "بهای تمام‌شده برای همه‌ی اعضا موجود بود؛ ولی تا اثباتِ اثر، تفاوتِ سودِ "
            "دو گروه «مشاهده‌ای» است نه «افزوده»."
        )


def _verdict(
    treatment: ArmStats,
    control: ArmStats,
    *,
    contact_cost_rial: int | None = None,
) -> CampaignReport:
    blocked = dict(_BLOCKED_METRICS)
    mde = minimum_detectable_effect(treatment, control)
    power = _power_note(mde)
    if contact_cost_rial is not None:
        blocked.pop("cost_per_incremental_order", None)

    # ۱) بدون گروه کنترل → هیچ ادعای علّی ممکن نیست
    if control.size == 0:
        return CampaignReport(
            treatment, control, VERDICT_ATTRIBUTION_ONLY,
            "این کمپین گروه کنترل ندارد؛ عددها فقط می‌گویند چه اتفاقی افتاد، "
            "نه اینکه به‌خاطر تماس شما بوده است.",
            blocked_metrics=blocked,
            detectable_effect=mde, power_note_fa=power,
        )

    # ۲) هنوز نتیجه‌ای ثبت نشده
    if treatment.size == 0:
        return CampaignReport(
            treatment, control, VERDICT_NOT_READY,
            "هنوز هیچ عضوی در گروه آزمایش در معرض تماس قرار نگرفته است.",
            blocked_metrics=blocked,
            detectable_effect=mde, power_note_fa=power,
        )

    absolute = treatment.conversion_rate - control.conversion_rate
    relative = (
        absolute / control.conversion_rate if control.conversion_rate > 0 else None
    )
    ci = _diff_ci(treatment, control)
    revenue_ci = _revenue_diff_ci(treatment, control)
    observed_orders = absolute * treatment.size
    observed_revenue = round(
        (treatment.revenue_per_customer - control.revenue_per_customer) * treatment.size
    )
    observed_revenue_ci = (
        round(revenue_ci[0] * treatment.size), round(revenue_ci[1] * treatment.size),
    )
    not_causal_note = (
        "تفاوتِ مشاهده‌شده‌ی دو گروه گزارش می‌شود ولی «افزوده» نیست: تا اثبات اثر، "
        "هیچ عددی به‌عنوان نتیجه‌ی تماس ارائه نمی‌شود."
    )

    # ۳) گروه‌های کوچک → تفاوت هست ولی ادعای «افزوده» نه
    if control.size < MIN_CONTROL_SIZE or treatment.size < MIN_TREATMENT_SIZE:
        return CampaignReport(
            treatment, control, VERDICT_INCONCLUSIVE,
            f"اندازه‌ی گروه‌ها کم است (آزمایش {treatment.size}، کنترل {control.size}؛ "
            f"حداقل لازم {MIN_TREATMENT_SIZE} و {MIN_CONTROL_SIZE}). "
            "اختلاف مشاهده‌شده ممکن است صرفاً نوسان باشد.",
            absolute, relative, ci, None, None, None,
            blocked, mde, power,
            observed_orders_diff=observed_orders,
            observed_revenue_diff_rial=observed_revenue,
            observed_revenue_diff_ci=observed_revenue_ci,
            causal_note_fa=not_causal_note,
        )

    # ۴) بازه‌ای که صفر را در بر می‌گیرد → اثر اثبات‌نشده
    if ci[0] <= 0 <= ci[1]:
        return CampaignReport(
            treatment, control, VERDICT_INCONCLUSIVE,
            "بازه‌ی اطمینان اثر، صفر را در بر می‌گیرد؛ یعنی با این داده "
            "نمی‌شود گفت تماس اثر داشته است.",
            absolute, relative, ci, None, None, None,
            blocked, mde, power,
            observed_orders_diff=observed_orders,
            observed_revenue_diff_rial=observed_revenue,
            observed_revenue_diff_ci=observed_revenue_ci,
            causal_note_fa=not_causal_note,
        )

    direction = "مثبت" if absolute > 0 else "منفی"
    return CampaignReport(
        treatment, control, VERDICT_PROVEN,
        f"اثر {direction} است و بازه‌ی اطمینان ۹۵٪ صفر را در بر نمی‌گیرد.",
        absolute, relative, ci, observed_orders, observed_revenue, observed_revenue_ci,
        blocked, mde, power,
        observed_orders_diff=observed_orders,
        observed_revenue_diff_rial=observed_revenue,
        observed_revenue_diff_ci=observed_revenue_ci,
        causal_note_fa="اثر با گروه کنترلِ تصادفی اثبات شده؛ عددِ افزوده علّی است.",
    )


__all__ = [
    "MIN_CONTROL_SIZE",
    "MIN_TREATMENT_SIZE",
    "VERDICT_ATTRIBUTION_ONLY",
    "VERDICT_INCONCLUSIVE",
    "VERDICT_LABELS_FA",
    "VERDICT_NOT_READY",
    "VERDICT_PROVEN",
    "ArmStats",
    "CampaignReport",
    "achievable_effect",
    "analyze_campaign",
    "minimum_detectable_effect",
    "required_control_size",
]
