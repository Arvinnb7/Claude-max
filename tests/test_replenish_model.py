"""مدعیِ یادآورِ تکرارِ خرید (`replenish`) — backtest روی holdout زمانی با بازه‌ی ادعای ±۲۵٪.

ادعاها: برچسب با خودِ دفتر کل بازمحاسبه می‌شود؛ ویژگی‌ها عکس را نمی‌بینند؛ اعتبارسنجی
بعد از آموزش است؛ روی داده‌ی با آهنگِ شخصی مدعی قهرمانِ «میانه‌ی کالا» را می‌برد و
سنجه‌اش درآمدی و برچسب‌دار است؛ با بها سنجه سودی می‌شود؛ داده‌ی نازک با عدد رد می‌شود؛
promote/rollback روی قاعده کار می‌کند و ستونِ مشتری NULL می‌ماند.
"""

from __future__ import annotations

import json
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
from mktcore.features.point_in_time import LeakageError  # noqa: E402
from mktcore.ingest.cleaning import clean_frame  # noqa: E402
from mktcore.ingest.mapper import SchemaMapper  # noqa: E402
from mktcore.ml.registry import promote_run, promoted_run, rollback_run  # noqa: E402
from mktcore.ml.replenish import (  # noqa: E402
    CHAMPION_UNCLAIMED,
    LABEL_BASIS,
    ReplenishSpec,
    build_pair_period,
    promoted_due_table,
    snapshot_dates,
)
from mktcore.ml.train import available_trainers, train_model  # noqa: E402
from mktcore.pipeline import run_analysis  # noqa: E402
from mktcore.synthetic import generate_replenishment_sales  # noqa: E402


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
def trained(tmp_path_factory):
    db = tmp_path_factory.mktemp("replenish") / "app.db"
    _ingest(db, generate_replenishment_sales())
    run = train_model("replenish", db_path=db)
    return {"db": db, "run": run}


# ═══════════════════════════════════════════ ثبت و ساختِ جدول
def test_trainer_is_registered():
    assert "replenish" in available_trainers()


def test_pair_labels_match_actual_same_product_purchases(trained):
    lines = _lines(trained["db"])
    spec = ReplenishSpec()
    table = build_pair_period(lines, spec)
    assert not table.empty and table.attrs["value_basis"] == "revenue"
    covered = table[table["future_covered"]]
    # همه‌ی ردیف‌های سنجیدنی بازه‌ی بازی دارند: نسبتِ عقب‌افتادگی نمی‌تواند از ۱٫۲۵ گذشته باشد
    assert (covered["overdue_ratio"] <= 1.25 + 1e-9).all(), "بازه‌ی گذشته «ادعا» نیست"
    assert covered["label"].sum() > 0 and (covered["label"] == 0).sum() > 0
    sample = covered[covered["label"] == 1].iloc[0]
    stamp = pd.Timestamp(sample["as_of"])
    lines["_date"] = pd.to_datetime(lines["line_date"])
    pair = lines[(lines["customer_id"] == sample["customer_id"]) & (lines["product_id"] == sample["product_id"])
                 & (~lines["is_return"].astype(bool))]
    past = pair[pair["_date"] < stamp]
    last = past["_date"].max()
    interval = float(sample["expected_interval_days"])
    due = last + pd.Timedelta(days=interval)
    start, end = max(due - pd.Timedelta(days=0.25 * interval), stamp), due + pd.Timedelta(days=0.25 * interval)
    inside = pair[(pair["_date"] > start) & (pair["_date"] <= end)]
    assert int(sample["label"]) == int(not inside.empty) == 1
    assert sample["value_rial"] == float(inside["revenue_rial"].sum()) > 0
    # و یک ردیفِ صفر هم با بازمحاسبه صفر است (نه به‌خاطرِ بازه‌ی گذشته)
    zero = covered[covered["label"] == 0].iloc[0]
    z_stamp = pd.Timestamp(zero["as_of"])
    z_pair = lines[(lines["customer_id"] == zero["customer_id"]) & (lines["product_id"] == zero["product_id"])
                   & (~lines["is_return"].astype(bool))]
    z_last = z_pair[z_pair["_date"] < z_stamp]["_date"].max()
    z_interval = float(zero["expected_interval_days"])
    z_due = z_last + pd.Timedelta(days=z_interval)
    z_end = z_due + pd.Timedelta(days=0.25 * z_interval)
    assert z_end > z_stamp
    z_inside = z_pair[(z_pair["_date"] > max(z_due - pd.Timedelta(days=0.25 * z_interval), z_stamp))
                      & (z_pair["_date"] <= z_end)]
    assert z_inside.empty


def test_snapshots_stop_before_the_tail_and_features_never_see_the_snapshot(trained):
    lines = _lines(trained["db"])
    spec = ReplenishSpec()
    dates = snapshot_dates(lines, spec)
    assert 3 <= len(dates) <= spec.max_snapshots
    data_max = pd.to_datetime(lines["line_date"]).max()
    assert pd.Timestamp(dates[-1]) + pd.Timedelta(days=spec.tail_days) <= data_max
    table = build_pair_period(lines, spec)
    assert (table["overdue_ratio"] >= 0).all(), "گذشته از آخرین خرید هرگز منفی نیست: خطوطِ بعد از عکس دیده نشده‌اند"
    # پوشش: ردیفِ پوشیده‌نشده کنار می‌رود، نه اینکه صفر بگیرد
    assert table["future_covered"].dtype == bool
    from mktcore.analysis.replenish_personal import LEDGER_COLUMNS, personal_cadence_table

    with pytest.raises(LeakageError):
        personal_cadence_table(lines, as_of=dates[0], columns=LEDGER_COLUMNS)


def test_champion_cycles_ignore_returns_and_only_see_the_past():
    """قهرمانِ تولیدی برگشت نمی‌بیند؛ و میانه‌اش از داده‌ی پیش از عکس است نه کلِ دفتر."""
    from mktcore.ml.replenish import _champion_cycles

    rows = []
    for c in range(20):   # ۲۰ مشتریِ تک‌خرید + برگشت (اگر برگشت شمرده شود، «تکراری» می‌شوند)
        rows += [(c, 7, "2024-01-10", 100, False), (c, 7, "2024-01-29", -100, True)]
    for c in range(20, 23):   # سه تکراریِ واقعی با فاصله‌ی ۴۰ روز
        rows += [(c, 7, "2024-01-05", 100, False), (c, 7, "2024-02-14", 100, False), (c, 7, "2024-03-25", 100, False)]
    frame = pd.DataFrame(rows, columns=["customer_id", "product_id", "line_date", "revenue_rial", "is_return"])
    frame["_date"] = pd.to_datetime(frame["line_date"])
    assert _champion_cycles(frame[~frame["is_return"]]) == {}, "۳ از ۲۳ تکراری < ۰٫۳ ⇒ مصرفی نیست"
    assert _champion_cycles(frame) == {7: 19.0}, "با برگشت، هر برگشت یک «خریدِ تکراری» جعلی می‌ساخت"
    table = build_pair_period(frame.drop(columns=["_date"]).assign(
        quantity_milli=1000, pack_size_milli=None, gross_profit_rial=None, cost_rial=None,
        unit_price_rial=None, discount_rial=None, discount_rate_bp=None, order_id=None,
        category=None, branch=None, channel=None,
    ), ReplenishSpec(period_days=10, tail_days=5, min_gaps=2))
    assert table.empty or (table["champion_score"] == CHAMPION_UNCLAIMED).all()


def test_validation_snapshots_are_later_than_training(trained):
    run = trained["run"]
    assert run["train_window"][1] <= run["validate_window"][0]


# ═══════════════════════════════════════════ دروازه‌ها
def test_challenger_beats_the_product_median_champion(trained):
    run = trained["run"]
    metrics = run["metrics"]
    assert run["status"] == ModelRun.STATUS_VALIDATED, run["blocked_reason_fa"]
    assert run["label_basis"] == LABEL_BASIS
    assert metrics["value_basis"] == "revenue" and "درآمد" in metrics["value_basis_note_fa"]
    assert "topk_captured_revenue_rial" in metrics and "topk_captured_gross_profit_rial" not in metrics
    assert metrics["topk_advantage_lower_rial"] > 0
    assert metrics["topk_lift_bp"] is None or metrics["topk_lift_bp"] >= 200
    assert metrics["topk_captured_revenue_rial"] > metrics["baseline_topk_captured_revenue_rial"]
    assert "baseline_by_offset_topk_captured_revenue_rial" in metrics
    assert metrics["brier"] < metrics["brier_baseline"]
    assert set(metrics["gates"]) == {"beats_baseline_brier", "beats_baseline_topk", "discriminates", "calibrated"}
    assert all(metrics["gates"].values())
    assert metrics["bin_spread"] >= 0.15
    assert metrics["topk_hit_precision"] > metrics["baseline_topk_hit_precision"]
    assert "±25" in metrics["label_window_fa"]
    assert metrics["coverage"]["pair_snapshots_covered"] >= 500
    assert isinstance(metrics["info_30d_hit_precision"], float)
    # مدل خودش JSON است، نه ضرایبِ خطی
    with session_scope(trained["db"]) as session:
        row = session.get(ModelRun, run["id"])
        table = json.loads(row.coefficients_json)
    assert table["kind"] == "replenish_rule_v1" and table["window_fraction"] == 0.25
    assert any(cell[0] is not None and cell[1] >= 20 for cell in table["cells"])


def test_cost_covered_data_switches_the_metric_to_gross_profit(tmp_path):
    db = tmp_path / "app.db"
    _ingest(db, generate_replenishment_sales(with_cost=True))
    run = train_model("replenish", db_path=db)
    metrics = run["metrics"]
    assert metrics["value_basis"] == "gross_profit"
    assert "topk_captured_gross_profit_rial" in metrics and "سود" in metrics["value_basis_note_fa"]


def test_thin_data_is_refused_with_numbers(tmp_path):
    db = tmp_path / "app.db"
    _ingest(db, generate_replenishment_sales(days=120, n_customers=20))
    run = train_model("replenish", db_path=db)
    assert run["status"] == ModelRun.STATUS_INSUFFICIENT
    assert run["blocked_reason_code"] in ("span_too_short", "too_few_snapshots", "too_few_pairs", "too_few_positives")
    requirements = {r["code"]: r for r in run["metrics"]["requirements"]}
    assert requirements[run["blocked_reason_code"]]["available"] < requirements[run["blocked_reason_code"]]["required"]
    assert "لازم" in run["blocked_reason_fa"]


def test_champion_score_is_unclaimed_outside_its_near_window(trained):
    table = build_pair_period(_lines(trained["db"]), ReplenishSpec())
    unclaimed = table[table["champion_score"] == CHAMPION_UNCLAIMED]
    claimed = table[table["champion_score"] > CHAMPION_UNCLAIMED]
    assert len(unclaimed) and len(claimed)
    assert (claimed["champion_score"] == -claimed["champion_offset_score"]).all(), "سررسیدِ پیشِ رو اول"
    assert (unclaimed["champion_offset_score"] == CHAMPION_UNCLAIMED).all()
    assert (claimed["champion_offset_score"] >= -0.2 * 400).all()


def test_a_trivial_challenger_cannot_pass_the_gates(trained):
    """مدعی‌ای که فقط «نرخِ پایه» را می‌گوید (بی‌مهارت) از کفِ مهارت رد می‌شود."""
    import numpy as np

    from mktcore.ml.linear_fit import chronological_cut
    from mktcore.ml.replenish import evaluate_replenish

    spec = ReplenishSpec()
    full = build_pair_period(_lines(trained["db"]), spec)
    table = full[full["future_covered"]]
    split = chronological_cut(table["as_of"], spec.train_fraction)
    train, validate = table[table["as_of"] < split], table[table["as_of"] >= split]
    prevalence = float(train["label"].mean())
    trivial = evaluate_replenish(
        validate, np.full(len(validate), prevalence), spec=spec, train=train, value_basis="revenue",
    )
    assert trivial["passed"] is False
    assert trivial["gates"]["discriminates"] is False, "پیش‌بینیِ ثابت یک بین دارد و تفکیک نمی‌کند"


# ═══════════════════════════════════════════ رجیستری: promote/rollback، بدون score_job
def test_promote_accepts_the_rule_model_and_rollback_works_and_customers_stay_null(trained):
    db, run = trained["db"], trained["run"]
    raw = generate_replenishment_sales(days=200, n_customers=40)
    mapper = SchemaMapper()
    clean = clean_frame(mapper.apply(raw, mapper.auto_detect(raw).mapping))
    write_customer_features(clean, run_analysis(clean, horizon=2, with_forecast=False), db_path=db)

    promoted = promote_run(run["id"], db_path=db, actor="آزمون")
    assert promoted["status"] == ModelRun.STATUS_PROMOTED
    with session_scope(db) as session:
        business_id = resolve_business_id(session, "default")
        active = promoted_due_table(session, business_id)
        assert active is not None and active[1]["kind"] == "replenish_rule_v1"
        assert promoted_run(session, business_id, "replenish").id == run["id"]
        assert all(
            f.replenish_probability_bp is None
            for f in session.scalars(select(CustomerFeature)).all()
        ), "قاعده از score_job نمی‌گذرد؛ ستونِ گرینِ مشتری NULL می‌ماند"
    # بازگشت یعنی فعال‌کردنِ نسخه‌ی قبلی؛ برای نخستین نسخه صریحاً رد می‌شود و فعال می‌ماند
    with pytest.raises(LookupError, match="نخستین"):
        rollback_run(run["id"], db_path=db, actor="آزمون")
    with session_scope(db) as session:
        assert promoted_due_table(session, resolve_business_id(session, "default")) is not None
