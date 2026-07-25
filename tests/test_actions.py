"""تست فهرست اقدام ریالی و خودسنجی کالیبراسیون احتمال."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.analysis.actions import (  # noqa: E402
    VALUE_AT_RISK,
    VALUE_OPPORTUNITY,
    build_action_list,
)
from mktcore.analysis.probability_eval import evaluate_probability  # noqa: E402
from mktcore.ingest.cleaning import clean_frame  # noqa: E402
from mktcore.ingest.mapper import SchemaMapper  # noqa: E402
from mktcore.pipeline import run_analysis  # noqa: E402
from mktcore.synthetic import generate_synthetic_sales  # noqa: E402


def _analyzed(rows: int = 8000):
    raw = generate_synthetic_sales(days=540).head(rows)
    m = SchemaMapper()
    clean = clean_frame(m.apply(raw, m.auto_detect(raw).mapping))
    return run_analysis(clean, horizon=3, with_forecast=False), clean


def test_action_list_built_and_sorted_by_value():
    bundle, clean = _analyzed()
    ap = bundle.actions
    assert ap.available, "فهرست اقدام نباید خالی باشد"
    values = [a.value_rial for a in ap.actions]
    assert values == sorted(values, reverse=True), "باید نزولی بر اساس ریال مرتب باشد"
    assert ap.total_value == sum(values)
    assert all(a.value_rial > 0 for a in ap.actions)
    for i, a in enumerate(ap.actions, 1):
        assert a.rank == i


def test_action_kinds_and_value_kinds():
    bundle, _ = _analyzed()
    kinds = {a.kind for a in bundle.actions.actions}
    assert len(kinds) >= 2, f"دست‌کم دو نوع اقدام انتظار می‌رود: {kinds}"
    vkinds = {a.value_kind for a in bundle.actions.actions}
    assert vkinds <= {VALUE_OPPORTUNITY, VALUE_AT_RISK}
    # خلاصه با اقلام هم‌خوان است
    total_from_summary = sum(s["جمع ارزش"] for s in bundle.actions.summary)
    assert abs(total_from_summary - bundle.actions.total_value) < 1.0


def test_one_action_per_customer_and_fields_filled():
    bundle, _ = _analyzed()
    ids = [a.customer_id for a in bundle.actions.actions]
    assert len(ids) == len(set(ids)), "هر مشتری باید حداکثر یک اقدام داشته باشد"
    for a in bundle.actions.actions[:20]:
        assert a.action_fa and a.reason_fa and a.confidence
        assert a.message_fa
        assert a.owner  # داده‌ی نمونه فروشنده دارد


def test_per_customer_cap_configurable():
    bundle, clean = _analyzed()
    ap2 = build_action_list(bundle, clean, per_customer_cap=2)
    counts: dict[str, int] = {}
    for a in ap2.actions:
        counts[a.customer_id] = counts.get(a.customer_id, 0) + 1
    assert max(counts.values()) <= 2


def test_empty_on_tiny_data_without_crash():
    df = pd.DataFrame({
        "customer_id": ["a", "b"],
        "date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
        "revenue": [10.0, 20.0],
        "product": ["x", "y"],
    })
    bundle = run_analysis(df, with_forecast=False)
    assert isinstance(bundle.actions.actions, list)
    assert bundle.actions.total_value >= 0.0


def test_probability_calibration_beats_baseline_on_cyclic_data():
    """داده‌ی چرخه‌ای: احتمال‌های مدل باید بهتر از حدس نرخ پایه باشند."""
    rng = np.random.default_rng(11)
    rows = []
    # نیمی مشتری فعال با چرخه‌ی ۲۰ روزه، نیمی رهاشده (۶ ماه پیش قطع کرده‌اند)
    for i in range(120):
        active = i % 2 == 0
        n = 12 if active else 4
        for b in range(n):
            day = b * 20 + int(rng.integers(0, 4))
            rows.append((f"c{i}", pd.Timestamp("2023-06-01") + pd.Timedelta(days=day),
                         100.0 + i, "P"))
    df = pd.DataFrame(rows, columns=["customer_id", "date", "revenue", "product"])
    cal = evaluate_probability(df)
    assert cal is not None
    assert cal.n_eval >= 50
    assert cal.beats_baseline, f"brier={cal.brier} baseline={cal.baseline_brier}"
    assert cal.bins, "جدول قابلیت‌اعتماد نباید خالی باشد"
    assert abs(cal.bias) < 0.35


def test_probability_calibration_none_on_insufficient_data():
    df = pd.DataFrame({
        "customer_id": ["a", "a", "b"],
        "date": pd.to_datetime(["2024-01-01", "2024-02-01", "2024-02-20"]),
        "revenue": [10.0, 20.0, 30.0],
        "product": ["x", "y", "x"],
    })
    assert evaluate_probability(df) is None
