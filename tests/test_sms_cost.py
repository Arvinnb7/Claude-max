"""هزینه‌ی پیامک — قطعه‌شماری واقعی، نه تقسیم ساده.

مهم‌ترین تستِ این فایل `test_long_message_uses_the_real_concatenation_rule` است:
اگر قطعه‌شماری با تقسیم ساده انجام شود، هزینه‌ی پیام‌های بلند **کم‌برآورد**
می‌شود و بودجه‌ی کمپین بیشتر از واقع به‌نظر می‌رسد.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.execution.cost import (  # noqa: E402
    DEFAULT_COST_PER_SEGMENT_RIAL,
    SEGMENT_CHARS_MULTIPART,
    SEGMENT_CHARS_SINGLE,
    cost_note_fa,
    message_cost_rial,
    segment_count,
    total_cost_rial,
)


def _fa(n: int) -> str:
    return "الف" * 0 + "ا" * n  # متن فارسی به طول دلخواه


# ═══════════════════════════════════════════════════ قطعه‌شماری
def test_empty_message_costs_nothing():
    assert segment_count("") == 0
    assert message_cost_rial("") == 0


def test_short_message_is_one_segment():
    assert segment_count(_fa(1)) == 1
    assert segment_count(_fa(69)) == 1


def test_exactly_seventy_characters_is_still_one_segment():
    """مرزِ دقیق: ۷۰ کاراکتر هنوز یک قطعه است."""
    assert segment_count(_fa(SEGMENT_CHARS_SINGLE)) == 1


def test_seventy_one_characters_becomes_two_segments():
    assert segment_count(_fa(71)) == 2


def test_long_message_uses_the_real_concatenation_rule():
    """پیام ۱۴۰ کاراکتری: تقسیم ساده ۲ قطعه می‌گوید، پنل ۳ قطعه می‌گیرد.

    ظرفیت هر قطعه در پیامِ چندقطعه‌ای ۶۷ است نه ۷۰، چون شش بایت سرآیندِ اتصال
    از هر قطعه کم می‌شود. کم‌برآوردِ هزینه سمتِ خطرناک است.
    """
    naive = math.ceil(140 / SEGMENT_CHARS_SINGLE)
    real = segment_count(_fa(140))
    assert naive == 2
    assert real == 3, "قاعده‌ی واقعی پنل باید استفاده شود، نه تقسیم ساده"
    assert real > naive


def test_multipart_capacity_is_sixty_seven():
    assert segment_count(_fa(SEGMENT_CHARS_MULTIPART * 2)) == 2
    assert segment_count(_fa(SEGMENT_CHARS_MULTIPART * 2 + 1)) == 3


def test_segment_count_never_decreases_with_length():
    """ناوردا: پیامِ بلندتر هرگز ارزان‌تر نمی‌شود."""
    previous = 0
    for length in range(0, 400, 7):
        current = segment_count(_fa(length))
        assert current >= previous
        previous = current


# ═════════════════════════════════════════════════════════ قیمت
def test_price_is_three_thousand_rial_per_segment():
    """۳۰۰ تومان = ۳۰۰۰ ریال، نرخ اعلام‌شده."""
    assert DEFAULT_COST_PER_SEGMENT_RIAL == 3_000
    assert message_cost_rial(_fa(50)) == 3_000
    assert message_cost_rial(_fa(140)) == 9_000


def test_price_per_segment_is_configurable():
    assert message_cost_rial(_fa(50), cost_per_segment_rial=5_000) == 5_000


def test_total_cost_sums_each_message_separately():
    """جمعِ هزینه باید هر پیام را جدا قطعه‌شماری کند، نه متن‌ها را بچسباند.

    چسباندن، دو پیامِ ۴۰ کاراکتری را ۸۰ کاراکتر و «۲ قطعه» می‌کرد؛ در واقع
    دو پیامِ جداست و هرکدام یک قطعه.
    """
    texts = [_fa(40), _fa(40)]
    assert total_cost_rial(texts) == 2 * 3_000


def test_total_cost_of_nothing_is_zero():
    assert total_cost_rial([]) == 0


def test_cost_is_integer_rial_like_every_other_money_in_the_system():
    value = message_cost_rial(_fa(200))
    assert isinstance(value, int)


# ═══════════════════════════════════════════════════════ توضیح
def test_cost_note_explains_the_numbers():
    note = cost_note_fa(2, 3, 9_000, display_text="۹۰۰ تومان")
    assert "2 پیام" in note
    assert "3 قطعه" in note
    assert "۹۰۰ تومان" in note
    assert "قطعه‌شماری" in note


def test_cost_note_for_empty_batch_is_honest():
    assert "هزینه‌ای هم ندارد" in cost_note_fa(0, 0, 0, display_text="۰")
