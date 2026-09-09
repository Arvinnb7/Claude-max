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
