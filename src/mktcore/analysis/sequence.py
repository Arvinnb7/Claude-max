"""الگوهای خرید توالی: «اگر A خریده شد، معمولاً در بازه‌ی n روز B هم خریده می‌شود».

برای هر جفت محصول (A→B)، نسبت مشتریانی که پس از خرید A در بازه‌ی مشخص B را هم
خریده‌اند و میانه‌ی فاصله‌ی زمانی محاسبه می‌شود. سپس مشتریانی که A را خریده‌اند
ولی هنوز B را نخریده‌اند و در «پنجره‌ی فرصت» هستند فهرست می‌شوند تا روی آن‌ها
مانور بازاریابی انجام شود.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..ingest.schema import ColumnRole, standard_column

_DATE = standard_column(ColumnRole.DATE)
_PRODUCT = standard_column(ColumnRole.PRODUCT)
_CUSTOMER = standard_column(ColumnRole.CUSTOMER_ID)


@dataclass
class SequencePattern:
    antecedent: str  # A
    consequent: str  # B
    completion_rate: float  # نسبت خریداران A که بعداً B هم خریدند
    median_lag_days: float  # میانه‌ی فاصله‌ی A→B
    n_antecedent_buyers: int
    incomplete_customers: list[str] = field(default_factory=list)  # خریدند A، هنوز نه B (در پنجره)

    def compact(self) -> dict:
        return {
            "الگو": f"{self.antecedent} ← {self.consequent}",
            "نرخ_تکمیل": round(self.completion_rate * 100, 1),
            "میانه_فاصله_روز": round(self.median_lag_days, 1),
            "تعداد_خریدار_A": self.n_antecedent_buyers,
            "مشتریان_ناتمام": len(self.incomplete_customers),
        }


@dataclass
class SequenceAnalysis:
    patterns: list[SequencePattern] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return bool(self.patterns)

    def top(self, n: int = 8) -> list[SequencePattern]:
        return self.patterns[:n]

    def compact(self, n: int = 6) -> list[dict]:
        return [p.compact() for p in self.top(n)]


def analyze_sequences(
    df: pd.DataFrame,
    *,
    window_days: int = 45,
    min_completion: float = 0.25,
    min_buyers: int = 20,
    top_products: int = 25,
    max_incomplete: int = 1000,
) -> SequenceAnalysis:
    """کشف الگوهای توالی A→B و فهرست مشتریان ناتمام برای هدف‌گیری.

    برای مقیاس‌پذیری، تحلیل فقط روی پرتکرارترین محصولات (top_products) و به‌صورت
    وکتورایز انجام می‌شود تا روی داده‌های بزرگ (ده‌ها هزار مشتری و محصول) هم سریع باشد.
    """
    res = SequenceAnalysis()
    if _CUSTOMER not in df.columns or _PRODUCT not in df.columns or df.empty:
        return res

    df = df.dropna(subset=[_CUSTOMER, _PRODUCT, _DATE])
    if df.empty:
        return res
    data_max = df[_DATE].max()

    # محدودسازی به پرتکرارترین محصولات بر اساس تعداد خریدار یکتا
    buyers_per_product = df.groupby(_PRODUCT)[_CUSTOMER].nunique().sort_values(ascending=False)
    keep = [p for p in buyers_per_product.index[:top_products]
            if buyers_per_product[p] >= min_buyers]
    if len(keep) < 2:
        return res

    sub = df[df[_PRODUCT].isin(keep)]
    first_buy = sub.groupby([_CUSTOMER, _PRODUCT])[_DATE].min().reset_index()
    pivot = first_buy.pivot(index=_CUSTOMER, columns=_PRODUCT, values=_DATE)

    for a in keep:
        if a not in pivot.columns:
            continue
        mask_a = pivot[a].notna()
        n_a = int(mask_a.sum())
        if n_a < min_buyers:
            continue
        a_dates = pivot.loc[mask_a, a]
        days_since_a = (data_max - a_dates).dt.days
        for b in keep:
            if a == b or b not in pivot.columns:
                continue
            b_dates = pivot.loc[mask_a, b]
            lag = (b_dates - a_dates).dt.days
            in_window = b_dates.notna() & (lag > 0) & (lag <= window_days)
            n_completed = int(in_window.sum())
            completion_rate = n_completed / n_a
            if completion_rate < min_completion or n_completed < 5:
                continue
            median_lag = float(lag[in_window].median())
            # مشتریان ناتمام: B را در بازه نخریده‌اند ولی هنوز در پنجره‌ی فرصت‌اند
            incomplete_mask = (~in_window) & (days_since_a <= window_days)
            incomplete = [str(c) for c in a_dates.index[incomplete_mask][:max_incomplete]]
            res.patterns.append(SequencePattern(
                antecedent=str(a), consequent=str(b), completion_rate=completion_rate,
                median_lag_days=median_lag, n_antecedent_buyers=n_a,
                incomplete_customers=incomplete,
            ))

    res.patterns.sort(key=lambda p: -p.completion_rate)
    return res


__all__ = ["SequenceAnalysis", "SequencePattern", "analyze_sequences"]
