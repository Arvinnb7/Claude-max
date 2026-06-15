"""تحلیل عملکرد فروشنده‌ها و شعب به‌صورت جداگانه."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..ingest.schema import ColumnRole, standard_column

_DATE = standard_column(ColumnRole.DATE)
_REVENUE = standard_column(ColumnRole.REVENUE)
_ORDER = standard_column(ColumnRole.ORDER_ID)
_CUSTOMER = standard_column(ColumnRole.CUSTOMER_ID)


@dataclass
class EntityPerformance:
    name: str
    revenue: float
    orders: int
    customers: int
    aov: float
    share: float
    growth: float | None  # رشد نیمه‌ی دوم نسبت به نیمه‌ی اول
    rank: int = 0


@dataclass
class PerformanceAnalysis:
    by_salesperson: list[EntityPerformance] = field(default_factory=list)
    by_branch: list[EntityPerformance] = field(default_factory=list)

    @property
    def has_salesperson(self) -> bool:
        return bool(self.by_salesperson)

    @property
    def has_branch(self) -> bool:
        return bool(self.by_branch)

    def compact(self) -> dict:
        def _c(items: list[EntityPerformance]) -> list[dict]:
            return [
                {"نام": e.name, "درآمد": round(e.revenue), "سهم": round(e.share * 100, 1),
                 "سفارش": e.orders, "رشد": None if e.growth is None else round(e.growth * 100, 1)}
                for e in items
            ]
        out: dict = {}
        if self.has_branch:
            out["شعب"] = _c(self.by_branch)
        if self.has_salesperson:
            out["فروشندگان"] = _c(self.by_salesperson)
        return out


def _analyze_dimension(df: pd.DataFrame, col: str) -> list[EntityPerformance]:
    order_col = _ORDER if _ORDER in df.columns else None
    cust_col = _CUSTOMER if _CUSTOMER in df.columns else None
    mid = df[_DATE].min() + (df[_DATE].max() - df[_DATE].min()) / 2
    first = df[df[_DATE] <= mid].groupby(col)[_REVENUE].sum()
    second = df[df[_DATE] > mid].groupby(col)[_REVENUE].sum()

    out: list[EntityPerformance] = []
    grand_total = df[_REVENUE].sum()
    for name, g in df.groupby(col):
        revenue = float(g[_REVENUE].sum())
        orders = int(g[order_col].nunique()) if order_col else int(len(g))
        customers = int(g[cust_col].nunique()) if cust_col else 0
        f, s = float(first.get(name, 0)), float(second.get(name, 0))
        growth = (s - f) / f if f > 0 else None
        out.append(EntityPerformance(
            name=str(name), revenue=revenue, orders=orders, customers=customers,
            aov=revenue / orders if orders else 0.0,
            share=revenue / grand_total if grand_total else 0.0,
            growth=growth,
        ))
    out.sort(key=lambda e: -e.revenue)
    for i, e in enumerate(out, 1):
        e.rank = i
    return out


def analyze_performance(df: pd.DataFrame) -> PerformanceAnalysis:
    """تحلیل عملکرد به تفکیک فروشنده و شعبه (در صورت وجود ستون‌ها)."""
    res = PerformanceAnalysis()
    if df.empty:
        return res
    sp_col = standard_column(ColumnRole.SALESPERSON)
    br_col = standard_column(ColumnRole.BRANCH)
    if sp_col in df.columns:
        res.by_salesperson = _analyze_dimension(df, sp_col)
    if br_col in df.columns:
        res.by_branch = _analyze_dimension(df, br_col)
    return res


__all__ = ["PerformanceAnalysis", "EntityPerformance", "analyze_performance"]
