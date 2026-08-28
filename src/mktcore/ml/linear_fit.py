"""برازشِ مدلِ خطیِ کالیبره — مشترکِ همه‌ی مدل‌های این لایه.

اینجا فقط «چطور برازش می‌دهیم» است؛ «چه چیزی را پیش‌بینی می‌کنیم» کار ماژول‌های
`whale` و `churn` است. جدا نگه‌داشتنش یعنی قواعدی که به سختی درست شدند — برشِ
زمانیِ کالیبراسیون، پرچمِ «این مقدار نامعلوم بود»، و انتخابِ سیگموئید در
نمونه‌ی کم — یک‌بار نوشته می‌شوند و در هر مدلِ تازه تکرار نمی‌شوند.

**چرا مدل خطی.** با چند ده نمونه‌ی مثبت، درختِ تقویت‌شده بیش‌برازش می‌کند و
بهبودش از holdout زمانی جان سالم به‌در نمی‌برد. ضمناً ضریبِ خطی مستقیماً به
جمله‌ی فارسی تبدیل می‌شود — چیزی که §۲۷.۷ می‌خواهد — و به JSON درمی‌آید، پس
بازگشت به نسخه‌ی قبلی بدون فایلِ آرتیفکت ممکن می‌ماند.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .scoring import apply_calibration
from .serialize import calibration_to_json, linear_model_to_json, sigmoid_calibration_to_json


@dataclass(frozen=True)
class FitConfig:
    """پارامترهای برازش — همه ثبت‌شدنی در `params_json`."""

    calibration_fraction: float = 0.30
    l2_c: float = 1.0
    balanced: bool = True
    isotonic_min_rows: int = 1_000
    isotonic_min_positives: int = 100


@dataclass(frozen=True)
class FitResult:
    coefficients: dict[str, Any]
    calibration: dict[str, Any]
    predicted: np.ndarray          # احتمالِ کالیبره‌شده روی بازوی اعتبارسنجی
    n_fit: int
    n_calibration: int


def chronological_cut(values: pd.Series, keep_fraction: float) -> Any:
    """مرزِ برشِ زمانی. برشِ تصادفی §۲۹.۱ را نقض می‌کند."""
    ordered = sorted(values.to_numpy())
    if not ordered:
        return None
    index = min(len(ordered) - 1, int(len(ordered) * keep_fraction))
    return ordered[index]


def fit_calibrated_linear(
    train: pd.DataFrame,
    validate: pd.DataFrame,
    *,
    columns: list[str],
    label_col: str,
    order_col: str,
    config: FitConfig,
) -> FitResult:
    """لجستیکِ L2 + کالیبراسیون روی **تازه‌ترین بخشِ دوره‌ی آموزش**."""
    from sklearn.linear_model import LogisticRegression

    cut = chronological_cut(train[order_col], 1.0 - config.calibration_fraction)
    fit_part = train[train[order_col] < cut] if cut is not None else train
    calib_part = train[train[order_col] >= cut] if cut is not None else train
    if fit_part[label_col].nunique() < 2 or calib_part.empty:
        # نمونه‌ی کم: برشِ جداگانه ممکن نیست، پس همان دوره‌ی آموزش هر دو نقش را
        # بازی می‌کند — و این در سنجه‌ها **گزارش** می‌شود، نه پنهان.
        fit_part = calib_part = train

    medians = fit_part[columns].median(numeric_only=True).reindex(columns).fillna(0.0)
    indicators = [name for name in columns if fit_part[name].isna().any()]

    def design(part: pd.DataFrame) -> np.ndarray:
        base = part[columns].astype(float)
        missing = base.isna()
        filled = base.fillna(medians)
        matrix = filled.to_numpy(dtype=float)
        if not indicators:
            return matrix
        flags = missing[indicators].astype(float).to_numpy(dtype=float)
        return np.hstack([matrix, flags])

    x_fit = design(fit_part)
    center = x_fit.mean(axis=0)
    scale = x_fit.std(axis=0)
    scale[scale == 0.0] = 1.0

    model = LogisticRegression(
        C=config.l2_c,
        class_weight="balanced" if config.balanced else None,
        solver="lbfgs", max_iter=2_000,
    )
    model.fit((x_fit - center) / scale, fit_part[label_col].to_numpy(dtype=int))

    raw_calib = model.predict_proba((design(calib_part) - center) / scale)[:, 1]
    calibration = fit_calibrator(
        raw_calib, calib_part[label_col].to_numpy(dtype=int), config,
    )
    raw_validate = model.predict_proba((design(validate) - center) / scale)[:, 1]
    predicted = np.clip(apply_calibration(calibration, raw_validate), 0.0, 1.0)

    coefficients = linear_model_to_json(
        features=columns,
        indicator_features=indicators,
        impute_median=[float(medians[name]) for name in columns],
        center=list(center), scale=list(scale),
        coef=list(model.coef_[0]), intercept=float(model.intercept_[0]),
    )
    return FitResult(
        coefficients=coefficients, calibration=calibration, predicted=predicted,
        n_fit=int(len(fit_part)), n_calibration=int(len(calib_part)),
    )


def fit_calibrator(
    raw: np.ndarray, labels: np.ndarray, config: FitConfig,
) -> dict[str, Any]:
    """کالیبراتور را از **داده** انتخاب می‌کند، نه از سلیقه.

    isotonic درجه‌آزادیِ بالایی دارد و با چندصد نمونه خودش را به نوفه برازش
    می‌دهد؛ در همین پروژه هم روی برشِ کوچک، خطای بین‌ها را از ۰٫۰۷ به ۰٫۲۵ برد.
    پس تا وقتی نمونه کوچک است سیگموئید (دو پارامتر) به‌کار می‌رود.
    """
    from sklearn.linear_model import LogisticRegression

    big_enough = (
        len(raw) >= config.isotonic_min_rows
        and int(labels.sum()) >= config.isotonic_min_positives
    )
    if big_enough:
        from sklearn.isotonic import IsotonicRegression

        isotonic = IsotonicRegression(out_of_bounds="clip").fit(raw, labels)
        return calibration_to_json(
            x=list(isotonic.X_thresholds_), y=list(isotonic.y_thresholds_),
        )

    eps = 1e-9
    clipped = np.clip(raw, eps, 1.0 - eps)
    logit = np.log(clipped / (1.0 - clipped)).reshape(-1, 1)
    platt = LogisticRegression(C=1e6, max_iter=1_000).fit(logit, labels)
    return sigmoid_calibration_to_json(
        slope=float(platt.coef_[0][0]), intercept=float(platt.intercept_[0]),
        n_calibration=int(len(raw)),
    )


def reliability_bins(
    predicted: np.ndarray, labels: np.ndarray,
    *, edges: tuple[float, ...] = (0.0, 0.1, 0.3, 0.5, 0.7, 1.0001),
) -> list[dict]:
    """جدولِ «۸۰٪ گفتیم، چند درصد شد؟» — §۲۹.۴."""
    out: list[dict] = []
    for low, high in zip(edges[:-1], edges[1:], strict=False):
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


def captured(value: np.ndarray, score: np.ndarray, top_k: int) -> float:
    """ارزشِ گرفته‌شده در K تای اولِ یک رتبه‌بندی — سنجه‌ی اقتصادیِ §۲۹.۳."""
    if not len(value):
        return 0.0
    order = np.argsort(-score, kind="stable")[:top_k]
    return float(value[order].sum())


def bootstrap_advantage(
    value: np.ndarray, model_score: np.ndarray, baseline_score: np.ndarray,
    *, top_fraction: float, samples: int = 400, quantile: float = 0.05,
    seed: int = 20240918,
) -> float | None:
    """پایین‌ترین صدکِ اختلافِ «ارزشِ K تای اول» بین مدل و خط پایه.

    چرا لازم است: با چند ده نمونه‌ی مثبت، اختلافِ چنددرصدی می‌تواند تصادفی
    باشد. اگر این عدد منفی باشد، برتری اثبات نشده — همان قاعده‌ای که گزارش
    کمپین‌ها دارد و نمی‌گذارد نوفه «اثر» نامیده شود.
    """
    n = len(value)
    if n < 20 or samples <= 0:
        return None
    import math

    rng = np.random.default_rng(seed)
    share = max(1, math.ceil(top_fraction * n))
    diffs = np.empty(samples, dtype=float)
    for index in range(samples):
        picks = rng.integers(0, n, n)
        sample_value = value[picks]
        diffs[index] = (
            captured(sample_value, model_score[picks], share)
            - captured(sample_value, baseline_score[picks], share)
        )
    return float(np.quantile(diffs, quantile))


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
        deciles[name] = [round(float(series.quantile(q / 10)), 4) for q in range(11)]
    return {
        "feature_deciles": deciles,
        "target_rate": round(float(labels.mean()), 4) if len(labels) else None,
        "n_rows": int(len(frame)),
    }


__all__ = [
    "FitConfig",
    "FitResult",
    "bootstrap_advantage",
    "captured",
    "chronological_cut",
    "drift_baseline",
    "explain_coefficients",
    "fit_calibrated_linear",
    "fit_calibrator",
    "reliability_bins",
]
