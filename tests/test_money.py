"""مرز پول: تبدیل بی‌اتلاف بین واحد نمایش و ریالِ عدد صحیح."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.money import (  # noqa: E402
    BP_SCALE,
    QUANTITY_SCALE,
    basis_points_to_ratio,
    format_rial_fa,
    money_payload,
    quantity_from_milli,
    rial_to_display,
    to_basis_points,
    to_quantity_milli,
    to_rial_int,
)


def test_toman_to_rial_is_ten_times():
    assert to_rial_int(1250, "تومان") == 12_500
    assert to_rial_int(1250, "ریال") == 1250


def test_round_trip_is_exact_for_integers():
    for amount in (0, 1, 999, 1_000_000, 987_654_321):
        for currency in ("تومان", "ریال"):
            assert rial_to_display(to_rial_int(amount, currency), currency) == amount


def test_unknown_is_none_never_zero():
    """صفر یعنی «مبلغ صفر بود»؛ نامعلوم باید NULL بماند وگرنه جمع‌ها غلط می‌شوند."""
    for bad in (None, float("nan"), float("inf"), float("-inf"), "", "abc", object()):
        assert to_rial_int(bad, "تومان") is None
    assert to_quantity_milli(None) is None
    assert to_basis_points(float("nan")) is None


def test_numeric_strings_are_accepted():
    """ستون‌های مخلوط اکسل رشته‌ی عددی می‌دهند؛ نباید بی‌صدا NULL شوند."""
    assert to_rial_int("1250", "تومان") == 12_500
    assert to_rial_int("1250.5", "تومان") == 12_505


def test_half_even_rounding_has_no_upward_bias():
    """گرد کردن بانکی: نیم‌ها به زوجِ نزدیک؛ جمعِ خطا در میلیون‌ها خط صفر می‌ماند."""
    assert to_rial_int(0.25, "ریال") == 0
    assert to_rial_int(0.75, "ریال") == 1
    assert to_rial_int(1.5, "ریال") == 2
    assert to_rial_int(2.5, "ریال") == 2
    assert to_rial_int(-2.5, "ریال") == -2


def test_negative_amounts_survive():
    """برگشت از فروش منفی است و باید منفی بماند."""
    assert to_rial_int(-1250, "تومان") == -12_500


def test_sum_of_rial_ints_is_exact_where_float_is_not():
    """چرا عدد صحیح: جمع float انجمنی نیست و آشتی را می‌شکند."""
    values = [0.1] * 30
    assert math.fsum(values) != sum(values)  # اثبات مسئله
    rials = [to_rial_int(v, "ریال") for v in values]
    assert sum(rials) == 0  # ۰.۱ ریال → ۰ (زیر واحد)، ولی قطعی و تکرارپذیر
    tomans = [to_rial_int(v, "تومان") for v in values]
    assert sum(tomans) == 30  # ۰.۱ تومان = ۱ ریال دقیقاً


def test_quantity_milli_keeps_fractional_weight():
    assert to_quantity_milli(1.5) == 1500
    assert quantity_from_milli(1500) == 1.5
    assert QUANTITY_SCALE == 1000


def test_basis_points_round_trip():
    assert to_basis_points(0.15) == 1500
    assert basis_points_to_ratio(1500) == 0.15
    assert to_basis_points(1.0) == BP_SCALE


def test_format_rial_fa_renders_display_unit_not_rial():
    """باگ واقعی: عدد ریالی مستقیم رندر می‌شد و ده برابر دیده می‌شد."""
    assert format_rial_fa(12_500, "تومان") == "1,250 تومان"
    assert format_rial_fa(12_500, "ریال") == "12,500 ریال"
    assert format_rial_fa(None) == "—"


def test_money_payload_shape_has_no_float():
    payload = money_payload(12_500, "تومان")
    assert payload == {
        "rial": 12_500,
        "display_text": "1,250 تومان",
        "display_currency": "تومان",
    }
    assert not isinstance(payload["rial"], float)


def test_invalid_currency_rejected():
    with pytest.raises(ValueError, match="نامعتبر"):
        to_rial_int(100, "دلار")
