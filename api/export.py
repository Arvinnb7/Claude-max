"""ساخت خروجی اکسل بخش‌های داشبورد از bundle و دیتافریم پاک‌شده‌ی نشست.

منبع، bundle و clean کامل است (نه analysis_json کپ‌شده) تا فهرست‌ها کامل
باشند — از جمله شماره‌ی موبایل مشتریان برای اجرای کمپین.
"""

from __future__ import annotations

import io
import re

import pandas as pd

from mktcore.execution.audience import _phone_lookup
from mktcore.ingest.schema import ColumnRole, standard_column

_CUSTOMER = standard_column(ColumnRole.CUSTOMER_ID)
_DATE = standard_column(ColumnRole.DATE)
_ORDER = standard_column(ColumnRole.ORDER_ID)

EXPORT_SECTIONS = ("segments", "next_purchase", "products", "diagnostics")

EXPORT_FA_NAMES = {
    "segments": "سگمنت‌های-مشتریان",
    "next_purchase": "پیش‌بینی-خرید-بعدی",
    "products": "محصولات",
    "diagnostics": "تشخیص-و-تأمین",
}

_INVALID_SHEET = re.compile(r"[\[\]:*?/\\]")

_STATUS_ORDER = {"سررسیدشده": 0, "نزدیک": 1, "زود": 2, "نامشخص": 3}


class EmptySection(Exception):
    """بخش انتخابی داده‌ای برای خروجی ندارد (پیام فارسی مستقیم به کاربر)."""


def _safe_sheet(name: str, used: set[str]) -> str:
    base = (_INVALID_SHEET.sub("_", str(name)).strip() or "Sheet")[:31]
    out, i = base, 2
    while out in used:
        out = f"{base[:28]}_{i}"
        i += 1
    used.add(out)
    return out


def _workbook_bytes(sheets: list[tuple[str, pd.DataFrame]]) -> bytes:
    buf = io.BytesIO()
    used: set[str] = set()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for name, frame in sheets:
            sn = _safe_sheet(name, used)
            frame.to_excel(xw, sheet_name=sn, index=False)
            xw.book[sn].sheet_view.rightToLeft = True
    return buf.getvalue()


# ------------------------------------------------------------------ سازنده‌ها
def _segments_sheets(bundle, clean) -> list[tuple[str, pd.DataFrame]]:
    rfm = getattr(bundle.segmentation, "rfm_table", None)
    if rfm is None or rfm.empty:
        raise EmptySection("سگمنت‌بندی مشتریان در این تحلیل موجود نیست (ستون مشتری لازم است).")

    phones = _phone_lookup(clean)
    g = clean.groupby(_CUSTOMER)
    last_buy = g[_DATE].max().dt.date.astype(str)
    if _ORDER in clean.columns and clean[_ORDER].notna().any():
        n_orders = g[_ORDER].nunique()
    else:
        n_orders = g.size()

    idx = rfm.index.astype(str)
    table = pd.DataFrame({
        "کد مشتری": idx,
        "موبایل": [phones.get(i, "") for i in idx],
        "سگمنت": rfm["segment_fa"].to_numpy(),
        "تازگی (روز)": rfm["recency"].to_numpy(),
        "تعداد خرید": rfm["frequency"].to_numpy(),
        "مجموع خرید": rfm["monetary"].round(0).to_numpy(),
        "آخرین خرید": [last_buy.get(i, "") for i in rfm.index],
        "تعداد سفارش": [int(n_orders.get(i, 0)) for i in rfm.index],
    })

    sheets: list[tuple[str, pd.DataFrame]] = []
    for seg_name, part in table.groupby("سگمنت", sort=False):
        part = part.sort_values("مجموع خرید", ascending=False).drop(columns=["سگمنت"])
        sheets.append((str(seg_name), part))
    if not sheets:
        raise EmptySection("هیچ سگمنتی برای خروجی موجود نیست.")
    return sheets


def _next_purchase_sheets(bundle, clean) -> list[tuple[str, pd.DataFrame]]:
    customers = getattr(bundle.next_purchase, "customers", [])
    if not customers:
        raise EmptySection("پیش‌بینی خرید بعدی در این تحلیل موجود نیست.")
    phones = _phone_lookup(clean)
    rows = [{
        "کد مشتری": c.customer_id,
        "موبایل": phones.get(c.customer_id, ""),
        "محتمل‌ترین محصول بعدی": c.recommendations[0].product if c.recommendations else "",
        "دلیل": c.recommendations[0].reason if c.recommendations else "",
        "آخرین خرید": c.last_purchase,
        "میانگین فاصله (روز)": c.avg_interval_days,
        "تاریخ پیش‌بینی": c.predicted_next_date or "",
        "وضعیت": c.status,
        "تأخیر (روز)": c.overdue_days,
        "احتمال خرید ۳۰ روز": c.buy_probability_30d,
        "ارزش مورد انتظار": round(c.expected_value),
        "سبد محتمل": "، ".join(c.likely_products),
        "دلیل پیشنهاد": "، ".join(f"{r.product} ({r.reason})" for r in c.recommendations),
    } for c in customers]
    df = pd.DataFrame(rows)
    df["_o"] = df["وضعیت"].map(_STATUS_ORDER).fillna(9)
    df = (df.sort_values(["_o", "تأخیر (روز)"], ascending=[True, False])
            .drop(columns=["_o"]))
    return [("پیش‌بینی خرید بعدی", df)]


def _products_sheets(bundle, clean) -> list[tuple[str, pd.DataFrame]]:
    items = getattr(bundle.products, "products", [])
    if not items:
        raise EmptySection("تحلیل محصولات در این تحلیل موجود نیست (ستون محصول لازم است).")
    df = pd.DataFrame([{
        "محصول": p.product,
        "درآمد": round(p.revenue),
        "تعداد": p.quantity,
        "تعداد سفارش": p.orders,
        "سهم از درآمد": round(p.share, 4),
        "کلاس ABC": p.abc_class,
        "رشد": None if p.growth is None else round(p.growth, 4),
    } for p in items])
    return [("محصولات پرفروش", df)]


def _diagnostics_sheets(bundle, clean) -> list[tuple[str, pd.DataFrame]]:
    sheets: list[tuple[str, pd.DataFrame]] = []

    inv = getattr(bundle.inventory, "items", [])
    if inv:
        sheets.append(("پیشنهاد تأمین", pd.DataFrame([{
            "محصول": i.product,
            "توصیه": i.recommendation,
            "فروش هفتگی اخیر (واحد)": round(i.recent_units_per_week, 1),
            "رشد": None if i.growth is None else round(i.growth, 4),
            "سهم از درآمد": round(i.revenue_share, 4),
            "حاشیه سود": None if i.margin is None else round(i.margin, 4),
            "دلیل": i.reason,
        } for i in inv])))

    diag = bundle.diagnostics
    if getattr(diag, "drivers", None):
        sheets.append(("محرک‌های تغییر", pd.DataFrame([{
            "دوره": diag.period_label,
            "بُعد": drv.dimension,
            "مورد": drv.label,
            "تغییر مطلق": round(drv.delta),
            "درصد تغییر": None if drv.pct_change is None else round(drv.pct_change, 4),
            "سهم از افت": round(drv.contribution_to_decline, 4),
        } for drv in diag.drivers])))

    pacing = bundle.pacing
    if pacing is not None:
        sheets.append(("خلاصه pacing", pd.DataFrame([{
            "تارگت ماه": round(pacing.monthly_target),
            "محقق‌شده": round(pacing.achieved),
            "فاصله": round(pacing.gap),
            "روزهای باقی‌مانده": pacing.days_remaining,
            "نرخ روزانه لازم": round(pacing.required_daily),
            "در مسیر": "بله" if pacing.on_track else "خیر",
            "نسبت پیشروی": round(pacing.pace_ratio, 3),
        }])))
        if pacing.week_plan:
            sheets.append(("برنامه هفته", pd.DataFrame([{
                "تاریخ": d.date,
                "روز هفته": d.weekday,
                "هدف روز": round(d.target_revenue),
                "تمرکز": d.emphasis,
            } for d in pacing.week_plan])))

    if not sheets:
        raise EmptySection("داده‌ای برای بخش تشخیص و تأمین موجود نیست.")
    return sheets


_BUILDERS = {
    "segments": _segments_sheets,
    "next_purchase": _next_purchase_sheets,
    "products": _products_sheets,
    "diagnostics": _diagnostics_sheets,
}


def build_export(section: str, bundle, clean) -> bytes:
    """ساخت بایت‌های xlsx برای یک بخش؛ EmptySection اگر داده‌ای نباشد."""
    return _workbook_bytes(_BUILDERS[section](bundle, clean))


__all__ = ["EXPORT_SECTIONS", "EXPORT_FA_NAMES", "EmptySection", "build_export"]
