"""تحلیل کوهورت: ماتریس نگه‌داشت مشتری بر اساس ماه نخستین خرید."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..ingest.schema import ColumnRole, standard_column

_DATE = standard_column(ColumnRole.DATE)
_CUSTOMER = standard_column(ColumnRole.CUSTOMER_ID)


@dataclass
class CohortResult:
    retention: pd.DataFrame = field(default_factory=pd.DataFrame)  # درصد نگه‌داشت
    counts: pd.DataFrame = field(default_factory=pd.DataFrame)  # تعداد مشتری

    @property
    def available(self) -> bool:
        return not self.retention.empty

    def compact(self) -> dict:
        """میانگین نگه‌داشت ماه‌های ۱ و ۳ (در صورت وجود)."""
        if self.retention.empty:
            return {}
        out: dict[str, float] = {}
        for m in (1, 3):
            if m in self.retention.columns:
                out[f"نگه‌داشت_ماه_{m}"] = round(float(self.retention[m].mean()), 3)
        return out


def compute_cohorts(df: pd.DataFrame) -> CohortResult:
    """ماتریس نگه‌داشت ماهانه بر اساس کوهورت ماه نخستین خرید."""
    res = CohortResult()
    if _CUSTOMER not in df.columns or df.empty:
        return res

    d = df[[_DATE, _CUSTOMER]].copy()
    d["order_month"] = d[_DATE].dt.to_period("M")
    cohort = d.groupby(_CUSTOMER)["order_month"].min().rename("cohort_month")
    d = d.join(cohort, on=_CUSTOMER)
    d["period_index"] = (
        (d["order_month"].dt.year - d["cohort_month"].dt.year) * 12
        + (d["order_month"].dt.month - d["cohort_month"].dt.month)
    )

    counts = (
        d.groupby(["cohort_month", "period_index"])[_CUSTOMER]
        .nunique()
        .unstack("period_index")
    )
    if counts.empty or 0 not in counts.columns:
        return res
    base = counts[0]
    retention = counts.divide(base, axis=0)
    counts.index = counts.index.astype(str)
    retention.index = retention.index.astype(str)
    res.counts = counts
    res.retention = retention
    return res


__all__ = ["CohortResult", "compute_cohorts"]
