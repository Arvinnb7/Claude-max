"""اثر افزوده‌ی سلولی و انقباض — تابع خالص، بدون دیتابیس.

ادعای مرکزی: تخمینِ سلولِ کوچک باید تقریباً به والد منقبض شود (چون نوفه است)، و
تخمینِ سلولِ بزرگ باید تقریباً خودش بماند (چون یافته است). بین این دو، انتقال
باید نرم باشد نه پرشی.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.uplift.empirical import (  # noqa: E402
    BASIS_CELL,
    BASIS_GLOBAL,
    BASIS_KIND,
    BASIS_NONE,
    MIN_CELL_OBSERVATIONS,
    SHRINKAGE_K,
    Observation,
    compute_uplift_table,
)


def _obs(
    kind: str, state: str, *, n_t: int, n_c: int, rate_t: float, rate_c: float,
) -> list[Observation]:
    """مشاهده‌های ساختگی با نرخ‌های دقیق (قطعی، نه تصادفی)."""
    out = []
    for i in range(n_t):
        out.append(Observation(kind, state, "treatment", i < round(n_t * rate_t)))
    for i in range(n_c):
        out.append(Observation(kind, state, "control", i < round(n_c * rate_c)))
    return out


# ------------------------------------------------------------ پایه
def test_empty_input_yields_no_adjustment():
    """بدون داده‌ی آزمایشی، ضریب باید بی‌اثر باشد — رفتار امروز حفظ شود."""
    table = compute_uplift_table([])
    assert not table.available
    uplift, basis = table.lookup("هر نوع", "هر حالت")
    assert uplift == 0.0
    assert basis == BASIS_NONE


def test_large_cell_keeps_its_own_estimate():
    """سلول با نمونه‌ی بزرگ باید تقریباً اثر خودش را نگه دارد."""
    table = compute_uplift_table(
        _obs("چرخه", "لغزش", n_t=2000, n_c=2000, rate_t=0.40, rate_c=0.20)
    )
    cell = table.cells[("چرخه", "لغزش")]
    assert cell.raw_uplift == pytest.approx(0.20, abs=0.01)
    # با ۲۰۰۰ نمونه، وزن سلول ≈ ۰٫۹۸ → تقریباً دست‌نخورده
    assert cell.shrunk_uplift == pytest.approx(0.20, abs=0.01)
    assert cell.basis == BASIS_CELL


def test_small_cell_is_pulled_toward_the_parent():
    """سلول کوچک با اثر افراطی نباید رتبه‌بندی را تکان بدهد."""
    # والد: اثر ملایم ۵٪ از یک سلول بزرگ در همان نوع
    big = _obs("چرخه", "وفادار", n_t=1000, n_c=1000, rate_t=0.25, rate_c=0.20)
    # سلول کوچک با اثر ظاهری ۵۰٪ — تقریباً قطعاً نوفه
    small = _obs("چرخه", "خفته", n_t=12, n_c=12, rate_t=0.75, rate_c=0.25)
    table = compute_uplift_table(big + small)

    cell = table.cells[("چرخه", "خفته")]
    assert cell.raw_uplift == pytest.approx(0.50, abs=0.05)
    # منقبض‌شده باید بسیار کمتر از خام و نزدیک والد باشد
    assert cell.shrunk_uplift < 0.20
    assert cell.shrunk_uplift > table.by_kind["چرخه"]  # کمی به‌سمت خودش کشیده


def test_shrinkage_weight_is_half_at_the_constant():
    """در `n = k` وزن سلول و والد باید برابر باشد (۵۰-۵۰)."""
    n = int(SHRINKAGE_K)
    parent_group = _obs("الف", "پایه", n_t=4000, n_c=4000, rate_t=0.20, rate_c=0.20)
    cell_group = _obs("الف", "هدف", n_t=n, n_c=n, rate_t=0.60, rate_c=0.20)
    table = compute_uplift_table(parent_group + cell_group)

    cell = table.cells[("الف", "هدف")]
    parent = table.by_kind["الف"]
    expected = 0.5 * cell.raw_uplift + 0.5 * parent
    assert cell.shrunk_uplift == pytest.approx(expected, abs=0.02)


def test_transition_is_smooth_not_a_cliff():
    """با بزرگ‌تر شدن نمونه، تخمین باید یکنوا به‌سمت اثر خام حرکت کند."""
    values = []
    for n in (12, 25, 50, 100, 400, 2000):
        base = _obs("الف", "پایه", n_t=4000, n_c=4000, rate_t=0.20, rate_c=0.20)
        cell = _obs("الف", "هدف", n_t=n, n_c=n, rate_t=0.60, rate_c=0.20)
        table = compute_uplift_table(base + cell)
        values.append(table.cells[("الف", "هدف")].shrunk_uplift)

    assert values == sorted(values), "حرکت باید یکنوا باشد"
    assert values[-1] > values[0] * 2


# ------------------------------------------------------ سلسله‌مراتب بازگشت
def test_unseen_cell_falls_back_to_its_kind():
    table = compute_uplift_table(
        _obs("چرخه", "لغزش", n_t=500, n_c=500, rate_t=0.35, rate_c=0.20)
    )
    uplift, basis = table.lookup("چرخه", "حالتی که هرگز دیده نشده")
    assert basis == BASIS_KIND
    assert uplift > 0


def test_unseen_kind_falls_back_to_global():
    table = compute_uplift_table(
        _obs("چرخه", "لغزش", n_t=500, n_c=500, rate_t=0.35, rate_c=0.20)
    )
    uplift, basis = table.lookup("نوعی که هرگز دیده نشده", "لغزش")
    assert basis == BASIS_GLOBAL
    assert uplift == pytest.approx(table.global_uplift)


def test_cell_below_minimum_observations_does_not_claim_cell_basis():
    table = compute_uplift_table(
        _obs("الف", "کوچک", n_t=MIN_CELL_OBSERVATIONS - 1, n_c=3,
             rate_t=0.9, rate_c=0.1)
    )
    _uplift, basis = table.lookup("الف", "کوچک")
    assert basis != BASIS_CELL


def test_missing_arm_produces_no_estimate():
    """گروهی که فقط بازوی آزمایش دارد، اثر نمی‌دهد — مقایسه‌ای وجود ندارد."""
    only_treatment = [
        Observation("الف", "ب", "treatment", i < 30) for i in range(100)
    ]
    table = compute_uplift_table(only_treatment)
    assert table.global_uplift is None
    _uplift, basis = table.lookup("الف", "ب")
    assert basis in (BASIS_GLOBAL, BASIS_NONE, BASIS_KIND)


# --------------------------------------------------------- حذفِ گروه بی‌اثر
def test_clearly_useless_group_is_flagged():
    """گروهی که تماس اثرش را بدتر می‌کند باید با اطمینان علامت بخورد."""
    table = compute_uplift_table(
        _obs("چرخه", "وفادار", n_t=2000, n_c=2000, rate_t=0.20, rate_c=0.40)
    )
    cell = table.is_useless("چرخه", "وفادار")
    assert cell is not None
    assert cell.ci[1] <= 0


def test_group_with_positive_effect_is_not_flagged():
    table = compute_uplift_table(
        _obs("چرخه", "لغزش", n_t=2000, n_c=2000, rate_t=0.40, rate_c=0.20)
    )
    assert table.is_useless("چرخه", "لغزش") is None


def test_small_group_is_never_flagged_as_useless():
    """حذفِ یک گروه تصمیم پرهزینه‌ای است؛ با نمونه‌ی کم انجام نمی‌شود."""
    table = compute_uplift_table(
        _obs("چرخه", "خفته", n_t=8, n_c=8, rate_t=0.0, rate_c=0.9)
    )
    assert table.is_useless("چرخه", "خفته") is None


def test_uncertain_zero_effect_is_not_flagged():
    """اثر صفر با بازه‌ی پهن، «بی‌فایده‌ی اثبات‌شده» نیست."""
    table = compute_uplift_table(
        _obs("چرخه", "نامعلوم", n_t=40, n_c=40, rate_t=0.30, rate_c=0.30)
    )
    assert table.is_useless("چرخه", "نامعلوم") is None


# ------------------------------------------------------------ بازتولیدپذیری
def test_same_input_gives_identical_table():
    observations = (
        _obs("الف", "یک", n_t=300, n_c=300, rate_t=0.4, rate_c=0.2)
        + _obs("ب", "دو", n_t=200, n_c=200, rate_t=0.1, rate_c=0.3)
    )
    first = compute_uplift_table(observations).to_dict()
    second = compute_uplift_table(observations).to_dict()
    assert first == second


def test_dict_shape_carries_evidence_for_every_cell():
    table = compute_uplift_table(
        _obs("الف", "یک", n_t=300, n_c=300, rate_t=0.4, rate_c=0.2)
    )
    payload = table.to_dict()
    assert payload["available"] is True
    cell = payload["cells"][0]
    for key in ("kind", "lifecycle_state", "n_treatment", "n_control",
                "rate_treatment", "rate_control", "uplift", "basis",
                "basis_label", "ci", "has_enough_data", "useless"):
        assert key in cell, key
    assert cell["basis_label"]
