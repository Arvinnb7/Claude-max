"""ورودِ فایل بها و انتسابش به خطوط فروش — تنها لایه‌ای که به دیتابیس دست می‌زند.

`basis.py` تابع خالص است؛ اینجا فقط خواندن/نوشتن انجام می‌شود.

**چرا مسیر ورودِ جدا.** بهای تمام‌شده در فایل فروشِ این کسب‌وکار نیست؛ در سیستم
دیگری نگه‌داری می‌شود. پس یک فایل جداگانه (نام کالا + بها + تاریخ اثر اختیاری)
گرفته می‌شود و به کالاهای canonical وصل می‌شود.

**کالای تطبیق‌نیافته بی‌صدا حذف نمی‌شود.** گزارش می‌گوید کدام نام‌ها به هیچ
کالایی وصل نشدند تا کاربر بتواند نامشان را اصلاح کند — وگرنه پوشش بها بی‌دلیل
ناقص می‌ماند و کسی نمی‌فهمد چرا.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from mktcore.db.engine import session_scope, write_lock
from mktcore.db.lookup import product_ids_by_raw_name, resolve_business_id
from mktcore.db.migrations import ensure_schema
from mktcore.db.models import OrderLine, Product, ProductCostHistory
from mktcore.money import to_rial_int

from .basis import (
    CONFIDENCE_FROM_FILE,
    CostLookup,
    CostPoint,
    coverage_ratio,
    gross_profit_rial,
    line_cost_rial,
)

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.orm import Session

logger = logging.getLogger("mktcore.costs.register")

CHUNK = 500

# وقتی فایل بها تاریخ اثر ندارد، از این تاریخ معتبر فرض می‌شود. عمداً بسیار
# قدیمی است تا **همه‌ی** خطوط تاریخی پوشش بگیرند — ولی چون تاریخِ واقعی نیست،
# سطح اطمینانشان با همان منطق `basis.py` تعیین می‌شود.
FALLBACK_EFFECTIVE_FROM = "1900-01-01"


def import_costs(
    rows: list[dict],
    *,
    display_currency: str = "تومان",
    business_slug: str = "default",
    db_path: Path | None = None,
) -> dict:
    """ثبت فایل بها. هر ردیف: `{"product": str, "cost": float, "date": str|None}`.

    idempotent است: همان کالا با همان تاریخ اثر، ردیف تازه نمی‌سازد و مقدارش
    به‌روز می‌شود.
    """
    ensure_schema(db_path)
    with write_lock, session_scope(db_path) as session:
        business_id = resolve_business_id(session, business_slug)
        if business_id is None:
            raise ValueError("کسب‌وکاری ثبت نشده است؛ اول یک فایل فروش تحلیل کنید.")

        names = [str(r.get("product") or "").strip() for r in rows]
        resolved = product_ids_by_raw_name(session, business_id, names)

        written = updated = 0
        unmatched: list[str] = []
        for row in rows:
            name = str(row.get("product") or "").strip()
            product_id = resolved.get(name)
            if product_id is None:
                if name:
                    unmatched.append(name)
                continue
            cost = row.get("cost")
            if cost is None:
                continue
            unit_cost = to_rial_int(cost, display_currency)
            if unit_cost is None:
                continue
            effective = str(row.get("date") or "").strip() or FALLBACK_EFFECTIVE_FROM

            existing = session.scalar(
                select(ProductCostHistory).where(
                    ProductCostHistory.business_id == business_id,
                    ProductCostHistory.product_id == product_id,
                    ProductCostHistory.effective_from == effective,
                )
            )
            if existing is None:
                session.add(ProductCostHistory(
                    business_id=business_id, product_id=product_id,
                    unit_cost_rial=int(unit_cost), effective_from=effective,
                    raw_product_name=name,
                ))
                written += 1
            else:
                existing.unit_cost_rial = int(unit_cost)
                existing.raw_product_name = name
                updated += 1
        session.flush()

    return {
        "written": written,
        "updated": updated,
        # فهرست یکتا و مرتب تا گزارش پایدار بماند
        "unmatched_products": sorted(set(unmatched)),
        "unmatched_count": len(set(unmatched)),
        "note_fa": (
            "کالاهایی که به هیچ محصولی وصل نشدند بها نگرفتند؛ نامشان را اصلاح "
            "کنید یا در فایل فروش همان نام را به‌کار ببرید."
            if unmatched else "همه‌ی ردیف‌ها به کالای شناخته‌شده وصل شدند."
        ),
    }


def load_cost_lookups(session: Session, business_id: int) -> dict[int, CostLookup]:
    """تاریخچه‌ی بها را یک‌بار می‌خواند — نه یک query به‌ازای هر خط."""
    rows = session.execute(
        select(
            ProductCostHistory.product_id,
            ProductCostHistory.effective_from,
            ProductCostHistory.unit_cost_rial,
        ).where(ProductCostHistory.business_id == business_id)
    ).all()

    grouped: dict[int, list[CostPoint]] = {}
    for product_id, effective_from, unit_cost in rows:
        grouped.setdefault(int(product_id), []).append(
            CostPoint(str(effective_from), int(unit_cost))
        )
    return {pid: CostLookup.from_points(points) for pid, points in grouped.items()}


def apply_costs(
    *, business_slug: str = "default", db_path: Path | None = None,
) -> dict:
    """انتساب بها و سود به خطوط فروش، بر پایه‌ی **تاریخ هر خط**.

    خطی که بهایش از خودِ فایل فروش آمده (`from_file`) دست نمی‌خورد — منبعِ
    مستقیم‌تر بر تاریخچه اولویت دارد.
    """
    ensure_schema(db_path)
    with write_lock, session_scope(db_path) as session:
        business_id = resolve_business_id(session, business_slug)
        if business_id is None:
            return {"updated": 0, "note_fa": "کسب‌وکاری ثبت نشده است."}

        lookups = load_cost_lookups(session, business_id)
        if not lookups:
            return {
                "updated": 0,
                "note_fa": "هیچ تاریخچه‌ی بهایی ثبت نشده است؛ چیزی برای انتساب نبود.",
            }

        lines = session.scalars(
            select(OrderLine).where(
                OrderLine.business_id == business_id,
                OrderLine.product_id.isnot(None),
            )
        ).all()

        updated = 0
        for line in lines:
            if line.cost_confidence == CONFIDENCE_FROM_FILE:
                # بهایش از خودِ فایل فروش آمده و منبعِ مستقیم‌تری است، پس
                # دوباره قیمت‌گذاری نمی‌شود — ولی سودش باید محاسبه شود، وگرنه
                # خطی که بها **دارد** بی‌سود می‌ماند.
                if line.gross_profit_rial is None:
                    line.gross_profit_rial = gross_profit_rial(
                        line.revenue_rial, line.cost_rial,
                    )
                    updated += 1
                continue
            found = line_cost_rial(
                lookups.get(int(line.product_id)), line.line_date, line.quantity_milli,
            )
            if found is None:
                continue
            cost, confidence = found
            # خط برگشتی درآمد منفی دارد؛ بهایش هم باید منفی شود تا سودِ خط اصلی
            # را خنثی کند، وگرنه برگشت، سود را دو برابر کم می‌کند.
            if line.is_return:
                cost = -abs(cost)
            line.cost_rial = cost
            line.cost_confidence = confidence
            line.gross_profit_rial = gross_profit_rial(line.revenue_rial, cost)
            updated += 1
        session.flush()

    return {"updated": updated, "note_fa": f"{updated} خط بها و سود گرفت."}


def cost_coverage(session: Session, business_id: int) -> tuple[int, int, float]:
    """(کل خطوط، خطوط دارای بها، نسبت) — مبنای تصمیمِ «محاسبه کنیم یا نه»."""
    total, with_cost = session.execute(
        select(func.count(OrderLine.id), func.count(OrderLine.cost_rial))
        .where(OrderLine.business_id == business_id)
    ).one()
    total, with_cost = int(total or 0), int(with_cost or 0)
    return total, with_cost, coverage_ratio(total, with_cost)


def _margin_rows(session: Session, business_id: int) -> list[tuple]:
    return session.execute(
        select(
            Product.canonical_name,
            Product.display_name,
            Product.category,
            func.count(OrderLine.id),
            func.count(OrderLine.cost_rial),
            func.sum(OrderLine.revenue_rial),
            func.sum(OrderLine.gross_profit_rial),
        )
        .join(OrderLine, OrderLine.product_id == Product.id)
        .where(OrderLine.business_id == business_id, OrderLine.is_return.is_(False))
        .group_by(Product.id)
    ).all()


def _margin_bp(revenue: int, profit: int) -> int | None:
    if revenue <= 0:
        return None
    return round(profit / revenue * 10_000)


def margin_by_product(session: Session, business_id: int) -> dict[str, int]:
    """حاشیه‌ی هر کالا به پایه‌ی هزارم، با کلیدِ نامِ canonical.

    فقط کالاهایی که **همه‌ی** خطوطشان بها دارند وارد می‌شوند؛ حاشیه‌ی محاسبه‌شده
    از داده‌ی ناقص، کالای سودده را زیانده نشان می‌دهد.
    """
    out: dict[str, int] = {}
    for name, _display, _category, total, with_cost, revenue, profit in _margin_rows(
        session, business_id,
    ):
        if not name or not total or int(with_cost or 0) != int(total):
            continue
        margin = _margin_bp(int(revenue or 0), int(profit or 0))
        if margin is not None:
            out[str(name)] = margin
    return out


def margin_by_customer(session: Session, business_id: int) -> dict[int, int]:
    """حاشیه‌ی وزنیِ خریدهای **خودِ مشتری** به پایه‌ی هزارم، با کلیدِ `customer_id`.

    برای فرصت‌هایی که کالای مشخصی ندارند (نجات از ریزش، بازگشت) تخفیف روی
    هرچه مشتری بخرد اعمال می‌شود؛ پس مبنای درستِ سقفِ تخفیف، حاشیه‌ی سبدِ
    معمولِ همان مشتری است. فقط مشتریانی که **همه‌ی** خطوطشان بها دارند وارد
    می‌شوند — همان قاعده‌ی `margin_by_product`.
    """
    rows = session.execute(
        select(
            OrderLine.customer_id,
            func.count(OrderLine.id),
            func.count(OrderLine.cost_rial),
            func.sum(OrderLine.revenue_rial),
            func.sum(OrderLine.gross_profit_rial),
        )
        .where(
            OrderLine.business_id == business_id,
            OrderLine.is_return.is_(False),
            OrderLine.customer_id.isnot(None),
        )
        .group_by(OrderLine.customer_id)
    ).all()
    out: dict[int, int] = {}
    for customer_id, total, with_cost, revenue, profit in rows:
        if not total or int(with_cost or 0) != int(total):
            continue
        margin = _margin_bp(int(revenue or 0), int(profit or 0))
        if margin is not None:
            out[int(customer_id)] = margin
    return out


def margin_lookup(session: Session, business_id: int) -> dict[str, int]:
    """همان حاشیه‌ها، ولی با **هر نامی که ممکن است در یک پیشنهاد بیاید**.

    چرا لازم است: دفتر کل کالا را با نامِ نرمال‌شده می‌شناسد، پیشنهاد با نامِ
    نمایشی، و پیشنهادِ «شکاف دسته» اصلاً با نامِ **دسته**. اگر فقط یک شکل از
    نام کلید باشد، `filter_margin_floor` همیشه «حاشیه محاسبه نشده» می‌دهد و
    کفِ تعیین‌شده‌ی کاربر عملاً بی‌اثر می‌ماند — بدون اینکه کسی بفهمد.

    حاشیه‌ی دسته، حاشیه‌ی **وزنی** همان دسته است و تنها وقتی وارد می‌شود که
    پوششِ بها در کلِ دسته کامل باشد؛ وگرنه کفِ حاشیه بر پایه‌ی نیمی از داده
    تصمیم می‌گیرد.
    """
    out: dict[str, int] = {}
    by_category: dict[str, list[int]] = {}
    category_complete: dict[str, bool] = {}

    for name, display, category, total, with_cost, revenue, profit in _margin_rows(
        session, business_id,
    ):
        complete = bool(total) and int(with_cost or 0) == int(total)
        revenue, profit = int(revenue or 0), int(profit or 0)
        if category:
            key = str(category)
            category_complete[key] = category_complete.get(key, True) and complete
            bucket = by_category.setdefault(key, [0, 0])
            bucket[0] += revenue
            bucket[1] += profit
        if not complete:
            continue
        margin = _margin_bp(revenue, profit)
        if margin is None:
            continue
        for key in (name, display):
            if key:
                out[str(key)] = margin

    for category, (revenue, profit) in by_category.items():
        if not category_complete.get(category):
            continue
        margin = _margin_bp(revenue, profit)
        # نامِ دسته هرگز نامِ کالا را بازنویسی نمی‌کند: کالا دقیق‌تر است.
        if margin is not None and category not in out:
            out[category] = margin
    return out


__all__ = [
    "FALLBACK_EFFECTIVE_FROM",
    "apply_costs",
    "cost_coverage",
    "import_costs",
    "load_cost_lookups",
    "margin_by_customer",
    "margin_by_product",
    "margin_lookup",
]
