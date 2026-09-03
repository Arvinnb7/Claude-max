"""§۲۸: تلاش دوباره با فاصله‌ی فزاینده، و شکستی که **دیده** می‌شود.

## قاعده‌ای که این فایل پین می‌کند

کارِ زمان‌بندی‌شده‌ای که شکست بخورد، تا امروز فقط یک `logger.exception` بود.
یعنی اگر بازآموزی مدل سه هفته پشت سر هم شکست می‌خورد، هیچ‌کس نمی‌فهمید مگر آنکه
لاگ را می‌خواند. حالا: تلاشِ دوباره با فاصله‌ی فزاینده، و در پایان یک ردیف در
**صف مرده** که کسی می‌بیندش.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.db.base import now_ts  # noqa: E402
from mktcore.db.migrations import ensure_schema, reset_ensure_cache  # noqa: E402
from mktcore.db.models import JobRun  # noqa: E402
from mktcore.jobs import (  # noqa: E402
    SCHEDULED_JOBS,
    JobSkipped,
    ScheduledJob,
    dead_letter_runs,
    recent_runs,
    register_job,
    retry_run,
    run_job,
    sweep_due_retries,
    unregister_job,
)
from mktcore.jobs.runner import backoff_seconds  # noqa: E402


@pytest.fixture
def db(tmp_path) -> Path:
    reset_ensure_cache()
    path = tmp_path / "app.db"
    ensure_schema(path)
    yield path
    reset_ensure_cache()


@pytest.fixture
def failing_job():
    calls = {"n": 0}

    def run(*, correlation_id=None):
        calls["n"] += 1
        raise RuntimeError("پنل پیامکی جواب نداد")

    register_job(ScheduledJob(
        name="_test_failing", title_fa="کارِ همیشه‌شکست", run=run, max_attempts=3,
    ))
    yield calls
    unregister_job("_test_failing")


@pytest.fixture
def flaky_job():
    """دو بار شکست، بارِ سوم موفق — همان الگوی خطای گذرای واقعی."""
    calls = {"n": 0}

    def run(*, correlation_id=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("شبکه لحظه‌ای قطع بود")
        return {"ok": True, "attempts": calls["n"]}

    register_job(ScheduledJob(
        name="_test_flaky", title_fa="کارِ گذرا", run=run, max_attempts=3,
    ))
    yield calls
    unregister_job("_test_flaky")


# ═══════════════════════════════════════════════════ فاصله‌ی فزاینده
def test_backoff_doubles_each_attempt():
    assert backoff_seconds(1) == 60
    assert backoff_seconds(2) == 120
    assert backoff_seconds(3) == 240


def test_a_failure_schedules_a_retry_instead_of_dying(db, failing_job):
    result = run_job("_test_failing", db_path=db)

    assert result["status"] == JobRun.STATUS_RETRY_SCHEDULED
    assert result["attempt"] == 1
    assert result["next_retry_at"] is not None
    # حدود ۶۰ ثانیه بعد؛ دقتِ ثانیه‌ای لازم نیست، ترتیبِ بزرگی مهم است
    assert 55 <= result["next_retry_at"] - now_ts() <= 65
    assert "پنل پیامکی" in result["note_fa"]


def test_the_sweeper_ignores_retries_that_are_not_due_yet(db, failing_job):
    run_job("_test_failing", db_path=db)

    assert sweep_due_retries(db_path=db)["retried"] == 0
    assert failing_job["n"] == 1


def test_three_failures_land_in_the_dead_letter_queue(db, failing_job):
    """دروازه‌ی پذیرش این گام: بعد از تمام‌شدن تلاش‌ها، **دیده** شود."""
    run_job("_test_failing", db_path=db)
    sweep_due_retries(now=now_ts() + 3_600, db_path=db)   # تلاش ۲
    sweep_due_retries(now=now_ts() + 7_200, db_path=db)   # تلاش ۳

    assert failing_job["n"] == 3
    dead = dead_letter_runs(db_path=db)
    assert len(dead) == 1
    assert dead[0]["attempt"] == 3
    assert dead[0]["error_type"] == "RuntimeError"
    assert "پنل پیامکی" in dead[0]["error_first_line"]
    assert dead[0]["next_retry_at"] is None, "کارِ مرده نباید تلاشِ برنامه‌ریزی‌شده داشته باشد"


def test_a_transient_failure_recovers_without_human_help(db, flaky_job):
    run_job("_test_flaky", db_path=db)
    sweep_due_retries(now=now_ts() + 3_600, db_path=db)
    result = sweep_due_retries(now=now_ts() + 7_200, db_path=db)["outcomes"][0]

    assert result["status"] == JobRun.STATUS_SUCCEEDED
    assert result["result"] == {"ok": True, "attempts": 3}
    assert dead_letter_runs(db_path=db) == []


def test_retries_reuse_one_row_so_the_attempt_count_survives(db, failing_job):
    """سه ردیف برای یک شکست، هم فهرست را شلوغ می‌کند هم «چند بار» را گم."""
    run_job("_test_failing", db_path=db)
    sweep_due_retries(now=now_ts() + 3_600, db_path=db)

    rows = [r for r in recent_runs(db_path=db) if r["job_name"] == "_test_failing"]
    assert len(rows) == 1
    assert rows[0]["attempt"] == 2


def test_the_correlation_id_survives_every_retry(db, failing_job):
    first = run_job("_test_failing", db_path=db)
    second = sweep_due_retries(now=now_ts() + 3_600, db_path=db)["outcomes"][0]

    assert second["correlation_id"] == first["correlation_id"]


def test_a_manual_retry_restarts_the_counter(db, failing_job):
    """اپراتوری که علت را رفع کرده نباید منتظرِ تلاش‌های تمام‌شده بماند."""
    run_job("_test_failing", db_path=db)
    sweep_due_retries(now=now_ts() + 3_600, db_path=db)
    sweep_due_retries(now=now_ts() + 7_200, db_path=db)
    dead = dead_letter_runs(db_path=db)[0]

    again = retry_run(dead["id"], db_path=db)

    assert again["attempt"] == 1
    assert again["status"] == JobRun.STATUS_RETRY_SCHEDULED


# ═══════════════════════════════════════════ «شرطش برقرار نبود» شکست نیست
def test_a_skipped_job_is_not_retried_and_not_dead(db):
    def run(*, correlation_id=None):
        raise JobSkipped("هیچ نشست تحلیل‌شده‌ای وجود ندارد.")

    register_job(ScheduledJob(name="_test_skip", title_fa="رد", run=run))
    try:
        result = run_job("_test_skip", db_path=db)
    finally:
        unregister_job("_test_skip")

    assert result["status"] == JobRun.STATUS_SKIPPED
    assert result["next_retry_at"] is None
    assert "تحلیل‌شده" in result["note_fa"]
    assert dead_letter_runs(db_path=db) == []


def test_an_unknown_job_name_is_reported_not_swallowed(db):
    assert run_job("کاری که وجود ندارد", db_path=db)["status"] == "unknown_job"


# ═══════════════════════════════════════════════════ خودِ فهرستِ کارها
def test_the_six_missing_section_28_jobs_are_registered():
    """اگر یکی از این‌ها حذف شود، همان شکافی برمی‌گردد که این گام بست."""
    required = {
        "opportunity_generation",
        "opportunity_expiration",
        "outcome_matching",
        "campaign_analysis",
        "model_retraining",
        "drift_monitoring",
    }
    assert required <= {job.name for job in SCHEDULED_JOBS}


def test_every_job_has_a_persian_title_and_a_schedule():
    for job in SCHEDULED_JOBS:
        assert job.title_fa.strip(), job.name
        assert (job.hour is not None) or (job.interval_hours is not None), job.name
        assert job.max_attempts >= 1


# ═════════════════════════════════ کارهای واقعی: سیم‌کشی، نه فقط نام
@pytest.mark.parametrize("name", [
    "opportunity_generation",
    "opportunity_expiration",
    "outcome_matching",
    "campaign_analysis",
    "model_retraining",
    "drift_monitoring",
])
def test_each_real_job_either_works_or_says_why_not(tmp_path, monkeypatch, name):
    """هیچ کارِ ثبت‌شده‌ای نباید با خطای برنامه‌نویسی بیفتد.

    فهرستِ کارها می‌تواند شش نامِ درست داشته باشد و هر شش‌تا با `ImportError`
    بیفتند — و چون شکست‌ها در دیتابیس می‌نشینند، تست‌های دیگر متوجه نمی‌شوند.
    اینجا هرکدام واقعاً صدا زده می‌شوند: نتیجه یا «موفق» است یا «رد شد **با
    دلیل**»؛ `retry_scheduled` یعنی چیزی در خودِ کد شکسته است.
    """
    from mktcore.config import get_settings
    from mktcore.db.engine import dispose_engine

    # دفتر کلِ خالی و ایزوله، تا این تست به داده‌ی تست‌های دیگر وابسته نباشد
    monkeypatch.setattr(get_settings(), "mkt_data_dir", str(tmp_path), raising=False)
    dispose_engine()
    reset_ensure_cache()
    try:
        result = run_job(name, db_path=tmp_path / "runs.db")
    finally:
        dispose_engine()
        reset_ensure_cache()

    assert result["status"] in (JobRun.STATUS_SUCCEEDED, JobRun.STATUS_SKIPPED), (
        f"{name} با خطا افتاد: {result.get('error_first_line')}"
    )
    if result["status"] == JobRun.STATUS_SKIPPED:
        assert result["note_fa"], f"{name} بدون دلیل رد شد"


# ═══════════════════════════════════════════ دیده‌شدن از راه API (§۲۸)
def test_the_api_shows_the_dead_letter_queue(db, failing_job, monkeypatch):
    """صفِ مرده‌ای که فقط در دیتابیس باشد، «دیده‌شدن» نیست."""
    from api.main import app
    from fastapi.testclient import TestClient

    # کارها روی دیتابیسِ پیش‌فرض ثبت می‌شوند، پس مسیرِ API هم همان را می‌بیند
    run_job("_test_failing")
    sweep_due_retries(now=now_ts() + 3_600)
    sweep_due_retries(now=now_ts() + 7_200)

    client = TestClient(app)
    body = client.get("/api/v1/ops/jobs/dead-letter").json()

    mine = [r for r in body["runs"] if r["job_name"] == "_test_failing"]
    assert mine, body["note_fa"]
    assert mine[0]["attempt"] == 3
    assert "صف مرده" in mine[0]["note_fa"]

    listing = client.get("/api/v1/ops/jobs").json()
    assert {job["name"] for job in listing["jobs"]} >= {"drift_monitoring"}


# ══════════════════════════════════════ دفترِ اجرا خودش بی‌کران رشد نکند
def test_the_sweeper_prunes_old_successful_runs_but_never_the_dead(db, failing_job):
    """جاروکش هر ربع ساعت یک ردیف می‌سازد؛ بدون هرس، دفتر بی‌کران رشد می‌کند.

    ولی صف مرده هرگز هرس نمی‌شود: همان‌ها تنها چیزی‌اند که باید دیده شوند.
    """
    from mktcore.jobs.runner import prune_completed_runs

    # یک ردیفِ مرده بساز
    run_job("_test_failing", db_path=db)
    sweep_due_retries(now=now_ts() + 3_600, db_path=db)
    sweep_due_retries(now=now_ts() + 7_200, db_path=db)

    # و یک ردیفِ موفق
    register_job(ScheduledJob(
        name="_test_ok", title_fa="موفق", run=lambda *, correlation_id=None: {"ok": 1},
    ))
    try:
        run_job("_test_ok", db_path=db)
    finally:
        unregister_job("_test_ok")

    # زمان را جلو ببر: هر دو «قدیمی» می‌شوند
    pruned = prune_completed_runs(now=now_ts() + 40 * 86_400, db_path=db)

    assert pruned == 1, "فقط ردیفِ موفق باید هرس شود"
    remaining = {r["job_name"] for r in recent_runs(db_path=db)}
    assert remaining == {"_test_failing"}
    assert len(dead_letter_runs(db_path=db)) == 1


# ═══════════════════════════════════ هشدارِ انحراف (§۲۹.۷) — بازبینی: شاخه‌ی مرده
def test_drift_job_raises_an_alert_on_a_shifted_model(tmp_path, monkeypatch, caplog):
    """سطحِ «تغییر معنادار» باید در نتیجه‌ی کار و در لاگ دیده شود.

    شرطِ قبلی با «زیاد»/«high» مقایسه می‌کرد — رشته‌هایی که هیچ‌جا تولید
    نمی‌شوند — پس هشدارِ زمان‌بند هرگز شلیک نمی‌شد.
    """
    import logging

    import pandas as pd

    from mktcore.config import get_settings
    from mktcore.db.engine import dispose_engine
    from mktcore.ml import drift as drift_mod
    from mktcore.ml import registry as ml_registry

    monkeypatch.setattr(get_settings(), "mkt_data_dir", str(tmp_path), raising=False)
    dispose_engine()
    reset_ensure_cache()
    try:
        import mktcore.db.lookup as lookup_mod
        import mktcore.features.ledger_frame as ledger_mod
        import mktcore.features.point_in_time as pit_mod

        monkeypatch.setattr(lookup_mod, "resolve_business_id", lambda *_a, **_k: 1)
        monkeypatch.setattr(
            ml_registry, "promoted_run",
            lambda session, business_id, key: object() if key == "whale" else None,
        )
        monkeypatch.setattr(
            ml_registry, "run_to_dict",
            lambda run, with_model=True: {"id": 42, "params": {}, "drift_baseline": {}, "calibration": {}},
        )
        monkeypatch.setattr(
            ledger_mod, "load_line_frame",
            lambda session, business_id: pd.DataFrame({"line_date": ["2026-01-01"], "customer_id": [1]}),
        )
        monkeypatch.setattr(pit_mod, "compute_point_in_time_features", lambda *_a, **_k: pd.DataFrame())
        monkeypatch.setattr(
            drift_mod, "measure_drift",
            lambda **_k: {"measured": True, "level": drift_mod.LEVEL_SHIFTED, "note_fa": "PSI بالا"},
        )
        with caplog.at_level(logging.WARNING, logger="mktcore.jobs.registry"):
            result = run_job("drift_monitoring", db_path=tmp_path / "runs.db")
    finally:
        dispose_engine()
        reset_ensure_cache()

    assert result["status"] == JobRun.STATUS_SUCCEEDED, result
    alerts = result["result"]["alerts"]
    assert len(alerts) == 1 and alerts[0]["model_key"] == "whale"
    assert alerts[0]["level"] == drift_mod.LEVEL_SHIFTED
    assert any("whale" in rec.getMessage() for rec in caplog.records if rec.levelno >= logging.WARNING)
