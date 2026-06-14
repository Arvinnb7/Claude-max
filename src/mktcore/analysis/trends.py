"""تحلیل روند: سری زمانی درآمد، رشد MoM/YoY و میانگین متحرک."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..ingest.schema import ColumnRole, standard_column

_DATE = standard_column(ColumnRole.DATE)
_REVENUE = standard_column(ColumnRole.REVENUE)


@dataclass
class TrendResult:
    """نتیجه‌ی تحلیل روند."""

    daily: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    monthly: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    monthly_growth: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    moving_avg_7: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    moving_avg_30: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    overall_trend_pct: float | None = None  # شیب کلی به‌صورت درصد رشد در کل دوره

    def compact(self) -> dict:
        """نمایش فشرده برای مدل: درآمد ماهانه‌ی اخیر و روند کلی."""
        recent = self.monthly.tail(12)
        return {
            "درآمد_ماهانه_اخیر": {str(k.date()): round(float(v)) for k, v in recent.items()},
            "روند_کلی_درصد": None if self.overall_trend_pct is None else round(self.overall_trend_pct, 1),
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
    res.monthly_growth = res.monthly.pct_change()
    res.moving_avg_7 = daily.rolling(7, min_periods=1).mean()
    res.moving_avg_30 = daily.rolling(30, min_periods=1).mean()

    # روند کلی: مقایسه‌ی میانگین ماه اول و آخر
    if len(res.monthly) >= 2:
        first = res.monthly.iloc[0]
        last = res.monthly.iloc[-1]
        if first > 0:
            res.overall_trend_pct = float((last - first) / first * 100)

    return res


__all__ = ["TrendResult", "compute_trends"]
