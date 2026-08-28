"""ویژگی‌های نقطه‌ی زمانی — و اثباتِ اینکه آینده را نمی‌بینند.

مهم‌ترین تست این فایل `test_features_are_identical_after_future_data_arrives`
است: اگر افزودنِ داده‌ی آینده عددی را تکان دهد، مدل در اعتبارسنجی خوش‌بین و در
عمل بی‌خاصیت می‌شود — و این تنها نشتی است که هیچ‌وقت خودش را نشان نمی‌دهد.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import select

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.analysis.kpis import compute_kpis  # noqa: E402
from mktcore.db import session_scope  # noqa: E402
from mktcore.db.migrations import reset_ensure_cache  # noqa: E402
from mktcore.db.models import Business  # noqa: E402
from mktcore.db.repo_import import write_import  # noqa: E402
from mktcore.features import (  # noqa: E402
    LeakageError,
    PointInTimeSpec,
    compute_outcome_window,
    compute_point_in_time_features,
    load_line_frame,
)
from mktcore.features.cohorts import (  # noqa: E402
    REASON_COHORTS,
    REASON_PROFIT,
    REASON_SPAN,
    MaturitySpec,
    assess_cohort_maturity,
    mature_anchors,
)
from mktcore.features.ledger_frame import first_order_dates  # noqa: E402
from mktcore.features.point_in_time import customer_anchors  # noqa: E402
from mktcore.ingest.cleaning import clean_frame  # noqa: E402
from mktcore.ingest.mapper import SchemaMapper  # noqa: E402
from mktcore.ingest.schema import ColumnRole  # noqa: E402

_COLS = ["تاریخ", "مبلغ", "مشتری", "فاکتور", "کالا", "تعداد", "بها", "دسته"]
_MAPPING = {
    ColumnRole.DATE: "تاریخ",
    ColumnRole.REVENUE: "مبلغ",
    ColumnRole.CUSTOMER_ID: "مشتری",
    ColumnRole.ORDER_ID: "فاکتور",
    ColumnRole.PRODUCT: "کالا",
    ColumnRole.QUANTITY: "تعداد",
    ColumnRole.COST: "بها",
    ColumnRole.CATEGORY: "دسته",
}


@pytest.fixture(autouse=True)
def _isolate():
    reset_ensure_cache()
    yield
    reset_ensure_cache()


def _ingest(db: Path, rows: list[tuple]) -> None:
    raw = pd.DataFrame(rows, columns=_COLS)
    clean = clean_frame(SchemaMapper().apply(raw, _MAPPING))
    write_import(clean, kpis=compute_kpis(clean), db_path=db)


def _frame(db: Path, **kwargs) -> pd.DataFrame:
    with session_scope(db) as session:
        business_id = session.scalar(select(Business.id))
        return load_line_frame(session, business_id, **kwargs)


_BASE_ROWS = [
    ("2023-01-10", 1_000, "C1", "A1", "کالای الف", 1, 400, "خوراک"),
    ("2023-02-15", 2_000, "C1", "A2", "کالای ب", 1, 900, "لوازم"),
    ("2023-03-20", 1_500, "C1", "A3", "کالای الف", 2, 600, "خوراک"),
    ("2023-01-12", 3_000, "C2", "B1", "کالای ب", 1, 1_000, "لوازم"),
]


# ═══════════════════════════════════════ گاردِ زمانی
def test_as_of_is_exclusive_not_inclusive(tmp_path):
    """خطِ دقیقاً روی `as_of` هنوز دانسته نبود.

    `line_date` تاریخ است نه زمان؛ خریدِ همان روز، دانشِ صبحِ همان روز نیست.
    """
    db = tmp_path / "app.db"
    _ingest(db, _BASE_ROWS)

    inclusive = _frame(db, as_of="2023-02-16")
    exclusive = _frame(db, as_of="2023-02-15")

    assert "2023-02-15" in set(inclusive["line_date"])
    assert "2023-02-15" not in set(exclusive["line_date"])


def test_leakage_error_when_frame_contains_future_rows(tmp_path):
    """لایه‌ی خالص هم مستقلاً بررسی می‌کند — گارد دورزدنی نیست."""
    db = tmp_path / "app.db"
    _ingest(db, _BASE_ROWS)
    everything = _frame(db)

    with pytest.raises(LeakageError) as err:
        compute_point_in_time_features(everything, PointInTimeSpec(as_of="2023-02-01"))
    assert "2023-03-20" in str(err.value)


def test_features_are_identical_after_future_data_arrives(tmp_path):
    """قلبِ §۲۹.۲: داده‌ی آینده نباید هیچ عددِ گذشته را تکان دهد."""
    db = tmp_path / "app.db"
    _ingest(db, _BASE_ROWS)
    spec = PointInTimeSpec(as_of="2023-04-01")
    before = compute_point_in_time_features(_frame(db, as_of=spec.as_of), spec)

    _ingest(db, [
        ("2023-06-01", 500_000, "C1", "Z1", "کالای الف", 40, 100_000, "خوراک"),
        ("2023-07-01", 900_000, "C2", "Z2", "کالای ب", 60, 200_000, "لوازم"),
    ])
    after = compute_point_in_time_features(_frame(db, as_of=spec.as_of), spec)

    pd.testing.assert_frame_equal(before, after)


# ═══════════════════════════════════════ صداقتِ ستون‌ها
def test_single_purchase_customer_has_nan_gaps_not_zero(tmp_path):
    """مشتری تک‌خرید فاصله‌ی خرید **ندارد**؛ صفر یعنی «هر روز می‌خرد»."""
    db = tmp_path / "app.db"
    _ingest(db, _BASE_ROWS)
    out = compute_point_in_time_features(
        _frame(db, as_of="2023-04-01"), PointInTimeSpec(as_of="2023-04-01"),
    )

    single = out[out["n_orders"] == 1].iloc[0]
    multi = out[out["n_orders"] > 1].iloc[0]
    assert pd.isna(single["median_gap_days"])
    assert pd.isna(single["days_to_second_order"])
    assert pd.isna(single["cv_gap"])
    assert multi["days_to_second_order"] > 0, "مشتری چندخریدی عدد واقعی می‌گیرد"


def test_partial_cost_coverage_yields_nan_margin_not_a_partial_number(tmp_path):
    """پوششِ ناقصِ بها ⇒ حاشیه نامعلوم است، نه حاشیه‌ی بخشی از خطوط."""
    db = tmp_path / "app.db"
    _ingest(db, [
        ("2023-01-10", 1_000, "C1", "A1", "کالای الف", 1, 400, "خوراک"),
        ("2023-02-10", 1_000, "C1", "A2", "کالای ب", 1, None, "لوازم"),
        ("2023-01-11", 2_000, "C2", "B1", "کالای الف", 1, 800, "خوراک"),
    ])
    out = compute_point_in_time_features(
        _frame(db, as_of="2023-03-01"), PointInTimeSpec(as_of="2023-03-01"),
    )

    covered = out[out["margin_quality_bp"].notna()]
    uncovered = out[out["margin_quality_bp"].isna()]
    assert len(covered) == 1 and len(uncovered) == 1
    assert pd.isna(uncovered.iloc[0]["gross_profit_rial"]), "سودِ ناقص گزارش نمی‌شود"
    assert covered.iloc[0]["margin_quality_bp"] == 6_000  # (2000−800)/2000


def test_no_discount_column_means_nan_full_price_share(tmp_path):
    """«ستون تخفیف نداریم» با «هیچ‌وقت تخفیف نداده» یکی نیست."""
    db = tmp_path / "app.db"
    _ingest(db, _BASE_ROWS)
    out = compute_point_in_time_features(
        _frame(db, as_of="2023-04-01"), PointInTimeSpec(as_of="2023-04-01"),
    )
    assert out["full_price_share_bp"].isna().all()


def test_observation_window_ignores_purchases_after_the_anchor(tmp_path):
    """پنجره‌ی مشاهده از نخستین خریدِ **خودِ مشتری** شروع می‌شود."""
    db = tmp_path / "app.db"
    _ingest(db, [
        ("2023-01-10", 1_000, "C1", "A1", "کالای الف", 1, 400, "خوراک"),
        ("2023-01-20", 2_000, "C1", "A2", "کالای ب", 1, 900, "لوازم"),
        ("2023-05-01", 9_000, "C1", "A3", "کالای الف", 9, 3_000, "خوراک"),
    ])
    spec = PointInTimeSpec(as_of="2023-12-01", observation_days=30)
    out = compute_point_in_time_features(_frame(db, as_of=spec.as_of), spec)

    assert out.loc[out.index[0], "n_orders"] == 2, "خریدِ ماه پنجم بیرونِ پنجره است"
    assert out.loc[out.index[0], "monetary_rial"] == 30_000  # ۳۰۰۰ تومان = ریال


def test_incomplete_observation_window_customer_is_dropped(tmp_path):
    """پنجره‌ی نیمه‌تمام یعنی «۳۰ روز اول» هنوز کامل نشده."""
    db = tmp_path / "app.db"
    _ingest(db, [
        ("2023-01-10", 1_000, "C1", "A1", "کالای الف", 1, 400, "خوراک"),
        ("2023-02-25", 1_000, "C2", "B1", "کالای الف", 1, 400, "خوراک"),
    ])
    spec = PointInTimeSpec(as_of="2023-03-01", observation_days=30)
    out = compute_point_in_time_features(_frame(db, as_of=spec.as_of), spec)

    assert len(out) == 1, "مشتریِ تازه هنوز پنجره‌اش تمام نشده"


def test_feature_schema_is_ordered_and_complete(tmp_path):
    """ترتیب ستون‌ها قرارداد است: بردار ضرایبِ مدل به آن گره می‌خورد."""
    from mktcore.features import PIT_FEATURE_SCHEMA

    db = tmp_path / "app.db"
    _ingest(db, _BASE_ROWS)
    out = compute_point_in_time_features(
        _frame(db, as_of="2023-04-01"), PointInTimeSpec(as_of="2023-04-01"),
    )
    assert tuple(out.columns) == PIT_FEATURE_SCHEMA


# ═══════════════════════════════════════ پنجره‌ی نتیجه
def test_outcome_window_counts_only_its_own_window(tmp_path):
    db = tmp_path / "app.db"
    _ingest(db, [
        ("2023-01-10", 1_000, "C1", "A1", "کالای الف", 1, 400, "خوراک"),
        ("2023-03-01", 5_000, "C1", "A2", "کالای ب", 1, 2_000, "لوازم"),
        ("2024-06-01", 7_000, "C1", "A3", "کالای ب", 1, 3_000, "لوازم"),
    ])
    lines = _frame(db)
    anchors = customer_anchors(lines, 30)
    out = compute_outcome_window(lines, starts=anchors, days=120)

    assert out.iloc[0]["future_orders"] == 1, "فقط خریدِ داخل پنجره شمرده می‌شود"
    assert out.iloc[0]["future_revenue_rial"] == 50_000
    assert out.iloc[0]["future_covered"]


def test_outcome_profit_is_nan_when_a_line_lacks_cost(tmp_path):
    db = tmp_path / "app.db"
    _ingest(db, [
        ("2023-01-10", 1_000, "C1", "A1", "کالای الف", 1, 400, "خوراک"),
        ("2023-03-01", 5_000, "C1", "A2", "کالای ب", 1, None, "لوازم"),
    ])
    lines = _frame(db)
    out = compute_outcome_window(lines, starts=customer_anchors(lines, 30), days=120)

    assert pd.isna(out.iloc[0]["future_gross_profit_rial"])
    assert not out.iloc[0]["future_covered"]


def test_customer_without_purchases_in_the_window_gets_a_certain_zero(tmp_path):
    """صفرِ قطعی: چیزی نخریده که سودش نامعلوم باشد."""
    db = tmp_path / "app.db"
    _ingest(db, [("2023-01-10", 1_000, "C1", "A1", "کالای الف", 1, 400, "خوراک")])
    lines = _frame(db)
    out = compute_outcome_window(lines, starts=customer_anchors(lines, 30), days=60)

    assert out.iloc[0]["future_gross_profit_rial"] == 0.0
    assert out.iloc[0]["future_covered"]


# ═══════════════════════════════════════ دروازه‌ی بلوغ
def _first_dates(n: int, *, start: str, step_days: int) -> pd.Series:
    base = pd.Timestamp(start)
    return pd.Series(
        [(base + pd.Timedelta(days=i * step_days)).strftime("%Y-%m-%d") for i in range(n)],
        index=range(n),
    )


def test_gate_refuses_when_the_span_is_too_short():
    spec = MaturitySpec()
    verdict = assess_cohort_maturity(
        _first_dates(500, start="2023-01-01", step_days=1),
        data_min="2023-01-01", data_max="2024-01-01", cost_coverage=1.0, spec=spec,
    )
    assert not verdict.ok
    assert verdict.reason_code == REASON_SPAN
    assert str(spec.required_span_days) in verdict.reason_fa


def test_gate_refuses_without_a_profit_basis():
    """§۱۸.۲ برچسبِ سودمحور می‌خواهد؛ بازگشت به درآمد ممنوع است."""
    verdict = assess_cohort_maturity(
        _first_dates(500, start="2021-01-01", step_days=2),
        data_min="2021-01-01", data_max="2025-01-01", cost_coverage=0.5,
    )
    assert not verdict.ok
    assert verdict.reason_code == REASON_PROFIT
    assert "۱۸.۲" in verdict.reason_fa or "سود ناخالص" in verdict.reason_fa


def test_gate_refuses_with_too_few_cohort_months():
    verdict = assess_cohort_maturity(
        pd.Series(["2021-01-05"] * 400, index=range(400)),
        data_min="2021-01-01", data_max="2025-01-01", cost_coverage=1.0,
    )
    assert not verdict.ok
    assert verdict.reason_code == REASON_COHORTS


def test_gate_passes_on_wide_mature_data():
    verdict = assess_cohort_maturity(
        _first_dates(1_200, start="2021-01-01", step_days=1),
        data_min="2021-01-01", data_max="2025-06-01", cost_coverage=1.0,
    )
    assert verdict.ok, verdict.reason_fa
    assert verdict.n_validate_customers > 0
    assert verdict.split_date is not None


def test_gate_reports_numbers_even_when_it_refuses():
    """«داده کافی نیست» بدون عدد، قابل‌اقدام نیست."""
    verdict = assess_cohort_maturity(
        _first_dates(10, start="2023-01-01", step_days=1),
        data_min="2023-01-01", data_max="2023-06-01", cost_coverage=1.0,
    )
    assert not verdict.ok
    assert verdict.requirements["بازه‌ی داده (روز)"]["لازم"] > 0
    assert "موجود" in verdict.requirements["مشتری بالغ"]


def test_censored_customers_are_excluded_from_anchors():
    """مشتری‌ای که پنجره‌ی نتیجه‌اش تمام نشده، غیرنهنگ برچسب نمی‌خورد."""
    spec = MaturitySpec(observation_days=30, outcome_days=90)
    first = pd.Series({1: "2023-01-01", 2: "2024-11-01"})
    anchors = mature_anchors(first, data_max="2024-12-31", spec=spec)

    assert list(anchors.index) == [1]


def test_first_order_dates_come_from_the_truncated_frame(tmp_path):
    """نخستین خرید باید از همان فریمِ برش‌خورده بیاید، نه از وضعیتِ امروز."""
    db = tmp_path / "app.db"
    _ingest(db, _BASE_ROWS)
    early = first_order_dates(_frame(db, as_of="2023-02-01"))
    assert set(early.to_numpy()) == {"2023-01-10", "2023-01-12"}
