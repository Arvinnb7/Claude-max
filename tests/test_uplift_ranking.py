"""رتبه‌بندی مبتنی بر اثر — تضمین عدم رگرسیون و اثبات یادگیری.

دو ادعای متقابل که هر دو باید درست باشند:

۱. **بدون داده‌ی آزمایشی، هیچ چیز عوض نمی‌شود.** ترتیب صندوق بیت‌به‌بیت مثل
   قبل است. قابلیتی که هنوز داده ندارد نباید چیزی را بدتر کند.
۲. **با داده، فهرست عوض می‌شود.** گروهی که اندازه‌گیری نشان داده به تماس پاسخ
   می‌دهد بالا می‌آید، و گروهی که پاسخ نمی‌دهد پایین می‌رود یا حذف می‌شود.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.opportunities.contract import (  # noqa: E402
    OUTCOME_BLOCK,
    OUTCOME_PASS,
    OUTCOME_SKIP,
    OpportunityCandidate,
)
from mktcore.opportunities.engine import (  # noqa: E402
    MIN_UPLIFT_MULTIPLIER,
    UPLIFT_REFERENCE,
    uplift_multiplier,
)
from mktcore.opportunities.filters import apply_filters, filter_uplift  # noqa: E402
from mktcore.uplift.empirical import Observation, compute_uplift_table  # noqa: E402


def _candidate(kind: str = "چرخه", key: str = "C1", value: float = 100_000.0):
    return OpportunityCandidate(
        kind=kind, generator="test", generator_version=1, customer_key=key,
        title_fa="ت", action_fa="ا", reason_fa="د",
        expected_value_display=value, value_kind="ارزش فرصت",
    )


def _obs(kind: str, state: str, *, n: int, rate_t: float, rate_c: float):
    out = []
    for i in range(n):
        out.append(Observation(kind, state, "treatment", i < round(n * rate_t)))
    for i in range(n):
        out.append(Observation(kind, state, "control", i < round(n * rate_c)))
    return out


# ─────────────────────────────────────────── ضریب رتبه‌بندی
def test_no_uplift_data_means_multiplier_one():
    """قلبِ تضمین عدم رگرسیون: بدون داده، ضریب دقیقاً ۱٫۰ است."""
    assert uplift_multiplier(None) == 1.0


def test_reference_uplift_maps_to_one():
    assert uplift_multiplier(UPLIFT_REFERENCE) == pytest.approx(1.0)


def test_stronger_effect_ranks_higher():
    assert uplift_multiplier(0.20) > uplift_multiplier(0.10) > uplift_multiplier(0.05)


def test_multiplier_never_reaches_zero():
    """امتیاز صفر یعنی «هرگز نشان نده» — و آن تصمیمِ فیلتر است، نه رتبه‌بندی."""
    assert uplift_multiplier(0.0) == MIN_UPLIFT_MULTIPLIER
    assert uplift_multiplier(-0.5) == MIN_UPLIFT_MULTIPLIER
    assert MIN_UPLIFT_MULTIPLIER > 0


def test_ranking_order_flips_when_effects_differ():
    """فرصتِ کم‌ارزش‌ترِ پرپاسخ باید از فرصتِ پرارزشِ کم‌پاسخ بالاتر برود.

    این کل نکته‌ی فاز است: «چه کسی می‌خرد» با «چه کسی به‌خاطر ما می‌خرد» یکی نیست.
    """
    high_value_low_effect = 1_000_000 * uplift_multiplier(0.01)
    low_value_high_effect = 300_000 * uplift_multiplier(0.30)
    assert low_value_high_effect > high_value_low_effect


# ─────────────────────────────────────────── فیلتر حذف
def test_filter_skips_when_no_uplift_data():
    """بدون داده، فیلتر «بررسی نشد» ثبت می‌کند — نه «قبول» و نه «رد»."""
    note = filter_uplift(_candidate(), {})
    assert note.outcome == OUTCOME_SKIP
    assert "داده‌ی آزمایشی" in note.detail_fa


def test_filter_blocks_a_measurably_useless_group():
    table = compute_uplift_table(
        _obs("چرخه", "وفادار", n=2000, rate_t=0.20, rate_c=0.40)
    )
    ctx = {"uplift_table": table, "lifecycle_of": {"C1": "وفادار"}}
    note = filter_uplift(_candidate(kind="چرخه"), ctx)

    assert note.outcome == OUTCOME_BLOCK
    assert "حوصله‌ی مشتری" in note.detail_fa


def test_filter_passes_a_responsive_group():
    table = compute_uplift_table(
        _obs("چرخه", "لغزش", n=2000, rate_t=0.40, rate_c=0.20)
    )
    ctx = {"uplift_table": table, "lifecycle_of": {"C1": "لغزش"}}
    note = filter_uplift(_candidate(kind="چرخه"), ctx)

    assert note.outcome == OUTCOME_PASS
    assert "اثر مثبت" in note.detail_fa


def test_filter_does_not_block_on_a_small_sample():
    """حذفِ یک گروه فروشِ بالقوه را از دست می‌دهد؛ با نمونه‌ی کم انجام نمی‌شود."""
    table = compute_uplift_table(
        _obs("چرخه", "خفته", n=6, rate_t=0.0, rate_c=1.0)
    )
    ctx = {"uplift_table": table, "lifecycle_of": {"C1": "خفته"}}
    assert filter_uplift(_candidate(), ctx).outcome != OUTCOME_BLOCK


def test_useless_group_is_removed_from_the_accepted_list():
    """اثر عملی: نامزدهای گروه بی‌اثر به صندوق نمی‌رسند."""
    table = compute_uplift_table(
        _obs("چرخه", "وفادار", n=2000, rate_t=0.10, rate_c=0.45)
    )
    ctx = {
        "uplift_table": table,
        "lifecycle_of": {"C1": "وفادار", "C2": "لغزش"},
        "recently_contacted": set(),
    }
    accepted, rejected = apply_filters(
        [_candidate(key="C1"), _candidate(key="C2")], ctx,
    )
    assert [c.customer_key for c in rejected] == ["C1"]
    assert [c.customer_key for c in accepted] == ["C2"]


def test_every_candidate_carries_an_uplift_factor():
    """هیچ جابه‌جایی در رتبه بی‌توضیح نمی‌ماند."""
    table = compute_uplift_table(
        _obs("چرخه", "لغزش", n=500, rate_t=0.35, rate_c=0.20)
    )
    ctx = {
        "uplift_table": table, "lifecycle_of": {"C1": "لغزش"},
        "recently_contacted": set(),
    }
    accepted, _ = apply_filters([_candidate()], ctx)
    codes = {f.code for f in accepted[0].factors}
    assert "uplift" in codes


# ─────────────────────────────────────── کلید فرار
def test_kill_switch_disables_learning(monkeypatch, tmp_path):
    """اگر یادگیری نتیجه‌ی نامطلوب داد، باید بشود خاموشش کرد."""
    from mktcore.config import get_settings
    from mktcore.opportunities.engine import _load_uplift_table

    monkeypatch.setenv("MKT_UPLIFT_RANKING", "0")
    get_settings.cache_clear()
    try:
        assert _load_uplift_table(tmp_path / "x.db") is None
    finally:
        monkeypatch.delenv("MKT_UPLIFT_RANKING", raising=False)
        get_settings.cache_clear()


def test_missing_database_does_not_break_the_engine(tmp_path):
    """نبودِ داده‌ی آزمایشی نباید تولید فرصت را بخواباند."""
    from mktcore.opportunities.engine import _load_uplift_table

    assert _load_uplift_table(tmp_path / "does-not-exist.db") is None


# ─────────────────────────────────────── نشتِ دروازه (بازبینی): داده‌ی نازک
def test_one_observation_per_arm_does_not_move_the_ranking():
    """قهرمان می‌ماند: با یک مشاهده در هر بازو، رتبه دقیقاً برابرِ ارزش است."""
    table = compute_uplift_table(_obs("چرخه", "لغزش", n=1, rate_t=1.0, rate_c=0.0))
    candidate = _candidate()

    note = filter_uplift(candidate, {"uplift_table": table, "lifecycle_of": {"C1": "لغزش"}})

    assert note.outcome == "filter_skip"
    assert "کافی وجود ندارد" in (note.detail_fa or "")
    assert table.lookup("چرخه", "لغزش") == (0.0, "none")
    assert uplift_multiplier(None) == 1.0


def test_uplift_label_follows_the_sign_and_names_a_borrowed_basis():
    from mktcore.uplift.empirical import MIN_CELL_OBSERVATIONS

    n = MIN_CELL_OBSERVATIONS
    # اثرِ منفی ولی نامعلوم (بازه‌ی پهن) ⇒ می‌گذرد، با متنِ صادق؛ نه «اثر مثبت»
    negative = compute_uplift_table(_obs("چرخه", "لغزش", n=n, rate_t=0.3, rate_c=0.4))
    note = filter_uplift(_candidate(), {"uplift_table": negative, "lifecycle_of": {"C1": "لغزش"}})
    assert note.outcome == "filter_pass"
    assert "اثرِ مثبتی نشان نمی‌دهد" in (note.detail_fa or "")
    assert "اثر مثبت دارد" not in (note.detail_fa or "")

    borrowed = filter_uplift(_candidate(), {"uplift_table": negative, "lifecycle_of": {"C1": "حالتِ ندیده"}})
    assert borrowed.outcome == "filter_pass"
    assert "عاریتی" in (borrowed.detail_fa or "") and "کمینه‌ی بازو" in (borrowed.detail_fa or "")
