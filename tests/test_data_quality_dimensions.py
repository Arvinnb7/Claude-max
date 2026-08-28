"""§۸.۵: نُه بُعدِ کیفیت داده — و اینکه هیچ‌کدام دروغ نگویند.

## قاعده‌ای که این فایل پین می‌کند

بُعدی که مبنایش وجود ندارد **صفر گزارش نمی‌شود**؛ `value=None` یعنی «سنجیده
نشد». صفرِ دروغین بدترین حالت است: مثل یک سنجشِ واقعی به‌نظر می‌رسد و کاربر
بر پایه‌اش تصمیم می‌گیرد.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from api.main import app  # noqa: E402

from mktcore.ingest.quality import (  # noqa: E402
    DIMENSION_LABELS_FA,
    build_quality_dimensions,
    overall_quality,
)

from .conftest import poll_job  # noqa: E402

client = TestClient(app)


def _dimensions(**overrides):
    base = dict(
        n_lines=100,
        lines_with_customer=100,
        lines_with_product=100,
        lines_with_cost=100,
        lines_with_date=100,
        lines_in_declared_range=100,
        n_orders=40,
        orders_with_branch=40,
        rows_total=110,
        rows_clean=100,
        rows_duplicate=5,
        has_doc_type_column=True,
        n_returns=2,
    )
    base.update(overrides)
    return {d.key: d for d in build_quality_dimensions(**base)}


# ═══════════════════════════════════════════ صفرِ دروغین ممنوع
def test_an_unmeasurable_dimension_is_none_not_zero():
    """بدون شمارِ ردیف‌های خام، «اعتبار» و «یکتایی» سنجیده نمی‌شوند."""
    dims = _dimensions(rows_total=None, rows_clean=None, rows_duplicate=None)

    for key in ("validity", "uniqueness"):
        assert dims[key].value is None, key
        assert dims[key].severity == "not_measured", key
        assert "سنجیده نشد" in dims[key].note_fa, key


def test_a_missing_date_range_does_not_become_a_hundred_percent():
    dims = _dimensions(lines_in_declared_range=None)

    assert dims["date_range_consistency"].value is None
    assert dims["date_range_consistency"].severity == "not_measured"


def test_the_score_ignores_unmeasured_dimensions():
    """حساب‌کردنِ «سنجیده نشد» به‌عنوان صفر یعنی جریمه برای ستونی که نبوده."""
    dims = build_quality_dimensions(**{
        **{k: v for k, v in _raw_defaults().items()},
        "rows_total": None, "rows_clean": None, "rows_duplicate": None,
    })
    summary = overall_quality(dims)

    assert summary["dimensions_total"] == 9
    assert summary["dimensions_measured"] == 7
    assert summary["score"] == 1.0


def _raw_defaults() -> dict:
    return dict(
        n_lines=100, lines_with_customer=100, lines_with_product=100,
        lines_with_cost=100, lines_with_date=100, lines_in_declared_range=100,
        n_orders=40, orders_with_branch=40, rows_total=100, rows_clean=100,
        rows_duplicate=0, has_doc_type_column=True, n_returns=0,
    )


# ═══════════════════════════════════════════ ابعادِ تازه‌ی §۸.۵
def test_all_nine_section_8_5_dimensions_are_present():
    expected = {
        "completeness", "validity", "uniqueness", "product_match_rate",
        "customer_identifier_rate", "cost_coverage", "branch_coverage",
        "return_clarity", "date_range_consistency",
    }
    assert set(_dimensions()) == expected
    assert set(DIMENSION_LABELS_FA) == expected


def test_missing_cost_is_blocking_not_a_warning():
    """بدون بها هیچ عددِ سودی گزارش نمی‌شود؛ این هشدار نیست، مسدودکننده است."""
    dims = _dimensions(lines_with_cost=0)

    assert dims["cost_coverage"].value == 0.0
    assert dims["cost_coverage"].severity == "blocking"
    assert "درآمدی" in dims["cost_coverage"].note_fa


def test_returns_without_a_document_type_column_are_called_a_guess():
    """تفاوتِ «اعلام‌شده» و «حدس‌زده» باید دیده شود."""
    guessed = _dimensions(has_doc_type_column=False, n_returns=7)["return_clarity"]
    declared = _dimensions(has_doc_type_column=True)["return_clarity"]

    assert guessed.value == 0.0
    assert "حدس است" in guessed.note_fa
    assert "7" in guessed.note_fa
    assert declared.value == 1.0
    assert "اعلام‌شده" in declared.note_fa


def test_no_branch_column_is_a_known_limitation_not_a_failure():
    dim = _dimensions(orders_with_branch=0)["branch_coverage"]

    assert dim.severity == "known_limitation"
    assert "شعبه‌ی محتمل" in dim.note_fa


def test_duplicates_lower_uniqueness_by_exactly_their_share():
    dim = _dimensions(rows_total=200, rows_duplicate=20)["uniqueness"]

    assert dim.value == 0.9
    assert "10٪" in dim.note_fa or "۱۰" in dim.note_fa


def test_rows_dropped_in_cleaning_lower_validity():
    dim = _dimensions(rows_total=100, rows_clean=80)["validity"]

    assert dim.value == 0.8
    assert "80" in dim.note_fa


def test_summary_lists_the_blocking_dimensions_by_name():
    summary = overall_quality(list(_dimensions(lines_with_cost=0).values()))

    assert "cost_coverage" in summary["blocking"]
    assert "بُعد" in summary["note_fa"]


# ═══════════════════════════════════════════ از راه API، روی داده‌ی واقعی
def test_the_api_reports_the_dimensions_on_real_data():
    r = client.post("/api/sample")
    data = r.json()
    roles = {x["role"]: x["suggested"] for x in data["roles"]}
    mapping = {role: col for role, col in roles.items() if col}
    job = client.post("/api/analyze", json={
        "session_id": data["session_id"], "mapping": mapping, "horizon": 3,
    })
    poll_job(client, job.json()["job_id"])

    body = client.get("/api/v1/data-quality").json()

    assert body["available"] is True
    assert len(body["dimensions"]) == 9
    assert body["quality_summary"]["dimensions_measured"] >= 8
    # قرارداد قبلیِ UI نباید بشکند
    assert body["gaps"], "کلید gaps باید سرِ جایش بماند"
    for dimension in body["dimensions"]:
        assert dimension["label_fa"]
        assert dimension["note_fa"]
        assert dimension["severity"] in (
            "ok", "warning", "blocking", "not_measured", "known_limitation",
        )
