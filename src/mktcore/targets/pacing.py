"""برنامه‌ریزی روزانه/هفتگی برای رسیدن به تارگت ماهانه (pacing).

با درنظرگرفتن فروش تحقق‌یافته‌ی ماه جاری، فاصله تا تارگت و روزهای باقی‌مانده،
نرخ فروش روزانه‌ی لازم و یک برنامه‌ی هفتگی روز‌به‌روز (با تأکید بر روزهای اوج
فروش) محاسبه می‌شود.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..analysis.seasonality import SeasonalityResult
from ..ingest.schema import ColumnRole, standard_column

_DATE = standard_column(ColumnRole.DATE)
_REVENUE = standard_column(ColumnRole.REVENUE)

_WEEKDAY_FA = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"]


@dataclass
class DayPlan:
    date: str
    weekday: str
    target_revenue: float
    emphasis: str  # راهنمای تمرکز آن روز


@dataclass
class PacingPlan:
    monthly_target: float
    achieved: float
    gap: float
    days_elapsed: int
    days_remaining: int
    required_daily: float  # نرخ روزانه‌ی لازم برای باقی ماه
    on_track: bool
    pace_ratio: float  # نسبت فروش فعلی به مسیر ایده‌آل
    week_plan: list[DayPlan] = field(default_factory=list)

    def compact(self) -> dict:
        return {
            "تارگت_ماه": round(self.monthly_target),
            "محقق‌شده": round(self.achieved),
            "فاصله_تا_تارگت": round(self.gap),
            "روزهای_باقی‌مانده": self.days_remaining,
            "نرخ_روزانه_لازم": round(self.required_daily),
            "در_مسیر": self.on_track,
            "نسبت_پیشروی": round(self.pace_ratio, 2),
            "برنامه_هفته": [
                {"تاریخ": d.date, "روز": d.weekday, "هدف_روز": round(d.target_revenue),
                 "تمرکز": d.emphasis}
                for d in self.week_plan
            ],
        }


def build_pacing_plan(
    df: pd.DataFrame,
    monthly_target: float,
    seasonality: SeasonalityResult | None = None,
    *,
    as_of: pd.Timestamp | None = None,
) -> PacingPlan:
    """ساخت برنامه‌ی pacing برای ماه جاری و توزیع هفتگی هدف.

    Args:
        df: داده‌ی پاک‌شده.
        monthly_target: تارگت کل ماه جاری.
        seasonality: شاخص فصلی هفتگی برای وزن‌دهی روزها.
        as_of: تاریخ مبنا (پیش‌فرض: آخرین تاریخ داده).
    """
    as_of = as_of or df[_DATE].max()
    month_start = as_of.replace(day=1)
    next_month = (month_start + pd.offsets.MonthBegin(1))
    days_in_month = (next_month - month_start).days
    days_elapsed = (as_of - month_start).days + 1
    days_remaining = max(days_in_month - days_elapsed, 0)

    month_df = df[(df[_DATE] >= month_start) & (df[_DATE] <= as_of)]
    achieved = float(month_df[_REVENUE].sum())
    gap = max(monthly_target - achieved, 0.0)
    required_daily = gap / days_remaining if days_remaining else 0.0

    ideal_so_far = monthly_target * (days_elapsed / days_in_month) if days_in_month else 0.0
    pace_ratio = achieved / ideal_so_far if ideal_so_far > 0 else 1.0
    on_track = pace_ratio >= 0.95

    # توزیع هدفِ روزهای باقی‌مانده‌ی هفته‌ی پیشِ‌رو با وزن فصلی
    weekday_idx = seasonality.weekday_index if (seasonality and seasonality.weekday_index) else {}
    plan: list[DayPlan] = []
    upcoming = pd.date_range(as_of + pd.Timedelta(days=1), periods=min(7, days_remaining), freq="D")
    if len(upcoming):
        weights = []
        for d in upcoming:
            wd = _WEEKDAY_FA[d.dayofweek]
            weights.append(weekday_idx.get(wd, 1.0))
        wsum = sum(weights) or 1.0
        week_budget = required_daily * len(upcoming)
        for d, w in zip(upcoming, weights, strict=True):
            wd = _WEEKDAY_FA[d.dayofweek]
            day_target = week_budget * (w / wsum)
            emphasis = (
                "روز اوج فروش — تمرکز کمپین و تماس‌های فروش" if w >= 1.15
                else "روز عادی — پیگیری سرنخ‌ها و سبدهای رهاشده"
            )
            plan.append(DayPlan(date=d.date().isoformat(), weekday=wd,
                                target_revenue=day_target, emphasis=emphasis))

    return PacingPlan(
        monthly_target=monthly_target, achieved=achieved, gap=gap,
        days_elapsed=days_elapsed, days_remaining=days_remaining,
        required_daily=required_daily, on_track=on_track, pace_ratio=pace_ratio,
        week_plan=plan,
    )


__all__ = ["PacingPlan", "DayPlan", "build_pacing_plan"]
