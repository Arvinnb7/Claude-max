"""نرمال‌سازی نام کالا و استخراج اندازه‌ی بسته — بدون هیچ فرض دامنه‌ای."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.catalog import (  # noqa: E402
    normalize_product_name,
    parse_pack_size,
    product_family_key,
)


def test_persian_spelling_variants_collapse():
    """ي/ك عربی، نیم‌فاصله، ارقام فارسی و فاصله‌ی اضافه نباید محصول را تکه کنند."""
    variants = [
        "غذای خشک گربه",
        "غذاي خشك گربه",
        "غذای‌خشک گربه",
        "  غذای   خشک   گربه ",
        "غذای خشک گربه‏",
    ]
    normalized = {normalize_product_name(v) for v in variants}
    assert len(normalized) == 1


def test_symbols_and_case_are_stripped():
    assert normalize_product_name("  Royal   Canin® 2Kg ") == "royal canin 2kg"
    assert normalize_product_name("محصول (ویژه)") == "محصول ویژه"


def test_decimal_separator_survives_normalization():
    """باگ واقعی: حذف نقطه، «۱٫۵ کیلو» را «۱ ۵ کیلو» می‌کرد و اندازه را ۵ برابر."""
    assert normalize_product_name("۱٫۵ کیلویی") == "1.5 کیلویی"
    assert parse_pack_size("غذای خشک ۱٫۵ کیلویی").value == 1500.0


def test_thousands_separator_is_removed_not_treated_as_decimal():
    assert normalize_product_name("روغن ۱,۵۰۰ گرم") == "روغن 1500 گرم"
    assert parse_pack_size("روغن ۱,۵۰۰ گرم").value == 1500.0


def test_none_and_empty_are_safe():
    assert normalize_product_name(None) == ""
    assert normalize_product_name("") == ""
    assert parse_pack_size(None) is None
    assert product_family_key(None) == ""


@pytest.mark.parametrize(("name", "value", "unit"), [
    ("غذای خشک ۱٫۵ کیلویی", 1500.0, "g"),
    ("غذای خشک 3kg", 3000.0, "g"),
    ("پودر ۲۵۰ گرمی", 250.0, "g"),
    ("قرص ۵۰۰ mg", 0.5, "g"),
    ("شامپو 500ml", 500.0, "ml"),
    ("شیر ۱ لیتری", 1000.0, "ml"),
    ("ماست ۹۰۰ سی‌سی", 900.0, "ml"),
    ("دستمال ۱۲ عددی", 12.0, "pcs"),
    ("نخ ۱۰۰ متری", 10000.0, "cm"),
    ("لوله ۲۰ سانتی‌متر", 20.0, "cm"),
])
def test_pack_size_extraction(name: str, value: float, unit: str):
    size = parse_pack_size(name)
    assert size is not None, name
    assert size.value == pytest.approx(value)
    assert size.unit == unit


def test_compound_unit_is_not_split_by_zwnj():
    """باگ واقعی: نیم‌فاصله «میلی‌لیتر» را به «میلی» + «لیتر» تکه می‌کرد."""
    size = parse_pack_size("نوشیدنی ۵۰۰ میلی‌لیتر")
    assert size is not None
    assert (size.value, size.unit) == (500.0, "ml")


def test_non_count_size_wins_over_count():
    """«۱۲ عددی ۵۰۰ میلی‌لیتر» → حجم تعیین‌کننده‌ی مصرف است، نه شمارش."""
    size = parse_pack_size("بسته ۱۲ عددی ۵۰۰ میلی‌لیتر")
    assert size is not None
    assert size.unit == "ml"


@pytest.mark.parametrize("name", [
    "کالای بدون اندازه",
    "کد 1234",
    "محصول 0 گرم",       # اندازه‌ی صفر بی‌معناست
    "",
])
def test_no_size_returns_none_not_a_guess(name: str):
    assert parse_pack_size(name) is None


def test_value_milli_is_integer_for_ledger():
    size = parse_pack_size("غذای خشک ۱٫۵ کیلویی")
    assert size.value_milli == 1_500_000
    assert isinstance(size.value_milli, int)


def test_family_key_groups_pack_variants():
    """همان کالا در بسته‌بندی دیگر باید یک خانواده باشد (در پیشنهاد «کالای نو» نیست)."""
    keys = {
        product_family_key("غذای خشک گربه ۱٫۵ کیلویی"),
        product_family_key("غذای خشک گربه 3kg"),
        product_family_key("غذای خشک گربه ۱۰ کیلوگرم"),
    }
    assert keys == {"غذای خشک گربه"}


def test_family_key_keeps_distinct_products_apart():
    assert product_family_key("غذای خشک گربه ۲kg") != product_family_key("غذای خشک سگ ۲kg")


def test_family_key_never_empty_when_name_is_only_a_size():
    """خالی‌شدن کلید، همه‌ی این کالاها را در یک خانواده‌ی جعلی جمع می‌کرد."""
    assert product_family_key("۱۲ تایی") == "12 تایی"


def test_normalization_is_idempotent():
    once = normalize_product_name("غذاي  خشك ۱٫۵ كيلويي")
    assert normalize_product_name(once) == once
    assert product_family_key(product_family_key("شامپو 500ml")) == "شامپو"
