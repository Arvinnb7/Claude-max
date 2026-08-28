"""دروازه‌ی بلوغِ کوهورت — «داده هنوز این مدل را تحمل نمی‌کند».

§۲۹.۶ سند صریح است:

> «Future-whale modeling requires mature historical cohorts.»
> «Do not train a meaningless model merely to satisfy a feature checklist.»

پس این ماژول یک چیز را جواب می‌دهد: آیا می‌شود مدلی آموخت که **بعداً هم**
معنا داشته باشد؟ و اگر نه، دقیقاً چه چیزی کم است — با عدد، نه با جمله‌ی کلی.

**«نه» یک نتیجه است، نه خطا.** خروجی این ماژول یک استثنا نیست؛ یک حکمِ
ساختاریافته است که در `model_runs` ثبت می‌شود تا فردا هم بشود دید چرا مدلی
وجود ندارد. استثنا فردا نامرئی است.

عمداً از `analysis/cohorts.py` جداست: آن ماتریسِ نگه‌داشتِ درون-فایل می‌سازد و
خروجی‌اش بخشی از قرارداد `MetricsBundle` است. این یکی به دفتر کل نگاه می‌کند و
کوهورت را از **نخستین خریدِ واقعیِ مشتری** می‌گیرد، نه از فایلِ جاری.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

# پوششی که سود را «محاسبه‌شدنی» می‌کند — همان آستانه‌ی `costs/basis.py`.
MIN_COST_COVERAGE = 0.999

REASON_SPAN = "span_too_short"
REASON_COHORTS = "too_few_cohorts"
REASON_CUSTOMERS = "too_few_customers"
REASON_POSITIVES = "too_few_positives"
REASON_PROFIT = "no_profit_basis"
REASON_VALIDATION = "no_validation_cohort"


@dataclass(frozen=True)
class MaturitySpec:
    """پیکربندی دروازه. پیش‌فرض‌ها عمداً محافظه‌کارانه‌اند (§۲۹.۶)."""

    observation_days: int = 90
    outcome_days: int = 365
    top_fraction: float = 0.10
    min_cohort_months: int = 6
    min_cohort_customers: int = 200
    min_positive_per_arm: int = 30
    train_fraction: float = 0.70

    @property
    def required_span_days(self) -> int:
        """کمینه‌ی بازه‌ی داده.

        یک پنجره‌ی مشاهده + **دو** پنجره‌ی نتیجه: یکی برای کوهورت‌های آموزش و
        یکی برای کوهورت‌های متأخر که §۱۸.۴ برای اعتبارسنجی می‌خواهد.
        """
        return self.observation_days + 2 * self.outcome_days


@dataclass(frozen=True)
class CohortMaturity:
    """حکمِ دروازه — همیشه با عدد، چه «بله» چه «نه»."""

    ok: bool
    reason_code: str | None
    reason_fa: str | None
    n_mature_customers: int
    n_train_customers: int
    n_validate_customers: int
    n_train_positives: int
    n_validate_positives: int
    n_cohort_months: int
    span_days: int
    required_span_days: int
    cost_coverage: float
    split_date: str | None
    requirements: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "reason_code": self.reason_code,
            "reason_fa": self.reason_fa,
            "n_mature_customers": self.n_mature_customers,
            "n_train_customers": self.n_train_customers,
            "n_validate_customers": self.n_validate_customers,
            "n_train_positives": self.n_train_positives,
            "n_validate_positives": self.n_validate_positives,
            "n_cohort_months": self.n_cohort_months,
            "span_days": self.span_days,
            "required_span_days": self.required_span_days,
            "cost_coverage": round(self.cost_coverage, 4),
            "split_date": self.split_date,
            "requirements": self.requirements,
        }


def mature_anchors(
    first_dates: pd.Series, *, data_max: str, spec: MaturitySpec,
) -> pd.Series:
    """لنگرِ مشتریانی که پنجره‌ی نتیجه‌شان **کامل مشاهده شده** است.

    مشتریِ سانسورشده حذف می‌شود، نه اینکه «غیرنهنگ» برچسب بخورد: نتیجه‌اش هنوز
    نیامده و صفر گرفتنش یعنی هر مشتری تازه‌ای خودبه‌خود ناموفق حساب شود.
    """
    if first_dates.empty:
        return pd.Series(dtype=object)
    anchors = pd.to_datetime(first_dates) + pd.Timedelta(days=spec.observation_days)
    complete = anchors + pd.Timedelta(days=spec.outcome_days)
    keep = complete <= pd.Timestamp(data_max)
    kept = anchors[keep]
    return pd.Series(
        kept.dt.strftime("%Y-%m-%d").to_numpy(), index=kept.index, name="anchor",
    )


def chronological_split(anchors: pd.Series, spec: MaturitySpec) -> str | None:
    """تاریخِ برشِ آموزش/اعتبارسنجی — **زمانی**، نه تصادفی (§۲۹.۱).

    برش روی صدکِ لنگرها گرفته می‌شود تا هر دو بازو مشتری داشته باشند؛ برشِ
    تقویمیِ ثابت روی داده‌ی نامتوازن یک بازو را خالی می‌کند.
    """
    if anchors.empty:
        return None
    ordered = sorted(anchors.to_numpy())
    index = min(len(ordered) - 1, int(len(ordered) * spec.train_fraction))
    return str(ordered[index])


def assess_cohort_maturity(
    first_dates: pd.Series,
    *,
    data_min: str,
    data_max: str,
    cost_coverage: float,
    spec: MaturitySpec | None = None,
) -> CohortMaturity:
    """آیا داده برای آموزشِ مدلِ نهنگ بالغ است؟"""
    spec = spec or MaturitySpec()
    span_days = int((pd.Timestamp(data_max) - pd.Timestamp(data_min)).days)
    anchors = mature_anchors(first_dates, data_max=data_max, spec=spec)
    split_date = chronological_split(anchors, spec)

    n_mature = int(len(anchors))
    if split_date is None:
        train = validate = pd.Series(dtype=object)
    else:
        train = anchors[anchors < split_date]
        validate = anchors[anchors >= split_date]
    n_train, n_validate = int(len(train)), int(len(validate))
    # برچسب یک برشِ صدکی است، پس تعداد مثبت‌ها از اندازه‌ی بازو درمی‌آید.
    n_train_pos = int(n_train * spec.top_fraction)
    n_validate_pos = int(n_validate * spec.top_fraction)
    months = (
        int(pd.to_datetime(anchors).dt.to_period("M").nunique()) if n_mature else 0
    )

    requirements = {
        "بازه‌ی داده (روز)": {"لازم": spec.required_span_days, "موجود": span_days},
        "کوهورت ماهانه‌ی بالغ": {"لازم": spec.min_cohort_months, "موجود": months},
        "مشتری بالغ": {"لازم": spec.min_cohort_customers, "موجود": n_mature},
        "نمونه‌ی مثبت (آموزش)": {
            "لازم": spec.min_positive_per_arm, "موجود": n_train_pos,
        },
        "نمونه‌ی مثبت (اعتبارسنجی)": {
            "لازم": spec.min_positive_per_arm, "موجود": n_validate_pos,
        },
        "پوشش بهای تمام‌شده": {"لازم": MIN_COST_COVERAGE, "موجود": round(cost_coverage, 4)},
    }

    def verdict(code: str, reason: str) -> CohortMaturity:
        return CohortMaturity(
            ok=False, reason_code=code, reason_fa=reason,
            n_mature_customers=n_mature, n_train_customers=n_train,
            n_validate_customers=n_validate, n_train_positives=n_train_pos,
            n_validate_positives=n_validate_pos, n_cohort_months=months,
            span_days=span_days, required_span_days=spec.required_span_days,
            cost_coverage=cost_coverage, split_date=split_date,
            requirements=requirements,
        )

    if cost_coverage < MIN_COST_COVERAGE:
        return verdict(REASON_PROFIT, (
            f"برچسبِ نهنگ باید بر پایه‌ی سود ناخالص باشد (§۱۸.۲) و پوشش بها "
            f"{round(cost_coverage * 100, 1)}٪ است. مدل آموزش نمی‌بیند تا عددِ "
            "درآمدی جای عددِ سودی جا نزند."
        ))
    if span_days < spec.required_span_days:
        return verdict(REASON_SPAN, (
            f"بازه‌ی داده {span_days} روز است؛ دست‌کم {spec.required_span_days} روز "
            f"لازم است ({spec.observation_days} روز مشاهده + دو دوره‌ی "
            f"{spec.outcome_days} روزه‌ی نتیجه) تا هم آموزش و هم اعتبارسنجی "
            "برچسبِ کاملاً مشاهده‌شده داشته باشند."
        ))
    if n_mature < spec.min_cohort_customers:
        return verdict(REASON_CUSTOMERS, (
            f"فقط {n_mature} مشتری پنجره‌ی نتیجه‌ی کاملش تمام شده؛ کمتر از "
            f"حداقلِ {spec.min_cohort_customers} نفر."
        ))
    if months < spec.min_cohort_months:
        return verdict(REASON_COHORTS, (
            f"فقط {months} کوهورت ماهانه‌ی بالغ وجود دارد؛ دست‌کم "
            f"{spec.min_cohort_months} کوهورت لازم است تا اعتبارسنجی روی "
            "کوهورت‌های بعدی (§۱۸.۴) ممکن شود."
        ))
    if not n_validate:
        return verdict(REASON_VALIDATION, (
            "هیچ کوهورتی نیست که هم بعد از دوره‌ی آموزش باشد و هم برچسبش کامل "
            "مشاهده شده باشد؛ اعتبارسنجی روی کوهورت متأخر ممکن نیست."
        ))
    if min(n_train_pos, n_validate_pos) < spec.min_positive_per_arm:
        return verdict(REASON_POSITIVES, (
            f"تعداد نمونه‌ی مثبت (آموزش {n_train_pos}، اعتبارسنجی "
            f"{n_validate_pos}) زیر حداقلِ {spec.min_positive_per_arm} است؛ "
            "زیر این اندازه هر عددی که مدل بدهد نوفه است."
        ))

    return CohortMaturity(
        ok=True, reason_code=None, reason_fa=None,
        n_mature_customers=n_mature, n_train_customers=n_train,
        n_validate_customers=n_validate, n_train_positives=n_train_pos,
        n_validate_positives=n_validate_pos, n_cohort_months=months,
        span_days=span_days, required_span_days=spec.required_span_days,
        cost_coverage=cost_coverage, split_date=split_date,
        requirements=requirements,
    )


__all__ = [
    "MIN_COST_COVERAGE",
    "REASON_COHORTS",
    "REASON_CUSTOMERS",
    "REASON_POSITIVES",
    "REASON_PROFIT",
    "REASON_SPAN",
    "REASON_VALIDATION",
    "CohortMaturity",
    "MaturitySpec",
    "assess_cohort_maturity",
    "chronological_split",
    "mature_anchors",
]
