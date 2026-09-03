"""طراحِ آزمایش: کمپین بعدی را روی چه گروهی، و با چه اندازه‌ای؟

## مسئله‌ای که حل می‌کند

فاز ۴ جدولِ اثر را ساخت، ولی آن جدول **منتظر** است: تا کمپینی اجرا نشود چیزی
یاد نمی‌گیرد. و کمپین‌ها به‌ترتیبِ اتفاق ساخته می‌شوند، نه به‌ترتیبِ آنچه
نمی‌دانیم. نتیجه این است که سیستم می‌تواند ماه‌ها پیام بفرستد و هنوز نداند
کدام گروه به پیام پاسخ می‌دهد.

این ماژول ترتیب را برمی‌گرداند: می‌گوید **کدام گروه بیشترین تماسِ بی‌شاهد را
دارد** — یعنی جایی که بیشترین تصمیم گرفته می‌شود و کم‌ترین شواهد پشتش است.

## معیار اولویت: تماسِ اندازه‌گیری‌نشده

```
تماسِ اندازه‌گیری‌نشده = فرصت‌های تماس در سلولی که شواهدش قطعی نیست
```

عمداً امتیازِ مرکبِ ساختگی نساخته‌ام. این یک عدد شمردنی است با معنای مستقیم:
«این‌قدر پیام می‌فرستید بی‌آنکه بدانید کار می‌کند یا نه». سلولی که شواهدش قطعی
است (اثر اثبات‌شده یا بی‌فایدگیِ اثبات‌شده) صفر می‌گیرد، چون آزمودنِ دوباره‌اش
چیزی اضافه نمی‌کند.

⚠️ **واحدِ این عدد «فرصتِ تماس» است، نه «نفر».** درونِ هر سلول، هر مشتری یک‌بار
شمرده می‌شود؛ ولی یک مشتری می‌تواند در دو سلولِ متفاوت (دو نوع اقدام) حاضر باشد
و آن‌جا دو فرصتِ تماسِ جدا است. پس جمعِ سلول‌ها سرشمارِ افراد **نیست** و
عمداً هم نباید باشد: دو پیامِ متفاوت به یک نفر، دو تماس است.

## دو پرسشِ متقارن

بسته به اینکه محدودیت کجاست، یکی از این دو پاسخِ عملی است:

| وضعیت | پرسش | تابع |
|---|---|---|
| مشتری کافی هست | «چند نفر لازم است؟» | `required_control_size` |
| مشتری محدود است | «با همین تعداد چه چیزی اثبات‌شدنی است؟» | `achievable_effect` |

هر دو گزارش می‌شوند، چون توصیه‌ی «۹۰۰ نفر لازم است» به کسی که ۳۰۰ نفر دارد
هیچ راهنمایی‌ای نمی‌دهد.

این ماژول **تابع خالص** است و هیچ I/O ندارد؛ خواندن از دیتابیس در `plan.py`
است — همان جداسازی `uplift/` و `contact/`.
"""

from __future__ import annotations

from dataclasses import dataclass

from mktcore.campaigns.analysis import achievable_effect, required_control_size
from mktcore.uplift.empirical import MIN_CELL_OBSERVATIONS, UpliftTable

# اثرِ هدفِ پیش‌فرض. زیر ۵ واحد درصد، اندازه‌ی نمونه منفجر می‌شود (طبق جدول
# `FINANCIAL_CALCULATION_RULES`: اثر ۳ واحد درصد با کنترل ۱۰٪ نیازمند ۹٬۹۶۰ نفر
# است)، پس ۵ واحد درصد کفِ عملیِ مستند است نه یک عددِ دلبخواه.
DEFAULT_TARGET_EFFECT = 0.05

# گروه کنترل پیشنهادی. ۲۰٪ آماری کاراتر از ۱۰٪ است (یافته‌ی فاز ۴): برای همان
# قدرت تفکیک، کل کمپین حدود نصف می‌شود.
DEFAULT_HOLDOUT_PCT = 20

# نرخ پایه‌ی فرضی، تنها وقتی هیچ مشاهده‌ای نیست. صریحاً به‌عنوان **فرض** برچسب
# می‌خورد تا کاربر بداند عددِ اندازه‌ی نمونه روی یک حدس ایستاده.
DEFAULT_BASELINE_RATE = 0.3

STATUS_PROVEN = "proven"
STATUS_USELESS = "useless"
STATUS_INCONCLUSIVE = "inconclusive"
STATUS_THIN = "thin"
STATUS_NO_DATA = "no_data"

STATUS_LABELS_FA = {
    STATUS_PROVEN: "اثر اثبات‌شده",
    STATUS_USELESS: "بی‌فایدگی اثبات‌شده",
    STATUS_INCONCLUSIVE: "شواهد کافی نیست",
    STATUS_THIN: "نمونه‌ی بسیار کم",
    STATUS_NO_DATA: "هیچ آزمایشی انجام نشده",
}

# سلولی که شواهدش قطعی است، آزمودنِ دوباره لازم ندارد.
_SETTLED = frozenset({STATUS_PROVEN, STATUS_USELESS})

BASELINE_CELL = "cell_control"
BASELINE_GLOBAL = "global_control"
BASELINE_DEFAULT = "assumed"

BASELINE_LABELS_FA = {
    BASELINE_CELL: "نرخ خرید گروه کنترلِ همین سلول",
    BASELINE_GLOBAL: "نرخ خرید گروه کنترل در همه‌ی کمپین‌ها",
    BASELINE_DEFAULT: "فرضی (هیچ گروه کنترلی وجود ندارد)",
}


@dataclass(frozen=True)
class CellSupply:
    """چند مشتریِ آماده‌ی تماس در یک سلول هست — سمتِ «عرضه»."""

    kind: str
    lifecycle_state: str
    available: int


@dataclass
class ExperimentSuggestion:
    """یک سطر از برنامه‌ی آزمایش."""

    kind: str
    lifecycle_state: str
    status: str
    available: int
    n_treatment: int = 0
    n_control: int = 0
    measured_uplift: float | None = None
    ci: tuple[float, float] | None = None
    baseline_rate: float = DEFAULT_BASELINE_RATE
    baseline_source: str = BASELINE_DEFAULT
    target_effect: float = DEFAULT_TARGET_EFFECT
    holdout_pct: int = DEFAULT_HOLDOUT_PCT
    required_total: int | None = None
    detectable_now: float | None = None
    unmeasured_contacts: int = 0

    @property
    def settled(self) -> bool:
        return self.status in _SETTLED

    @property
    def feasible_now(self) -> bool:
        """آیا با مشتریانِ موجود می‌شود اثرِ هدف را دید؟"""
        return bool(self.required_total and self.available >= self.required_total)

    def note_fa(self) -> str:
        if self.status == STATUS_PROVEN:
            return (
                f"اثر این گروه اندازه‌گیری شده است "
                f"({round((self.measured_uplift or 0) * 100, 1)} واحد درصد). "
                "آزمودنِ دوباره چیزی اضافه نمی‌کند."
            )
        if self.status == STATUS_USELESS:
            return (
                "اندازه‌گیری نشان داده تماس با این گروه نتیجه را بهتر نمی‌کند؛ "
                "این گروه از فهرست تماس حذف می‌شود."
            )
        if not self.available:
            return "الان مشتریِ آماده‌ی تماسی در این گروه نیست، پس آزمایش‌شدنی نیست."
        if self.feasible_now:
            return (
                f"با {self.available} مشتریِ موجود می‌شود آزمایش کرد: کمپینی "
                f"{self.required_total} نفره با گروه کنترل {self.holdout_pct}٪ "
                f"اثری در حد {round(self.target_effect * 100, 1)} واحد درصد را نشان می‌دهد."
            )
        if self.detectable_now:
            return (
                f"{self.available} مشتری برای دیدن اثرِ "
                f"{round(self.target_effect * 100, 1)} واحد درصد کافی نیست "
                f"({self.required_total} نفر لازم است). با همین تعداد فقط اثرهای "
                f"بزرگ‌تر از {round(self.detectable_now * 100, 1)} واحد درصد "
                "اثبات‌شدنی‌اند."
            )
        return "برای آزمایشِ معنادار، تعداد مشتریانِ این گروه بسیار کم است."

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "lifecycle_state": self.lifecycle_state,
            "status": self.status,
            "status_label_fa": STATUS_LABELS_FA[self.status],
            "settled": self.settled,
            "available": self.available,
            "n_treatment": self.n_treatment,
            "n_control": self.n_control,
            "measured_uplift": (
                None if self.measured_uplift is None else round(self.measured_uplift, 4)
            ),
            "ci": None if self.ci is None else [round(self.ci[0], 4), round(self.ci[1], 4)],
            "baseline_rate": round(self.baseline_rate, 4),
            "baseline_source": self.baseline_source,
            "baseline_source_fa": BASELINE_LABELS_FA[self.baseline_source],
            "target_effect": round(self.target_effect, 4),
            "holdout_pct": self.holdout_pct,
            "required_total": self.required_total,
            "detectable_now": (
                None if self.detectable_now is None else round(self.detectable_now, 4)
            ),
            "feasible_now": self.feasible_now,
            "unmeasured_contacts": self.unmeasured_contacts,
            "note_fa": self.note_fa(),
        }


@dataclass
class ExperimentPlan:
    """برنامه‌ی آزمایش: سلول‌ها به‌ترتیبِ تماسِ اندازه‌گیری‌نشده."""

    suggestions: list[ExperimentSuggestion]
    target_effect: float = DEFAULT_TARGET_EFFECT
    holdout_pct: int = DEFAULT_HOLDOUT_PCT

    @property
    def total_unmeasured(self) -> int:
        """جمعِ **فرصت‌های تماسِ** بی‌شاهد — نه سرشمارِ افراد.

        یک مشتری که در دو نوع اقدام حاضر است، دو بار شمرده می‌شود، چون دو پیامِ
        متفاوت دو تماس است.
        """
        return sum(s.unmeasured_contacts for s in self.suggestions)

    @property
    def next_experiment(self) -> ExperimentSuggestion | None:
        """بهترین آزمایشِ بعدی: بیشترین تماسِ بی‌شاهد که **همین حالا** اجراشدنی است."""
        runnable = [
            s for s in self.suggestions if not s.settled and s.feasible_now
        ]
        return runnable[0] if runnable else None

    def to_dict(self) -> dict:
        nxt = self.next_experiment
        return {
            "available": bool(self.suggestions),
            "target_effect": round(self.target_effect, 4),
            "holdout_pct": self.holdout_pct,
            "total_unmeasured_contacts": self.total_unmeasured,
            "next_experiment": None if nxt is None else nxt.to_dict(),
            "cells": [s.to_dict() for s in self.suggestions],
        }


def _cell_status(n_treatment: int, n_control: int,
                 ci: tuple[float, float] | None,
                 min_cell_observations: int = MIN_CELL_OBSERVATIONS) -> str:
    if not n_treatment and not n_control:
        return STATUS_NO_DATA
    if n_treatment < min_cell_observations or n_control < min_cell_observations:
        return STATUS_THIN
    if ci is None:
        return STATUS_INCONCLUSIVE
    if ci[0] > 0:
        return STATUS_PROVEN
    if ci[1] <= 0:
        return STATUS_USELESS
    return STATUS_INCONCLUSIVE


def _global_control_rate(table: UpliftTable) -> float | None:
    """نرخ خرید گروه کنترل روی همه‌ی سلول‌ها — والدِ نرخ پایه."""
    n = sum(c.n_control for c in table.cells.values())
    if not n:
        return None
    return sum(c.conv_control for c in table.cells.values()) / n


def build_plan(
    supplies: list[CellSupply],
    table: UpliftTable | None,
    *,
    target_effect: float = DEFAULT_TARGET_EFFECT,
    holdout_pct: int = DEFAULT_HOLDOUT_PCT,
    min_cell_observations: int = MIN_CELL_OBSERVATIONS,
) -> ExperimentPlan:
    """ساخت برنامه از عرضه‌ی سلول‌ها و جدولِ اثرِ آموخته‌شده.

    `table` می‌تواند `None` باشد (هیچ آزمایشی انجام نشده) — در آن حالت همه‌ی
    سلول‌ها `no_data` می‌شوند و نرخ پایه صریحاً «فرضی» برچسب می‌خورد.
    `min_cell_observations` همان آستانه‌ی دروازه‌ی داده است (§۲۹.۶) — تنظیمِ
    کاربر، نه ثابتِ کد، تا نمای برنامه‌ریز با نمای آمادگی یکی باشد.
    """
    global_rate = _global_control_rate(table) if table is not None else None
    suggestions: list[ExperimentSuggestion] = []

    for supply in supplies:
        cell = None
        if table is not None:
            cell = table.cells.get((supply.kind, supply.lifecycle_state))

        n_t = cell.n_treatment if cell else 0
        n_c = cell.n_control if cell else 0
        ci = cell.ci if cell else None
        status = _cell_status(n_t, n_c, ci, min_cell_observations)

        # نرخ پایه: سلولِ خودش → کلِ کمپین‌ها → فرض. پایه صریحاً گزارش می‌شود
        # چون عددِ اندازه‌ی نمونه به آن حساس است.
        if cell is not None and n_c >= min_cell_observations:
            baseline, source = cell.rate_control, BASELINE_CELL
        elif global_rate is not None:
            baseline, source = global_rate, BASELINE_GLOBAL
        else:
            baseline, source = DEFAULT_BASELINE_RATE, BASELINE_DEFAULT

        # نرخ صفر یا صد واریانس صفر می‌دهد و اندازه‌ی نمونه را بی‌معنا می‌کند
        if not 0 < baseline < 1:
            baseline, source = DEFAULT_BASELINE_RATE, BASELINE_DEFAULT

        control_needed = required_control_size(
            target_effect, baseline, holdout_pct=holdout_pct,
        )
        required_total = (
            None if control_needed is None
            else int(round(control_needed * 100 / holdout_pct))
        )

        suggestion = ExperimentSuggestion(
            kind=supply.kind,
            lifecycle_state=supply.lifecycle_state,
            status=status,
            available=supply.available,
            n_treatment=n_t,
            n_control=n_c,
            measured_uplift=cell.shrunk_uplift if cell and cell.has_enough_data else None,
            ci=ci,
            baseline_rate=baseline,
            baseline_source=source,
            target_effect=target_effect,
            holdout_pct=holdout_pct,
            required_total=required_total,
            detectable_now=achievable_effect(
                supply.available, baseline, holdout_pct=holdout_pct,
            ),
            unmeasured_contacts=0 if status in _SETTLED else supply.available,
        )
        suggestions.append(suggestion)

    # ترتیب: تماسِ بی‌شاهدِ بیشتر اول. گره‌شکن ثابت است تا خروجی بازتولیدپذیر بماند.
    suggestions.sort(key=lambda s: (-s.unmeasured_contacts, s.kind, s.lifecycle_state))
    return ExperimentPlan(
        suggestions=suggestions, target_effect=target_effect, holdout_pct=holdout_pct,
    )


__all__ = [
    "BASELINE_CELL",
    "BASELINE_DEFAULT",
    "BASELINE_GLOBAL",
    "BASELINE_LABELS_FA",
    "DEFAULT_BASELINE_RATE",
    "DEFAULT_HOLDOUT_PCT",
    "DEFAULT_TARGET_EFFECT",
    "STATUS_INCONCLUSIVE",
    "STATUS_LABELS_FA",
    "STATUS_NO_DATA",
    "STATUS_PROVEN",
    "STATUS_THIN",
    "STATUS_USELESS",
    "CellSupply",
    "ExperimentPlan",
    "ExperimentSuggestion",
    "build_plan",
]
