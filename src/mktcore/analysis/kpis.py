"""محاسبه‌ی شاخص‌های کلیدی عملکرد (KPI) — با خالص‌سازی برگشت از فروش."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import pandas as pd

from ..ingest.cleaning import get_returns
from ..ingest.schema import ColumnRole, standard_column

_DATE = standard_column(ColumnRole.DATE)
_REVENUE = standard_column(ColumnRole.REVENUE)
_QUANTITY = standard_column(ColumnRole.QUANTITY)
_COST = standard_column(ColumnRole.COST)
_DISCOUNT = standard_column(ColumnRole.DISCOUNT)
_CUSTOMER = standard_column(ColumnRole.CUSTOMER_ID)
_ORDER = standard_column(ColumnRole.ORDER_ID)


@dataclass
class KPISet:
    """مجموعه‌ی شاخص‌های کلیدی محاسبه‌شده.

    قرارداد: total_revenue = فروش خالص (net_sales). برای فایل بدون برگشت،
    خالص و ناخالص برابرند و رفتار قبلی حفظ می‌شود.
    """

    total_revenue: float = 0.0
    gross_sales: float = 0.0  # مجموع ردیف‌های فروش (مثبت)
    returns_total: float = 0.0  # قدرمطلق مجموع برگشت از فروش
    returns_count: int = 0
    return_rate: float | None = None  # returns_total / gross_sales
    net_sales: float = 0.0  # ناخالص منهای برگشت
    discount_total: float | None = None  # فقط وقتی ستون تخفیف مبلغی باشد
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


def _net_monthly(df: pd.DataFrame, returns: pd.DataFrame) -> pd.Series:
    """سری ماهانه‌ی فروش خالص: خرید منهای برگشت هر ماه."""
    monthly = _period_revenue(df, "ME")
    if len(returns) and _DATE in returns.columns:
        ret_monthly = returns.set_index(_DATE)[_REVENUE].resample("ME").sum()
        monthly = monthly.add(ret_monthly, fill_value=0.0)
    return monthly


def compute_kpis(df: pd.DataFrame) -> KPISet:
    """محاسبه‌ی همه‌ی KPIها از DataFrame پاک‌شده‌ی استاندارد."""
    k = KPISet()
    if df.empty or _REVENUE not in df.columns:
        k.flags.append("داده‌ی کافی برای محاسبه‌ی KPI وجود ندارد.")
        return k

    returns = get_returns(df)

    k.gross_sales = float(df[_REVENUE].sum())
    k.returns_count = int(len(returns))
    k.returns_total = float(-returns[_REVENUE].sum()) if k.returns_count else 0.0
    k.net_sales = k.gross_sales - k.returns_total
    if k.gross_sales > 0 and k.returns_count:
        k.return_rate = k.returns_total / k.gross_sales
    k.total_revenue = k.net_sales

    if _DISCOUNT in df.columns:
        disc = pd.to_numeric(df[_DISCOUNT], errors="coerce").dropna()
        nonzero = disc[disc != 0]
        # فقط تخفیفِ «مبلغی» جمع‌پذیر است؛ ستون نسبتی (۰..۱) جمع معناداری ندارد
        if len(nonzero) and (nonzero.abs() > 1).mean() > 0.8:
            k.discount_total = float(nonzero.sum())

    # شمارش سفارش: فاکتورهای با جمع خالص مثبت (فاکتور کاملاً برگشتی نمی‌شمارد)
    positive_orders: pd.Index | None = None
    if _ORDER in df.columns:
        combined = df[[_ORDER, _REVENUE]]
        if k.returns_count and _ORDER in returns.columns:
            combined = pd.concat(
                [combined, returns[[_ORDER, _REVENUE]]], ignore_index=True)
        order_net = combined.groupby(_ORDER)[_REVENUE].sum()
        positive_orders = order_net[order_net > 0].index
        k.n_orders = int(len(positive_orders))
    else:
        k.n_orders = int(len(df))

    k.aov = k.net_sales / k.n_orders if k.n_orders else 0.0

    # درآمد روزانه‌ی میانگین (بر مبنای فروش خالص)
    days = max((df[_DATE].max() - df[_DATE].min()).days + 1, 1)
    k.avg_daily_revenue = k.net_sales / days

    # رشد ماهانه و سالانه بر سری خالص
    monthly = _net_monthly(df, returns)
    if len(monthly) >= 2 and monthly.iloc[-2] > 0:
        k.mom_growth = float((monthly.iloc[-1] - monthly.iloc[-2]) / monthly.iloc[-2])
    if len(monthly) >= 13 and monthly.iloc[-13] > 0:
        k.yoy_growth = float((monthly.iloc[-1] - monthly.iloc[-13]) / monthly.iloc[-13])

    # مشتری‌ها و نرخ تکرار
    if _CUSTOMER in df.columns:
        k.n_customers = int(df[_CUSTOMER].nunique())
        if k.n_customers:
            k.revenue_per_customer = k.net_sales / k.n_customers
            if _ORDER in df.columns:
                base = df[[_CUSTOMER, _ORDER]]
                if positive_orders is not None:
                    base = base[base[_ORDER].isin(positive_orders)]
                per_cust = base.groupby(_CUSTOMER)[_ORDER].nunique()
            else:
                per_cust = df.groupby(_CUSTOMER).size()
            k.repeat_rate = float((per_cust >= 2).mean()) if len(per_cust) else None

    # حاشیه‌ی سود (هزینه‌ی برگشتی‌ها هم کسر می‌شود)
    if _COST in df.columns and df[_COST].notna().any() and k.net_sales > 0:
        total_cost = float(df[_COST].sum())
        if k.returns_count and _COST in returns.columns:
            total_cost += float(returns[_COST].sum())  # مقادیر منفی، خودکار کسر
        k.gross_margin = (k.net_sales - total_cost) / k.net_sales
    else:
        k.flags.append("ستون هزینه موجود نیست؛ حاشیه‌ی سود و CAC/LTV محاسبه نشد.")

    return k


__all__ = ["KPISet", "compute_kpis"]
