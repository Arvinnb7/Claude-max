"""تشخیص ناهنجاری در سری زمانی درآمد روزانه."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..ingest.schema import ColumnRole, standard_column

_DATE = standard_column(ColumnRole.DATE)
_REVENUE = standard_column(ColumnRole.REVENUE)


@dataclass
class Anomaly:
    date: str
    value: float
    expected: float
    z_score: float
    direction: str  # "جهش" یا "افت"


@dataclass
class AnomalyResult:
    anomalies: list[Anomaly] = field(default_factory=list)

    def compact(self, n: int = 8) -> list[dict]:
        ranked = sorted(self.anomalies, key=lambda a: -abs(a.z_score))[:n]
        return [
            {"تاریخ": a.date, "مقدار": round(a.value), "مورد_انتظار": round(a.expected),
             "انحراف_z": round(a.z_score, 1), "نوع": a.direction}
            for a in ranked
        ]


def detect_anomalies(df: pd.DataFrame, *, z_threshold: float = 3.0) -> AnomalyResult:
    """تشخیص ناهنجاری با باقیمانده‌ی روند (میانگین متحرک) و z-score.

    از میانگین/انحراف متحرک ۳۰ روزه استفاده می‌شود تا روند و فصلی‌بودن تا حدی
    خنثی شوند؛ نقاطی که باقیمانده‌شان از آستانه فراتر رود ناهنجار علامت می‌خورند.
    """
    res = AnomalyResult()
    if df.empty or _REVENUE not in df.columns:
        return res

    daily = df.set_index(_DATE)[_REVENUE].resample("D").sum()
    if len(daily) < 14:
        return res

    roll_mean = daily.rolling(30, min_periods=7, center=True).mean()
    roll_std = daily.rolling(30, min_periods=7, center=True).std().replace(0, np.nan)
    resid_z = (daily - roll_mean) / roll_std

    for date, z in resid_z.items():
        if pd.notna(z) and abs(z) >= z_threshold:
            res.anomalies.append(
                Anomaly(
                    date=str(date.date()),
                    value=float(daily[date]),
                    expected=float(roll_mean[date]),
                    z_score=float(z),
                    direction="جهش" if z > 0 else "افت",
                )
            )
    return res


__all__ = ["Anomaly", "AnomalyResult", "detect_anomalies"]
