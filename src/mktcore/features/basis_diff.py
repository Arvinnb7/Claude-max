"""پرونده‌ی ۳۶۰ از **دفتر کل** — مدعیِ سایه (§۷.۴ / §۳۵ فاز ۱).

قهرمان (`repo_features._per_customer_frame`) جمع‌های پایه‌ی هر مشتری را از فریمِ
**همان آپلود** می‌سازد. پیامدش: مشتری‌ای که در فایلِ ماهِ دوم نیست، برای آن
`as_of` ردیف نمی‌گیرد و شمار خرید و ارزشِ مشتریِ حاضر فقط همان فایل را می‌بیند.

مدعی همان ستون‌ها را از دفتر کل تا **شاملِ** `as_of` می‌سازد (تصمیمِ کاربر: همان
رفتارِ قهرمان که تاریخِ مرجع = آخرین روزِ داده و خودِ آن روز حساب می‌شود).

**هیچ‌چیز نوشته نمی‌شود.** این ماژول فقط اختلافِ مدعی با قهرمان را به‌ازای هر
ستون گزارش می‌کند تا ارتقا — که اعدادِ پرونده، حالتِ چرخه‌ی عمر و سلولِ اثر را
عوض می‌کند — با شاهدِ روی دفترِ واقعی تصمیم گرفته شود، نه با حدس.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
from sqlalchemy import select

from mktcore.db.models import CustomerFeature, Product
from mktcore.features.ledger_frame import load_line_frame
from mktcore.features.point_in_time import _order_counts
from mktcore.lifecycle import LifecycleInput, classify_lifecycle
from mktcore.lifecycle.states import population_gap, vip_threshold
from mktcore.money import to_rial_int

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

CHAMPION_BASIS = "upload_frame"
CHALLENGER_BASIS = "ledger_inclusive_as_of"

# ستون‌هایی که مدعی می‌تواند بدون تحلیلِ pandas بازسازی کند و بیت‌به‌بیت مقایسه می‌شوند.
COMPARED_COLUMNS: tuple[str, ...] = (
    "n_orders", "n_lines", "monetary_rial", "aov_rial", "recency_days", "tenure_days",
    "top_product", "lifecycle_state",
)


def ledger_per_customer_frame(session: Session, business_id: int, as_of: str) -> pd.DataFrame:
    """جمع‌های پایه‌ی هر مشتری از دفتر کل تا **شاملِ** `as_of` — قراردادِ قهرمان.

    * برگشتی‌ها بیرون‌اند (فریمِ تحلیل هم فقط خرید دارد).
    * `n_orders` با قراردادِ `_order_counts`: فاکتورهای یکتا + خطوطِ بی‌فاکتور.
    * `monetary_rial` جمعِ ریالِ خطوط (نه گردکردنِ جمعِ واحدِ نمایش — تفاوتِ
      گردکردن، اگر باشد، در diff دیده می‌شود).
    * `top_product` = نامِ نمایشیِ کالای با بیشترین درآمد.
    """
    lines = load_line_frame(session, business_id)
    if lines.empty:
        return pd.DataFrame(columns=[
            "n_lines", "monetary_rial", "first_date", "last_date", "n_orders", "top_product",
        ])
    lines = lines[(lines["line_date"] <= as_of) & (~lines["is_return"])]
    if lines.empty:
        return pd.DataFrame(columns=[
            "n_lines", "monetary_rial", "first_date", "last_date", "n_orders", "top_product",
        ])
    grouped = lines.groupby("customer_id")
    frame = pd.DataFrame({
        "n_lines": grouped.size(),
        "monetary_rial": grouped["revenue_rial"].sum(),
        "first_date": grouped["line_date"].min(),
        "last_date": grouped["line_date"].max(),
    })
    frame["n_orders"] = _order_counts(lines).reindex(frame.index).fillna(0).astype(int)

    with_product = lines[lines["product_id"].notna()]
    if len(with_product):
        top = (
            with_product.groupby(["customer_id", "product_id"])["revenue_rial"].sum()
            .reset_index().sort_values("revenue_rial", ascending=False, kind="stable")
            .drop_duplicates("customer_id").set_index("customer_id")["product_id"]
        )
        names = dict(session.execute(
            select(Product.id, Product.display_name).where(
                Product.id.in_(sorted({int(p) for p in top.to_numpy()})),
            )
        ).all())
        frame["top_product"] = top.map(lambda pid: names.get(int(pid)))
    else:
        frame["top_product"] = None
    return frame


def _champion_rows(
    session: Session, business_id: int, as_of: str, feature_version: int,
) -> dict[int, CustomerFeature]:
    rows = session.scalars(
        select(CustomerFeature).where(
            CustomerFeature.business_id == business_id,
            CustomerFeature.as_of_date == as_of,
            CustomerFeature.feature_version == feature_version,
        )
    ).all()
    return {int(row.customer_id): row for row in rows}


def _challenger_states(
    session: Session, business_id: int, as_of: str, frame: pd.DataFrame,
    champion: dict[int, CustomerFeature],
) -> dict[int, str]:
    """حالتِ چرخه‌ی عمرِ مدعی — با همان ماشینِ حالت و همان ورودی‌های مدل.

    آنچه مدعی عوض می‌کند فقط شمار خرید، تازگی و سابقه است؛ آهنگِ شخصی،
    احتمالِ زنده‌بودن و CLV از عکسِ قهرمان (همان `as_of`) می‌آیند و آستانه‌های
    جامعه از توزیعِ همان عکس بازسازی می‌شوند. مشتریِ غایب از آپلود (بدون عکس)
    این ورودی‌ها را ندارد — همان‌طور که قهرمان برای مشتریِ بی‌پیش‌بینی ندارد.
    """
    from mktcore.db.repo_features import _previous_states

    pop_gap = population_gap([float(r.avg_gap_days or 0) for r in champion.values()])
    vip_floor = vip_threshold([int(r.clv_rial or 0) for r in champion.values()])
    ids = {int(cid) for cid in frame.index}
    previous = _previous_states(session, business_id, as_of, ids)
    reference = pd.Timestamp(as_of)

    states: dict[int, str] = {}
    for cid, row in frame.iterrows():
        customer_id = int(cid)
        snap = champion.get(customer_id)
        prev = previous.get(customer_id)
        last = pd.Timestamp(row["last_date"])
        verdict = classify_lifecycle(LifecycleInput(
            n_orders=int(row["n_orders"]),
            recency_days=int((reference - last).days),
            tenure_days=int((reference - pd.Timestamp(row["first_date"])).days),
            avg_gap_days=float(snap.avg_gap_days) if snap and snap.avg_gap_days is not None else None,
            p_alive=(snap.p_alive_bp / 10_000) if snap and snap.p_alive_bp is not None else None,
            clv_rial=int(snap.clv_rial) if snap and snap.clv_rial is not None else None,
            population_gap_days=pop_gap,
            vip_clv_threshold_rial=vip_floor,
            previous_state=prev.state if prev else None,
            purchased_since_previous=bool(prev and last > pd.Timestamp(prev.as_of)),
        ))
        states[customer_id] = verdict.state
    return states


def _challenger_value(column: str, row: pd.Series, as_of: str, state: str | None):
    reference = pd.Timestamp(as_of)
    n_orders = int(row["n_orders"])
    monetary = int(row["monetary_rial"])
    if column == "n_orders":
        return n_orders
    if column == "n_lines":
        return int(row["n_lines"])
    if column == "monetary_rial":
        return monetary
    if column == "aov_rial":
        return to_rial_int(monetary / n_orders, "ریال") if n_orders else None
    if column == "recency_days":
        return int((reference - pd.Timestamp(row["last_date"])).days)
    if column == "tenure_days":
        return int((reference - pd.Timestamp(row["first_date"])).days)
    if column == "top_product":
        value = row.get("top_product")
        return None if value is None or (isinstance(value, float) and pd.isna(value)) else str(value)
    if column == "lifecycle_state":
        return state
    raise KeyError(column)


def compare_feature_bases(
    session: Session,
    business_id: int,
    *,
    as_of: str,
    feature_version: int | None = None,
    example_limit: int = 5,
) -> dict:
    """اختلافِ مدعی (دفتر کل) با قهرمان (فریمِ آپلود) برای یک `as_of` — بدون نوشتن.

    خروجی به‌ازای هر ستون شمارِ اختلاف و چند نمونه‌ی (مشتری، قهرمان، مدعی) دارد؛
    به‌علاوه مشتری‌هایی که فقط یک طرف دارد (غایب از آپلود ولی حاضر در دفتر کل).
    `identical=True` یعنی روی این `as_of` ارتقا هیچ عددی را عوض نمی‌کرد.
    """
    from mktcore.db.repo_features import FEATURE_VERSION

    version = FEATURE_VERSION if feature_version is None else feature_version
    champion = _champion_rows(session, business_id, as_of, version)
    challenger = ledger_per_customer_frame(session, business_id, as_of)
    states = _challenger_states(session, business_id, as_of, challenger, champion)

    champion_ids = set(champion)
    challenger_ids = {int(cid) for cid in challenger.index}
    both = sorted(champion_ids & challenger_ids)
    only_champion = sorted(champion_ids - challenger_ids)
    only_challenger = sorted(challenger_ids - champion_ids)

    columns: dict[str, dict] = {}
    for column in COMPARED_COLUMNS:
        mismatches = 0
        examples: list[dict] = []
        for customer_id in both:
            snap = champion[customer_id]
            row = challenger.loc[customer_id]
            expected = getattr(snap, column)
            actual = _challenger_value(column, row, as_of, states.get(customer_id))
            if expected != actual:
                mismatches += 1
                if len(examples) < example_limit:
                    examples.append({
                        "customer_id": customer_id, "champion": expected, "challenger": actual,
                    })
        columns[column] = {"mismatches": mismatches, "examples": examples}

    transitions = 0
    from mktcore.db.repo_features import _previous_states

    previous = _previous_states(session, business_id, as_of, challenger_ids)
    for customer_id, state in states.items():
        prev = previous.get(customer_id)
        if prev is not None and prev.state != state:
            transitions += 1

    identical = (
        not only_champion and not only_challenger
        and all(c["mismatches"] == 0 for c in columns.values())
    )
    total_mismatch = sum(c["mismatches"] for c in columns.values())
    return {
        "as_of": as_of,
        "feature_version": version,
        "champion": {"basis": CHAMPION_BASIS, "customers": len(champion_ids)},
        "challenger": {"basis": CHALLENGER_BASIS, "customers": len(challenger_ids)},
        "compared_customers": len(both),
        "only_in_champion": len(only_champion),
        "only_in_challenger": len(only_challenger),
        "only_in_challenger_ids": only_challenger[:example_limit],
        "columns": columns,
        "lifecycle_changes": columns["lifecycle_state"]["mismatches"],
        "challenger_transitions": transitions,
        "identical": identical,
        "written": False,
        "note_fa": (
            "مدعی (دفتر کل) با قهرمان (فریمِ آپلود) روی این تاریخ بیت‌به‌بیت یکی است؛ "
            "ارتقا هیچ عددی را عوض نمی‌کرد."
            if identical else
            f"مدعی با قهرمان فرق دارد: {total_mismatch} اختلافِ ستونی روی {len(both)} مشتریِ "
            f"مشترک، {len(only_challenger)} مشتری فقط در دفتر کل (غایب از این آپلود) و "
            f"{len(only_champion)} مشتری فقط در عکسِ آپلود. چیزی نوشته نشد؛ ارتقا تصمیمِ "
            "بعدی است."
        ),
    }


__all__ = [
    "CHALLENGER_BASIS",
    "CHAMPION_BASIS",
    "COMPARED_COLUMNS",
    "compare_feature_bases",
    "ledger_per_customer_frame",
]
