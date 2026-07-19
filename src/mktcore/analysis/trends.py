"""تحلیل روند: سری زمانی درآمد، رشد MoM/YoY و میانگین متحرک.

ماه ناقص: آخرین ماه وقتی داده تا پایان ماه نرسیده «ناقص» است؛ رشد ماهانه فقط
بین ماه‌های کامل محاسبه می‌شود و برای ماه جاری MTD واقعی + برآورد پایان ماه
(nowcast وزن‌دار روز-هفته) جداگانه گزارش می‌شود — مقایسه‌ی ۲۱ روز با ۳۱ روز ممنوع.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..ingest.schema import ColumnRole, standard_column

_DATE = standard_column(ColumnRole.DATE)
_REVENUE = standard_column(ColumnRole.REVENUE)


def month_end(ts: pd.Timestamp) -> pd.Timestamp:
    """آخرین روز ماهِ یک تاریخ."""
    return (ts.normalize() + pd.offsets.MonthEnd(0))


def complete_month_series(monthly: pd.Series, data_max: pd.Timestamp) -> pd.Series:
    """حذف ماه انتهاییِ ناقص از یک سری ماهانه (ME)."""
    if len(monthly) and pd.notna(data_max) and data_max.normalize() < month_end(data_max):
        last_label = monthly.index[-1]
        if month_end(pd.Timestamp(last_label)) == month_end(data_max):
            return monthly.iloc[:-1]
    return monthly


@dataclass
class TrendResult:
    """نتیجه‌ی تحلیل روند."""

    daily: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    monthly: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    monthly_growth: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    moving_avg_7: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    moving_avg_30: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    overall_trend_pct: float | None = None  # شیب کلی به‌صورت درصد رشد در کل دوره
    partial_month: dict | None = None  # {label, days_covered, days_in_month, mtd_actual, nowcast}

    def compact(self) -> dict:
        """نمایش فشرده برای مدل: درآمد ماهانه‌ی اخیر و روند کلی."""
        recent = self.monthly.tail(12)
        out = {
            "درآمد_ماهانه_اخیر": {str(k.date()): round(float(v)) for k, v in recent.items()},
            "روند_کلی_درصد": None if self.overall_trend_pct is None else round(self.overall_trend_pct, 1),
        }
        if self.partial_month:
            pm = self.partial_month
            out["ماه_ناقص"] = {
                "ماه": pm["label"],
                "روز_پوشش": pm["days_covered"],
                "روز_ماه": pm["days_in_month"],
                "فروش_تاکنون": round(pm["mtd_actual"]),
                "برآورد_پایان_ماه": round(pm["nowcast"]),
                "هشدار": "رشد ماه جاری با ماه کامل مقایسه نشده است.",
            }
        return out


def _nowcast(daily: pd.Series, data_max: pd.Timestamp) -> dict:
    """برآورد پایان ماه جاری با وزن روز-هفته؛ با تاریخچه‌ی کم به برآورد خطی می‌افتد."""
    month_start = data_max.normalize().replace(day=1)
    m_end = month_end(data_max)
    days_in_month = int(m_end.day)
    days_covered = int((data_max.normalize() - month_start).days) + 1
    mtd = float(daily[daily.index >= month_start].sum())

    nowcast = mtd / max(days_covered, 1) * days_in_month
    history = daily[daily.index < month_start]
    if len(history) >= 14:
        weekday_mean = history.groupby(history.index.dayofweek).mean()
        all_days = pd.date_range(month_start, m_end, freq="D")
        w = weekday_mean.reindex(range(7)).fillna(weekday_mean.mean())
        total_w = float(w.loc[all_days.dayofweek].sum())
        elapsed_w = float(w.loc[all_days[:days_covered].dayofweek].sum())
        if elapsed_w > 0 and total_w > 0:
            nowcast = mtd / elapsed_w * total_w

    return {
        "label": f"{data_max.year}-{data_max.month:02d}",
        "days_covered": days_covered,
        "days_in_month": days_in_month,
        "mtd_actual": mtd,
        "nowcast": float(nowcast),
    }


def compute_trends(df: pd.DataFrame) -> TrendResult:
    """محاسبه‌ی سری‌های زمانی و نرخ رشد."""
    res = TrendResult()
    if df.empty or _REVENUE not in df.columns:
        return res

    ts = df.set_index(_DATE)[_REVENUE].sort_index()
    daily = ts.resample("D").sum()
    res.daily = daily
    res.monthly = ts.resample("ME").sum()
    res.moving_avg_7 = daily.rolling(7, min_periods=1).mean()
    res.moving_avg_30 = daily.rolling(30, min_periods=1).mean()

    data_max = pd.Timestamp(ts.index.max())
    complete = complete_month_series(res.monthly, data_max)
    res.monthly_growth = complete.pct_change()
    if len(complete) < len(res.monthly):
        res.partial_month = _nowcast(daily, data_max)

    # روند کلی: مقایسه‌ی ماه اول و آخرین ماه «کامل»
    if len(complete) >= 2:
        first = complete.iloc[0]
        last = complete.iloc[-1]
        if first > 0:
            res.overall_trend_pct = float((last - first) / first * 100)

    return res


__all__ = ["TrendResult", "compute_trends", "complete_month_series", "month_end"]
