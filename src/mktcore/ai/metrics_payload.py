"""تبدیل MetricsBundle به JSON فشرده، قطعی و sorted-key برای ارسال به مدل.

هرگز DataFrame خام ارسال نمی‌شود؛ فقط خلاصه‌های عددی. کلیدها مرتب‌اند تا کش
پرامپت پایدار بماند.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..pipeline import MetricsBundle


def build_payload(bundle: MetricsBundle, *, currency: str = "تومان") -> dict:
    """ساخت دیکشنری فشرده‌ی متریک‌ها."""
    k = bundle.kpis
    payload: dict = {
        "واحد_پول": currency,
        "kpi": {
            "درآمد_کل": round(k.total_revenue),
            "تعداد_سفارش": k.n_orders,
            "تعداد_مشتری": k.n_customers,
            "میانگین_ارزش_سفارش": round(k.aov),
            "رشد_ماهانه": None if k.mom_growth is None else round(k.mom_growth * 100, 1),
            "رشد_سالانه": None if k.yoy_growth is None else round(k.yoy_growth * 100, 1),
            "نرخ_مشتری_تکراری": None if k.repeat_rate is None else round(k.repeat_rate * 100, 1),
            "حاشیه_سود": None if k.gross_margin is None else round(k.gross_margin * 100, 1),
            "هشدارها": k.flags,
        },
        "روند": bundle.trends.compact(),
        "سگمنت‌بندی": bundle.segmentation.top_segments_compact(),
        "ناهنجاری‌ها": bundle.anomalies.compact(),
        "فصلی‌بودن": bundle.seasonality.compact(),
        "کوهورت": bundle.cohorts.compact(),
        "کیفیت_داده": bundle.quality.to_compact(),
    }

    # تفکیک ابعاد (سهم بالایی‌ها)
    breakdowns: dict = {}
    for dim, table in bundle.segmentation.breakdowns.items():
        rows = table.head(5)
        first_col = rows.columns[0]
        breakdowns[dim] = [
            {"عنوان": str(r[first_col]), "درآمد": round(float(r["revenue"])), "سهم": round(float(r["share"]) * 100, 1)}
            for _, r in rows.iterrows()
        ]
    payload["تفکیک_ابعاد"] = breakdowns

    if bundle.forecast is not None:
        payload["پیش‌بینی"] = bundle.forecast.compact()
    if bundle.targets is not None:
        payload["تارگت"] = bundle.targets.compact()

    # تحلیل‌های پیشرفته
    if getattr(bundle, "products", None) and bundle.products.available:
        payload["محصولات"] = bundle.products.compact()
    if getattr(bundle, "basket", None) and bundle.basket.available:
        payload["محصولات_مکمل"] = bundle.basket.compact()
    if getattr(bundle, "sequences", None) and bundle.sequences.available:
        payload["الگوهای_توالی"] = bundle.sequences.compact()
    if getattr(bundle, "next_purchase", None) and bundle.next_purchase.available:
        payload["خرید_بعدی_سررسیدشده"] = bundle.next_purchase.compact(8)
    if getattr(bundle, "purchase_cycle", None) and bundle.purchase_cycle.available:
        payload["چرخه_خرید"] = bundle.purchase_cycle.compact()
    if getattr(bundle, "performance", None):
        perf = bundle.performance.compact()
        if perf:
            payload["عملکرد"] = perf
    if getattr(bundle, "inventory", None) and bundle.inventory.available:
        payload["تأمین_کالا"] = bundle.inventory.compact()
    if getattr(bundle, "diagnostics", None) and bundle.diagnostics.period_label:
        payload["تشخیص_افت"] = bundle.diagnostics.compact()
    if getattr(bundle, "branch_targets", None) and bundle.branch_targets is not None:
        payload["تارگت_شعب"] = bundle.branch_targets.compact()
    if getattr(bundle, "salesperson_targets", None) and bundle.salesperson_targets is not None:
        payload["تارگت_فروشندگان"] = bundle.salesperson_targets.compact()
    if getattr(bundle, "pacing", None) and bundle.pacing is not None:
        payload["pacing_ماهانه"] = bundle.pacing.compact()

    return payload


def payload_to_json(payload: dict) -> str:
    """سریال‌سازی قطعی با کلیدهای مرتب (پایدار برای کش پرامپت)."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


__all__ = ["build_payload", "payload_to_json"]
