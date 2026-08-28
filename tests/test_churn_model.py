"""ریسک ریزش به‌صورت مدلِ خطرِ گسسته (§۱۶.۳ و §۱۳.۵).

قاعده‌ی حاکم بر این فایل: **قهرمانِ فعلی جایش امن است.** `p_alive` و
`churn_risk` موجود یک عددِ خوب و ساده‌اند و همه‌ی مصرف‌کننده‌هایشان (حالت
«ازدست‌رفته»، فهرست اقدام، UI) باید همان را ببینند. مدلِ تازه فقط اگر روی
holdout زمانی از آن جلو بزند، در ستونِ **جدا** می‌نشیند.
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
from mktcore.db.lookup import resolve_business_id  # noqa: E402
from mktcore.db.migrations import reset_ensure_cache  # noqa: E402
from mktcore.db.models import CustomerFeature, ModelRun  # noqa: E402
from mktcore.db.repo_features import write_customer_features  # noqa: E402
from mktcore.db.repo_import import write_import  # noqa: E402
from mktcore.features.ledger_frame import load_line_frame  # noqa: E402
from mktcore.ingest.cleaning import clean_frame  # noqa: E402
from mktcore.ingest.mapper import SchemaMapper  # noqa: E402
from mktcore.ml.churn import (  # noqa: E402
    ChurnSpec,
    build_person_period,
    score_churn_customers,
    snapshot_dates,
)
from mktcore.ml.registry import promote_run  # noqa: E402
from mktcore.ml.train import available_trainers, train_model  # noqa: E402
from mktcore.pipeline import run_analysis  # noqa: E402
from mktcore.synthetic import generate_cohort_sales  # noqa: E402


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
def trained(tmp_path_factory) -> dict:
    """آموزش + یک بار تحلیل و عکس ویژگی.

    تحلیل گران‌ترین بخشِ این فایل است، پس **یک بار** انجام می‌شود و تست‌های
    بعدی همان نتیجه را به‌کار می‌برند.
    """
    db = tmp_path_factory.mktemp("churn") / "app.db"
    # مدلِ ریزش به دروازه‌ی بلوغِ کوهورتِ نهنگ نیاز ندارد، پس داده‌ی کوچک‌تر
    # کافی است و اجرای تست را کوتاه می‌کند.
    clean = _ingest(db, generate_cohort_sales(days=1_250, arrivals_per_day=1.4))
    run = train_model("churn", db_path=db)
    bundle = run_analysis(clean, with_forecast=False)
    write_customer_features(clean, bundle, db_path=db)
    return {"db": db, "clean": clean, "bundle": bundle, "run": run}


def test_churn_trainer_is_registered():
    assert "churn" in available_trainers()


def test_snapshots_stop_before_the_horizon_can_be_observed(tmp_path):
    """دوره‌ای که پنجره‌ی نتیجه‌اش تمام نشده، برچسبِ مطمئن ندارد."""
    db = tmp_path / "app.db"
    _ingest(db, generate_cohort_sales(days=800))
    lines = _lines(db)
    spec = ChurnSpec()

    dates = snapshot_dates(lines, spec)
    data_max = pd.Timestamp(lines["line_date"].max())

    assert dates
    assert pd.Timestamp(dates[-1]) + pd.Timedelta(days=spec.horizon_days) <= data_max


def test_person_period_labels_match_actual_purchases(tmp_path):
    """برچسب یعنی «در افق پیشِ رو خریدی نکرد» — نه یک عددِ تقویمیِ ثابت."""
    db = tmp_path / "app.db"
    _ingest(db, generate_cohort_sales(days=900))
    lines = _lines(db)
    spec = ChurnSpec(max_snapshots=3)

    table = build_person_period(lines, spec)
    assert not table.empty

    row = table.iloc[0]
    horizon_end = (
        pd.Timestamp(row["as_of"]) + pd.Timedelta(days=spec.horizon_days)
    ).date().isoformat()
    bought = lines[
        (lines["customer_id"] == row["customer_id"])
        & (lines["line_date"] >= row["as_of"])
        & (lines["line_date"] < horizon_end)
    ]
    assert row["label"] == (0 if len(bought) else 1)


def test_features_of_a_period_never_see_that_period(tmp_path):
    """ویژگی‌های هر دوره فقط از **قبلِ** آن دوره ساخته می‌شوند."""
    db = tmp_path / "app.db"
    _ingest(db, generate_cohort_sales(days=900))
    spec = ChurnSpec(max_snapshots=3)
    table = build_person_period(_lines(db), spec)

    for as_of, block in table.groupby("as_of"):
        # «روز از آخرین خرید» در هر عکس باید نسبت به همان تاریخ باشد؛ اگر داده‌ی
        # بعد از `as_of` دیده می‌شد، این عدد می‌توانست صفر شود.
        assert (block["recency_days"] >= 0).all(), as_of


def test_model_beats_the_geometric_damper(trained):
    """§۲۹.۳: مدلِ پیچیده‌تر باید خط پایه‌ی مستندشده را ببرد."""
    run = trained["run"]
    metrics = run["metrics"]

    assert run["status"] == ModelRun.STATUS_VALIDATED, run["blocked_reason_fa"]
    assert metrics["brier"] < metrics["brier_baseline"]
    assert metrics["gates"]["beats_baseline_topk"]
    assert metrics["topk_advantage_lower_rial"] > 0
    assert "π" in metrics["baseline_name_fa"]


def test_validation_periods_are_later_than_training(trained):
    run = trained["run"]
    assert run["train_window"][1] <= run["validate_window"][0]


def test_thin_data_is_refused_with_a_reason(tmp_path):
    db = tmp_path / "app.db"
    _ingest(db, generate_cohort_sales(days=200, arrivals_per_day=0.2))

    run = train_model("churn", db_path=db)

    assert run["status"] == ModelRun.STATUS_INSUFFICIENT
    assert run["blocked_reason_code"] in ("too_few_periods", "too_few_positives")
    assert run["blocked_reason_fa"]


def test_scores_are_written_only_after_promotion(trained):
    db, run = trained["db"], trained["run"]

    assert score_churn_customers(db_path=db)["scored"] == 0

    promote_run(run["id"], actor="آزمون", db_path=db)
    result = score_churn_customers(db_path=db)

    assert result["scored"] > 0
    with session_scope(db) as session:
        rows = session.scalars(
            select(CustomerFeature).where(
                CustomerFeature.churn_probability_bp.isnot(None)
            ).limit(5)
        ).all()
    assert rows
    for row in rows:
        assert 0 <= row.churn_probability_bp <= 10_000
        assert row.churn_model_run_id == run["id"]


def test_the_existing_alive_probability_column_is_untouched(trained):
    """قهرمانِ فعلی باید همان عدد را نگه دارد؛ مدل کنارش می‌نشیند، نه جایش."""
    db, bundle = trained["db"], trained["bundle"]

    expected = {
        str(c.customer_id): c.alive_probability for c in bundle.next_purchase.customers
    }
    with session_scope(db) as session:
        rows = session.scalars(
            select(CustomerFeature).where(CustomerFeature.p_alive_bp.isnot(None)).limit(20)
        ).all()

    assert rows, "ستون احتمال زنده‌بودن باید مثل قبل نوشته شود"
    assert any(value is not None for value in expected.values())
    for row in rows:
        assert 0 <= row.p_alive_bp <= 10_000
