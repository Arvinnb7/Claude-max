"""دو قاعده‌ی تداخلِ §۲۳.۳ که داده‌ی تازه نمی‌خواهند.

قاعده‌ی ۱: در سقفِ پرِ هر مشتری، یادآوریِ تکرارِ خرید بر فروشِ مکملِ عمومی مقدم است
(کم‌ارزش‌ترین مکمل جا می‌دهد؛ هیچ ارزش/رتبه‌ای عوض نمی‌شود؛ ظرفیتِ تیم پس داده می‌شود).
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.analysis.actions import (  # noqa: E402
    KIND_BASKET,
    KIND_CHURN,
    KIND_CYCLE,
    KIND_ONETIME,
    KIND_SEQUENCE,
    VALUE_AT_RISK,
    VALUE_OPPORTUNITY,
)
from mktcore.opportunities.contract import OpportunityCandidate  # noqa: E402
from mktcore.opportunities.filters import (  # noqa: E402
    CROSS_SELL_KINDS,
    REPLENISHMENT_KINDS,
    apply_filters,
)


def _candidate(kind: str, value: float, product: str, customer: str = "C1", value_kind=VALUE_OPPORTUNITY):
    return OpportunityCandidate(
        kind=kind, generator="test", generator_version=1, customer_key=customer,
        title_fa=kind, action_fa="اقدام", reason_fa="دلیل", expected_value_display=value,
        value_kind=value_kind, product_name=product,
    )


def _ctx(**extra) -> dict:
    return {"recently_contacted": set(), "fatigue_window_days": 14, "per_customer_open_cap": 2, **extra}


def test_kind_priority_constants_match_the_action_kinds():
    assert REPLENISHMENT_KINDS == (KIND_CYCLE,)
    assert set(CROSS_SELL_KINDS) >= {KIND_ONETIME, KIND_SEQUENCE}


def test_replenishment_takes_the_slot_of_the_cheapest_generic_cross_sell():
    onetime = _candidate(KIND_ONETIME, 90_000, "مکمل")
    sequence = _candidate(KIND_SEQUENCE, 80_000, "الگو")
    cycle = _candidate(KIND_CYCLE, 70_000, "غذا")
    accepted, rejected = apply_filters([onetime, sequence, cycle], _ctx())

    assert {c.kind for c in accepted} == {KIND_ONETIME, KIND_CYCLE}
    assert rejected == [sequence]
    block = sequence.blocked_by
    assert block.code == "conflict" and "جای خود را" in block.detail_fa and "غذا" in block.detail_fa
    # ارزش و ترتیبِ بازمانده‌ها دست نخورده
    assert [c.expected_value_display for c in accepted] == [90_000, 70_000]
    assert "مقدم" in cycle.factors[-1].detail_fa or any("مقدم" in (f.detail_fa or "") for f in cycle.factors)


def test_without_a_generic_cross_sell_to_yield_the_cap_still_binds():
    """سبد و نجاتِ ریزش مکملِ عمومی نیستند ⇒ رفتارِ امروز: یادآوری رد می‌شود."""
    basket = _candidate(KIND_BASKET, 90_000, "سبد")
    churn = _candidate(KIND_CHURN, 80_000, "ریزش", value_kind=VALUE_AT_RISK)
    cycle = _candidate(KIND_CYCLE, 70_000, "غذا")
    accepted, rejected = apply_filters([basket, churn, cycle], _ctx())
    assert accepted == [basket, churn] and rejected == [cycle]
    assert "سقف" in cycle.blocked_by.detail_fa


def test_a_second_replenishment_does_not_evict_a_replenishment():
    first = _candidate(KIND_CYCLE, 90_000, "غذا")
    onetime = _candidate(KIND_ONETIME, 80_000, "مکمل")
    second = _candidate(KIND_CYCLE, 70_000, "خاک")
    third = _candidate(KIND_CYCLE, 60_000, "کنسرو")
    accepted, rejected = apply_filters([first, onetime, second, third], _ctx())
    assert accepted == [first, second], "مکمل جا داد؛ یادآوریِ سوم به سقف خورد"
    assert rejected == [onetime, third] or rejected == [third, onetime]
    assert "سقف" in third.blocked_by.detail_fa and "جای خود را" in onetime.blocked_by.detail_fa


def test_yielding_returns_the_operator_capacity_slot():
    onetime = _candidate(KIND_ONETIME, 90_000, "مکمل")
    sequence = _candidate(KIND_SEQUENCE, 80_000, "الگو")
    cycle = _candidate(KIND_CYCLE, 70_000, "غذا")
    ctx = _ctx(daily_capacity=2)
    accepted, rejected = apply_filters([onetime, sequence, cycle], ctx)
    assert {c.kind for c in accepted} == {KIND_ONETIME, KIND_CYCLE}
    assert ctx["_capacity_used"]["money"] == 2, "جایگاهِ مکملِ کنارگذاشته پس داده شد و یادآوری آن را گرفت"
    capacity_note = [f for f in cycle.factors if f.code == "operator_capacity"][0]
    assert capacity_note.outcome == "filter_pass"


def test_other_customers_are_untouched():
    c1_onetime = _candidate(KIND_ONETIME, 90_000, "مکمل", customer="C1")
    c1_seq = _candidate(KIND_SEQUENCE, 80_000, "الگو", customer="C1")
    c2_cycle = _candidate(KIND_CYCLE, 70_000, "غذا", customer="C2")
    accepted, rejected = apply_filters([c1_onetime, c1_seq, c2_cycle], _ctx())
    assert accepted == [c1_onetime, c1_seq, c2_cycle] and rejected == []


# ═══════════════════════════════ قاعده‌ی ۲: خریدِ همان کالا فرصت را می‌بندد (§۲۳.۳ بند ۴)
import json  # noqa: E402

from sqlalchemy import select  # noqa: E402

from mktcore.db import session_scope  # noqa: E402
from mktcore.db.models import Customer, Opportunity, OpportunityEvent, Product  # noqa: E402
from mktcore.opportunities import (  # noqa: E402
    close_fulfilled_opportunities,
    run_opportunity_engine,
)
from mktcore.opportunities.engine import STATUS_ACCEPTED, STATUS_SUPERSEDED  # noqa: E402
from mktcore.pipeline import run_analysis  # noqa: E402

from .test_golden_scenarios import _clean, _ingest  # noqa: E402

PRODUCT = "مواد مصرفی"


def _regular_rows() -> list[tuple]:
    """همان فیکسچرِ طلایی: «منظم» هر ۳۰ روز می‌خرد و ۶۰ روز نیامده ⇒ یادآوریِ چرخه."""
    rows = []
    for i in range(8):
        day = 1 + i * 30
        month, dom = divmod(day - 1, 30)
        rows.append((f"1402/{month + 1:02d}/{dom + 1:02d}", 500_000, 1, "منظم", f"F{i}", PRODUCT, "09121110000"))
    # پرکننده‌ها دو بار با فاصله‌ی ۳۰ روز می‌خرند تا کالا «مصرفی» طبقه‌بندی شود (نرخِ تکرار ≥ ۰٫۳)
    for j in range(20):
        month = (j % 8) + 1
        rows.append((f"1402/{month:02d}/15", 200_000 + j * 1000, 1, f"C{j}", f"G{j}a", PRODUCT, ""))
        rows.append((f"1402/{month + 1:02d}/15", 200_000 + j * 1000, 1, f"C{j}", f"G{j}b", PRODUCT, ""))
    rows.append(("1402/10/15", 150_000, 1, "C_last", "GL", PRODUCT, ""))   # آخرین روزِ داده
    return rows


def _cycle_card(db: Path):
    with session_scope(db) as session:
        customer = session.scalar(select(Customer.id).where(Customer.canonical_key == "منظم"))
        product = session.scalar(select(Product.id).where(Product.display_name == PRODUCT))
        card = session.scalar(select(Opportunity).where(
            Opportunity.customer_id == customer, Opportunity.product_id == product,
            Opportunity.kind == KIND_CYCLE,
        ).order_by(Opportunity.id))
        assert card is not None, "فیکسچرِ طلایی یادآوریِ چرخه می‌سازد"
        session.expunge(card)
        return card


def _run(rows: list[tuple], db: Path, dataset_key: str):
    clean = _clean(rows)
    _ingest(clean, db, dataset_key=dataset_key)
    bundle = run_analysis(clean, horizon=2, with_forecast=False)
    return run_opportunity_engine(bundle, clean, db_path=db)


def test_a_purchase_of_the_same_product_after_creation_closes_the_card(tmp_path):
    db = tmp_path / "app.db"
    base = _regular_rows()
    first = _run(base, db, "m1")
    assert first.closed_by_purchase == 0
    card = _cycle_card(db)
    with session_scope(db) as session:
        session.get(Opportunity, card.id).status = STATUS_ACCEPTED   # تیم پذیرفته

    # فایلِ بعدی: «منظم» همان کالا را ۱۰ روز بعد می‌خرد (پس از ساختِ فرصت)
    later = base + [("1402/11/05", 500_000, 1, "منظم", "F9", PRODUCT, "09121110000")]
    purchase_date = str(_clean(later)["date"].max().date())
    second = _run(later, db, "m2")
    with session_scope(db) as session:
        closed = session.get(Opportunity, card.id)
        events = session.scalars(select(OpportunityEvent).where(
            OpportunityEvent.opportunity_id == card.id,
            OpportunityEvent.event_type == "fulfilled_by_purchase",
        )).all()
        assert closed.status == STATUS_SUPERSEDED and "خرید" in closed.status_reason_fa
        assert len(events) == 1 and events[0].from_status == STATUS_ACCEPTED
        assert json.loads(events[0].payload_json)["purchase_date"] == purchase_date
    assert second.closed_by_purchase == 1
    assert second.to_dict()["closed_by_purchase"] == 1


def test_a_different_product_or_a_same_day_purchase_does_not_close_the_card(tmp_path):
    db = tmp_path / "app.db"
    base = _regular_rows()
    _run(base, db, "m1")
    card = _cycle_card(db)
    first_as_of = str(_clean(base)["date"].max().date())
    with session_scope(db) as session:
        session.get(Opportunity, card.id).status = STATUS_ACCEPTED

    # کالای دیگر، و خریدِ همان روزِ اجرای نخست (< اکید) ⇒ بسته نمی‌شود
    jalali_same_day = base[-1][0]  # آخرین تاریخِ فیکسچر همان as_of است
    assert str(_clean(base)["date"].max().date()) == first_as_of
    later = base + [
        (jalali_same_day, 500_000, 1, "منظم", "F9", PRODUCT, "09121110000"),
        ("1402/11/05", 300_000, 1, "منظم", "F10", "کالای دیگر", "09121110000"),
    ]
    result = _run(later, db, "m2")
    with session_scope(db) as session:
        assert session.get(Opportunity, card.id).status == STATUS_ACCEPTED
    assert result.closed_by_purchase == 0


def test_standalone_close_is_idempotent_and_the_expiration_job_reports_it(tmp_path, monkeypatch):
    from mktcore.config import get_settings
    from mktcore.db.migrations import reset_ensure_cache
    from mktcore.jobs.registry import _job_opportunity_expiration

    monkeypatch.setenv("MKT_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    reset_ensure_cache()
    try:
        db = None  # مسیرِ پیش‌فرضِ تنظیمات
        base = _regular_rows()
        clean = _clean(base)
        from mktcore.analysis.kpis import compute_kpis
        from mktcore.db.repo_import import write_import

        write_import(clean, kpis=compute_kpis(clean), dataset_key="m1")
        bundle = run_analysis(clean, horizon=2, with_forecast=False)
        run_opportunity_engine(bundle, clean)
        later = _clean(base + [("1402/11/05", 500_000, 1, "منظم", "F9", PRODUCT, "09121110000")])
        write_import(later, kpis=compute_kpis(later), dataset_key="m2")   # فقط دفتر کل، بدونِ موتور
        as_of = str(later["date"].max().date())

        first = close_fulfilled_opportunities(as_of=as_of)
        assert first["closed_by_purchase"] == 1
        assert close_fulfilled_opportunities(as_of=as_of)["closed_by_purchase"] == 0
        report = _job_opportunity_expiration()
        assert set(report) >= {"expired", "closed_by_purchase", "as_of"}
        assert db is None
    finally:
        get_settings.cache_clear()
        reset_ensure_cache()
