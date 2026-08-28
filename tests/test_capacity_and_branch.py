"""ظرفیت پیگیری تیم (§۲۵) و شعبه‌ی محتملِ مشتری (§۲۴.۵).

## قاعده‌ی مشترکِ این دو

هیچ‌کدام عدد **حدس نمی‌زنند**. ظرفیتِ تنظیم‌نشده «بررسی نشد» ثبت می‌کند نه
«قبول»، و نبودِ ستون شعبه `None` با دلیل برمی‌گرداند نه «شعبه‌ی نامشخص» — که
مثل یک شعبه‌ی واقعی به‌نظر می‌رسد.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.analysis.branch import likely_branch  # noqa: E402
from mktcore.opportunities.contract import (  # noqa: E402
    OUTCOME_BLOCK,
    OUTCOME_PASS,
    OUTCOME_SKIP,
    OpportunityCandidate,
)
from mktcore.opportunities.filters import filter_operator_capacity  # noqa: E402


def _candidate(key: str, value: float = 1_000.0) -> OpportunityCandidate:
    return OpportunityCandidate(
        kind="یادآوری چرخه‌ی مصرف",
        generator="آزمون",
        generator_version=1,
        customer_key=key,
        title_fa="عنوان",
        action_fa="اقدام",
        reason_fa="دلیل",
        expected_value_display=value,
        value_kind="ارزش فرصت",
    )


# ═════════════════════════════════════════════════ ظرفیت پیگیری تیم
def test_without_a_configured_capacity_nothing_is_blocked():
    """مهم‌ترین ادعا: بدون تنظیم، «بررسی نشد» — نه «قبول»، نه رد."""
    note = filter_operator_capacity(_candidate("c1"), {})

    assert note.outcome == OUTCOME_SKIP
    assert not note.blocking
    assert "تنظیم نشده" in note.detail_fa


def test_capacity_blocks_only_after_the_cap_is_reached():
    ctx = {"daily_capacity": 2}

    outcomes = [
        filter_operator_capacity(_candidate(f"c{i}"), ctx).outcome for i in range(4)
    ]

    assert outcomes == [OUTCOME_PASS, OUTCOME_PASS, OUTCOME_BLOCK, OUTCOME_BLOCK]


def test_the_blocking_note_says_the_number_so_it_is_actionable():
    ctx = {"daily_capacity": 1}
    filter_operator_capacity(_candidate("c1"), ctx)

    note = filter_operator_capacity(_candidate("c2"), ctx)

    assert "1" in note.detail_fa
    assert note.value_text == "1"


def test_relationship_actions_have_their_own_quota():
    """اقدام رابطه‌ای نباید جای تماس فروش را بگیرد — و برعکس."""
    from mktcore.opportunities.contract import VALUE_RELATIONSHIP

    ctx = {"daily_capacity": 1}
    money = _candidate("c1")
    rapport = _candidate("c2")
    rapport.value_kind = VALUE_RELATIONSHIP

    assert filter_operator_capacity(money, ctx).outcome == OUTCOME_PASS
    assert filter_operator_capacity(rapport, ctx).outcome == OUTCOME_PASS


def test_capacity_is_the_last_filter_in_the_chain():
    """شمارشش فقط وقتی درست است که همه‌ی فیلترهای قبلی پاس شده باشند."""
    from mktcore.opportunities.filters import FILTER_CHAIN

    assert FILTER_CHAIN[-1] is filter_operator_capacity


def test_zero_capacity_is_treated_as_not_configured(tmp_path):
    """صفر یعنی «هیچ‌کس نمی‌تواند پیگیری کند» — احتمالاً منظور کاربر نبوده."""
    from sqlalchemy import select

    from mktcore.db.engine import session_scope
    from mktcore.db.lookup import resolve_business_id
    from mktcore.db.migrations import ensure_schema, reset_ensure_cache
    from mktcore.db.models import AppSetting, Business
    from mktcore.settings_store import daily_capacity, set_setting

    reset_ensure_cache()
    db = tmp_path / "app.db"
    ensure_schema(db)
    with session_scope(db) as session:
        session.add(Business(slug="default", name="آزمون"))
        session.flush()
        business_id = resolve_business_id(session, "default")
        set_setting(session, business_id, AppSetting.KEY_DAILY_CAPACITY, "0")

    with session_scope(db) as session:
        assert daily_capacity(session, resolve_business_id(session, "default")) is None
        assert session.scalar(select(AppSetting.value_text)) == "0"
    reset_ensure_cache()


# ═════════════════════════════════════════════════ شعبه‌ی محتمل
def test_no_branch_column_means_none_with_a_reason():
    result = likely_branch([None, None, None])

    assert result.branch is None
    assert result.confidence == "نامشخص"
    assert "وجود ندارد" in result.note_fa


def test_a_dominant_branch_is_reported_with_high_confidence():
    result = likely_branch(["مرکزی"] * 8 + ["شرق"] * 2)

    assert result.branch == "مرکزی"
    assert result.share == 0.8
    assert result.confidence == "بالا"
    assert "۸" in result.note_fa or "8" in result.note_fa


def test_a_split_customer_is_not_claimed_as_dominant():
    result = likely_branch(["مرکزی"] * 3 + ["شرق"] * 2 + ["غرب"])

    assert result.branch == "مرکزی"
    assert result.confidence == "متوسط"
    assert "غالب نیست" in result.note_fa


def test_one_order_does_not_become_a_hundred_percent_claim():
    """۱۰۰٪ از یک سفارش، همان ۱۰۰٪ از هیچ است."""
    result = likely_branch(["مرکزی"])

    assert result.share == 1.0
    assert result.confidence == "پایین"
    assert "کم است" in result.note_fa


def test_missing_branches_are_counted_and_disclosed():
    result = likely_branch(["مرکزی"] * 4 + [None, None])

    assert result.total_orders == 6
    assert result.order_count == 4
    assert "بدون شعبه" in result.note_fa


def test_a_tie_is_broken_deterministically():
    """ترتیبِ نامعین یعنی همان مشتری امروز «الف» و فردا «ب» باشد."""
    first = likely_branch(["ب", "الف", "ب", "الف"]).branch
    second = likely_branch(["الف", "ب", "الف", "ب"]).branch

    assert first == second


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_blank_branch_values_do_not_become_a_branch(blank):
    assert likely_branch([blank, blank]).branch is None
