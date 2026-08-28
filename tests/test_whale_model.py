"""مدلِ «نهنگ آینده» (§۱۸) — نشت، دروازه، و دروازه‌ی پذیرشِ فاز ۴.

سه چیز اینجا اثبات می‌شود و هر سه به یک اندازه مهم‌اند:

1. **برچسب از آینده ساخته می‌شود و ویژگی فقط از گذشته** — و تغییر هرکدام،
   دیگری را تکان نمی‌دهد.
2. **مدلی که خط پایه را نبرد فعال نمی‌شود** — و آن هم یک نتیجه‌ی موفق است، نه
   خطا.
3. **روی داده‌ای که مدل را تحمل نمی‌کند، پاسخ صادقانه «مدل نداریم» است.**
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.analysis.kpis import compute_kpis  # noqa: E402
from mktcore.db import session_scope  # noqa: E402
from mktcore.db.engine import write_lock  # noqa: E402
from mktcore.db.lookup import resolve_business_id  # noqa: E402
from mktcore.db.migrations import reset_ensure_cache  # noqa: E402
from mktcore.db.models import CustomerFeature, ModelRun, OrderLine  # noqa: E402
from mktcore.db.repo_features import write_customer_features  # noqa: E402
from mktcore.db.repo_import import write_import  # noqa: E402
from mktcore.features.cohorts import REASON_PROFIT, REASON_SPAN  # noqa: E402
from mktcore.features.ledger_frame import load_line_frame  # noqa: E402
from mktcore.ingest.cleaning import clean_frame  # noqa: E402
from mktcore.ingest.mapper import SchemaMapper  # noqa: E402
from mktcore.ml.registry import promote_run, rollback_run  # noqa: E402
from mktcore.ml.train import train_model  # noqa: E402
from mktcore.ml.whale import (  # noqa: E402
    WhaleSpec,
    build_training_table,
    score_whale_customers,
    whale_labels,
)
from mktcore.pipeline import run_analysis  # noqa: E402
from mktcore.synthetic import generate_cohort_sales, generate_synthetic_sales  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate():
    reset_ensure_cache()
    yield
    reset_ensure_cache()


def _ingest(db: Path, raw: pd.DataFrame) -> pd.DataFrame:
    mapper = SchemaMapper()
    clean = clean_frame(mapper.apply(raw, mapper.auto_detect(raw).mapping))
    write_import(clean, kpis=compute_kpis(clean), db_path=db)
    return clean


def _lines(db: Path) -> pd.DataFrame:
    with session_scope(db) as session:
        return load_line_frame(session, resolve_business_id(session, "default"))


@pytest.fixture(scope="module")
def cohort_frame() -> pd.DataFrame:
    """داده‌ی کوهورت‌دار — یک بار ساخته می‌شود، چهار سال داده است."""
    return generate_cohort_sales()


@pytest.fixture(scope="module")
def trained(tmp_path_factory, cohort_frame) -> dict:
    """یک آموزشِ کامل روی داده‌ی بالغ — پایه‌ی چند تست."""
    db = tmp_path_factory.mktemp("whale") / "app.db"
    clean = _ingest(db, cohort_frame)
    result = train_model("whale", db_path=db)
    return {"db": db, "clean": clean, "run": result}


# ═══════════════════════════════════════ نشت
def test_label_ignores_changes_inside_the_observation_window(tmp_path, cohort_frame):
    """§۱۸.۲: درآمد/سودِ **داخل** پنجره‌ی مشاهده هرگز برچسب نیست.

    اگر خرجِ ۹۰ روز اولِ همه را ده برابر کنیم و برچسب‌ها تکان بخورند، یعنی
    برچسب از پنجره‌ی پیش‌بینی ساخته شده — دقیقاً همان چیزی که سند ممنوع کرده.
    """
    db = tmp_path / "app.db"
    _ingest(db, cohort_frame)
    spec = WhaleSpec()
    before = build_training_table(_lines(db), spec=spec)

    lines = _lines(db)
    first = lines.groupby("customer_id")["line_date"].min()
    anchor = (
        pd.to_datetime(first) + pd.Timedelta(days=spec.observation_days)
    ).dt.strftime("%Y-%m-%d")
    inside = lines[lines["line_date"] < lines["customer_id"].map(anchor)]

    with write_lock, session_scope(db) as session:
        rows = session.scalars(
            select(OrderLine).where(OrderLine.id.isnot(None))
        ).all()
        inside_dates = set(zip(inside["customer_id"], inside["line_date"], strict=False))
        for row in rows:
            if (row.customer_id, row.line_date) in inside_dates:
                row.revenue_rial = int(row.revenue_rial) * 10
                if row.gross_profit_rial is not None:
                    row.gross_profit_rial = int(row.gross_profit_rial) * 10

    after = build_training_table(_lines(db), spec=spec)
    pd.testing.assert_series_equal(
        before.frame["label"], after.frame["label"], check_names=False,
    )


def test_features_ignore_purchases_after_the_anchor(tmp_path, cohort_frame):
    """§۱۸.۴: در لحظه‌ی پیش‌بینی فقط داده‌ی پنجره‌ی اولیه در دسترس است."""
    db = tmp_path / "app.db"
    _ingest(db, cohort_frame.head(4_000))
    spec = WhaleSpec(min_cohort_customers=1, min_positive_per_arm=0, min_cohort_months=1)
    before = build_training_table(_lines(db), spec=spec)

    lines = _lines(db)
    first = lines.groupby("customer_id")["line_date"].min()
    anchor = (
        pd.to_datetime(first) + pd.Timedelta(days=spec.observation_days)
    ).dt.strftime("%Y-%m-%d")
    outside = lines[lines["line_date"] >= lines["customer_id"].map(anchor)]

    with write_lock, session_scope(db) as session:
        rows = session.scalars(select(OrderLine)).all()
        outside_pairs = set(zip(outside["customer_id"], outside["line_date"], strict=False))
        for row in rows:
            if (row.customer_id, row.line_date) in outside_pairs:
                row.revenue_rial = int(row.revenue_rial) * 7

    after = build_training_table(_lines(db), spec=spec)
    feature_columns = [
        c for c in before.frame.columns
        if not c.startswith("future_") and c not in ("label", "anchor", "window_start", "window_end")
    ]
    pd.testing.assert_frame_equal(
        before.frame[feature_columns], after.frame[feature_columns],
    )


def test_censored_customers_never_enter_the_table(tmp_path, cohort_frame):
    """مشتریِ سانسورشده حذف می‌شود، نه اینکه «غیرنهنگ» برچسب بخورد."""
    db = tmp_path / "app.db"
    _ingest(db, cohort_frame)
    table = build_training_table(_lines(db), spec=WhaleSpec())

    lines = _lines(db)
    data_max = pd.Timestamp(lines["line_date"].max())
    latest_anchor = pd.to_datetime(table.frame["anchor"]).max()

    assert latest_anchor + pd.Timedelta(days=365) <= data_max


def test_labels_are_taken_within_the_anchor_quarter():
    """صدکِ سراسری یعنی مدل «فصلِ جذب» را یاد بگیرد، نه رفتار را."""
    profit = pd.Series(list(range(100)) + [1_000 + i for i in range(100)])
    anchors = pd.Series(["2023-02-01"] * 100 + ["2024-02-01"] * 100)

    labels = whale_labels(profit, anchors, top_fraction=0.10)

    assert labels[:100].sum() > 0, "کوهورت قدیمی هم باید نهنگ داشته باشد"
    assert labels[100:].sum() > 0


# ═══════════════════════════════════════ دروازه‌ی داده
def test_the_default_sample_is_refused_with_numbers(tmp_path):
    """داده‌ی نمونه کوهورت متأخر ندارد؛ پاسخِ صادقانه «مدل نداریم» است."""
    db = tmp_path / "app.db"
    _ingest(db, generate_synthetic_sales(seed=7, days=540))

    run = train_model("whale", db_path=db)

    assert run["status"] == ModelRun.STATUS_INSUFFICIENT
    assert run["blocked_reason_code"] == REASON_SPAN
    assert run["promoted"] is False
    assert run["metrics"]["requirements"]["بازه‌ی داده (روز)"]["موجود"] > 0
    with session_scope(db) as session:
        stored = session.get(ModelRun, run["id"])
        assert stored.coefficients_json is None, "مدلی وجود ندارد که ذخیره شود"


def test_missing_cost_refuses_instead_of_falling_back_to_revenue(tmp_path, cohort_frame):
    """§۱۸.۲ برچسبِ سودمحور می‌خواهد؛ جایگزینیِ بی‌صدای درآمد ممنوع است."""
    db = tmp_path / "app.db"
    _ingest(db, cohort_frame)
    with write_lock, session_scope(db) as session:
        for row in session.scalars(select(OrderLine).limit(500)).all():
            row.cost_rial = None
            row.gross_profit_rial = None

    run = train_model("whale", db_path=db)

    assert run["status"] == ModelRun.STATUS_INSUFFICIENT
    assert run["blocked_reason_code"] == REASON_PROFIT
    assert "سود" in run["blocked_reason_fa"]


def test_shuffled_labels_are_not_promoted(tmp_path, cohort_frame):
    """مدلی که خط پایه را نبرد **فعال نمی‌شود** — و این یک تستِ سبز است."""
    db = tmp_path / "app.db"
    _ingest(db, cohort_frame)
    lines = _lines(db)
    table = build_training_table(lines, spec=WhaleSpec())

    from mktcore.ml.whale import fit_whale

    shuffled = table.frame.copy()
    rng = np.random.default_rng(11)
    shuffled["label"] = rng.permutation(shuffled["label"].to_numpy())
    fitted = fit_whale(
        type(table)(**{**table.__dict__, "frame": shuffled}), WhaleSpec(),
    )

    assert fitted["metrics"]["passed"] is False


# ═══════════════════════════════════════ دروازه‌ی پذیرش فاز ۴
def test_model_beats_the_deterministic_baseline_on_topk_gross_profit(trained):
    """دروازه‌ی پذیرش §۳۵ فاز ۴، سرتاسری روی داده‌ی کوهورت‌دار."""
    run = trained["run"]
    metrics = run["metrics"]

    assert run["status"] == ModelRun.STATUS_VALIDATED, run["blocked_reason_fa"]
    assert metrics["gates"]["beats_prevalence_brier"]
    assert metrics["gates"]["beats_baseline_topk"]
    assert metrics["gates"]["calibrated"]
    assert (
        metrics["topk_captured_gross_profit_rial"]
        > metrics["baseline_topk_captured_gross_profit_rial"]
    )
    assert metrics["topk_advantage_lower_rial"] > 0, "برتری باید آماری هم واقعی باشد"


def test_validation_cohorts_are_strictly_later_than_training(trained):
    """§۲۹.۱: برشِ زمانی، نه تصادفی."""
    run = trained["run"]
    assert run["train_window"][1] <= run["validate_window"][0]


def test_calibration_is_within_tolerance(trained):
    """§۲۹.۴: «۸۰٪ گفتیم» باید تقریباً ۸۰٪ شود."""
    bins = trained["run"]["metrics"]["reliability_bins"]
    assert bins, "جدول اتکا باید ثبت شود"
    for row in bins:
        if row["تعداد"] >= 20:
            assert abs(row["خطا"]) <= 0.15


def test_explanation_is_persian_and_names_features(trained):
    """§۲۷.۷: «پیچیدگی خام ML را بدون تفسیر کسب‌وکاری نشان نده»."""
    explanation = trained["run"]["metrics"]["explanation_fa"]
    assert explanation
    assert any("احتمال" in line for line in explanation)


def test_scoring_writes_probabilities_only_after_promotion(trained):
    """قاعده‌ی قهرمان/مدعی: تا فعال‌سازی، هیچ ستونی لمس نمی‌شود."""
    db, clean, run = trained["db"], trained["clean"], trained["run"]

    before = score_whale_customers(db_path=db)
    assert before["scored"] == 0
    assert "فعال" in before["note_fa"]

    promote_run(run["id"], actor="آزمون", db_path=db)
    bundle = run_analysis(clean, with_forecast=False)
    write_customer_features(clean, bundle, db_path=db)
    after = score_whale_customers(db_path=db)

    assert after["scored"] > 0
    with session_scope(db) as session:
        rows = session.scalars(
            select(CustomerFeature).where(
                CustomerFeature.whale_probability_bp.isnot(None)
            ).limit(5)
        ).all()
        assert rows
        for row in rows:
            assert 0 <= row.whale_probability_bp <= 10_000
            assert row.whale_model_run_id == run["id"]
            assert row.scored_at is not None


def test_rollback_leaves_no_promoted_model_and_scoring_stops(trained):
    """بازگشت وقتی نسخه‌ی قبلی وجود ندارد، مدلِ فعلی را خاموش نمی‌کند."""
    db, run = trained["db"], trained["run"]

    with pytest.raises(LookupError):
        rollback_run(run["id"], db_path=db)

    with session_scope(db) as session:
        assert session.get(ModelRun, run["id"]).promoted is True
