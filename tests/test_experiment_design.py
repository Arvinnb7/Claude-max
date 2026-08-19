"""طراحِ آزمایش — اولویت‌بندی، اندازه‌ی نمونه، و صداقتِ نرخ پایه.

مهم‌ترین تستِ این فایل `test_settled_cells_are_not_proposed_again` است: اگر سلولی
که اثرش اثبات شده دوباره پیشنهاد شود، سیستم بی‌پایان همان چیز را می‌آزماید و
هیچ‌وقت به سلول‌های ناشناخته نمی‌رسد.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.campaigns.analysis import (  # noqa: E402
    achievable_effect,
    required_control_size,
)
from mktcore.experiments.design import (  # noqa: E402
    BASELINE_CELL,
    BASELINE_DEFAULT,
    BASELINE_GLOBAL,
    DEFAULT_BASELINE_RATE,
    STATUS_INCONCLUSIVE,
    STATUS_NO_DATA,
    STATUS_PROVEN,
    STATUS_THIN,
    STATUS_USELESS,
    CellSupply,
    build_plan,
)
from mktcore.uplift.empirical import UpliftCell, UpliftTable  # noqa: E402


def _table(*cells: UpliftCell) -> UpliftTable:
    table = UpliftTable(
        cells={(c.kind, c.lifecycle_state): c for c in cells},
        n_observations=sum(c.n_treatment + c.n_control for c in cells),
    )
    return table


def _cell(kind="یادآوری", state="slipping", *, n_t=100, n_c=100,
          conv_t=45, conv_c=30, ci=(0.03, 0.27)) -> UpliftCell:
    return UpliftCell(
        kind=kind, lifecycle_state=state, n_treatment=n_t, n_control=n_c,
        conv_treatment=conv_t, conv_control=conv_c,
        shrunk_uplift=(conv_t / n_t - conv_c / n_c) if n_t and n_c else 0.0,
        ci=ci,
    )


# ═══════════════════════════════════════════════════ وضعیتِ شواهد
def test_cell_without_any_experiment_is_no_data():
    plan = build_plan([CellSupply("یادآوری", "slipping", 500)], None)
    assert plan.suggestions[0].status == STATUS_NO_DATA


def test_cell_with_positive_ci_is_proven():
    plan = build_plan(
        [CellSupply("یادآوری", "slipping", 500)],
        _table(_cell(ci=(0.03, 0.27))),
    )
    assert plan.suggestions[0].status == STATUS_PROVEN


def test_cell_with_ci_below_zero_is_useless():
    plan = build_plan(
        [CellSupply("یادآوری", "loyal", 500)],
        _table(_cell(state="loyal", conv_t=25, conv_c=40, ci=(-0.28, -0.02))),
    )
    assert plan.suggestions[0].status == STATUS_USELESS


def test_cell_with_ci_straddling_zero_is_inconclusive():
    plan = build_plan(
        [CellSupply("یادآوری", "slipping", 500)],
        _table(_cell(ci=(-0.05, 0.11))),
    )
    assert plan.suggestions[0].status == STATUS_INCONCLUSIVE


def test_cell_below_minimum_observations_is_thin():
    plan = build_plan(
        [CellSupply("یادآوری", "slipping", 500)],
        _table(_cell(n_t=6, n_c=4, conv_t=3, conv_c=1, ci=(-0.4, 0.6))),
    )
    assert plan.suggestions[0].status == STATUS_THIN


# ═══════════════════════════════════ اولویت: تماسِ اندازه‌گیری‌نشده
def test_settled_cells_are_not_proposed_again():
    """سلولِ قطعی‌شده صفر تماسِ بی‌شاهد دارد، پس در اولویت پایین می‌رود."""
    plan = build_plan(
        [
            CellSupply("یادآوری", "slipping", 900),   # اثبات‌شده
            CellSupply("توسعه", "loyal", 400),        # ناشناخته
        ],
        _table(_cell(ci=(0.03, 0.27))),
    )
    first = plan.suggestions[0]
    assert (first.kind, first.lifecycle_state) == ("توسعه", "loyal")
    assert plan.suggestions[1].unmeasured_contacts == 0
    assert plan.suggestions[1].settled is True


def test_useless_cell_is_also_settled():
    plan = build_plan(
        [CellSupply("یادآوری", "loyal", 900)],
        _table(_cell(state="loyal", conv_t=25, conv_c=40, ci=(-0.28, -0.02))),
    )
    assert plan.suggestions[0].unmeasured_contacts == 0
    assert plan.total_unmeasured == 0


def test_bigger_unmeasured_supply_ranks_first():
    plan = build_plan(
        [
            CellSupply("الف", "new", 100),
            CellSupply("ب", "new", 5000),
            CellSupply("ج", "new", 800),
        ],
        None,
    )
    assert [s.kind for s in plan.suggestions] == ["ب", "ج", "الف"]
    assert plan.total_unmeasured == 5900


def test_ordering_is_deterministic_on_ties():
    """گره‌شکنِ ثابت لازم است، وگرنه خروجی هر بار جابه‌جا می‌شود."""
    supplies = [
        CellSupply("ب", "new", 100),
        CellSupply("الف", "new", 100),
        CellSupply("الف", "loyal", 100),
    ]
    first = [(s.kind, s.lifecycle_state) for s in build_plan(supplies, None).suggestions]
    second = [
        (s.kind, s.lifecycle_state)
        for s in build_plan(list(reversed(supplies)), None).suggestions
    ]
    assert first == second


# ═════════════════════════════════════════════ اندازه‌ی نمونه و امکان
def test_required_total_matches_the_documented_formula():
    plan = build_plan([CellSupply("الف", "new", 10_000)], None,
                      target_effect=0.10, holdout_pct=20)
    suggestion = plan.suggestions[0]
    expected_control = required_control_size(
        0.10, DEFAULT_BASELINE_RATE, holdout_pct=20,
    )
    assert suggestion.required_total == round(expected_control * 100 / 20)
    # جدول سند: اثر ۱۰ واحد درصد با کنترل ۲۰٪ ⇒ ۵۰۵ نفر
    assert suggestion.required_total == 505


def test_feasible_when_supply_covers_the_requirement():
    plan = build_plan([CellSupply("الف", "new", 5000)], None, target_effect=0.10,
                      holdout_pct=20)
    suggestion = plan.suggestions[0]
    assert suggestion.feasible_now is True
    assert "می‌شود آزمایش کرد" in suggestion.note_fa()


def test_not_feasible_reports_what_is_achievable_instead():
    """توصیه‌ی «۹۰۰ نفر لازم است» به کسی که ۳۰۰ نفر دارد بی‌مصرف است."""
    plan = build_plan([CellSupply("الف", "new", 300)], None, target_effect=0.05,
                      holdout_pct=20)
    suggestion = plan.suggestions[0]
    assert suggestion.feasible_now is False
    assert suggestion.detectable_now is not None
    assert suggestion.detectable_now > 0.05, "با نمونه‌ی کمتر، اثرِ دیدنی بزرگ‌تر است"
    assert suggestion.detectable_now == achievable_effect(
        300, DEFAULT_BASELINE_RATE, holdout_pct=20,
    )
    note = suggestion.note_fa()
    assert "کافی نیست" in note


def test_empty_supply_is_reported_as_not_testable():
    plan = build_plan([CellSupply("الف", "new", 0)], None)
    suggestion = plan.suggestions[0]
    assert suggestion.detectable_now is None
    assert suggestion.feasible_now is False
    assert "آزمایش‌شدنی نیست" in suggestion.note_fa()


def test_next_experiment_is_the_biggest_runnable_one():
    plan = build_plan(
        [
            CellSupply("بزرگ‌ولی‌کم‌ظرفیت", "new", 50),     # بی‌شاهد ولی اجراناشدنی
            CellSupply("اجراشدنی", "slipping", 4000),
        ],
        None, target_effect=0.05, holdout_pct=20,
    )
    nxt = plan.next_experiment
    assert nxt is not None
    assert nxt.kind == "اجراشدنی"


def test_next_experiment_is_none_when_nothing_is_runnable():
    plan = build_plan([CellSupply("الف", "new", 20)], None, target_effect=0.05)
    assert plan.next_experiment is None


def test_next_experiment_is_none_when_everything_is_settled():
    plan = build_plan(
        [CellSupply("یادآوری", "slipping", 9000)],
        _table(_cell(ci=(0.03, 0.27))),
    )
    assert plan.next_experiment is None


# ═════════════════════════════════════════════ صداقتِ نرخ پایه
def test_baseline_from_the_cell_when_it_has_enough_control():
    plan = build_plan(
        [CellSupply("یادآوری", "slipping", 5000)],
        _table(_cell(n_c=200, conv_c=50, ci=(-0.02, 0.10))),
    )
    suggestion = plan.suggestions[0]
    assert suggestion.baseline_source == BASELINE_CELL
    assert abs(suggestion.baseline_rate - 0.25) < 1e-9


def test_baseline_falls_back_to_global_for_an_unmeasured_cell():
    plan = build_plan(
        [CellSupply("نوعِ تازه", "new", 5000)],
        _table(_cell(n_c=200, conv_c=50, ci=(-0.02, 0.10))),
    )
    suggestion = plan.suggestions[0]
    assert suggestion.baseline_source == BASELINE_GLOBAL
    assert abs(suggestion.baseline_rate - 0.25) < 1e-9


def test_baseline_is_labelled_assumed_when_there_is_no_control_anywhere():
    """عددِ اندازه‌ی نمونه روی یک حدس می‌ایستد؛ باید صریح گفته شود."""
    plan = build_plan([CellSupply("الف", "new", 5000)], None)
    suggestion = plan.suggestions[0]
    assert suggestion.baseline_source == BASELINE_DEFAULT
    assert suggestion.baseline_rate == DEFAULT_BASELINE_RATE
    assert "فرضی" in suggestion.to_dict()["baseline_source_fa"]


def test_degenerate_baseline_rate_falls_back_to_the_assumption():
    """نرخ صفر یا صد واریانس صفر می‌دهد و اندازه‌ی نمونه را بی‌معنا می‌کند."""
    plan = build_plan(
        [CellSupply("یادآوری", "slipping", 5000)],
        _table(_cell(n_c=100, conv_c=0, n_t=100, conv_t=0, ci=(0.0, 0.0))),
    )
    suggestion = plan.suggestions[0]
    assert suggestion.baseline_source == BASELINE_DEFAULT
    assert suggestion.required_total is not None


# ═════════════════════════════════════════════════════ قرارداد خروجی
def test_plan_to_dict_is_serialisable_and_complete():
    plan = build_plan(
        [CellSupply("یادآوری", "slipping", 4000), CellSupply("توسعه", "loyal", 100)],
        _table(_cell(ci=(-0.02, 0.10))),
    )
    payload = plan.to_dict()
    assert payload["available"] is True
    assert payload["total_unmeasured_contacts"] == 4100
    assert len(payload["cells"]) == 2
    for cell in payload["cells"]:
        assert cell["status_label_fa"]
        assert cell["note_fa"]
        assert cell["baseline_source_fa"]


def test_empty_plan_is_honest_about_having_nothing():
    plan = build_plan([], None)
    payload = plan.to_dict()
    assert payload["available"] is False
    assert payload["cells"] == []
    assert payload["next_experiment"] is None
