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

import numpy as np
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
) -> PurchaseCycleAnalysis:
    """تحلیل چرخه‌ی خرید، طبقه‌بندی مصرفی/تک‌خریدی و تولید اعلان‌ها و هدف‌گیری."""
    res = PurchaseCycleAnalysis()
    if _PRODUCT not in df.columns or _CUSTOMER not in df.columns or df.empty:
        return res

    data_max = df[_DATE].max()

    for product, g in df.groupby(_PRODUCT):
        buyers = g.groupby(_CUSTOMER)[_DATE].nunique()
        n_buyers = int(len(buyers))
        n_repeat = int((buyers >= 2).sum())
        repurchase_rate = n_repeat / n_buyers if n_buyers else 0.0
        intervals = _intervals_by_customer(g)
        median_cycle = float(np.median(intervals)) if intervals else None

        if n_buyers < min_buyers:
            ptype = UNKNOWN
        elif repurchase_rate >= consumable_repurchase_threshold and median_cycle:
            ptype = CONSUMABLE
        else:
            ptype = ONE_TIME

        res.product_cycles.append(ProductCycle(
            product=str(product), product_type=ptype, repurchase_rate=repurchase_rate,
            median_cycle_days=median_cycle, n_buyers=n_buyers, n_repeat_buyers=n_repeat,
        ))

        # اعلان‌های چرخه برای کالاهای مصرفی
        if ptype == CONSUMABLE and median_cycle and median_cycle > 0:
            last_by_cust = g.groupby(_CUSTOMER)[_DATE].max()
            near = max(median_cycle * near_fraction, 3)
            for cust, last in last_by_cust.items():
                days_since = int((data_max - last).days)
                offset = int(days_since - median_cycle)  # مثبت = عقب‌افتاده
                if offset >= 0:
                    status = "عقب‌افتاده"
                elif offset >= -near:
                    status = "نزدیک"
                else:
                    status = "در مسیر"
                if status in ("عقب‌افتاده", "نزدیک"):
                    res.notifications.append(CycleNotification(
                        customer_id=str(cust), product=str(product),
                        last_purchase=last.date().isoformat(), cycle_days=median_cycle,
                        days_since=days_since, days_offset=offset, status=status,
                    ))

    # هدف‌گیری تک‌خریدی‌ها بر اساس قواعد انجمنی
    all_customers = set(df[_CUSTOMER].astype(str).unique())
    for pc in res.onetime():
        product = pc.product
        buyers = set(df[df[_PRODUCT] == product][_CUSTOMER].astype(str).unique())
        gateways: list[str] = []
        if basket is not None and basket.available:
            # کالاهایی که خریدشان احتمال خرید این تک‌خریدی را بالا می‌برد (antecedent → product)
            gateways = [r.antecedent for r in basket.rules
                        if r.consequent == product and r.lift > 1.0][:3]
        if gateways:
            gw_buyers = set(df[df[_PRODUCT].isin(gateways)][_CUSTOMER].astype(str).unique())
            potential = sorted(gw_buyers - buyers)
        else:
            # در نبود رابطه‌ی مشخص: همه‌ی مشتریان فعالی که هنوز نخریده‌اند
            potential = sorted(all_customers - buyers)
        res.onetime_targets.append(OneTimeTarget(
            product=product, gateway_products=gateways,
            potential_customers=potential[:500], existing_buyers=len(buyers),
        ))

    return res


__all__ = [
    "PurchaseCycleAnalysis", "ProductCycle", "CycleNotification", "OneTimeTarget",
    "analyze_purchase_cycles", "CONSUMABLE", "ONE_TIME", "UNKNOWN",
]
