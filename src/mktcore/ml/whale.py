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

import json
import logging
import math
from dataclasses import asdict, dataclass, replace
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
from sqlalchemy import func

from mktcore.db.base import now_ts
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
from mktcore.ml.registry import compute_data_hash, record_run
from mktcore.ml.scoring import apply_calibration
from mktcore.ml.serialize import (
    calibration_to_json,
    linear_model_to_json,
    sigmoid_calibration_to_json,
)
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
    """برازشِ لجستیکِ کالیبره + سنجش در برابر دو خطِ پایه.

    مدل عمداً خطی است: با ۳۰ نمونه‌ی مثبت در هر بازو، درختِ تقویت‌شده بیش‌برازش
    می‌کند و بهبودش از holdout زمانی جان سالم به‌در نمی‌برد. ضمناً ضریبِ خطی
    مستقیماً به توضیحِ فارسی تبدیل می‌شود — چیزی که §۲۷.۷ می‌خواهد.
    """
    from sklearn.linear_model import LogisticRegression

    frame, split_date = table.frame, table.split_date
    train = frame[frame["anchor"] < split_date]
    validate = frame[frame["anchor"] >= split_date]

    # برشِ کالیبراسیون: تازه‌ترین بخشِ **دوره‌ی آموزش**، نه نمونه‌ی تصادفی
    calibration_split = chronological_split(
        train["anchor"], replace(spec.maturity, train_fraction=1.0 - spec.calibration_fraction),
    )
    fit_part = train[train["anchor"] < calibration_split]
    calib_part = train[train["anchor"] >= calibration_split]
    if fit_part["label"].nunique() < 2 or calib_part.empty:
        fit_part, calib_part = train, train

    columns = feature_columns()
    medians = fit_part[columns].median(numeric_only=True)
    medians = medians.reindex(columns).fillna(0.0)
    indicator_columns = [
        name for name in columns if fit_part[name].isna().any()
    ]

    def design(part: pd.DataFrame) -> np.ndarray:
        base = part[columns].astype(float)
        missing = base.isna()
        filled = base.fillna(medians)
        if not indicator_columns:
            return filled.to_numpy(dtype=float)
        flags = missing[indicator_columns].astype(float)
        return np.hstack([filled.to_numpy(dtype=float), flags.to_numpy(dtype=float)])

    x_fit, y_fit = design(fit_part), fit_part["label"].to_numpy(dtype=int)
    center = x_fit.mean(axis=0)
    scale = x_fit.std(axis=0)
    scale[scale == 0.0] = 1.0

    # `penalty="l2"` پیش‌فرض است و در نسخه‌های تازه‌ی scikit-learn منسوخ شده؛
    # `class_weight="balanced"` می‌ماند چون نسبت مثبت‌ها حدود یک‌دهم است.
    model = LogisticRegression(
        C=spec.l2_c, class_weight="balanced", solver="lbfgs", max_iter=2_000,
    )
    model.fit((x_fit - center) / scale, y_fit)

    raw_calib = model.predict_proba((design(calib_part) - center) / scale)[:, 1]
    calibrator, calibration_seed = _fit_calibrator(
        raw_calib, calib_part["label"].to_numpy(dtype=int), spec,
    )

    coefficients = linear_model_to_json(
        features=columns,
        indicator_features=indicator_columns,
        impute_median=[float(medians[name]) for name in columns],
        center=list(center), scale=list(scale),
        coef=list(model.coef_[0]), intercept=float(model.intercept_[0]),
    )
    raw_validate = model.predict_proba((design(validate) - center) / scale)[:, 1]
    predicted = np.clip(apply_calibration(calibration_seed, raw_validate), 0.0, 1.0)
    bins = reliability_bins(predicted, validate["label"].to_numpy(dtype=int))
    calibration = {**calibration_seed, "reliability_bins": bins}

    metrics = evaluate_whale(
        validate, predicted, spec=spec, bins=bins, train=train,
    )
    return {
        "coefficients": coefficients,
        "calibration": calibration,
        "metrics": metrics,
        "train": train,
        "validate": validate,
        "drift_baseline": drift_baseline(fit_part, columns, y_fit),
        "explanation_fa": explain_coefficients(coefficients),
    }


def _fit_calibrator(
    raw: np.ndarray, labels: np.ndarray, spec: WhaleSpec,
) -> tuple[dict, dict]:
    """کالیبراتور را از **داده** انتخاب می‌کند، نه از سلیقه.

    isotonic درجه‌آزادیِ بالایی دارد و با چندصد نمونه خودش را به نوفه برازش
    می‌دهد؛ در همین پروژه هم روی برشِ کالیبراسیونِ کوچک، خطای بین‌ها را بدتر
    کرد. پس تا وقتی نمونه کوچک است سیگموئید (دو پارامتر) به‌کار می‌رود.
    """
    from sklearn.linear_model import LogisticRegression

    big_enough = (
        len(raw) >= spec.isotonic_min_rows
        and int(labels.sum()) >= spec.isotonic_min_positives
    )
    if big_enough:
        from sklearn.isotonic import IsotonicRegression

        isotonic = IsotonicRegression(out_of_bounds="clip").fit(raw, labels)
        artifact = calibration_to_json(
            x=list(isotonic.X_thresholds_), y=list(isotonic.y_thresholds_),
        )
        return artifact, artifact

    eps = 1e-9
    clipped = np.clip(raw, eps, 1.0 - eps)
    logit = np.log(clipped / (1.0 - clipped)).reshape(-1, 1)
    platt = LogisticRegression(C=1e6, max_iter=1_000).fit(logit, labels)
    artifact = sigmoid_calibration_to_json(
        slope=float(platt.coef_[0][0]), intercept=float(platt.intercept_[0]),
        n_calibration=int(len(raw)),
    )
    return artifact, artifact


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
    model_top = _captured(profit, predicted, top_k)
    baseline_top = _captured(
        profit, validate["baseline_score"].to_numpy(dtype=float), top_k,
    )
    perfect_top = float(np.sort(profit)[::-1][:top_k].sum())

    lift_bp = (
        int(round((model_top / baseline_top - 1.0) * 10_000))
        if baseline_top > 0 else None
    )
    max_bin_error = max((abs(b["خطا"]) for b in bins if b["تعداد"] >= 20), default=0.0)
    lower_bound = _bootstrap_lower_bound(
        profit, predicted, validate["baseline_score"].to_numpy(dtype=float), spec=spec,
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


def _bootstrap_lower_bound(
    profit: np.ndarray, model_score: np.ndarray, baseline_score: np.ndarray,
    *, spec: WhaleSpec,
) -> float | None:
    """پایین‌ترین صدکِ اختلافِ «سودِ K تای اول» بین مدل و خط پایه.

    چرا لازم است: با ۵۰ نمونه‌ی مثبت، اختلافِ ۵٪ می‌تواند کاملاً تصادفی باشد.
    نمونه‌گیری مجدد از همان مشتریانِ اعتبارسنجی می‌گوید این اختلاف چقدر پایدار
    است. اگر صدکِ پایین منفی باشد، ادعای برتری اثبات نشده — همان قاعده‌ای که
    گزارش کمپین‌ها دارد.
    """
    n = len(profit)
    if n < 20 or spec.bootstrap_samples <= 0:
        return None
    rng = np.random.default_rng(20240918)
    share = max(1, math.ceil(spec.top_fraction * n))
    diffs = np.empty(spec.bootstrap_samples, dtype=float)
    for index in range(spec.bootstrap_samples):
        picks = rng.integers(0, n, n)
        sample_profit = profit[picks]
        diffs[index] = (
            _captured(sample_profit, model_score[picks], share)
            - _captured(sample_profit, baseline_score[picks], share)
        )
    return float(np.quantile(diffs, spec.bootstrap_quantile))


def _captured(profit: np.ndarray, score: np.ndarray, top_k: int) -> float:
    if not len(profit):
        return 0.0
    order = np.argsort(-score, kind="stable")[:top_k]
    return float(profit[order].sum())


def reliability_bins(predicted: np.ndarray, labels: np.ndarray) -> list[dict]:
    """جدولِ «۸۰٪ گفتیم، چند درصد شد؟» — §۲۹.۴."""
    out: list[dict] = []
    for low, high in zip(_RELIABILITY_BINS[:-1], _RELIABILITY_BINS[1:], strict=False):
        mask = (predicted >= low) & (predicted < high)
        count = int(mask.sum())
        if not count:
            continue
        mean_predicted = float(predicted[mask].mean())
        actual = float(labels[mask].mean())
        out.append({
            "از": round(low, 3), "تا": round(min(high, 1.0), 3), "تعداد": count,
            "پیش‌بینی": round(mean_predicted, 4), "واقعی": round(actual, 4),
            "خطا": round(mean_predicted - actual, 4),
        })
    return out


def drift_baseline(frame: pd.DataFrame, columns: list[str], labels: np.ndarray) -> dict:
    """دهک‌های ویژگی در لحظه‌ی آموزش — خط‌پایه‌ی §۲۹.۷.

    دهک به‌جای میانگین/انحراف: این ویژگی‌ها به‌شدت چوله‌اند و جابه‌جاییِ میانگین
    سیگنالِ ضعیفی است.
    """
    deciles = {}
    for name in columns:
        series = frame[name].dropna()
        if series.empty:
            continue
        deciles[name] = [
            round(float(series.quantile(q / 10)), 4) for q in range(11)
        ]
    return {
        "feature_deciles": deciles,
        "target_rate": round(float(labels.mean()), 4) if len(labels) else None,
        "n_rows": int(len(frame)),
    }


def explain_coefficients(coefficients: dict, *, top: int = 5) -> list[str]:
    """توضیحِ فارسیِ ضرایب — §۲۷.۷: «بدون تفسیر کسب‌وکاری نمایش نده»."""
    names = list(coefficients["features"]) + [
        f"نامعلوم‌بودنِ {name}" for name in coefficients.get("indicator_features") or []
    ]
    pairs = sorted(
        zip(names, coefficients["coef"], strict=False),
        key=lambda pair: abs(pair[1]), reverse=True,
    )[:top]
    return [
        f"{name}: {'افزایش' if weight > 0 else 'کاهش'} احتمال (وزن {round(weight, 3)})"
        for name, weight in pairs
    ]


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
    """نوشتنِ احتمالِ نهنگ روی تازه‌ترین عکسِ ویژگی — فقط با مدلِ **فعال**.

    بدون مدلِ فعال هیچ ستونی نوشته نمی‌شود و ستون‌ها `NULL` می‌مانند؛ `NULL`
    یعنی «مدلی نداریم»، نه «احتمال صفر».
    """
    from sqlalchemy import select

    from mktcore.db.engine import write_lock
    from mktcore.db.models import CustomerFeature
    from mktcore.ml.registry import mark_scored, promoted_run
    from mktcore.ml.scoring import score_from_json, to_basis_points

    ensure_schema(db_path)
    with write_lock, session_scope(db_path) as session:
        business_id = resolve_business_id(session, business_slug)
        if business_id is None:
            return {"scored": 0, "note_fa": "کسب‌وکاری ثبت نشده است."}
        run = promoted_run(session, business_id, MODEL_KEY)
        if run is None or not run.coefficients_json:
            return {
                "scored": 0,
                "note_fa": (
                    "هیچ مدلِ نهنگی فعال نیست؛ امتیازی نوشته نشد و ستون‌ها "
                    "خالی ماندند."
                ),
            }

        spec = WhaleSpec().with_params(json.loads(run.params_json or "{}"))
        lines = load_line_frame(session, business_id)
        if lines.empty:
            return {"scored": 0, "note_fa": "دفتر کل خالی است."}

        exclusive_end = _day_after(str(lines["line_date"].max()))
        features = compute_point_in_time_features(
            lines[lines["line_date"] < exclusive_end],
            PointInTimeSpec(
                as_of=exclusive_end, observation_days=spec.observation_days,
                require_complete_window=True,
            ),
        )
        if features.empty:
            return {
                "scored": 0,
                "note_fa": (
                    "هیچ مشتری‌ای پنجره‌ی مشاهده‌اش کامل نشده؛ امتیاز معنا ندارد."
                ),
            }

        probabilities = score_from_json(
            json.loads(run.coefficients_json),
            json.loads(run.calibration_json) if run.calibration_json else None,
            features,
        )
        by_customer = dict(zip(features.index, to_basis_points(probabilities), strict=False))

        latest_as_of = session.scalar(
            select(func.max(CustomerFeature.as_of_date)).where(
                CustomerFeature.business_id == business_id
            )
        )
        if not latest_as_of:
            return {"scored": 0, "note_fa": "هنوز عکسِ ویژگی‌ای ثبت نشده است."}

        rows = session.scalars(
            select(CustomerFeature).where(
                CustomerFeature.business_id == business_id,
                CustomerFeature.as_of_date == latest_as_of,
            )
        ).all()
        stamp = now_ts()
        written = 0
        for row in rows:
            value = by_customer.get(row.customer_id)
            if value is None:
                continue
            row.whale_probability_bp = int(value)
            row.whale_model_run_id = run.id
            row.scored_at = stamp
            written += 1
        mark_scored(session, run.id, n_scored=written)
        session.flush()

    logger.info("امتیاز نهنگ روی %s مشتری نوشته شد (اجرای %s)", written, run.id)
    return {
        "scored": written,
        "model_run_id": run.id,
        "as_of": latest_as_of,
        "note_fa": f"احتمالِ نهنگ برای {written} مشتری به‌روز شد.",
    }


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
