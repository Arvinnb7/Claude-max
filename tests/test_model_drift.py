"""سنجشِ انحراف (§۲۹.۷).

ادعای اصلی این فایل: **«نسنجیده» هرگز «پایدار» گزارش نمی‌شود.** سنجه‌ای که
وقتی داده ندارد خوش‌بین جواب می‌دهد، بدتر از نبودنش است.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.ml.drift import (  # noqa: E402
    LEVEL_SHIFTED,
    LEVEL_STABLE,
    LEVEL_WARN,
    level_for,
    measure_drift,
    population_stability_index,
)
from mktcore.ml.linear_fit import drift_baseline  # noqa: E402


def _frame(values: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"monetary_rial": values})


def _baseline(values: list[float]) -> dict:
    return drift_baseline(
        _frame(values), ["monetary_rial"], np.array([0, 1] * (len(values) // 2)),
    )


def test_psi_is_near_zero_on_the_training_population():
    values = list(np.linspace(0, 1_000, 400))
    baseline = _baseline(values)

    psi = population_stability_index(baseline["feature_deciles"]["monetary_rial"], pd.Series(values))

    assert psi is not None
    assert psi < 0.01


def test_a_shifted_distribution_raises_the_index():
    values = list(np.linspace(0, 1_000, 400))
    baseline = _baseline(values)
    shifted = pd.Series(list(np.linspace(900, 2_000, 400)))

    psi = population_stability_index(baseline["feature_deciles"]["monetary_rial"], shifted)

    assert psi > 0.25
    assert level_for(psi) == LEVEL_SHIFTED


def test_levels_have_conservative_thresholds():
    assert level_for(0.05) == LEVEL_STABLE
    assert level_for(0.15) == LEVEL_WARN
    assert level_for(0.40) == LEVEL_SHIFTED
    assert level_for(None) == LEVEL_STABLE


def test_missing_baseline_reports_unmeasured_not_stable():
    report = measure_drift(baseline=None, current_features=_frame([1.0] * 50))

    assert report["measured"] is False
    assert report["level"] is None
    assert "پایدار" in report["note_fa"], "متن باید همین اشتباه را رد کند"


def test_empty_population_reports_unmeasured():
    baseline = _baseline(list(np.linspace(0, 100, 40)))
    report = measure_drift(baseline=baseline, current_features=pd.DataFrame())

    assert report["measured"] is False


def test_stable_population_reports_no_retraining_needed():
    values = list(np.linspace(0, 1_000, 400))
    report = measure_drift(baseline=_baseline(values), current_features=_frame(values))

    assert report["measured"] is True
    assert report["level"] == LEVEL_STABLE
    assert "بازآموزی" in report["note_fa"]


def test_target_rate_shift_is_reported_separately():
    values = list(np.linspace(0, 1_000, 400))
    report = measure_drift(
        baseline=_baseline(values), current_features=_frame(values),
        current_target_rate=0.9,
    )

    assert report["target_shift"]["measured"] is True
    assert report["target_shift"]["shifted"] is True
    assert report["level"] == LEVEL_SHIFTED


def test_calibration_decay_is_reported_separately():
    values = list(np.linspace(0, 1_000, 400))
    report = measure_drift(
        baseline=_baseline(values), current_features=_frame(values),
        calibration_bins=[{"تعداد": 100, "خطا": 0.4}],
    )

    assert report["calibration"]["decayed"] is True
    assert report["level"] == LEVEL_SHIFTED
    assert "کالیبراسیون" in report["note_fa"]


def test_drift_never_demotes_a_model_by_itself():
    """§۲۹.۷: هشدار می‌دهد، ولی برداشتنِ مدل تصمیمِ آدم است."""
    values = list(np.linspace(0, 1_000, 400))
    report = measure_drift(
        baseline=_baseline(values),
        current_features=_frame(list(np.linspace(5_000, 9_000, 400))),
    )

    assert report["level"] == LEVEL_SHIFTED
    assert "خودبه‌خود خاموش نمی‌شود" in report["note_fa"]
