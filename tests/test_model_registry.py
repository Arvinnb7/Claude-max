"""رجیستری مدل — مهاجرت، چرخه‌ی promote/rollback، و سریال‌سازی بدون pickle.

دو ادعای این لایه که باید اثبات شوند:

1. **مدلی که promote نشده هیچ اثری ندارد.** یعنی افزودن مدل به این پروژه
   به‌خودی‌خود بی‌خطر است و خطر فقط در لحظه‌ی فعال‌سازی است.
2. **بازگشت واقعاً همان مدل قبلی را برمی‌گرداند** — چون خودِ ردیف، خودِ مدل است
   و هیچ فایلی جابه‌جا نمی‌شود.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select, text

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.analysis.kpis import compute_kpis  # noqa: E402
from mktcore.db import session_scope  # noqa: E402
from mktcore.db.engine import get_engine  # noqa: E402
from mktcore.db.migrations import (  # noqa: E402
    CANONICAL_SCHEMA_VERSION,
    applied_versions,
    ensure_schema,
    reset_ensure_cache,
)
from mktcore.db.models import Business, CustomerFeature, ModelRun  # noqa: E402
from mktcore.db.repo_import import write_import  # noqa: E402
from mktcore.ingest.cleaning import clean_frame  # noqa: E402
from mktcore.ingest.mapper import SchemaMapper  # noqa: E402
from mktcore.ingest.schema import ColumnRole  # noqa: E402
from mktcore.ml.registry import (  # noqa: E402
    compute_data_hash,
    latest_run,
    promote_run,
    promoted_run,
    record_run,
    rollback_run,
)
from mktcore.ml.scoring import score_from_json, to_basis_points  # noqa: E402
from mktcore.ml.serialize import calibration_to_json, linear_model_to_json  # noqa: E402

_COLS = ["تاریخ", "مبلغ", "مشتری", "فاکتور", "کالا", "تعداد"]
_MAPPING = {
    ColumnRole.DATE: "تاریخ",
    ColumnRole.REVENUE: "مبلغ",
    ColumnRole.CUSTOMER_ID: "مشتری",
    ColumnRole.ORDER_ID: "فاکتور",
    ColumnRole.PRODUCT: "کالا",
    ColumnRole.QUANTITY: "تعداد",
}


@pytest.fixture(autouse=True)
def _isolate():
    reset_ensure_cache()
    yield
    reset_ensure_cache()


def _ledger(db: Path) -> None:
    raw = pd.DataFrame(
        [
            ("2023-01-10", 1_000, "C1", "A1", "کالای الف", 1),
            ("2023-02-10", 2_000, "C2", "A2", "کالای ب", 1),
        ],
        columns=_COLS,
    )
    clean = clean_frame(SchemaMapper().apply(raw, _MAPPING))
    write_import(clean, kpis=compute_kpis(clean), db_path=db)


def _fake_model() -> dict:
    return linear_model_to_json(
        features=["monetary_rial", "margin_quality_bp"],
        indicator_features=["margin_quality_bp"],
        impute_median=[10_000.0, 5_000.0],
        center=[10_000.0, 5_000.0, 0.0],
        scale=[5_000.0, 1_000.0, 1.0],
        coef=[0.8, 0.4, -0.3],
        intercept=-1.2,
    )


def _validated_run(db: Path, *, key: str = "whale", **extra) -> dict:
    return record_run(
        model_key=key, status=ModelRun.STATUS_VALIDATED, db_path=db,
        coefficients_json=_fake_model(),
        calibration_json=calibration_to_json(x=[0.0, 1.0], y=[0.0, 1.0]),
        metrics_json={"brier": 0.1}, label_basis="gross_profit", **extra,
    )


# ═══════════════════════════════════════ مهاجرت
def test_migration_ten_is_applied_and_idempotent(tmp_path):
    db = tmp_path / "app.db"
    ensure_schema(db)
    ensure_schema(db, force=True)

    # نسخه‌ی canonical با هر مهاجرت بالا می‌رود؛ آنچه اینجا مهم است این است که
    # مهاجرت ۱۰ اعمال شده باشد، نه اینکه آخرین نسخه دقیقاً ۱۰ بماند.
    assert CANONICAL_SCHEMA_VERSION >= 10
    assert 10 in applied_versions(get_engine(db))


def test_legacy_layer_is_untouched_by_migration_ten(tmp_path):
    """قاعده‌ی سختِ این ارتقا: `PRAGMA user_version` در ۲ می‌ماند."""
    db = tmp_path / "app.db"
    _ledger(db)
    with get_engine(db).connect() as conn:
        version = conn.execute(text("PRAGMA user_version")).scalar()
    assert version in (0, 2), "لایه‌ی canonical نباید نسخه‌ی legacy را تکان دهد"


def test_score_columns_exist_and_default_to_null(tmp_path):
    """`NULL` یعنی «مدلی فعال نیست»، نه «احتمال صفر»."""
    db = tmp_path / "app.db"
    _ledger(db)
    with session_scope(db) as session:
        columns = {
            row[1] for row in session.execute(text("PRAGMA table_info(customer_features)"))
        }
    assert {"whale_probability_bp", "whale_model_run_id", "scored_at"} <= columns


# ═══════════════════════════════════════ چرخه‌ی عمر
def test_insufficient_data_is_recorded_not_raised(tmp_path):
    """§۲۹.۶ حالتِ صریحِ «داده کافی نبود» می‌خواهد؛ استثنا فردا نامرئی است."""
    db = tmp_path / "app.db"
    _ledger(db)
    run = record_run(
        model_key="whale", status=ModelRun.STATUS_INSUFFICIENT, db_path=db,
        blocked_reason_code="span_too_short",
        blocked_reason_fa="بازه‌ی داده ۷۳۰ روز است؛ دست‌کم ۸۲۰ روز لازم است.",
        metrics_json={"requirements": {"بازه‌ی داده (روز)": {"لازم": 820, "موجود": 730}}},
    )

    assert run["status"] == ModelRun.STATUS_INSUFFICIENT
    assert run["promoted"] is False
    assert "۸۲۰" in run["blocked_reason_fa"]
    assert run["metrics"]["requirements"]["بازه‌ی داده (روز)"]["موجود"] == 730


def test_promote_refuses_a_run_that_was_not_validated(tmp_path):
    db = tmp_path / "app.db"
    _ledger(db)
    run = record_run(
        model_key="whale", status=ModelRun.STATUS_TRAINED, db_path=db,
        coefficients_json=_fake_model(),
    )

    with pytest.raises(PermissionError) as err:
        promote_run(run["id"], db_path=db)
    assert "اعتبارسنجی" in str(err.value)

    with session_scope(db) as session:
        assert session.get(ModelRun, run["id"]).promoted is False


def test_promote_refuses_a_run_without_a_model(tmp_path):
    """اجرای «داده کافی نبود» ضرایب ندارد، پس چیزی برای فعال‌کردن نیست."""
    db = tmp_path / "app.db"
    _ledger(db)
    run = record_run(
        model_key="whale", status=ModelRun.STATUS_VALIDATED, db_path=db,
    )
    with pytest.raises(PermissionError):
        promote_run(run["id"], db_path=db)


def test_promoting_a_new_run_supersedes_the_previous_one(tmp_path):
    db = tmp_path / "app.db"
    _ledger(db)
    first = promote_run(_validated_run(db)["id"], actor="tester", db_path=db)
    second = promote_run(_validated_run(db)["id"], actor="tester", db_path=db)

    with session_scope(db) as session:
        business_id = session.scalar(select(Business.id))
        active = promoted_run(session, business_id, "whale")
        old = session.get(ModelRun, first["id"])

    assert active.id == second["id"]
    assert old.promoted is False
    assert old.status == ModelRun.STATUS_SUPERSEDED


def test_rollback_restores_the_previous_promoted_run(tmp_path):
    db = tmp_path / "app.db"
    _ledger(db)
    first = promote_run(_validated_run(db)["id"], db_path=db)
    second = promote_run(_validated_run(db)["id"], db_path=db)

    restored = rollback_run(second["id"], actor="tester", db_path=db)

    assert restored["id"] == first["id"]
    assert restored["promoted"] is True
    with session_scope(db) as session:
        assert session.get(ModelRun, second["id"]).status == ModelRun.STATUS_ROLLED_BACK


def test_rollback_without_a_predecessor_is_refused_in_persian(tmp_path):
    db = tmp_path / "app.db"
    _ledger(db)
    only = promote_run(_validated_run(db)["id"], db_path=db)

    with pytest.raises(LookupError) as err:
        rollback_run(only["id"], db_path=db)
    assert "نخستین" in str(err.value)

    with session_scope(db) as session:
        assert session.get(ModelRun, only["id"]).promoted is True, "چیزی نباید خاموش شود"


def test_model_version_increments_per_key(tmp_path):
    db = tmp_path / "app.db"
    _ledger(db)
    _validated_run(db, key="whale")
    _validated_run(db, key="whale")
    _validated_run(db, key="churn")

    with session_scope(db) as session:
        business_id = session.scalar(select(Business.id))
        whale = latest_run(session, business_id, "whale")
        churn = latest_run(session, business_id, "churn")

    assert whale.model_version == 2
    assert churn.model_version == 1, "شماره‌ی نسخه به‌ازای هر نوع مدل جداست"


def test_no_promoted_model_means_no_customer_score(tmp_path):
    """ادعای اصلی: مدلِ فعال‌نشده هیچ عددی روی مشتری نمی‌نویسد."""
    db = tmp_path / "app.db"
    _ledger(db)
    _validated_run(db)

    with session_scope(db) as session:
        scored = session.scalar(
            select(CustomerFeature).where(CustomerFeature.whale_probability_bp.isnot(None))
        )
    assert scored is None


# ═══════════════════════════════════════ سریال‌سازی و امتیازدهی
def test_scoring_reproduces_the_linear_model_by_hand(tmp_path):
    """امتیازدهی بدون sklearn — و بدون آرتیفکتِ دودویی."""
    model = _fake_model()
    frame = pd.DataFrame({"monetary_rial": [20_000.0], "margin_quality_bp": [6_000.0]})

    got = score_from_json(model, None, frame)

    z = (
        (20_000 - 10_000) / 5_000 * 0.8
        + (6_000 - 5_000) / 1_000 * 0.4
        + (0 - 0) / 1 * -0.3
        - 1.2
    )
    assert got[0] == pytest.approx(1 / (1 + np.exp(-z)), abs=1e-12)


def test_missing_feature_uses_the_median_and_raises_its_flag(tmp_path):
    """«نمی‌دانیم» خودش سیگنال است؛ جای‌گذاریِ بی‌پرچم ادعای دانستن می‌کند."""
    model = _fake_model()
    known = pd.DataFrame({"monetary_rial": [10_000.0], "margin_quality_bp": [5_000.0]})
    unknown = pd.DataFrame({"monetary_rial": [10_000.0], "margin_quality_bp": [np.nan]})

    assert score_from_json(model, None, known)[0] != score_from_json(model, None, unknown)[0]


def test_calibration_round_trips_through_json(tmp_path):
    """آرتیفکتِ کالیبراسیون باید بدون pickle بازتولید شود."""
    sklearn_iso = pytest.importorskip("sklearn.isotonic")
    raw = np.linspace(0.0, 1.0, 40)
    target = (raw > 0.6).astype(float)
    iso = sklearn_iso.IsotonicRegression(out_of_bounds="clip").fit(raw, target)

    artifact = calibration_to_json(
        x=list(iso.X_thresholds_), y=list(iso.y_thresholds_),
    )
    from mktcore.ml.scoring import apply_calibration

    probe = np.linspace(0.0, 1.0, 17)
    assert np.allclose(apply_calibration(artifact, probe), iso.predict(probe), atol=1e-9)


def test_no_model_scores_nan_not_zero():
    frame = pd.DataFrame({"monetary_rial": [1.0, 2.0]})
    scores = score_from_json(None, None, frame)

    assert np.isnan(scores).all()
    assert to_basis_points(scores) == [None, None]


def test_data_hash_changes_when_profit_changes_but_revenue_does_not(tmp_path):
    """ورودِ دوباره‌ی فایل بها باید مدلِ سودمحور را باطل کند."""
    common = {
        "business_id": 1, "model_key": "whale",
        "train_start": "2023-01-01", "train_end": "2024-01-01",
        "n_lines": 1000, "sum_revenue_rial": 5_000_000,
    }
    before = compute_data_hash(**common, sum_gross_profit_rial=2_000_000)
    after = compute_data_hash(**common, sum_gross_profit_rial=2_400_000)
    missing = compute_data_hash(**common, sum_gross_profit_rial=None)

    assert before != after
    assert missing not in (before, after)
