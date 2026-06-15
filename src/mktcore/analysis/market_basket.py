"""تحلیل سبد خرید (market basket): محصولات مکملِ پرتکرار با قواعد انجمنی.

برای هر جفت محصول که در یک سفارش با هم خریده می‌شوند، شاخص‌های support،
confidence و lift محاسبه می‌شود تا محصولات مکمل (که خرید یکی احتمال خرید
دیگری را بالا می‌برد) شناسایی شوند.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations

import pandas as pd

from ..ingest.schema import ColumnRole, standard_column

_PRODUCT = standard_column(ColumnRole.PRODUCT)
_ORDER = standard_column(ColumnRole.ORDER_ID)
_CUSTOMER = standard_column(ColumnRole.CUSTOMER_ID)


@dataclass
class AssociationRule:
    antecedent: str  # اگر این خریده شد
    consequent: str  # آن‌گاه این هم
    support: float  # نسبت سفارش‌های حاوی هر دو
    confidence: float  # احتمال خرید consequent به‌شرط antecedent
    lift: float  # نسبت به خرید مستقل (>۱ یعنی مکمل)
    pair_count: int


@dataclass
class BasketAnalysis:
    rules: list[AssociationRule] = field(default_factory=list)
    avg_basket_size: float = 0.0

    @property
    def available(self) -> bool:
        return bool(self.rules)

    def top(self, n: int = 10) -> list[AssociationRule]:
        return self.rules[:n]

    def complements_for(self, product: str, n: int = 3) -> list[AssociationRule]:
        """مکمل‌های یک محصول مشخص (بر اساس بالاترین lift)."""
        items = [r for r in self.rules if r.antecedent == product]
        return sorted(items, key=lambda r: -r.lift)[:n]

    def compact(self, n: int = 10) -> list[dict]:
        return [
            {"اگر_خرید": r.antecedent, "آنگاه": r.consequent,
             "اطمینان": round(r.confidence * 100, 1), "lift": round(r.lift, 2),
             "تعداد": r.pair_count}
            for r in self.top(n)
        ]


def analyze_basket(
    df: pd.DataFrame, *, min_support: float = 0.005, min_lift: float = 1.05
) -> BasketAnalysis:
    """قواعد انجمنی جفتی را از سفارش‌های چندقلمی استخراج می‌کند.

    اگر ستون سفارش نباشد، از (مشتری، تاریخ) به‌عنوان واحد سبد استفاده می‌شود.
    """
    res = BasketAnalysis()
    if _PRODUCT not in df.columns or df.empty:
        return res

    if _ORDER in df.columns:
        basket_key = _ORDER
    elif _CUSTOMER in df.columns:
        df = df.assign(_bk=df[_CUSTOMER].astype(str) + "|" + df[standard_column(ColumnRole.DATE)].astype(str))
        basket_key = "_bk"
    else:
        return res

    # مجموعه‌ی محصولات هر سبد
    baskets = df.groupby(basket_key)[_PRODUCT].apply(lambda s: sorted(set(s)))
    n_baskets = len(baskets)
    if n_baskets == 0:
        return res
    res.avg_basket_size = float(baskets.apply(len).mean())

    # شمارش تکی و جفتی
    item_count: dict[str, int] = {}
    pair_count: dict[tuple[str, str], int] = {}
    for items in baskets:
        for it in items:
            item_count[it] = item_count.get(it, 0) + 1
        for a, b in combinations(items, 2):
            pair_count[(a, b)] = pair_count.get((a, b), 0) + 1

    rules: list[AssociationRule] = []
    for (a, b), c in pair_count.items():
        support = c / n_baskets
        if support < min_support:
            continue
        # هر دو جهت
        for ante, cons in ((a, b), (b, a)):
            conf = c / item_count[ante]
            lift = conf / (item_count[cons] / n_baskets)
            if lift >= min_lift:
                rules.append(AssociationRule(
                    antecedent=ante, consequent=cons, support=support,
                    confidence=conf, lift=lift, pair_count=c,
                ))

    rules.sort(key=lambda r: (-r.lift, -r.confidence))
    res.rules = rules
    return res


__all__ = ["BasketAnalysis", "AssociationRule", "analyze_basket"]
