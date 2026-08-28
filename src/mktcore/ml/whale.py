"""تشخیص «نهنگ آینده» — §۱۸ سند.

## برچسب

```
لنگر(c)   = نخستین خرید(c) + observation_days
ویژگی(c)  = فقط پنجره‌ی [نخستین خرید ، لنگر)
برچسب(c)  = ۱ اگر سودِ ناخالصِ محقق‌شده در [لنگر ، لنگر+outcome_days)
            در صدکِ بالای **سه‌ماهه‌ی لنگرِ خودش** باشد
```

چهار قاعده که این را از «تقریبِ §۱۸.۲» به خودِ §۱۸.۲ تبدیل می‌کند:

1. سود/درآمدِ **داخل** پنجره‌ی مشاهده فقط ویژگی است، هرگز برچسب. §۱۸.۲ صریحاً
   «historical revenue measured inside the prediction window» را رد می‌کند.
2. مبنا **سود ناخالص** است. هیچ بازگشتی به درآمد وجود ندارد؛ نبودِ بها یعنی
   آموزش انجام نمی‌شود، نه اینکه عددِ درآمدی جای عددِ سودی بنشیند.
3. صدک **درونِ سه‌ماهه‌ی لنگر** گرفته می‌شود. با صدکِ سراسری، «نهنگ» عملاً یعنی
   «کسی که در فصلِ خوبی جذب شده» و مدل به‌جای رفتار، تقویم را یاد می‌گیرد.
4. مشتریِ سانسورشده **حذف** می‌شود، نه اینکه صفر برچسب بخورد. برچسب‌زدنِ صفر به
   کسی که هنوز فرصتش تمام نشده، هر مشتری تازه‌ای را خودبه‌خود ناموفق می‌کند —
   کلاسیک‌ترین باگِ خاموشِ این نوع مدل.

## خطِ پایه‌ای که باید برده شود

`سودِ پنجره‌ی مشاهده ÷ طول پنجره` — یعنی «هرکس در ۹۰ روز اول پرسودتر بوده،
نهنگِ آینده است». این همان کاری است که یک آدمِ باتجربه می‌کند و عمداً سخت
انتخاب شده: خطِ پایه‌ی ضعیف، دروازه‌ی §۲۹.۳ را بی‌معنا می‌کند.
"""

from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass, replace
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from mktcore.db.engine import session_scope
from mktcore.db.lookup import resolve_business_id
from mktcore.db.migrations import ensure_schema
from mktcore.db.models import ModelRun
from mktcore.features.cohorts import (
    CohortMaturity,
    MaturitySpec,
    assess_cohort_maturity,
    chronological_split,
    mature_anchors,
)
from mktcore.features.ledger_frame import load_line_frame
from mktcore.features.point_in_time import (
    PIT_FEATURE_SCHEMA,
    PIT_SCHEMA_VERSION,
    PointInTimeSpec,
    compute_outcome_window,
    compute_point_in_time_features,
)
from mktcore.ml.linear_fit import (
    FitConfig,
    bootstrap_advantage,
    captured,
    drift_baseline,
    explain_coefficients,
    fit_calibrated_linear,
    reliability_bins,
)
from mktcore.ml.registry import compute_data_hash, record_run
from mktcore.ml.train import register_trainer

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger("mktcore.ml.whale")

MODEL_KEY = "whale"
LABEL_BASIS_PROFIT = "gross_profit"

# ویژگی‌هایی که در پنجره‌ی مشاهده ثابت‌اند و چیزی یاد نمی‌دهند
_EXCLUDED_FEATURES = ("tenure_days",)
# بین‌های اتکا — همان مرزهایی که `analysis/probability_eval.py` دارد
_RELIABILITY_BINS = (0.0, 0.1, 0.3, 0.5, 0.7, 1.0001)


@dataclass(frozen=True)
class WhaleSpec:
    """پیکربندی کاملِ آموزش. همه‌چیز اینجاست تا در `params_json` ثبت شود."""

    observation_days: int = 90
    outcome_days: int = 365
    top_fraction: float = 0.10
    # سهمی از دوره‌ی آموزش که برای کالیبراسیون کنار گذاشته می‌شود — **زمانی**،
    # نه تصادفی: K-fold تصادفی §۲۹.۱ را نقض می‌کند.
    calibration_fraction: float = 0.30
    train_fraction: float = 0.70
    # دو شرط برای «materially» در §۲۹.۳:
    # ۱) کفِ مادی — بهبودِ کوچک‌تر از این ارزشِ جابه‌جا کردنِ رفتار سیستم را ندارد.
    # ۲) شرطِ آماری (پایین‌ترین صدکِ بوت‌استرپ > ۰) — همان قاعده‌ای که کمپین‌ها
    #    دارند: عددی که بازه‌اش صفر را در بر بگیرد، اثباتِ چیزی نیست.
    min_topk_lift_bp: int = 200
    bootstrap_samples: int = 400
    bootstrap_quantile: float = 0.05
    max_calibration_bin_error: float = 0.15
    # زیر این اندازه، کالیبراسیونِ سیگموئید (دو پارامتر) به isotonic ترجیح دارد
    isotonic_min_rows: int = 1_000
    isotonic_min_positives: int = 100
    min_cohort_months: int = 6
    min_cohort_customers: int = 200
    min_positive_per_arm: int = 30
    l2_c: float = 1.0

    @property
    def maturity(self) -> MaturitySpec:
        return MaturitySpec(
            observation_days=self.observation_days,
            outcome_days=self.outcome_days,
            top_fraction=self.top_fraction,
            min_cohort_months=self.min_cohort_months,
            min_cohort_customers=self.min_cohort_customers,
            min_positive_per_arm=self.min_positive_per_arm,
            train_fraction=self.train_fraction,
        )

    def with_params(self, params: dict[str, Any] | None) -> WhaleSpec:
        if not params:
            return self
        known = {k: v for k, v in params.items() if k in asdict(self)}
        return replace(self, **known)


@dataclass(frozen=True)
class TrainingTable:
    frame: pd.DataFrame          # ویژگی + برچسب + لنگر
    maturity: CohortMaturity
    split_date: str | None
    data_min: str
    data_max: str
    cost_coverage: float
    n_lines: int
    sum_revenue_rial: int
    sum_gross_profit_rial: int | None


# ───────────────────────────────────────────────── ساخت جدول آموزش
def cost_coverage_of(lines: pd.DataFrame) -> float:
    if lines.empty:
        return 0.0
    return float(lines["gross_profit_rial"].notna().mean())


def whale_labels(
    future_profit: pd.Series, anchors: pd.Series, *, top_fraction: float,
) -> pd.Series:
    """برچسب: صدکِ بالای سودِ آینده، **درون سه‌ماهه‌ی لنگر**."""
    buckets = pd.to_datetime(anchors.reindex(future_profit.index)).dt.to_period("Q")
    labels = pd.Series(0, index=future_profit.index, dtype=int)
    for _bucket, group in future_profit.groupby(buckets):
        if len(group) < 10:
            # سه‌ماهه‌ی کم‌جمعیت صدکِ بی‌معنا می‌دهد؛ به سطلِ سراسری واگذار می‌شود
            continue
        threshold = float(group.quantile(1.0 - top_fraction))
        labels.loc[group.index] = (group > threshold).astype(int)
    small = labels.index.difference(
        future_profit.groupby(buckets).filter(lambda g: len(g) >= 10).index
    )
    if len(small):
        threshold = float(future_profit.quantile(1.0 - top_fraction))
        labels.loc[small] = (future_profit.loc[small] > threshold).astype(int)
    return labels


def build_training_table(
    lines: pd.DataFrame, *, spec: WhaleSpec,
) -> TrainingTable:
    """ویژگی‌های پنجره‌ی اولیه + برچسبِ سودِ آینده، برای مشتریانِ بالغ."""
    data_min = str(lines["line_date"].min()) if not lines.empty else ""
    data_max = str(lines["line_date"].max()) if not lines.empty else ""
    coverage = cost_coverage_of(lines)
    totals = _totals(lines)

    first_dates = (
        lines.groupby("customer_id")["line_date"].min() if not lines.empty
        else pd.Series(dtype=object)
    )
    maturity = assess_cohort_maturity(
        first_dates, data_min=data_min or "1900-01-01", data_max=data_max or "1900-01-01",
        cost_coverage=coverage, spec=spec.maturity,
    )
    empty = TrainingTable(
        frame=pd.DataFrame(), maturity=maturity, split_date=maturity.split_date,
        data_min=data_min, data_max=data_max, cost_coverage=coverage, **totals,
    )
    if not maturity.ok:
        return empty

    anchors = mature_anchors(first_dates, data_max=data_max, spec=spec.maturity)
    exclusive_end = _day_after(data_max)
    features = compute_point_in_time_features(
        lines[lines["line_date"] < exclusive_end],
        PointInTimeSpec(
            as_of=exclusive_end, observation_days=spec.observation_days,
            require_complete_window=True,
        ),
    )
    outcome = compute_outcome_window(lines, starts=anchors, days=spec.outcome_days)

    frame = features.join(outcome, how="inner")
    # سودِ نامعلوم = برچسبِ نامعلوم. حذف می‌شود، نه صفر.
    frame = frame[frame["future_covered"].astype(bool)]
    frame = frame[frame["future_gross_profit_rial"].notna()]
    if frame.empty:
        return empty

    frame["anchor"] = anchors.reindex(frame.index)
    frame["label"] = whale_labels(
        frame["future_gross_profit_rial"], frame["anchor"],
        top_fraction=spec.top_fraction,
    )
    frame["baseline_score"] = (
        frame["gross_profit_rial"].fillna(0.0) / max(spec.observation_days, 1)
    )
    split_date = chronological_split(frame["anchor"], spec.maturity)
    return TrainingTable(
        frame=frame, maturity=maturity, split_date=split_date,
        data_min=data_min, data_max=data_max, cost_coverage=coverage, **totals,
    )


def _totals(lines: pd.DataFrame) -> dict:
    if lines.empty:
        return {"n_lines": 0, "sum_revenue_rial": 0, "sum_gross_profit_rial": None}
    profit = lines["gross_profit_rial"]
    return {
        "n_lines": int(len(lines)),
        "sum_revenue_rial": int(lines["revenue_rial"].sum()),
        "sum_gross_profit_rial": (
            None if profit.isna().any() else int(profit.sum())
        ),
    }


def _day_after(day: str) -> str:
    return (pd.Timestamp(day) + pd.Timedelta(days=1)).date().isoformat()


def feature_columns() -> list[str]:
    return [name for name in PIT_FEATURE_SCHEMA if name not in _EXCLUDED_FEATURES]


# ───────────────────────────────────────────────── برازش و اعتبارسنجی
def fit_whale(table: TrainingTable, spec: WhaleSpec) -> dict[str, Any]:
    """برازش + سنجش در برابر دو خطِ پایه.

    خودِ برازش در `ml/linear_fit.py` است تا قواعدی که سخت درست شدند (برشِ زمانیِ
    کالیبراسیون، پرچمِ «نامعلوم»، انتخابِ سیگموئید در نمونه‌ی کم) در هر مدلِ
    تازه دوباره نوشته نشوند.
    """
    frame, split_date = table.frame, table.split_date
    train = frame[frame["anchor"] < split_date]
    validate = frame[frame["anchor"] >= split_date]
    columns = feature_columns()

    fitted = fit_calibrated_linear(
        train, validate,
        columns=columns, label_col="label", order_col="anchor",
        config=FitConfig(
            calibration_fraction=spec.calibration_fraction,
            l2_c=spec.l2_c,
            isotonic_min_rows=spec.isotonic_min_rows,
            isotonic_min_positives=spec.isotonic_min_positives,
        ),
    )
    predicted = fitted.predicted
    bins = reliability_bins(predicted, validate["label"].to_numpy(dtype=int))
    calibration = {**fitted.calibration, "reliability_bins": bins}

    metrics = evaluate_whale(validate, predicted, spec=spec, bins=bins, train=train)
    metrics["n_fit_rows"] = fitted.n_fit
    metrics["n_calibration_rows"] = fitted.n_calibration
    return {
        "coefficients": fitted.coefficients,
        "calibration": calibration,
        "metrics": metrics,
        "train": train,
        "validate": validate,
        "drift_baseline": drift_baseline(
            train, columns, train["label"].to_numpy(dtype=int),
        ),
        "explanation_fa": explain_coefficients(fitted.coefficients),
    }


def evaluate_whale(
    validate: pd.DataFrame,
    predicted: np.ndarray,
    *,
    spec: WhaleSpec,
    bins: list[dict],
    train: pd.DataFrame,
) -> dict:
    """سه شرطِ promote — و اعدادی که هر سه را قابل بازبینی می‌کنند."""
    labels = validate["label"].to_numpy(dtype=int)
    prevalence = float(train["label"].mean()) if len(train) else 0.0

    brier = float(np.mean((predicted - labels) ** 2)) if len(labels) else None
    brier_baseline = (
        float(np.mean((np.full(len(labels), prevalence) - labels) ** 2))
        if len(labels) else None
    )

    top_k = max(1, math.ceil(spec.top_fraction * len(validate)))
    profit = validate["future_gross_profit_rial"].to_numpy(dtype=float)
    model_top = captured(profit, predicted, top_k)
    baseline_top = captured(
        profit, validate["baseline_score"].to_numpy(dtype=float), top_k,
    )
    perfect_top = float(np.sort(profit)[::-1][:top_k].sum())

    lift_bp = (
        int(round((model_top / baseline_top - 1.0) * 10_000))
        if baseline_top > 0 else None
    )
    max_bin_error = max((abs(b["خطا"]) for b in bins if b["تعداد"] >= 20), default=0.0)
    lower_bound = bootstrap_advantage(
        profit, predicted, validate["baseline_score"].to_numpy(dtype=float),
        top_fraction=spec.top_fraction, samples=spec.bootstrap_samples,
        quantile=spec.bootstrap_quantile,
    )

    beats_brier = bool(brier is not None and brier_baseline is not None and brier < brier_baseline)
    # دو شرط، نه یکی: هم بهبود باید **مادی** باشد، هم **آماری واقعی**. عددی که
    # بازه‌اش صفر را در بر بگیرد، همان نوفه‌ای است که کمپین‌ها هم رد می‌کنند.
    beats_topk = bool(
        lift_bp is not None
        and lift_bp >= spec.min_topk_lift_bp
        and lower_bound is not None
        and lower_bound > 0
    )
    calibrated = bool(max_bin_error <= spec.max_calibration_bin_error)

    return {
        "n_validate": int(len(validate)),
        "n_validate_positives": int(labels.sum()),
        "prevalence": round(prevalence, 4),
        "brier": None if brier is None else round(brier, 5),
        "brier_baseline": None if brier_baseline is None else round(brier_baseline, 5),
        "top_k": top_k,
        "topk_captured_gross_profit_rial": int(round(model_top)),
        "baseline_topk_captured_gross_profit_rial": int(round(baseline_top)),
        "perfect_topk_captured_gross_profit_rial": int(round(perfect_top)),
        "topk_lift_bp": lift_bp,
        "topk_advantage_lower_rial": (
            None if lower_bound is None else int(round(lower_bound))
        ),
        "max_calibration_bin_error": round(float(max_bin_error), 4),
        "reliability_bins": bins,
        "gates": {
            "beats_prevalence_brier": beats_brier,
            "beats_baseline_topk": beats_topk,
            "calibrated": calibrated,
        },
        "passed": bool(beats_brier and beats_topk and calibrated),
    }











# ───────────────────────────────────────────────── آموزش‌دهنده
def train_whale(
    *,
    business_slug: str = "default",
    params: dict[str, Any] | None = None,
    db_path: Path | None = None,
) -> dict:
    """آموزشِ کامل: دروازه → جدول → برازش → اعتبارسنجی → ثبت در رجیستری."""
    ensure_schema(db_path)
    spec = WhaleSpec().with_params(params)

    with session_scope(db_path) as session:
        business_id = resolve_business_id(session, business_slug)
        if business_id is None:
            raise ValueError("کسب‌وکاری ثبت نشده است؛ اول یک فایل فروش تحلیل کنید.")
        lines = load_line_frame(session, business_id)

    table = build_training_table(lines, spec=spec)
    common = {
        "business_slug": business_slug,
        "model_key": MODEL_KEY,
        "db_path": db_path,
        "feature_schema_version": PIT_SCHEMA_VERSION,
        "feature_schema_json": feature_columns(),
        "params_json": asdict(spec),
        "label_basis": LABEL_BASIS_PROFIT,
        "data_hash": compute_data_hash(
            business_id=business_id, model_key=MODEL_KEY,
            train_start=table.data_min, train_end=table.data_max,
            n_lines=table.n_lines, sum_revenue_rial=table.sum_revenue_rial,
            sum_gross_profit_rial=table.sum_gross_profit_rial,
        ),
    }

    if not table.maturity.ok or table.frame.empty:
        verdict = table.maturity
        return record_run(
            status=ModelRun.STATUS_INSUFFICIENT,
            blocked_reason_code=verdict.reason_code or "empty_training_table",
            blocked_reason_fa=verdict.reason_fa or (
                "پس از اعمال دروازه‌ها، هیچ مشتریِ برچسب‌خورده‌ای باقی نماند."
            ),
            metrics_json=verdict.to_dict(),
            note_fa="مدلی ساخته نشد؛ هیچ امتیازی روی مشتریان نوشته نمی‌شود.",
            **common,
        )

    fitted = fit_whale(table, spec)
    metrics = fitted["metrics"]
    metrics["maturity"] = table.maturity.to_dict()
    metrics["explanation_fa"] = fitted["explanation_fa"]
    train, validate = fitted["train"], fitted["validate"]

    status = (
        ModelRun.STATUS_VALIDATED if metrics["passed"] else ModelRun.STATUS_REJECTED
    )
    return record_run(
        status=status,
        train_start=str(train["anchor"].min()) if len(train) else None,
        train_end=str(train["anchor"].max()) if len(train) else None,
        validate_start=str(validate["anchor"].min()) if len(validate) else None,
        validate_end=str(validate["anchor"].max()) if len(validate) else None,
        n_train=int(len(train)), n_validate=int(len(validate)),
        n_train_positives=int(train["label"].sum()),
        n_validate_positives=int(validate["label"].sum()),
        metrics_json=metrics,
        calibration_json=fitted["calibration"],
        coefficients_json=fitted["coefficients"],
        drift_baseline_json=fitted["drift_baseline"],
        blocked_reason_fa=(
            None if metrics["passed"] else _rejection_reason(metrics, spec)
        ),
        blocked_reason_code=None if metrics["passed"] else "did_not_beat_baseline",
        note_fa=(
            "این مدل خط پایه را برد و آماده‌ی فعال‌سازی است."
            if metrics["passed"] else
            "این مدل فعال نمی‌شود؛ رفتار سیستم دقیقاً مثل قبل می‌ماند."
        ),
        **common,
    )


def _rejection_reason(metrics: dict, spec: WhaleSpec) -> str:
    gates = metrics["gates"]
    parts: list[str] = []
    if not gates["beats_prevalence_brier"]:
        parts.append(
            f"دقتِ احتمال از حدسِ ساده بهتر نشد (Brier {metrics['brier']} در برابر "
            f"{metrics['brier_baseline']})"
        )
    if not gates["beats_baseline_topk"]:
        lift = metrics["topk_lift_bp"]
        lower = metrics.get("topk_advantage_lower_rial")
        detail = ""
        if lift is not None:
            detail = (
                f" (اختلاف {lift / 100:.1f}٪ در برابر حداقلِ "
                f"{spec.min_topk_lift_bp / 100:.1f}٪"
            )
            if lower is not None and lower <= 0:
                detail += "؛ و بازه‌ی اطمینانش صفر را در بر می‌گیرد"
            detail += ")"
        parts.append("سودِ K تای اول از خط پایه‌ی قطعی جلو نزد" + detail)
    if not gates["calibrated"]:
        parts.append(
            f"کالیبراسیون خارج از تلرانس است (بیشترین خطای بین "
            f"{metrics['max_calibration_bin_error']})"
        )
    return "؛ ".join(parts) + "."


# ───────────────────────────────────────────────── امتیازدهی
def score_whale_customers(
    *, business_slug: str = "default", db_path: Path | None = None,
) -> dict:
    """نوشتنِ احتمالِ نهنگ روی تازه‌ترین عکسِ ویژگی — فقط با مدلِ **فعال**."""
    from mktcore.ml.score_job import write_customer_scores

    spec = WhaleSpec()
    return write_customer_scores(
        model_key=MODEL_KEY,
        probability_column="whale_probability_bp",
        run_column="whale_model_run_id",
        observation_days=spec.observation_days,
        business_slug=business_slug,
        db_path=db_path,
    )


register_trainer(MODEL_KEY, train_whale)

__all__ = [
    "LABEL_BASIS_PROFIT",
    "MODEL_KEY",
    "TrainingTable",
    "WhaleSpec",
    "build_training_table",
    "drift_baseline",
    "evaluate_whale",
    "explain_coefficients",
    "feature_columns",
    "fit_whale",
    "reliability_bins",
    "score_whale_customers",
    "train_whale",
    "whale_labels",
]
