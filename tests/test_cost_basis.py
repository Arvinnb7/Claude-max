"""بهای زمانِ معامله و سود ناخالص — تابع خالص.

مهم‌ترین تستِ این فایل `test_old_sale_uses_the_old_cost_not_the_latest` است.
§۳.۴ سند صریحاً استفاده از «آخرین قیمت خرید» را ممنوع کرده، و دلیلش در اقتصادِ
تورمی آشکار است: کالایی که پارسال ۱۰۰ خریده و ۱۵۰ فروخته شده، با بهای امروزِ
۲۰۰ «زیان‌ده» به‌نظر می‌رسد — و سیستم کالایی را کنار می‌گذارد که سودده بوده.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.costs.basis import (  # noqa: E402
    CONFIDENCE_HISTORY_EXACT,
    CONFIDENCE_HISTORY_IMPUTED,
    CostLookup,
    CostPoint,
    coverage_note_fa,
    coverage_ratio,
    gross_profit_rial,
    is_computable,
    line_cost_rial,
)


def _lookup(*pairs: tuple[str, int]) -> CostLookup:
    return CostLookup.from_points([CostPoint(d, c) for d, c in pairs])


# ═══════════════════════════════ بهای زمانِ معامله (§۳.۴)
def test_old_sale_uses_the_old_cost_not_the_latest():
    """قاعده‌ای که سند صریحاً می‌خواهد."""
    lookup = _lookup(("2023-01-01", 100), ("2024-01-01", 200))

    cost, confidence = lookup.at("2023-06-15")
    assert cost == 100, "بهای پارسال باید استفاده شود، نه ۲۰۰ امسال"
    assert confidence == CONFIDENCE_HISTORY_EXACT

    assert lookup.at("2024-06-15")[0] == 200


def test_exact_boundary_belongs_to_the_new_cost():
    """در روزِ دقیقِ اثر، بهای تازه معتبر است."""
    lookup = _lookup(("2023-01-01", 100), ("2024-01-01", 200))
    assert lookup.at("2024-01-01") == (200, CONFIDENCE_HISTORY_EXACT)
    assert lookup.at("2023-12-31") == (100, CONFIDENCE_HISTORY_EXACT)


def test_sale_before_any_known_cost_is_imputed_not_exact():
    """بهای بعدی به عقب تعمیم می‌شود، ولی **تخمینی** برچسب می‌خورد."""
    lookup = _lookup(("2024-01-01", 200))
    cost, confidence = lookup.at("2023-05-05")
    assert cost == 200
    assert confidence == CONFIDENCE_HISTORY_IMPUTED, (
        "تعمیم به عقب نباید مثل بهای دقیق برچسب بخورد"
    )


def test_empty_history_returns_nothing():
    assert CostLookup.from_points([]).at("2024-01-01") is None


def test_points_are_sorted_regardless_of_input_order():
    """ورودی نامرتب نباید نتیجه را عوض کند."""
    scrambled = _lookup(("2024-01-01", 200), ("2022-01-01", 50), ("2023-01-01", 100))
    assert scrambled.at("2023-06-01") == (100, CONFIDENCE_HISTORY_EXACT)
    assert scrambled.at("2022-06-01") == (50, CONFIDENCE_HISTORY_EXACT)


# ═══════════════════════════════════════ بهای خط (مقدار × واحد)
def test_line_cost_multiplies_by_quantity():
    lookup = _lookup(("2023-01-01", 100))
    # سه واحد ⇒ quantity_milli = 3000
    assert line_cost_rial(lookup, "2023-06-01", 3000) == (300, CONFIDENCE_HISTORY_EXACT)


def test_missing_quantity_means_one_unit():
    lookup = _lookup(("2023-01-01", 100))
    assert line_cost_rial(lookup, "2023-06-01", None) == (100, CONFIDENCE_HISTORY_EXACT)


def test_fractional_quantity_is_supported():
    """مقدارِ کسری (مثلاً ۲٫۵ کیلو) باید درست ضرب شود."""
    lookup = _lookup(("2023-01-01", 100))
    assert line_cost_rial(lookup, "2023-06-01", 2500)[0] == 250


def test_no_lookup_means_no_cost():
    assert line_cost_rial(None, "2023-06-01", 1000) is None


# ═════════════════════════════════════ سود: NULL هرگز صفر نمی‌شود
def test_gross_profit_is_revenue_minus_cost():
    assert gross_profit_rial(1000, 600) == 400


def test_missing_cost_gives_none_not_zero():
    """صفر یعنی «سودی نداشت»؛ واقعیت «نمی‌دانیم» است. این دو یکی نیستند."""
    assert gross_profit_rial(1000, None) is None


def test_missing_revenue_gives_none():
    assert gross_profit_rial(None, 600) is None


def test_negative_profit_is_reported_not_hidden():
    """فروش زیر بها اتفاق می‌افتد و باید دیده شود."""
    assert gross_profit_rial(500, 800) == -300


def test_return_line_reverses_the_profit():
    """خط برگشتی درآمد و بهای منفی دارد، پس سودِ خط اصلی را خنثی می‌کند."""
    original = gross_profit_rial(1000, 600)
    reversal = gross_profit_rial(-1000, -600)
    assert original + reversal == 0


# ═══════════════════════════════════ پوشش: عددِ ناقص چاپ نمی‌شود
def test_full_coverage_is_computable():
    assert coverage_ratio(100, 100) == 1.0
    assert is_computable(1.0) is True


def test_partial_coverage_is_not_computable():
    coverage = coverage_ratio(100, 99)
    assert coverage == 0.99
    assert is_computable(coverage) is False, (
        "۹۹٪ هم کافی نیست: جمعِ ناقص کمتر از واقع نشان می‌دهد"
    )


def test_zero_coverage_is_not_computable():
    assert is_computable(coverage_ratio(100, 0)) is False


def test_no_lines_means_zero_coverage():
    assert coverage_ratio(0, 0) == 0.0


def test_coverage_note_states_the_percentage_when_partial():
    note = coverage_note_fa(coverage_ratio(100, 40))
    assert "۴۰" in note or "40" in note
    assert "محاسبه نشد" in note


def test_coverage_note_distinguishes_none_from_partial():
    assert "هیچ" in coverage_note_fa(0.0)
    assert "محاسبه شد" in coverage_note_fa(1.0)
