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
    max_basket_customers: int = 1500,
) -> NextPurchaseAnalysis:
    """پیش‌بینی زمان و سبد خرید بعدی برای هر مشتری (وکتورایز و مقیاس‌پذیر)."""
    res = NextPurchaseAnalysis()
    if _CUSTOMER not in df.columns or df.empty:
        return res

    d = df.dropna(subset=[_CUSTOMER, _DATE]).copy()
    if d.empty:
        return res
    data_max = d[_DATE].max()
    order_col = _ORDER if (_ORDER in d.columns and d[_ORDER].notna().any()) else None

    # آماره‌های هر مشتری به‌صورت وکتورایز
    g = d.groupby(_CUSTOMER)
    last = g[_DATE].max()
    first = g[_DATE].min()
    n_dates = g[_DATE].nunique()
    if order_col:
        ov = d.groupby([_CUSTOMER, order_col])[_REVENUE].sum().groupby(level=0).mean()
    else:
        ov = g[_REVENUE].mean()

    span_days = (last - first).dt.days
    avg_interval = (span_days / (n_dates - 1).where(n_dates > 1)).astype(float)
    predicted = last + pd.to_timedelta(avg_interval.fillna(0), unit="D")
    overdue = (data_max - predicted).dt.days

    top_products = list(d.groupby(_PRODUCT)[_REVENUE].sum().sort_values(ascending=False).index[:3]) \
        if _PRODUCT in d.columns else []

    customers = list(last.index)
    np_by_id: dict[str, NextPurchase] = {}
    for cust in customers:
        nd = int(n_dates[cust])
        if nd >= 2:
            ov_days = int(overdue[cust]) if pd.notna(overdue[cust]) else 0
            status = ("سررسیدشده" if ov_days >= 0 else
                      ("نزدیک" if ov_days >= -near_window else "زود"))
            pred_str = predicted[cust].date().isoformat() if pd.notna(predicted[cust]) else None
            ai = float(avg_interval[cust]) if pd.notna(avg_interval[cust]) else None
        else:
            ov_days, status, pred_str, ai = 0, "نامشخص", None, None
        npr = NextPurchase(
            customer_id=str(cust),
            last_purchase=last[cust].date().isoformat(),
            avg_interval_days=ai, predicted_next_date=pred_str, status=status,
            overdue_days=ov_days, likely_products=[],
            expected_value=float(ov.get(cust, 0.0)),
        )
        np_by_id[str(cust)] = npr
        res.customers.append(npr)

    # سبد محتمل فقط برای مشتریان سررسیدشده/نزدیک (محدود برای کارایی)
    due = sorted([c for c in res.customers if c.status in ("سررسیدشده", "نزدیک")],
                 key=lambda c: -c.overdue_days)[:max_basket_customers]
    if due and _PRODUCT in d.columns:
        due_ids = {c.customer_id for c in due}
        bought_map = (
            d[d[_CUSTOMER].astype(str).isin(due_ids)]
            .groupby(_CUSTOMER)[_PRODUCT]
            .agg(lambda s: {str(x) for x in s if pd.notna(x)})
        )
        for c in due:
            bought = bought_map.get(c.customer_id, set())
            likely: list[str] = []
            if basket is not None and basket.available:
                for p in bought:
                    for rule in basket.complements_for(p, n=2):
                        if rule.consequent not in bought and rule.consequent not in likely:
                            likely.append(rule.consequent)
            for p in top_products:
                ps = str(p)
                if ps not in bought and ps not in likely:
                    likely.append(ps)
            c.likely_products = likely[:3]

    return res


__all__ = ["NextPurchaseAnalysis", "NextPurchase", "predict_next_purchases"]
