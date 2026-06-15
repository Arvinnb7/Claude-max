"""الگوهای خرید توالی: «اگر A خریده شد، معمولاً در بازه‌ی n روز B هم خریده می‌شود».

برای هر جفت محصول (A→B)، نسبت مشتریانی که پس از خرید A در بازه‌ی مشخص B را هم
خریده‌اند و میانه‌ی فاصله‌ی زمانی محاسبه می‌شود. سپس مشتریانی که A را خریده‌اند
ولی هنوز B را نخریده‌اند و در «پنجره‌ی فرصت» هستند فهرست می‌شوند تا روی آن‌ها
مانور بازاریابی انجام شود.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
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
) -> SequenceAnalysis:
    """کشف الگوهای توالی A→B و فهرست مشتریان ناتمام برای هدف‌گیری.

    منطق: برای هر جفت، نگاه می‌کنیم خریداران A چه نسبتی بعد از اولین خرید A و در
    بازه‌ی `window_days` محصول B را هم خریده‌اند. مشتریان ناتمام = کسانی که A را
    خریده‌اند، B را هنوز نخریده‌اند و هنوز در پنجره‌ی فرصت قرار دارند.
    """
    res = SequenceAnalysis()
    if _CUSTOMER not in df.columns or _PRODUCT not in df.columns or df.empty:
        return res

    data_max = df[_DATE].max()
    # اولین تاریخ خرید هر (مشتری، محصول)
    first_buy = df.groupby([_CUSTOMER, _PRODUCT])[_DATE].min().reset_index()
    pivot = first_buy.pivot(index=_CUSTOMER, columns=_PRODUCT, values=_DATE)
    products = list(pivot.columns)

    for a in products:
        buyers_a = pivot[pivot[a].notna()]
        n_a = len(buyers_a)
        if n_a < min_buyers:
            continue
        for b in products:
            if a == b:
                continue
            lags = (buyers_a[b] - buyers_a[a]).dt.days
            # تکمیل‌شده: B بعد از A و در بازه
            completed = lags[(lags > 0) & (lags <= window_days)]
            completion_rate = len(completed) / n_a
            if completion_rate < min_completion or len(completed) < 5:
                continue
            median_lag = float(np.median(completed)) if len(completed) else float(window_days)

            # مشتریان ناتمام: A خریده، B نخریده (یا بعد از پنجره)، و هنوز در پنجره‌ی فرصت
            incomplete = []
            for cust, row in buyers_a.iterrows():
                a_date = row[a]
                b_date = row[b]
                days_since_a = (data_max - a_date).days
                bought_b_in_window = pd.notna(b_date) and 0 < (b_date - a_date).days <= window_days
                if not bought_b_in_window and days_since_a <= window_days:
                    incomplete.append(str(cust))

            res.patterns.append(SequencePattern(
                antecedent=str(a), consequent=str(b), completion_rate=completion_rate,
                median_lag_days=median_lag, n_antecedent_buyers=n_a,
                incomplete_customers=incomplete,
            ))

    res.patterns.sort(key=lambda p: -p.completion_rate)
    return res


__all__ = ["SequenceAnalysis", "SequencePattern", "analyze_sequences"]
