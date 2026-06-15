"""تشخیص دلایل افت فروش: شناسایی ابعادی که بیشترین افت را به فروش تحمیل کرده‌اند."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..ingest.schema import ColumnRole, standard_column

_DATE = standard_column(ColumnRole.DATE)
_REVENUE = standard_column(ColumnRole.REVENUE)


@dataclass
class DeclineDriver:
    dimension: str  # نام بُعد (محصول/کانال/منطقه/...)
    label: str  # مقدار بُعد
    delta: float  # تغییر مطلق درآمد (منفی = افت)
    pct_change: float | None
    contribution_to_decline: float  # سهم از کل افت


@dataclass
class DiagnosticsReport:
    overall_delta: float = 0.0
    overall_pct: float | None = None
    period_label: str = ""
    drivers: list[DeclineDriver] = field(default_factory=list)

    @property
    def is_declining(self) -> bool:
        return self.overall_delta < 0

    def compact(self) -> dict:
        return {
            "تغییر_کلی_درصد": None if self.overall_pct is None else round(self.overall_pct * 100, 1),
            "دوره": self.period_label,
            "محرک‌های_افت": [
                {"بُعد": d.dimension, "مقدار": d.label,
                 "تغییر_درصد": None if d.pct_change is None else round(d.pct_change * 100, 1),
                 "سهم_از_افت": round(d.contribution_to_decline * 100, 1)}
                for d in self.drivers
            ],
        }


def diagnose(df: pd.DataFrame, *, period: str = "ME") -> DiagnosticsReport:
    """مقایسه‌ی دوره‌ی اخیر با دوره‌ی قبل و یافتن ابعادی که بیشترین افت را ساختند."""
    rep = DiagnosticsReport()
    if df.empty or _REVENUE not in df.columns:
        return rep

    monthly = df.set_index(_DATE)[_REVENUE].resample(period).sum()
    if len(monthly) < 2:
        return rep
    last_val, prev_val = float(monthly.iloc[-1]), float(monthly.iloc[-2])
    rep.overall_delta = last_val - prev_val
    rep.overall_pct = (last_val - prev_val) / prev_val if prev_val else None
    rep.period_label = f"{monthly.index[-1].date()} نسبت به {monthly.index[-2].date()}"

    # بازه‌ی دو دوره‌ی آخر (مرز ابتدای ماه از تایم‌استمپ پایان دوره)
    last_start = monthly.index[-1].replace(day=1)
    prev_start = monthly.index[-2].replace(day=1)
    last_df = df[df[_DATE] >= last_start]
    prev_df = df[(df[_DATE] >= prev_start) & (df[_DATE] < last_start)]

    total_decline = 0.0
    raw_drivers: list[DeclineDriver] = []
    for role in (ColumnRole.PRODUCT, ColumnRole.CHANNEL, ColumnRole.REGION,
                 ColumnRole.CATEGORY, ColumnRole.BRANCH, ColumnRole.SALESPERSON):
        col = standard_column(role)
        if col not in df.columns:
            continue
        last_g = last_df.groupby(col)[_REVENUE].sum()
        prev_g = prev_df.groupby(col)[_REVENUE].sum()
        labels = set(last_g.index) | set(prev_g.index)
        for lab in labels:
            delta = float(last_g.get(lab, 0)) - float(prev_g.get(lab, 0))
            if delta < 0:
                total_decline += -delta
            p = float(prev_g.get(lab, 0))
            pct = (float(last_g.get(lab, 0)) - p) / p if p > 0 else None
            raw_drivers.append(DeclineDriver(
                dimension=role.value, label=str(lab), delta=delta, pct_change=pct,
                contribution_to_decline=0.0,
            ))

    # فقط افت‌ها، مرتب بر اساس شدت
    decliners = [d for d in raw_drivers if d.delta < 0]
    for d in decliners:
        d.contribution_to_decline = (-d.delta) / total_decline if total_decline else 0.0
    decliners.sort(key=lambda d: d.delta)
    rep.drivers = decliners[:10]
    return rep


__all__ = ["DiagnosticsReport", "DeclineDriver", "diagnose"]
