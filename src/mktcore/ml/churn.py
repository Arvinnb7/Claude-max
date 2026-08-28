"""ریسک ریزش به‌صورت **مدلِ خطرِ گسسته** — §۱۶.۳ و §۱۳.۵.

## چرا این شکل

§۱۶.۳ «a calibrated tabular model or survival model» با holdout زمانی می‌خواهد،
و §۱۳.۵ مدلی که «censoring را مدیریت کند». مدلِ خطرِ گسسته هر دو را می‌دهد بدون
هیچ وابستگیِ تازه: جدولِ «مشتری × دوره» ساخته می‌شود و روی آن لجستیک برازش
می‌شود. دوره‌ای که پنجره‌ی نتیجه‌اش هنوز تمام نشده **حذف** می‌شود — همان کاری
که تحلیل بقا با داده‌ی سانسورشده می‌کند.

`lifelines` نصب نیست و افزودنش برای همین یک مدل، وابستگیِ تازه‌ای می‌آورد که
همان کار را می‌کند.

## قهرمانِ فعلی که باید برده شود

`next_purchase.alive_probability` — دامپینگِ هندسیِ π=۰٫۸۵ روی «چند برابرِ
آهنگِ خودش گذشته». این حدسِ بدی نیست؛ برای همین همان خطِ پایه است. مدلِ تازه
تا وقتی این را نبرد **فعال نمی‌شود** و رفتار سیستم دقیقاً همان می‌ماند که بود.

## سنجه‌ی اقتصادی

فقط Brier کافی نیست: مدلی که ریزشِ مشتریانِ کم‌ارزش را خوب پیش‌بینی کند ولی
پرارزش‌ها را از دست بدهد، از نظر آماری خوب و از نظر کسب‌وکاری بی‌فایده است. پس
سنجه‌ی K تای اول، **سودِ در معرض خطر** است: سودِ ۳۶۵ روزِ گذشته‌ی کسانی که
واقعاً ریزش کردند و مدل بالای فهرست گذاشتشان.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, replace
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from mktcore.db.engine import session_scope
from mktcore.db.lookup import resolve_business_id
from mktcore.db.migrations import ensure_schema
from mktcore.db.models import ModelRun
from mktcore.features.ledger_frame import load_line_frame
from mktcore.features.point_in_time import (
    PIT_SCHEMA_VERSION,
    PointInTimeSpec,
    compute_point_in_time_features,
)
from mktcore.ml.linear_fit import (
    FitConfig,
    bootstrap_advantage,
    captured,
    chronological_cut,
    drift_baseline,
    explain_coefficients,
    fit_calibrated_linear,
    reliability_bins,
)
from mktcore.ml.registry import compute_data_hash, record_run
from mktcore.ml.train import register_trainer

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger("mktcore.ml.churn")

MODEL_KEY = "churn"

# ویژگی‌هایی که در جدولِ دوره‌ای معنا ندارند یا مستقیماً برچسب را لو می‌دهند
_EXCLUDED = ("tenure_days",)


@dataclass(frozen=True)
class ChurnSpec:
    """پیکربندی. همه‌ی اعداد ثبت می‌شوند تا اجرا بازتولیدپذیر بماند."""

    # فاصله‌ی عکس‌های زمانی. کوچک‌تر یعنی داده‌ی بیشتر و اجرای کندتر؛ ۶۰ روز
    # تعادلِ عمدیِ این نصب است.
    period_days: int = 60
    # «ریزش» یعنی در این افق هیچ خریدی نکرده — نه یک عددِ تقویمیِ ثابت مثل ۹۰
    # روز برای همه (§۱۶.۱)، چون ویژگی‌های مدل آهنگِ شخصیِ مشتری را می‌بینند.
    horizon_days: int = 90
    max_snapshots: int = 12
    value_window_days: int = 365
    train_fraction: float = 0.70
    calibration_fraction: float = 0.30
    top_fraction: float = 0.10
    min_rows: int = 500
    min_positive_per_arm: int = 50
    min_topk_lift_bp: int = 200
    max_calibration_bin_error: float = 0.15
    bootstrap_samples: int = 400
    bootstrap_quantile: float = 0.05
    l2_c: float = 1.0

    def with_params(self, params: dict[str, Any] | None) -> ChurnSpec:
        if not params:
            return self
        known = {k: v for k, v in params.items() if k in asdict(self)}
        return replace(self, **known)


def snapshot_dates(lines: pd.DataFrame, spec: ChurnSpec) -> list[str]:
    """تاریخ‌هایی که در آن‌ها «آن‌موقع چه می‌دانستیم» بازسازی می‌شود.

    از انتها به عقب ساخته می‌شود و آخرین تاریخِ ممکن `data_max − horizon` است:
    دوره‌ای که پنجره‌ی نتیجه‌اش تمام نشده، برچسبِ مطمئن ندارد.
    """
    if lines.empty:
        return []
    data_min = pd.Timestamp(lines["line_date"].min())
    latest = pd.Timestamp(lines["line_date"].max()) - pd.Timedelta(days=spec.horizon_days)
    out: list[pd.Timestamp] = []
    cursor = latest
    while len(out) < spec.max_snapshots and cursor > data_min:
        out.append(cursor)
        cursor -= pd.Timedelta(days=spec.period_days)
    return [stamp.date().isoformat() for stamp in sorted(out)]


def build_person_period(lines: pd.DataFrame, spec: ChurnSpec) -> pd.DataFrame:
    """جدولِ «مشتری × دوره» با ویژگیِ نقطه‌ی زمانی و برچسبِ ریزش."""
    frames: list[pd.DataFrame] = []
    for as_of in snapshot_dates(lines, spec):
        past = lines[lines["line_date"] < as_of]
        if past.empty:
            continue
        features = compute_point_in_time_features(past, PointInTimeSpec(as_of=as_of))
        if features.empty:
            continue

        horizon_end = (
            pd.Timestamp(as_of) + pd.Timedelta(days=spec.horizon_days)
        ).date().isoformat()
        window = lines[(lines["line_date"] >= as_of) & (lines["line_date"] < horizon_end)]
        buyers = set(window["customer_id"].unique())

        value_start = (
            pd.Timestamp(as_of) - pd.Timedelta(days=spec.value_window_days)
        ).date().isoformat()
        recent = past[past["line_date"] >= value_start]
        at_risk = (
            recent.groupby("customer_id")["gross_profit_rial"].sum()
            if not recent.empty else pd.Series(dtype=float)
        )

        block = features.copy()
        block["as_of"] = as_of
        block["label"] = [
            0 if customer_id in buyers else 1 for customer_id in block.index
        ]
        block["at_risk_profit_rial"] = (
            at_risk.reindex(block.index).fillna(0.0).astype(float)
        )
        block["baseline_score"] = _baseline_churn_score(block)
        frames.append(block.reset_index())

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _baseline_churn_score(features: pd.DataFrame) -> pd.Series:
    """قهرمانِ فعلی: ۱ − احتمالِ زنده‌بودنِ هندسی.

    عمداً همان تابعِ تولیدی صدا زده می‌شود، نه بازنویسی‌اش: اگر خطِ پایه
    نسخه‌ی دیگری از فرمول باشد، مقایسه بی‌معنا می‌شود.
    """
    from mktcore.analysis.next_purchase import alive_probability

    gap = features["median_gap_days"].astype(float)
    fallback = float(gap.median()) if gap.notna().any() else 60.0
    mu = gap.fillna(fallback).clip(lower=1.0).to_numpy(dtype=float)
    elapsed = features["recency_days"].astype(float).fillna(0.0).to_numpy(dtype=float)
    return pd.Series(
        1.0 - alive_probability(elapsed, mu), index=features.index, dtype=float,
    )


def feature_columns(frame: pd.DataFrame) -> list[str]:
    reserved = {
        "customer_id", "as_of", "label", "at_risk_profit_rial", "baseline_score",
    }
    return [
        name for name in frame.columns
        if name not in reserved and name not in _EXCLUDED
    ]


def evaluate_churn(
    validate: pd.DataFrame, predicted: np.ndarray, *, spec: ChurnSpec,
    bins: list[dict], train: pd.DataFrame,
) -> dict:
    """سه شرطِ promote — با سنجه‌ی اقتصادیِ «سودِ در معرض خطر»."""
    import math

    labels = validate["label"].to_numpy(dtype=int)
    baseline_score = validate["baseline_score"].to_numpy(dtype=float)
    # ارزشی که مدل باید «بگیرد»: سودِ گذشته‌ی کسانی که واقعاً ریزش کردند.
    value = (
        validate["at_risk_profit_rial"].to_numpy(dtype=float) * labels.astype(float)
    )

    brier = float(np.mean((predicted - labels) ** 2)) if len(labels) else None
    baseline_brier = (
        float(np.mean((np.clip(baseline_score, 0.0, 1.0) - labels) ** 2))
        if len(labels) else None
    )

    top_k = max(1, math.ceil(spec.top_fraction * len(validate)))
    model_top = captured(value, predicted, top_k)
    baseline_top = captured(value, baseline_score, top_k)
    lift_bp = (
        int(round((model_top / baseline_top - 1.0) * 10_000)) if baseline_top > 0 else None
    )
    lower_bound = bootstrap_advantage(
        value, predicted, baseline_score, top_fraction=spec.top_fraction,
        samples=spec.bootstrap_samples, quantile=spec.bootstrap_quantile,
    )
    max_bin_error = max((abs(b["خطا"]) for b in bins if b["تعداد"] >= 20), default=0.0)

    beats_brier = bool(
        brier is not None and baseline_brier is not None and brier < baseline_brier
    )
    beats_topk = bool(
        lift_bp is not None
        and lift_bp >= spec.min_topk_lift_bp
        and lower_bound is not None
        and lower_bound > 0
    )
    calibrated = bool(max_bin_error <= spec.max_calibration_bin_error)

    return {
        "n_train": int(len(train)),
        "n_validate": int(len(validate)),
        "n_validate_positives": int(labels.sum()),
        "churn_rate": round(float(labels.mean()), 4) if len(labels) else None,
        "brier": None if brier is None else round(brier, 5),
        "brier_baseline": None if baseline_brier is None else round(baseline_brier, 5),
        "baseline_name_fa": "دامپینگ هندسیِ فعلی (π=۰٫۸۵)",
        "top_k": top_k,
        "topk_captured_at_risk_profit_rial": int(round(model_top)),
        "baseline_topk_captured_at_risk_profit_rial": int(round(baseline_top)),
        "topk_lift_bp": lift_bp,
        "topk_advantage_lower_rial": None if lower_bound is None else int(round(lower_bound)),
        "max_calibration_bin_error": round(float(max_bin_error), 4),
        "reliability_bins": bins,
        "gates": {
            "beats_baseline_brier": beats_brier,
            "beats_baseline_topk": beats_topk,
            "calibrated": calibrated,
        },
        "passed": bool(beats_brier and beats_topk and calibrated),
    }


def train_churn(
    *,
    business_slug: str = "default",
    params: dict[str, Any] | None = None,
    db_path: Path | None = None,
) -> dict:
    """آموزشِ مدلِ خطرِ گسسته و ثبتش در رجیستری."""
    ensure_schema(db_path)
    spec = ChurnSpec().with_params(params)

    with session_scope(db_path) as session:
        business_id = resolve_business_id(session, business_slug)
        if business_id is None:
            raise ValueError("کسب‌وکاری ثبت نشده است؛ اول یک فایل فروش تحلیل کنید.")
        lines = load_line_frame(session, business_id)

    profit = lines["gross_profit_rial"] if not lines.empty else pd.Series(dtype=float)
    common = {
        "business_slug": business_slug,
        "model_key": MODEL_KEY,
        "db_path": db_path,
        "model_kind": "hazard_logit",
        "feature_schema_version": PIT_SCHEMA_VERSION,
        "params_json": asdict(spec),
        "label_basis": "no_purchase_in_horizon",
        "data_hash": compute_data_hash(
            business_id=business_id, model_key=MODEL_KEY,
            train_start=str(lines["line_date"].min()) if not lines.empty else None,
            train_end=str(lines["line_date"].max()) if not lines.empty else None,
            n_lines=int(len(lines)),
            sum_revenue_rial=int(lines["revenue_rial"].sum()) if not lines.empty else 0,
            sum_gross_profit_rial=(
                None if lines.empty or profit.isna().any() else int(profit.sum())
            ),
        ),
    }

    table = build_person_period(lines, spec)
    if len(table) < spec.min_rows:
        return record_run(
            status=ModelRun.STATUS_INSUFFICIENT,
            blocked_reason_code="too_few_periods",
            blocked_reason_fa=(
                f"فقط {len(table)} ردیفِ «مشتری × دوره» ساخته شد؛ دست‌کم "
                f"{spec.min_rows} ردیف لازم است تا مدلِ خطر معنا داشته باشد."
            ),
            metrics_json={"n_rows": int(len(table))},
            note_fa="مدلی ساخته نشد؛ ریسک ریزش دقیقاً مثل قبل محاسبه می‌شود.",
            **common,
        )

    split_date = chronological_cut(table["as_of"], spec.train_fraction)
    train = table[table["as_of"] < split_date]
    validate = table[table["as_of"] >= split_date]
    positives = min(int(train["label"].sum()), int(validate["label"].sum()))
    if train.empty or validate.empty or positives < spec.min_positive_per_arm:
        return record_run(
            status=ModelRun.STATUS_INSUFFICIENT,
            blocked_reason_code="too_few_positives",
            blocked_reason_fa=(
                f"کمینه‌ی نمونه‌ی مثبت در دو بازو {positives} است؛ زیر حداقلِ "
                f"{spec.min_positive_per_arm}."
            ),
            metrics_json={"n_rows": int(len(table)), "positives": positives},
            note_fa="مدلی ساخته نشد؛ ریسک ریزش دقیقاً مثل قبل محاسبه می‌شود.",
            **common,
        )

    columns = feature_columns(table)
    fitted = fit_calibrated_linear(
        train, validate, columns=columns, label_col="label", order_col="as_of",
        config=FitConfig(
            calibration_fraction=spec.calibration_fraction, l2_c=spec.l2_c,
        ),
    )
    bins = reliability_bins(fitted.predicted, validate["label"].to_numpy(dtype=int))
    metrics = evaluate_churn(
        validate, fitted.predicted, spec=spec, bins=bins, train=train,
    )
    metrics["explanation_fa"] = explain_coefficients(fitted.coefficients)
    metrics["snapshots"] = sorted(table["as_of"].unique().tolist())

    status = ModelRun.STATUS_VALIDATED if metrics["passed"] else ModelRun.STATUS_REJECTED
    return record_run(
        status=status,
        train_start=str(train["as_of"].min()), train_end=str(train["as_of"].max()),
        validate_start=str(validate["as_of"].min()),
        validate_end=str(validate["as_of"].max()),
        n_train=int(len(train)), n_validate=int(len(validate)),
        n_train_positives=int(train["label"].sum()),
        n_validate_positives=int(validate["label"].sum()),
        feature_schema_json=columns,
        metrics_json=metrics,
        calibration_json={**fitted.calibration, "reliability_bins": bins},
        coefficients_json=fitted.coefficients,
        drift_baseline_json=drift_baseline(
            train, columns, train["label"].to_numpy(dtype=int),
        ),
        blocked_reason_code=None if metrics["passed"] else "did_not_beat_baseline",
        blocked_reason_fa=None if metrics["passed"] else _rejection_reason(metrics, spec),
        note_fa=(
            "این مدل قهرمانِ فعلی را برد و آماده‌ی فعال‌سازی است."
            if metrics["passed"] else
            "این مدل فعال نمی‌شود؛ ریسک ریزش دقیقاً مثل قبل محاسبه می‌شود."
        ),
        **common,
    )


def _rejection_reason(metrics: dict, spec: ChurnSpec) -> str:
    gates = metrics["gates"]
    parts: list[str] = []
    if not gates["beats_baseline_brier"]:
        parts.append(
            f"دقتش از دامپینگ هندسیِ فعلی بهتر نشد (Brier {metrics['brier']} در "
            f"برابر {metrics['brier_baseline']})"
        )
    if not gates["beats_baseline_topk"]:
        parts.append(
            "سودِ در معرض خطرِ K تای اول از خط پایه جلو نزد یا اختلافش آماری "
            f"واقعی نبود (حداقل {spec.min_topk_lift_bp / 100:.1f}٪)"
        )
    if not gates["calibrated"]:
        parts.append(
            f"کالیبراسیون خارج از تلرانس است ({metrics['max_calibration_bin_error']})"
        )
    return "؛ ".join(parts) + "."


def score_churn_customers(
    *, business_slug: str = "default", db_path: Path | None = None,
) -> dict:
    """نوشتنِ احتمالِ ریزشِ **مدل** روی عکس ویژگی.

    ستونِ `p_alive_bp` دست‌نخورده می‌ماند: آن عددِ قهرمانِ فعلی است و همه‌ی
    مصرف‌کننده‌هایش (حالت «ازدست‌رفته»، فهرست اقدام، UI) باید همان را ببینند.
    عددِ مدل کنارش می‌نشیند، نه جایش.
    """
    from mktcore.ml.score_job import write_customer_scores

    return write_customer_scores(
        model_key=MODEL_KEY,
        probability_column="churn_probability_bp",
        run_column="churn_model_run_id",
        business_slug=business_slug,
        db_path=db_path,
    )


register_trainer(MODEL_KEY, train_churn)

__all__ = [
    "MODEL_KEY",
    "ChurnSpec",
    "build_person_period",
    "evaluate_churn",
    "feature_columns",
    "score_churn_customers",
    "snapshot_dates",
    "train_churn",
]
