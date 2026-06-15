"""پیش‌بینی خرید بعدی و سبد بعدی هر مشتری.

- زمان خرید بعدی: بر اساس میانگین فاصله‌ی بین خریدهای هر مشتری (cadence) و زمان
  سپری‌شده از آخرین خرید، تاریخ تقریبی خرید بعدی و وضعیت «سررسید/معوق» تعیین می‌شود.
- سبد بعدی: ترکیبی از قواعد انجمنی (محصولات مکمل تاریخچه‌ی مشتری) و محصولات
  پرفروشی که مشتری هنوز نخریده است.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..ingest.schema import ColumnRole, standard_column
from .market_basket import BasketAnalysis

_DATE = standard_column(ColumnRole.DATE)
_PRODUCT = standard_column(ColumnRole.PRODUCT)
_CUSTOMER = standard_column(ColumnRole.CUSTOMER_ID)
_ORDER = standard_column(ColumnRole.ORDER_ID)
_REVENUE = standard_column(ColumnRole.REVENUE)


@dataclass
class NextPurchase:
    customer_id: str
    last_purchase: str
    avg_interval_days: float | None
    predicted_next_date: str | None
    status: str  # "سررسیدشده" | "نزدیک" | "زود" | "نامشخص"
    overdue_days: int  # روزهای گذشته از پیش‌بینی (مثبت = معوق)
    likely_products: list[str] = field(default_factory=list)
    expected_value: float = 0.0


@dataclass
class NextPurchaseAnalysis:
    customers: list[NextPurchase] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return bool(self.customers)

    def due_now(self, n: int = 50) -> list[NextPurchase]:
        """مشتریانی که خریدشان سررسید شده یا معوق است (بیشترین تأخیر اول)."""
        due = [c for c in self.customers if c.status in ("سررسیدشده", "نزدیک")]
        return sorted(due, key=lambda c: -c.overdue_days)[:n]

    def compact(self, n: int = 10) -> list[dict]:
        return [
            {"مشتری": c.customer_id, "خرید_بعدی": c.predicted_next_date, "وضعیت": c.status,
             "تأخیر_روز": c.overdue_days, "سبد_محتمل": c.likely_products,
             "ارزش_مورد_انتظار": round(c.expected_value)}
            for c in self.due_now(n)
        ]


def predict_next_purchases(
    df: pd.DataFrame,
    basket: BasketAnalysis | None = None,
    *,
    near_window: int = 14,
) -> NextPurchaseAnalysis:
    """پیش‌بینی زمان و سبد خرید بعدی برای هر مشتری."""
    res = NextPurchaseAnalysis()
    if _CUSTOMER not in df.columns or df.empty:
        return res

    data_max = df[_DATE].max()
    order_col = _ORDER if _ORDER in df.columns else None

    # میانگین ارزش هر سفارش مشتری (برای ارزش مورد انتظار)
    if order_col:
        order_value = df.groupby([_CUSTOMER, order_col])[_REVENUE].sum()
        avg_order_value = order_value.groupby(level=0).mean()
    else:
        avg_order_value = df.groupby(_CUSTOMER)[_REVENUE].mean()

    # پرفروش‌های کلی (برای پیشنهاد به مشتریان کم‌سابقه)
    top_products = list(df.groupby(_PRODUCT)[_REVENUE].sum().sort_values(ascending=False).index[:3])

    for cust, g in df.groupby(_CUSTOMER):
        if order_col:
            dates = g.groupby(order_col)[_DATE].min().sort_values()
        else:
            dates = g[_DATE].sort_values()
        unique_dates = pd.Series(sorted(dates.unique()))
        last = pd.Timestamp(unique_dates.iloc[-1])

        if len(unique_dates) >= 2:
            intervals = unique_dates.diff().dropna().dt.days
            avg_interval = float(intervals.mean())
            predicted = last + pd.Timedelta(days=avg_interval)
            overdue = int((data_max - predicted).days)
            if overdue >= 0:
                status = "سررسیدشده"
            elif overdue >= -near_window:
                status = "نزدیک"
            else:
                status = "زود"
            predicted_str = predicted.date().isoformat()
        else:
            avg_interval = None
            predicted_str = None
            overdue = 0
            status = "نامشخص"

        # سبد محتمل: مکمل‌های محصولات تاریخچه + پرفروش‌هایی که نخریده
        bought = set(g[_PRODUCT].unique())
        likely: list[str] = []
        if basket is not None and basket.available:
            for p in bought:
                for rule in basket.complements_for(p, n=2):
                    if rule.consequent not in bought and rule.consequent not in likely:
                        likely.append(rule.consequent)
        for p in top_products:
            if p not in bought and p not in likely:
                likely.append(p)
        likely = likely[:3]

        res.customers.append(NextPurchase(
            customer_id=str(cust),
            last_purchase=last.date().isoformat(),
            avg_interval_days=avg_interval,
            predicted_next_date=predicted_str,
            status=status,
            overdue_days=overdue,
            likely_products=likely,
            expected_value=float(avg_order_value.get(cust, 0.0)),
        ))

    return res


__all__ = ["NextPurchaseAnalysis", "NextPurchase", "predict_next_purchases"]
