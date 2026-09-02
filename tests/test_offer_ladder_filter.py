"""نردبانِ تخفیف در زنجیره‌ی فیلتر — §۲۰.۳، بدونِ دیتابیس.

## سه قاعده‌ای که این فایل پین می‌کند

1. **بدون نردبان، هیچ‌چیز عوض نمی‌شود** — همان `SKIP` و همان متنِ «تخفیفی
   پیشنهاد نشده».
2. **کف حاشیه روی حاشیه‌ی پس از تخفیف** اعمال می‌شود: (m − d)/(1 − d)، نه m − d.
   حاشیه ۲۴٪، کف ۲۰٪، پله ۵٪ ⇒ دقیقاً ۲۰٪ = مجاز. این مرز با فرمولِ ساده رد
   می‌شد.
3. **این فیلتر هرگز رد نمی‌کند** و ارزش/رتبه را دست نمی‌زند: تخفیف فقط
   پیشنهاد است.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.opportunities.contract import (  # noqa: E402
    OUTCOME_PASS,
    OUTCOME_SKIP,
    VALUE_RELATIONSHIP,
    OpportunityCandidate,
)
from mktcore.opportunities.filters import (  # noqa: E402
    apply_filters,
    filter_offer_policy,
    pick_rung,
    post_discount_margin_bp,
)

LADDER = (500, 1000, 1500)


def _candidate(key: str = "C1", product: str = "P", **kwargs) -> OpportunityCandidate:
    base = {
        "kind": "یادآوری چرخه‌ی مصرف", "generator": "test", "generator_version": 1,
        "customer_key": key, "title_fa": "t", "action_fa": "a", "reason_fa": "r",
        "expected_value_display": 100_000.0, "value_kind": "ارزش فرصت",
        "product_name": product,
    }
    base.update(kwargs)
    return OpportunityCandidate(**base)


def _ctx(**over) -> dict:
    ctx = {
        "has_cost_data": True, "margin_floor_bp": 2_000,
        "margin_by_product": {"P": 3_000}, "offer_ladder_bp": LADDER,
        "full_price_tier_of": {"C1": "low"}, "recently_contacted": set(),
    }
    ctx.update(over)
    return ctx


# ═══════════════════════════════════════════════════ فرمول
def test_post_discount_margin_uses_the_discounted_price_as_denominator():
    assert post_discount_margin_bp(2_400, 500) == 2_000      # (24−5)/(1−0.05) = 20%
    assert post_discount_margin_bp(3_000, 1_000) == 2_222   # (30−10)/0.9
    assert post_discount_margin_bp(2_000, 10_000) is None    # تخفیفِ ۱۰۰٪ بی‌معنا


def test_pick_rung_returns_the_smallest_rung_that_keeps_the_floor():
    assert pick_rung(LADDER, 3_000, 2_000) == 500
    assert pick_rung((1_500, 500), 3_000, 2_000) == 500     # ترتیبِ ورودی مهم نیست


def test_boundary_exactly_on_the_floor_is_allowed():
    """۲۴۰۰/۲۰۰۰/۵۰۰ ⇒ دقیقاً ۲۰۰۰؛ فرمولِ ساده (m−d ≥ floor) این را رد می‌کرد."""
    assert pick_rung(LADDER, 2_400, 2_000) == 500


def test_no_rung_when_even_the_smallest_breaks_the_floor():
    assert pick_rung(LADDER, 2_050, 2_000) is None


# ═══════════════════════════════════════════════ فیلتر — بدون نردبان
def test_without_a_ladder_the_note_and_outcome_are_unchanged():
    note = filter_offer_policy(_candidate(), _ctx(offer_ladder_bp=None))

    assert note.outcome == OUTCOME_SKIP
    assert "تخفیفی پیشنهاد نشده" in note.detail_fa


def test_without_a_ladder_the_candidate_carries_no_suggestion():
    candidate = _candidate()
    filter_offer_policy(candidate, _ctx(offer_ladder_bp=None))
    assert candidate.suggested_discount_bp is None


# ═══════════════════════════════════════════════ فیلتر — با نردبان
def test_low_tier_customer_gets_the_smallest_safe_rung():
    candidate = _candidate()
    note = filter_offer_policy(candidate, _ctx())

    assert note.outcome == OUTCOME_PASS
    assert candidate.suggested_discount_bp == 500
    assert candidate.offer_tier == "low"
    assert candidate.offer_margin_bp == 3_000 and candidate.offer_floor_bp == 2_000
    assert note.value_text == "5٪"
    assert "تأییدِ انسان" in note.detail_fa


def test_full_price_customer_gets_no_discount_explicitly():
    candidate = _candidate()
    note = filter_offer_policy(candidate, _ctx(full_price_tier_of={"C1": "high"}))

    assert note.outcome == OUTCOME_PASS
    assert candidate.suggested_discount_bp == 0
    assert note.value_text == "0٪"
    assert "تمام‌قیمت" in note.detail_fa


def test_mid_tier_gets_no_discount_in_the_first_step():
    candidate = _candidate()
    filter_offer_policy(candidate, _ctx(full_price_tier_of={"C1": "mid"}))
    assert candidate.suggested_discount_bp == 0


def test_relationship_actions_never_get_a_discount():
    """§۱۸.۵ — حتی با نردبان و طبقه‌ی «وابسته به تخفیف»."""
    candidate = _candidate(value_kind=VALUE_RELATIONSHIP, product=None)
    note = filter_offer_policy(candidate, _ctx())

    assert candidate.suggested_discount_bp == 0
    assert "رابطه‌ای" in note.detail_fa
    assert "تخفیف" not in (note.value_text or "")


@pytest.mark.parametrize(("override", "fragment"), [
    ({"full_price_tier_of": {}}, "نامعلوم"),
    ({"has_cost_data": False}, "بهای تمام‌شده"),
    ({"margin_floor_bp": None}, "کف حاشیه"),
    ({"margin_by_product": {}}, "حاشیه‌ی این کالا"),
])
def test_missing_inputs_are_skipped_with_a_reason_not_passed(override, fragment):
    candidate = _candidate()
    note = filter_offer_policy(candidate, _ctx(**override))

    assert note.outcome == OUTCOME_SKIP
    assert fragment in note.detail_fa
    assert candidate.suggested_discount_bp is None


def test_no_safe_rung_means_explicit_zero_not_skip():
    candidate = _candidate()
    note = filter_offer_policy(candidate, _ctx(margin_by_product={"P": 2_050}))

    assert note.outcome == OUTCOME_PASS
    assert candidate.suggested_discount_bp == 0
    assert "هیچ پله‌ای" in note.detail_fa


def test_the_filter_never_blocks_and_never_touches_value():
    candidate = _candidate()
    accepted, rejected = apply_filters([candidate], _ctx())

    assert accepted and not rejected
    assert accepted[0].expected_value_display == 100_000.0
    outcomes = {f.code: f.outcome for f in accepted[0].factors}
    assert outcomes["offer_policy"] == OUTCOME_PASS


def test_product_name_is_matched_after_normalisation():
    """دفتر کل کالا را با نامِ نرمال‌شده می‌شناسد و پیشنهاد با نامِ نمایشی."""
    candidate = _candidate(product="  Pet Food ")
    filter_offer_policy(candidate, _ctx(margin_by_product={"pet food": 3_000}))
    assert candidate.suggested_discount_bp == 500


# ═══════════════════════════════════ فرصتِ بی‌کالا: مبنا حاشیه‌ی خودِ مشتری
def test_a_productless_opportunity_uses_the_customers_own_margin():
    """نجات از ریزش کالای مشخصی ندارد؛ سقفِ تخفیف از سبدِ معمولِ همان مشتری می‌آید."""
    candidate = _candidate(product=None)
    note = filter_offer_policy(candidate, _ctx(customer_margin_bp_of={"C1": 3_000}))

    assert note.outcome == OUTCOME_PASS
    assert candidate.suggested_discount_bp == 500
    assert "خودِ مشتری" in note.detail_fa


def test_a_productless_opportunity_without_customer_margin_is_skipped():
    candidate = _candidate(product=None)
    note = filter_offer_policy(candidate, _ctx())

    assert note.outcome == OUTCOME_SKIP
    assert candidate.suggested_discount_bp is None
    assert "کالای مشخصی ندارد" in note.detail_fa
