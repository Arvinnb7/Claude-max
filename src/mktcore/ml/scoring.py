"""امتیازدهی از روی JSON — بدون `sklearn`، بدون بارگذاری آرتیفکت.

آموزش یک کارِ گاه‌به‌گاه است؛ امتیازدهی در مسیرِ هر بارگذاری اجرا می‌شود. جدا
نگه‌داشتنشان یعنی مسیرِ داغ نه به کتابخانه‌ی سنگین وابسته است و نه به فایلی که
ممکن است سرِ جایش نباشد.

ریاضی‌اش کوتاه است و همین کوتاهی، ارزشش است:

    x        = ویژگی، با جای‌گذاریِ میانه هرجا نامعلوم بود
    indicator= ۱ اگر آن ویژگی نامعلوم بود، وگرنه ۰
    z        = ((x ⧺ indicator) − center) / scale
    p        = sigmoid(z · coef + intercept)
    p        = interp(p, calibration.x, calibration.y)
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def build_design_matrix(coefficients: dict[str, Any], frame: pd.DataFrame) -> np.ndarray:
    """ماتریسِ طراحی به همان ترتیبی که مدل با آن آموزش دیده.

    ستونِ غایب در فریم = «نامعلوم» (NaN)، نه صفر: صفر یعنی ادعایی که نداریم.
    """
    features = list(coefficients["features"])
    indicators = list(coefficients.get("indicator_features") or [])
    medians = np.asarray(coefficients["impute_median"], dtype=float)

    raw = np.empty((len(frame), len(features)), dtype=float)
    for position, name in enumerate(features):
        column = (
            pd.to_numeric(frame[name], errors="coerce").to_numpy(dtype=float)
            if name in frame.columns
            else np.full(len(frame), np.nan)
        )
        raw[:, position] = column

    missing = np.isnan(raw)
    filled = np.where(missing, medians[np.newaxis, :], raw)
    if not indicators:
        return filled

    index_of = {name: position for position, name in enumerate(features)}
    flags = np.column_stack([
        missing[:, index_of[name]].astype(float) if name in index_of
        else np.zeros(len(frame))
        for name in indicators
    ])
    return np.hstack([filled, flags])


def score_from_json(
    coefficients: dict[str, Any] | None,
    calibration: dict[str, Any] | None,
    frame: pd.DataFrame,
) -> np.ndarray:
    """احتمالِ کالیبره‌شده برای هر ردیف. بدون مدل ⇒ آرایه‌ی خالیِ NaN.

    NaN عمدی است: «مدلی نداریم» با «احتمال صفر» یکی نیست، و هیچ‌جای این سیستم
    اجازه ندارد نبودِ مدل را صفر گزارش کند.
    """
    if not coefficients or frame.empty:
        return np.full(len(frame), np.nan)

    design = build_design_matrix(coefficients, frame)
    center = np.asarray(coefficients["center"], dtype=float)
    scale = np.asarray(coefficients["scale"], dtype=float)
    coef = np.asarray(coefficients["coef"], dtype=float)
    scale = np.where(scale == 0.0, 1.0, scale)

    z = ((design - center) / scale) @ coef + float(coefficients["intercept"])
    probability = 1.0 / (1.0 + np.exp(-np.clip(z, -60.0, 60.0)))
    return apply_calibration(calibration, probability)


def apply_calibration(
    calibration: dict[str, Any] | None, probability: np.ndarray,
) -> np.ndarray:
    """اعمالِ isotonic ذخیره‌شده. بدون آرتیفکت، عددِ خام برمی‌گردد."""
    if not calibration or not calibration.get("x"):
        return probability
    x = np.asarray(calibration["x"], dtype=float)
    y = np.asarray(calibration["y"], dtype=float)
    # `np.interp` بیرونِ بازه را خودش به دو سر می‌چسباند — همان `out_of_bounds="clip"`
    return np.clip(np.interp(probability, x, y), 0.0, 1.0)


def to_basis_points(probability: np.ndarray) -> list[int | None]:
    """احتمال → پایه‌ی هزارم، با نگه‌داشتنِ NaN به‌صورت `None`."""
    out: list[int | None] = []
    for value in probability:
        out.append(None if value is None or np.isnan(value) else int(round(value * 10_000)))
    return out


__all__ = ["apply_calibration", "build_design_matrix", "score_from_json", "to_basis_points"]
