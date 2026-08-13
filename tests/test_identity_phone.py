"""نرمال‌سازی شماره‌ی ایرانی — همان مشتری در نگارش‌های مختلف باید یکی شود."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.identity import (  # noqa: E402
    is_mobile,
    mask_phone,
    normalize_phone,
    phone_identity_key,
)

_SAME_MOBILE = [
    "09123456789",
    "0912 345 6789",
    "0912-345-6789",
    "۰۹۱۲۳۴۵۶۷۸۹",
    "۰۹۱۲-۳۴۵-۶۷۸۹",
    "+989123456789",
    "+98 912 345 6789",
    "00989123456789",
    "989123456789",
    "9123456789",
    " 0912.345.6789 ",
    "0912 345 67 89 داخلی 23",
]


@pytest.mark.parametrize("raw", _SAME_MOBILE)
def test_all_spellings_collapse_to_one_key(raw: str):
    """اگر این تست بشکند، یک مشتری به چند مشتری تکه می‌شود."""
    assert normalize_phone(raw) == "+989123456789"


def test_identity_key_is_the_normalized_form():
    assert phone_identity_key("0912 345 6789") == "+989123456789"
    assert phone_identity_key("نامعتبر") is None


def test_landline_with_known_area_code():
    assert normalize_phone("021-88776655") == "+982188776655"
    assert normalize_phone("۰۲۱ ۸۸۷۷۶۶۵۵") == "+982188776655"
    assert normalize_phone("+982188776655") == "+982188776655"


@pytest.mark.parametrize("raw", [
    "",
    None,
    "12345",
    "abc",
    "0912345678",      # یک رقم کم
    "091234567890",    # یک رقم زیاد
    "+1 415 555 1234",  # خارجی — این ماژول ادعای پوشش ندارد
    "1234567890",      # شناسه‌ی عددی، نه تلفن (کد استان ۱۲ وجود ندارد)
    "0221234567",      # کد استان نامعتبر
])
def test_invalid_inputs_are_rejected_not_guessed(raw):
    """حل‌نشدن بی‌ضرر است؛ حلِ غلط یعنی پیامک به آدم اشتباه."""
    assert normalize_phone(raw) is None


def test_is_mobile_separates_sms_capable_numbers():
    assert is_mobile("09123456789") is True
    assert is_mobile("021-88776655") is False
    assert is_mobile("نامعتبر") is False


def test_mask_hides_middle_digits():
    masked = mask_phone("09123456789")
    assert masked.startswith("+98912")
    assert masked.endswith("6789")
    assert "*" in masked
    assert "345" not in masked


def test_mask_handles_unnormalizable_input():
    assert mask_phone("") == "—"
    assert mask_phone("12345").endswith("2345")
    assert mask_phone("12345").startswith("*")


def test_idempotent():
    once = normalize_phone("0912 345 6789")
    assert normalize_phone(once) == once
