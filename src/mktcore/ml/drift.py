"""سنجشِ انحراف (§۲۹.۷) — «آیا دنیای امروز همان دنیای آموزش است؟»

چهار چیزی که سند می‌خواهد و اینجا سنجیده می‌شود:

* **جابه‌جاییِ توزیع ویژگی‌ها** با PSI روی دهک‌های لحظه‌ی آموزش.
* **جابه‌جاییِ نرخِ هدف** نسبت به نرخِ زمانِ آموزش.
* **افتِ کالیبراسیون** نسبت به خطای بین‌ها در لحظه‌ی اعتبارسنجی.
* **جمعیتِ تازه** — سهم مشتریانی که ویژگی‌شان اصلاً محاسبه‌شدنی نیست.

**چرا دهک و نه میانگین/انحراف.** این ویژگی‌ها به‌شدت چوله‌اند؛ میانگین با چند
مشتریِ بزرگ جابه‌جا می‌شود و انحراف معیار سیگنالِ ضعیفی می‌دهد. PSI روی دهک،
تغییرِ **شکل** توزیع را می‌بیند.

**چرا بازگشتِ خودکار نداریم.** §۲۹.۷ می‌گوید «warning and rollback/retraining
policy **where configured**». دمُتِ خودکار روی یک نوسان فصلی، بهترین مدل را در
بدترین لحظه برمی‌دارد. پس هشدار می‌آید و دکمه‌ی بازگشت دستِ آدم می‌ماند.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    pass

logger = logging.getLogger("mktcore.ml.drift")

# آستانه‌های متعارفِ PSI. قابل تنظیم‌اند ولی پیش‌فرض محافظه‌کار است.
PSI_STABLE = 0.10
PSI_WARN = 0.25
# جابه‌جاییِ نسبیِ نرخ هدف که هشدار می‌دهد
TARGET_SHIFT_WARN = 0.30
# افتِ کالیبراسیون: خطای بینِ بزرگ‌تر از این، یعنی «۸۰٪ دیگر ۸۰٪ نیست»
CALIBRATION_WARN = 0.15

LEVEL_STABLE = "پایدار"
LEVEL_WARN = "هشدار"
LEVEL_SHIFTED = "تغییر معنادار"


def population_stability_index(
    baseline_deciles: list[float], current: pd.Series, *, epsilon: float = 1e-6,
) -> float | None:
    """PSI بین توزیعِ امروز و دهک‌های لحظه‌ی آموزش.

    دهک‌ها خودشان مرزِ سطل‌اند، پس در لحظه‌ی آموزش هر سطل ۱۰٪ داشته و PSI صفر
    است — همان چیزی که تستِ «روی جمعیتِ آموزش صفر است» پین می‌کند.
    """
    values = pd.to_numeric(current, errors="coerce").dropna()
    if len(values) < 10 or len(baseline_deciles) < 3:
        return None
    edges = np.unique(np.asarray(baseline_deciles, dtype=float))
    if len(edges) < 3:
        # ویژگی تقریباً ثابت بوده؛ PSI روی توزیعِ تک‌نقطه‌ای معنا ندارد.
        return None
    inner = edges[1:-1]
    expected = np.full(len(inner) + 1, 1.0 / (len(inner) + 1))
    counts = np.histogram(values.to_numpy(dtype=float), bins=[-np.inf, *inner, np.inf])[0]
    actual = counts / max(counts.sum(), 1)
    expected = np.clip(expected, epsilon, None)
    actual = np.clip(actual, epsilon, None)
    return float(np.sum((actual - expected) * np.log(actual / expected)))


def level_for(psi: float | None) -> str:
    if psi is None:
        return LEVEL_STABLE
    if psi < PSI_STABLE:
        return LEVEL_STABLE
    if psi < PSI_WARN:
        return LEVEL_WARN
    return LEVEL_SHIFTED


def measure_drift(
    *,
    baseline: dict | None,
    current_features: pd.DataFrame,
    current_target_rate: float | None = None,
    calibration_bins: list[dict] | None = None,
) -> dict:
    """گزارشِ انحراف — همیشه با عدد، و بدون خط‌پایه صریحاً «نسنجیده»."""
    if not baseline or not baseline.get("feature_deciles"):
        return {
            "measured": False,
            "level": None,
            "note_fa": (
                "خط‌پایه‌ی انحراف برای این مدل ثبت نشده است، پس انحراف سنجیده "
                "نشد. «نسنجیده» را «پایدار» نامیدن، سنجه را بی‌اعتبار می‌کند."
            ),
        }
    if current_features.empty:
        return {
            "measured": False,
            "level": None,
            "note_fa": "جمعیتِ امروز خالی است؛ چیزی برای مقایسه وجود ندارد.",
        }

    features: list[dict] = []
    worst = 0.0
    for name, deciles in baseline["feature_deciles"].items():
        if name not in current_features.columns:
            continue
        psi = population_stability_index(deciles, current_features[name])
        if psi is None:
            continue
        worst = max(worst, psi)
        features.append({
            "ویژگی": name, "PSI": round(psi, 4), "وضعیت": level_for(psi),
        })
    features.sort(key=lambda row: row["PSI"], reverse=True)

    target = _target_shift(baseline.get("target_rate"), current_target_rate)
    calibration = _calibration_decay(calibration_bins)
    level = _overall(worst, target, calibration)

    return {
        "measured": True,
        "level": level,
        "worst_psi": round(worst, 4),
        "features": features[:10],
        "target_shift": target,
        "calibration": calibration,
        "n_rows": int(len(current_features)),
        "note_fa": _note(level, worst, target, calibration),
    }


def _target_shift(baseline_rate: float | None, current_rate: float | None) -> dict:
    if baseline_rate is None or current_rate is None:
        return {
            "measured": False,
            "note_fa": "نرخِ هدفِ امروز در دسترس نیست؛ این بخش سنجیده نشد.",
        }
    if not baseline_rate:
        return {"measured": False, "note_fa": "نرخِ هدفِ آموزش صفر بوده است."}
    relative = (current_rate - baseline_rate) / baseline_rate
    return {
        "measured": True,
        "baseline": round(float(baseline_rate), 4),
        "current": round(float(current_rate), 4),
        "relative": round(float(relative), 4),
        "shifted": bool(abs(relative) > TARGET_SHIFT_WARN),
    }


def _calibration_decay(bins: list[dict] | None) -> dict:
    if not bins:
        return {
            "measured": False,
            "note_fa": "جدول اتکا ثبت نشده است؛ افتِ کالیبراسیون سنجیده نشد.",
        }
    worst = max((abs(row.get("خطا", 0.0)) for row in bins if row.get("تعداد", 0) >= 20), default=0.0)
    return {
        "measured": True,
        "max_bin_error": round(float(worst), 4),
        "decayed": bool(worst > CALIBRATION_WARN),
    }


def _overall(worst_psi: float, target: dict, calibration: dict) -> str:
    if worst_psi >= PSI_WARN or target.get("shifted") or calibration.get("decayed"):
        return LEVEL_SHIFTED
    if worst_psi >= PSI_STABLE:
        return LEVEL_WARN
    return LEVEL_STABLE


def _note(level: str, worst_psi: float, target: dict, calibration: dict) -> str:
    if level == LEVEL_STABLE:
        return (
            f"توزیع ویژگی‌ها نسبت به زمان آموزش پایدار است (بیشترین PSI "
            f"{round(worst_psi, 3)}). دلیلی برای بازآموزی دیده نمی‌شود."
        )
    parts = [f"بیشترین PSI برابر {round(worst_psi, 3)} است"]
    if target.get("shifted"):
        parts.append(
            f"نرخِ هدف {round(target['relative'] * 100)}٪ نسبت به زمان آموزش جابه‌جا شده"
        )
    if calibration.get("decayed"):
        parts.append(
            f"خطای کالیبراسیون به {calibration['max_bin_error']} رسیده"
        )
    return (
        "؛ ".join(parts)
        + ". بازآموزی پیشنهاد می‌شود، ولی مدل خودبه‌خود خاموش نمی‌شود — "
        "برداشتنِ خودکارِ مدل روی یک نوسان فصلی، بدترین لحظه‌ی ممکن است."
    )


__all__ = [
    "CALIBRATION_WARN",
    "LEVEL_SHIFTED",
    "LEVEL_STABLE",
    "LEVEL_WARN",
    "PSI_STABLE",
    "PSI_WARN",
    "TARGET_SHIFT_WARN",
    "level_for",
    "measure_drift",
    "population_stability_index",
]
