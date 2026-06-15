"""تحلیل محصولات: پرفروش‌ها، رشد، سهم و تحلیل ABC."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..ingest.schema import ColumnRole, standard_column

_DATE = standard_column(ColumnRole.DATE)
_REVENUE = standard_column(ColumnRole.REVENUE)
_QUANTITY = standard_column(ColumnRole.QUANTITY)
_PRODUCT = standard_column(ColumnRole.PRODUCT)


@dataclass
class ProductStat:
    product: str
    revenue: float
    quantity: float
    orders: int
    share: float
    abc_class: str  # A / B / C
    growth: float | None  # رشد نیمه‌ی دوم نسبت به نیمه‌ی اول دوره


@dataclass
class ProductAnalysis:
    products: list[ProductStat] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return bool(self.products)

    def top(self, n: int = 10) -> list[ProductStat]:
        return self.products[:n]

    def compact(self, n: int = 8) -> list[dict]:
        return [
            {"محصول": p.product, "درآمد": round(p.revenue), "سهم": round(p.share * 100, 1),
             "کلاس_ABC": p.abc_class, "رشد": None if p.growth is None else round(p.growth * 100, 1)}
            for p in self.top(n)
        ]


def analyze_products(df: pd.DataFrame) -> ProductAnalysis:
    """تحلیل محصولات با سهم، رشد و طبقه‌بندی ABC (پارتو ۸۰/۹۵)."""
    res = ProductAnalysis()
    if _PRODUCT not in df.columns or df.empty:
        return res

    qty_col = _QUANTITY if _QUANTITY in df.columns else None
    agg = df.groupby(_PRODUCT).agg(
        revenue=(_REVENUE, "sum"),
        quantity=(qty_col, "sum") if qty_col else (_REVENUE, "count"),
        orders=(_REVENUE, "count"),
    ).sort_values("revenue", ascending=False)

    total = agg["revenue"].sum()
    agg["share"] = agg["revenue"] / total if total else 0.0
    cum = agg["share"].cumsum()

    # رشد: مقایسه‌ی نیمه‌ی دوم با نیمه‌ی اول بازه‌ی زمانی
    mid = df[_DATE].min() + (df[_DATE].max() - df[_DATE].min()) / 2
    first = df[df[_DATE] <= mid].groupby(_PRODUCT)[_REVENUE].sum()
    second = df[df[_DATE] > mid].groupby(_PRODUCT)[_REVENUE].sum()

    for prod, row in agg.iterrows():
        c = cum[prod]
        abc = "A" if c <= 0.8 else ("B" if c <= 0.95 else "C")
        f, s = float(first.get(prod, 0)), float(second.get(prod, 0))
        growth = (s - f) / f if f > 0 else None
        res.products.append(ProductStat(
            product=str(prod), revenue=float(row["revenue"]), quantity=float(row["quantity"]),
            orders=int(row["orders"]), share=float(row["share"]), abc_class=abc, growth=growth,
        ))
    return res


__all__ = ["ProductAnalysis", "ProductStat", "analyze_products"]
