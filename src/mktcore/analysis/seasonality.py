"""تحلیل فصلی‌بودن: شاخص‌های ماهانه/هفتگی و قدرت فصلی."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..ingest.schema import ColumnRole, standard_column

_DATE = standard_column(ColumnRole.DATE)
_REVENUE = standard_column(ColumnRole.REVENUE)

_WEEKDAY_FA = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"]


@dataclass
class SeasonalityResult:
    weekday_index: dict[str, float] = field(default_factory=dict)
    month_index: dict[int, float] = field(default_factory=dict)
    seasonality_strength: float | None = None  # ۰ تا ۱
    has_yearly: bool = False

    def compact(self) -> dict:
        peak_day = max(self.weekday_index, key=self.weekday_index.get) if self.weekday_index else None
        return {
            "قوی‌ترین_روز_هفته": peak_day,
            "شاخص_روز_هفته": {k: round(v, 2) for k, v in self.weekday_index.items()},
            "قدرت_فصلی": None if self.seasonality_strength is None else round(self.seasonality_strength, 2),
        }


def compute_seasonality(df: pd.DataFrame) -> SeasonalityResult:
    """شاخص‌های فصلی و قدرت فصلی (بر پایه‌ی تجزیه‌ی STL در صورت داده‌ی کافی)."""
    res = SeasonalityResult()
    if df.empty or _REVENUE not in df.columns:
        return res

    daily = df.set_index(_DATE)[_REVENUE].resample("D").sum()
    overall_mean = daily.mean()
    if overall_mean <= 0:
        return res

    # شاخص روز هفته
    by_weekday = daily.groupby(daily.index.dayofweek).mean()
    res.weekday_index = {
        _WEEKDAY_FA[int(d)]: float(v / overall_mean) for d, v in by_weekday.items()
    }

    # شاخص ماه
    monthly = daily.resample("ME").sum()
    if len(monthly) >= 12:
        by_month = monthly.groupby(monthly.index.month).mean()
        mm = by_month.mean()
        if mm > 0:
            res.month_index = {int(m): float(v / mm) for m, v in by_month.items()}
            res.has_yearly = True

    # قدرت فصلی با STL (نیازمند حداقل دو دوره)
    try:
        from statsmodels.tsa.seasonal import STL

        if len(daily) >= 14:
            stl = STL(daily, period=7, robust=True).fit()
            var_resid = np.nanvar(stl.resid)
            var_seas_resid = np.nanvar(stl.seasonal + stl.resid)
            if var_seas_resid > 0:
                res.seasonality_strength = float(max(0.0, 1 - var_resid / var_seas_resid))
    except Exception:
        pass

    return res


__all__ = ["SeasonalityResult", "compute_seasonality"]
