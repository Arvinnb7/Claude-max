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
class TripleRule:
    """قاعده‌ی چندقلمی «اگر A و B، آن‌گاه C» — هم‌ارز خروجی FP-Growth در این مقیاس."""

    antecedents: tuple[str, str]
    consequent: str
    support: float
    confidence: float
    lift: float
    count: int


@dataclass
class BasketAnalysis:
    rules: list[AssociationRule] = field(default_factory=list)
    triple_rules: list[TripleRule] = field(default_factory=list)
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

    # مجموعه‌ی محصولات هر سبد (حذف مقادیر تهی و یکدست‌سازی به رشته)
    def _unique_items(s: pd.Series) -> list[str]:
        return sorted({str(x) for x in s if pd.notna(x)})

    baskets = df.groupby(basket_key)[_PRODUCT].apply(_unique_items)
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
    res.triple_rules = _mine_triples(baskets, item_count, pair_count, n_baskets)
    return res


# سقف اقلام هر سبد هنگام استخراج سه‌تایی‌ها (سبدهای عمده‌فروشی منفجر نشوند)
_TRIPLE_BASKET_CAP = 15
# فقط وقتی داده به‌قدر کافی بزرگ و سبدها چندقلمی باشند سه‌تایی می‌سازیم
_TRIPLE_MIN_BASKETS = 2000
_TRIPLE_MIN_AVG_SIZE = 3.0
_TRIPLE_TOP_PRODUCTS = 300


def _mine_triples(baskets, item_count: dict[str, int],
                  pair_count: dict[tuple[str, str], int], n_baskets: int) -> list[TripleRule]:
    """قواعد «A+B→C» با هرس Apriori: فقط گسترش جفت‌های از قبل frequent."""
    if n_baskets < _TRIPLE_MIN_BASKETS:
        return []
    avg_size = float(baskets.apply(len).mean())
    if avg_size < _TRIPLE_MIN_AVG_SIZE:
        return []

    min_count = max(5, int(0.002 * n_baskets))
    top = set(sorted(item_count, key=item_count.get, reverse=True)[:_TRIPLE_TOP_PRODUCTS])
    frequent_pairs = {p for p, c in pair_count.items()
                      if c >= min_count and p[0] in top and p[1] in top}
    if not frequent_pairs:
        return []

    triple_count: dict[tuple[str, str, str], int] = {}
    for items in baskets:
        keep = [i for i in items if i in top][:_TRIPLE_BASKET_CAP]
        if len(keep) < 3:
            continue
        for combo in combinations(keep, 3):  # از قبل مرتب است (baskets sorted)
            a, b, c = combo
            # هرس: دست‌کم یکی از جفت‌های درون سه‌تایی باید frequent باشد
            if (a, b) in frequent_pairs or (a, c) in frequent_pairs or (b, c) in frequent_pairs:
                triple_count[combo] = triple_count.get(combo, 0) + 1

    rules: list[TripleRule] = []
    for (a, b, c3), cnt in triple_count.items():
        if cnt < min_count:
            continue
        support = cnt / n_baskets
        # هر عضو یک‌بار consequent می‌شود، به‌شرط frequent بودن جفتِ antecedent
        for ante, cons in (((a, b), c3), ((a, c3), b), ((b, c3), a)):
            pc = pair_count.get(ante)
            if pc is None or pc < min_count:
                continue
            conf = cnt / pc
            lift = conf / (item_count[cons] / n_baskets)
            if lift >= 1.2:
                rules.append(TripleRule(antecedents=ante, consequent=cons,
                                        support=support, confidence=conf,
                                        lift=lift, count=cnt))
    rules.sort(key=lambda r: (-r.confidence, -r.lift))
    return rules[:200]


__all__ = ["BasketAnalysis", "AssociationRule", "TripleRule", "analyze_basket"]
