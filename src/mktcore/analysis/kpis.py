"""محاسبه‌ی شاخص‌های کلیدی عملکرد (KPI)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import pandas as pd

from ..ingest.schema import ColumnRole, standard_column

_DATE = standard_column(ColumnRole.DATE)
_REVENUE = standard_column(ColumnRole.REVENUE)
_QUANTITY = standard_column(ColumnRole.QUANTITY)
_COST = standard_column(ColumnRole.COST)
_CUSTOMER = standard_column(ColumnRole.CUSTOMER_ID)
_ORDER = standard_column(ColumnRole.ORDER_ID)


@dataclass
class KPISet:
    """مجموعه‌ی شاخص‌های کلیدی محاسبه‌شده."""

    total_revenue: float = 0.0
    n_orders: int = 0
    n_customers: int = 0
    aov: float = 0.0  # میانگین ارزش سفارش
    avg_daily_revenue: float = 0.0
    mom_growth: float | None = None  # رشد ماه آخر نسبت به ماه قبل
    yoy_growth: float | None = None  # رشد سال‌به‌سال
    repeat_rate: float | None = None  # نرخ مشتری تکراری
    gross_margin: float | None = None  # حاشیه‌ی سود ناخالص (در صورت وجود هزینه)
    revenue_per_customer: float | None = None
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _period_revenue(df: pd.DataFrame, freq: str) -> pd.Series:
    """مجموع درآمد در هر دوره (M=ماهانه، …)."""
    return df.set_index(_DATE)[_REVENUE].resample(freq).sum()


def compute_kpis(df: pd.DataFrame) -> KPISet:
    """محاسبه‌ی همه‌ی KPIها از DataFrame پاک‌شده‌ی استاندارد."""
    k = KPISet()
    if df.empty or _REVENUE not in df.columns:
        k.flags.append("داده‌ی کافی برای محاسبه‌ی KPI وجود ندارد.")
        return k

    k.total_revenue = float(df[_REVENUE].sum())

    if _ORDER in df.columns:
        k.n_orders = int(df[_ORDER].nunique())
    else:
        k.n_orders = int(len(df))

    k.aov = k.total_revenue / k.n_orders if k.n_orders else 0.0

    # درآمد روزانه‌ی میانگین
    days = max((df[_DATE].max() - df[_DATE].min()).days + 1, 1)
    k.avg_daily_revenue = k.total_revenue / days

    # رشد ماهانه و سالانه
    monthly = _period_revenue(df, "ME")
    if len(monthly) >= 2 and monthly.iloc[-2] > 0:
        k.mom_growth = float((monthly.iloc[-1] - monthly.iloc[-2]) / monthly.iloc[-2])
    if len(monthly) >= 13 and monthly.iloc[-13] > 0:
        k.yoy_growth = float((monthly.iloc[-1] - monthly.iloc[-13]) / monthly.iloc[-13])

    # مشتری‌ها و نرخ تکرار
    if _CUSTOMER in df.columns:
        k.n_customers = int(df[_CUSTOMER].nunique())
        if k.n_customers:
            k.revenue_per_customer = k.total_revenue / k.n_customers
            order_col = _ORDER if _ORDER in df.columns else None
            if order_col:
                per_cust = df.groupby(_CUSTOMER)[order_col].nunique()
            else:
                per_cust = df.groupby(_CUSTOMER).size()
            k.repeat_rate = float((per_cust >= 2).mean())

    # حاشیه‌ی سود
    if _COST in df.columns and df[_COST].notna().any() and k.total_revenue > 0:
        total_cost = float(df[_COST].sum())
        k.gross_margin = (k.total_revenue - total_cost) / k.total_revenue
    else:
        k.flags.append("ستون هزینه موجود نیست؛ حاشیه‌ی سود و CAC/LTV محاسبه نشد.")

    return k


__all__ = ["KPISet", "compute_kpis"]
