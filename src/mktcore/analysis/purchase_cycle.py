"""چرخه‌ی خرید: به تفکیک مشتری و محصول، تشخیص محصول مصرفی/تک‌خریدی و اعلان‌ها.

- چرخه‌ی محصول: میانه‌ی فاصله‌ی بازخرید هر کالا و نرخ بازخرید.
- طبقه‌بندی: «مصرفی» (نرخ بازخرید بالا و چرخه‌ی منظم) در برابر «تک‌خریدی».
- چرخه‌ی مشتری-محصول: برای کالاهای مصرفی، برای هر مشتری چقدر از چرخه گذشته یا
  چقدر مانده — به‌صورت اعلان (notification).
- هدف‌گیری تک‌خریدی: برای کالای تک‌خریدی، مشتریان بالقوه = کسانی که کالای پیش‌نیاز/
  مرتبط را خریده‌اند ولی هنوز خودِ کالا را نگرفته‌اند (خریداران فعلی حذف می‌شوند).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..ingest.schema import ColumnRole, standard_column
from .market_basket import BasketAnalysis

_DATE = standard_column(ColumnRole.DATE)
_PRODUCT = standard_column(ColumnRole.PRODUCT)
_CUSTOMER = standard_column(ColumnRole.CUSTOMER_ID)

CONSUMABLE = "مصرفی"
ONE_TIME = "تک‌خریدی"
UNKNOWN = "نامشخص"


@dataclass
class ProductCycle:
    product: str
    product_type: str  # مصرفی / تک‌خریدی / نامشخص
    repurchase_rate: float  # نسبت خریدارانی که ≥۲ بار خریده‌اند
    median_cycle_days: float | None  # میانه‌ی فاصله‌ی بازخرید
    n_buyers: int
    n_repeat_buyers: int

    def compact(self) -> dict:
        return {
            "محصول": self.product, "نوع": self.product_type,
            "نرخ_بازخرید": round(self.repurchase_rate * 100, 1),
            "چرخه_روز": None if self.median_cycle_days is None else round(self.median_cycle_days),
            "خریداران": self.n_buyers,
        }


@dataclass
class CycleNotification:
    customer_id: str
    product: str
    last_purchase: str
    cycle_days: float
    days_since: int
    days_offset: int  # مثبت = عقب‌افتاده از چرخه، منفی = مانده تا چرخه
    status: str  # «عقب‌افتاده» / «نزدیک» / «در مسیر»

    def message(self) -> str:
        if self.days_offset > 0:
            return f"مشتری {self.customer_id}: {self.days_offset} روز از چرخه‌ی خرید «{self.product}» گذشته است."
        return f"مشتری {self.customer_id}: {abs(self.days_offset)} روز تا چرخه‌ی خرید «{self.product}» مانده است."

    def compact(self) -> dict:
        return {"مشتری": self.customer_id, "محصول": self.product,
                "چرخه_روز": round(self.cycle_days), "انحراف_روز": self.days_offset,
                "وضعیت": self.status, "پیام": self.message()}


@dataclass
class OneTimeTarget:
    product: str
    gateway_products: list[str]  # کالاهای پیش‌نیاز/مرتبط
    potential_customers: list[str] = field(default_factory=list)  # بالقوه‌ها (نخریده‌اند)
    existing_buyers: int = 0

    def compact(self) -> dict:
        return {"محصول": self.product, "کالاهای_مرتبط": self.gateway_products,
                "تعداد_بالقوه": len(self.potential_customers),
                "خریداران_فعلی": self.existing_buyers}


@dataclass
class PurchaseCycleAnalysis:
    product_cycles: list[ProductCycle] = field(default_factory=list)
    notifications: list[CycleNotification] = field(default_factory=list)
    onetime_targets: list[OneTimeTarget] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return bool(self.product_cycles)

    def overdue(self, n: int = 50) -> list[CycleNotification]:
        items = [x for x in self.notifications if x.status in ("عقب‌افتاده", "نزدیک")]
        return sorted(items, key=lambda x: -x.days_offset)[:n]

    def consumables(self) -> list[ProductCycle]:
        return [c for c in self.product_cycles if c.product_type == CONSUMABLE]

    def onetime(self) -> list[ProductCycle]:
        return [c for c in self.product_cycles if c.product_type == ONE_TIME]

    def compact(self) -> dict:
        return {
            "چرخه_محصولات": [c.compact() for c in self.product_cycles],
            "اعلان‌های_چرخه": [x.compact() for x in self.overdue(12)],
            "هدف‌گیری_تک‌خریدی": [t.compact() for t in self.onetime_targets],
        }


def _intervals_by_customer(g: pd.DataFrame) -> list[float]:
    """فاصله‌های بازخرید (روز) درون هر مشتری برای یک محصول."""
    out: list[float] = []
    for _, cg in g.groupby(_CUSTOMER):
        dates = pd.Series(sorted(cg[_DATE].dt.normalize().unique()))
        if len(dates) >= 2:
            out.extend(dates.diff().dropna().dt.days.tolist())
    return out


def analyze_purchase_cycles(
    df: pd.DataFrame,
    basket: BasketAnalysis | None = None,
    *,
    consumable_repurchase_threshold: float = 0.30,
    min_buyers: int = 15,
    near_fraction: float = 0.2,
    max_notifications: int = 3000,
    max_onetime_targets: int = 25,
) -> PurchaseCycleAnalysis:
    """تحلیل چرخه‌ی خرید، طبقه‌بندی مصرفی/تک‌خریدی و تولید اعلان‌ها و هدف‌گیری.

    کاملاً وکتورایز است تا روی داده‌های بزرگ (هزاران محصول و ده‌ها هزار مشتری) سریع باشد.
    """
    res = PurchaseCycleAnalysis()
    if _PRODUCT not in df.columns or _CUSTOMER not in df.columns or df.empty:
        return res

    d = df.dropna(subset=[_PRODUCT, _CUSTOMER, _DATE]).copy()
    if d.empty:
        return res
    d[_PRODUCT] = d[_PRODUCT].astype(str)
    d[_CUSTOMER] = d[_CUSTOMER].astype(str)
    data_max = d[_DATE].max()

    # آماره‌های هر (محصول، مشتری) و هر محصول — وکتورایز
    pc_dates = d.groupby([_PRODUCT, _CUSTOMER])[_DATE].nunique()
    buyers = pc_dates.groupby(level=0).size()
    repeat = (pc_dates >= 2).groupby(level=0).sum()
    # چرخه: میانه‌ی فاصله‌ی بازخرید درون هر (محصول، مشتری)
    ds = d.sort_values([_PRODUCT, _CUSTOMER, _DATE])
    gap = ds.groupby([_PRODUCT, _CUSTOMER])[_DATE].diff().dt.days
    gap_pos = gap[gap > 0]
    median_cycle = gap_pos.groupby(ds.loc[gap_pos.index, _PRODUCT]).median() if len(gap_pos) else pd.Series(dtype=float)

    for product in buyers.index:
        n_buyers = int(buyers[product])
        n_repeat = int(repeat.get(product, 0))
        rate = n_repeat / n_buyers if n_buyers else 0.0
        mc = float(median_cycle[product]) if product in median_cycle.index and pd.notna(median_cycle[product]) else None
        if n_buyers < min_buyers:
            ptype = UNKNOWN
        elif rate >= consumable_repurchase_threshold and mc:
            ptype = CONSUMABLE
        else:
            ptype = ONE_TIME
        res.product_cycles.append(ProductCycle(
            product=str(product), product_type=ptype, repurchase_rate=rate,
            median_cycle_days=mc, n_buyers=n_buyers, n_repeat_buyers=n_repeat,
        ))
    res.product_cycles.sort(key=lambda c: -c.n_buyers)

    # اعلان‌های چرخه برای کالاهای مصرفی (وکتورایز، با سقف)
    consumable_cycle = {c.product: c.median_cycle_days for c in res.consumables() if c.median_cycle_days}
    if consumable_cycle:
        last_cp = d[d[_PRODUCT].isin(consumable_cycle)].groupby([_PRODUCT, _CUSTOMER])[_DATE].max().reset_index()
        last_cp["cycle"] = last_cp[_PRODUCT].map(consumable_cycle)
        last_cp["days_since"] = (data_max - last_cp[_DATE]).dt.days
        last_cp["offset"] = last_cp["days_since"] - last_cp["cycle"]
        near = (last_cp["cycle"] * near_fraction).clip(lower=3)
        flagged = last_cp[last_cp["offset"] >= -near].sort_values("offset", ascending=False).head(max_notifications)
        for _, r in flagged.iterrows():
            status = "عقب‌افتاده" if r["offset"] >= 0 else "نزدیک"
            res.notifications.append(CycleNotification(
                customer_id=str(r[_CUSTOMER]), product=str(r[_PRODUCT]),
                last_purchase=r[_DATE].date().isoformat(), cycle_days=float(r["cycle"]),
                days_since=int(r["days_since"]), days_offset=int(r["offset"]), status=status,
            ))

    # هدف‌گیری تک‌خریدی‌ها: فقط پرخریدارترین کالاهای تک‌خریدی (وکتورایز)
    all_customers = set(d[_CUSTOMER].unique())
    onetime_top = sorted(res.onetime(), key=lambda c: -c.n_buyers)[:max_onetime_targets]
    for pc in onetime_top:
        product = pc.product
        buyers_set = set(d.loc[d[_PRODUCT] == product, _CUSTOMER].unique())
        gateways: list[str] = []
        if basket is not None and basket.available:
            gateways = [r.antecedent for r in basket.rules
                        if r.consequent == product and r.lift > 1.0][:3]
        if gateways:
            pool = set(d.loc[d[_PRODUCT].isin(gateways), _CUSTOMER].unique())
        else:
            pool = all_customers
        potential = sorted(pool - buyers_set, key=str)
        res.onetime_targets.append(OneTimeTarget(
            product=product, gateway_products=gateways,
            potential_customers=potential[:500], existing_buyers=len(buyers_set),
        ))

    return res


__all__ = [
    "PurchaseCycleAnalysis", "ProductCycle", "CycleNotification", "OneTimeTarget",
    "analyze_purchase_cycles", "CONSUMABLE", "ONE_TIME", "UNKNOWN",
]
