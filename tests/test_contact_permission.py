"""دروازه‌ی مجوز تماس — تصمیم، ترتیب دلیل، و صداقتِ «بررسی نشد».

مهم‌ترین تستِ این فایل `test_control_arm_member_is_blocked` است: اگر بشکند، یعنی
مسیرِ ارسال می‌تواند به گروه کنترل پیام بدهد و هر آزمایشی که بعد از آن اجرا شود
بی‌معنا است — بدون اینکه ردی از خرابی بماند.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from dataclasses import dataclass  # noqa: E402

from mktcore.contact.permission import (  # noqa: E402
    REASON_CONSENT,
    REASON_CONTROL,
    REASON_FATIGUE,
    ContactGate,
)
from mktcore.opportunities.contract import (  # noqa: E402
    OUTCOME_BLOCK,
    OUTCOME_PASS,
    OUTCOME_SKIP,
)


def _full_gate(**overrides) -> ContactGate:
    """دروازه‌ای که همه‌ی بررسی‌هایش داده دارد — تا `skip` قاطیِ تست نشود."""
    base = {
        "fatigue_window_days": 14,
        "has_suppression_data": True,
        "has_campaign_data": True,
    }
    base.update(overrides)
    return ContactGate(**base)


# ═══════════════════════════════════════════════════ تصمیم‌های پایه
def test_clean_customer_is_allowed():
    gate = _full_gate()
    assert gate.reason_for("C1") is None
    note = gate.check("C1")
    assert note.outcome == OUTCOME_PASS
    assert note.blocking is False


def test_control_arm_member_is_blocked():
    """خطِ سرخ: عضو گروه کنترل هرگز مجاز نیست."""
    gate = _full_gate(control_arm=frozenset({"C1"}))
    assert gate.reason_for("C1") == REASON_CONTROL
    note = gate.check("C1")
    assert note.outcome == OUTCOME_BLOCK
    assert note.blocking is True
    assert "آزمایش" in (note.detail_fa or "")


def test_opted_out_customer_is_blocked():
    gate = _full_gate(opted_out=frozenset({"C2"}))
    assert gate.reason_for("C2") == REASON_CONSENT
    assert gate.check("C2").outcome == OUTCOME_BLOCK


def test_opt_out_by_phone_blocks_even_without_customer_key_match():
    """لیست سیاهِ پنل و «لغو ۱۱» فقط شماره می‌شناسند، نه کلید مشتری."""
    gate = _full_gate(opted_out_phones=frozenset({"+989121234567"}))
    assert gate.reason_for("C3") is None
    assert gate.reason_for("C3", phone="+989121234567") == REASON_CONSENT


def test_recently_contacted_customer_is_blocked():
    gate = _full_gate(recently_contacted=frozenset({"C4"}))
    note = gate.check("C4")
    assert note.outcome == OUTCOME_BLOCK
    assert "۱۴" in (note.detail_fa or "") or "14" in (note.detail_fa or "")


def test_missing_customer_key_does_not_crash():
    gate = _full_gate(opted_out=frozenset({"C1"}))
    assert gate.reason_for(None) is None
    assert gate.reason_for(None, phone=None) is None


def test_non_string_customer_key_is_normalised():
    """کلید مشتری در جاهای مختلف int یا str است؛ دروازه نباید به آن حساس باشد."""
    gate = _full_gate(control_arm=frozenset({"77"}))
    assert gate.reason_for(77) == REASON_CONTROL


# ═════════════════════════════════════════════ ترتیب دلیل (ماندگاری)
def test_opt_out_wins_over_control_arm():
    """اگر هر دو برقرار باشد، «منصرف» گزارش می‌شود.

    چون عضویت در کنترل با بسته‌شدن کمپین تمام می‌شود ولی انصراف هرگز؛ گزارشِ
    دلیلِ ماندگارتر به کاربر می‌گوید «دوباره هم تلاش نکن».
    """
    gate = _full_gate(
        control_arm=frozenset({"C1"}), opted_out=frozenset({"C1"}),
    )
    assert gate.reason_for("C1") == REASON_CONSENT


def test_control_arm_wins_over_fatigue():
    gate = _full_gate(
        control_arm=frozenset({"C1"}), recently_contacted=frozenset({"C1"}),
    )
    assert gate.reason_for("C1") == REASON_CONTROL


# ═══════════════════════════════════════ صداقت: «بررسی نشد» ≠ «قبول»
def test_missing_suppression_register_is_reported_as_unchecked():
    gate = ContactGate(fatigue_window_days=14, has_campaign_data=True)
    assert REASON_CONSENT in gate.unchecked_reasons()
    note = gate.check("C1")
    assert note.outcome == OUTCOME_SKIP, "نبودِ داده هرگز نباید «قبول» ثبت شود"


def test_missing_fatigue_window_is_reported_as_unchecked():
    gate = ContactGate(
        has_suppression_data=True, has_campaign_data=True, fatigue_window_days=None,
    )
    assert REASON_FATIGUE in gate.unchecked_reasons()
    assert gate.check("C1").outcome == OUTCOME_SKIP


def test_fully_loaded_gate_reports_nothing_unchecked():
    assert _full_gate().unchecked_reasons() == ()


def test_block_beats_skip_when_data_is_partial():
    """نبودِ یک بررسی نباید بررسیِ دیگری را که **قطعاً** رد کرده خفه کند."""
    gate = ContactGate(control_arm=frozenset({"C1"}), has_campaign_data=True)
    assert gate.check("C1").outcome == OUTCOME_BLOCK


# ═════════════════════════════════════════════════════ غربالِ فهرست
@dataclass
class _Recipient:
    customer_id: str
    phone: str | None = None


def test_partition_splits_and_counts_reasons():
    gate = _full_gate(
        control_arm=frozenset({"A"}),
        opted_out=frozenset({"B"}),
        recently_contacted=frozenset({"C"}),
    )
    people = [_Recipient(k) for k in ("A", "B", "C", "D", "E")]
    result = gate.partition(people, key=lambda r: r.customer_id)

    assert [r.customer_id for r in result.allowed] == ["D", "E"]
    assert result.suppressed_count == 3
    assert result.counts_by_reason() == {
        REASON_CONTROL: 1, REASON_CONSENT: 1, REASON_FATIGUE: 1,
    }


def test_partition_uses_phone_extractor():
    gate = _full_gate(opted_out_phones=frozenset({"+989120000000"}))
    people = [_Recipient("A", "+989120000000"), _Recipient("B", "+989121111111")]
    result = gate.partition(
        people, key=lambda r: r.customer_id, phone=lambda r: r.phone,
    )
    assert [r.customer_id for r in result.allowed] == ["B"]


def test_suppression_is_never_silent():
    """قاعده‌ی پروژه: حذف باید شمرده و دلیل‌دار گزارش شود."""
    gate = _full_gate(opted_out=frozenset({"A"}))
    result = gate.partition([_Recipient("A"), _Recipient("B")], key=lambda r: r.customer_id)

    payload = result.to_dict()
    assert payload["مسدودشده"] == 1
    assert payload["دلایل_مسدودی"] == [{"دلیل": "رضایت تماس", "تعداد": 1}]
    note = result.note_fa()
    assert note is not None and "رضایت تماس" in note


def test_nothing_suppressed_means_no_note():
    gate = _full_gate()
    result = gate.partition([_Recipient("A")], key=lambda r: r.customer_id)
    assert result.suppressed_count == 0
    assert result.note_fa() is None
    assert result.to_dict()["مسدودشده"] == 0


def test_unchecked_dimensions_are_reported_in_payload():
    gate = ContactGate(has_campaign_data=True, fatigue_window_days=14)
    result = gate.partition([_Recipient("A")], key=lambda r: r.customer_id)
    assert "بررسی‌نشده" in result.to_dict()


def test_empty_gate_allows_everyone_but_admits_it_checked_nothing():
    """رفتار پیش از این ارتقا: هیچ گاردی نبود. دروازه‌ی خالی همان است — ولی صریح."""
    gate = ContactGate()
    result = gate.partition([_Recipient("A"), _Recipient("B")], key=lambda r: r.customer_id)
    assert result.suppressed_count == 0
    assert len(gate.unchecked_reasons()) == 3
