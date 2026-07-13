"""تست سنجش دقت پیشنهاد سبد (leave-last-basket-out)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.analysis.recommender_eval import evaluate_recommender  # noqa: E402


def _two_cluster_frame() -> pd.DataFrame:
    """دو خوشه‌ی ترجیحی مجزا: مدل CF باید بهتر از پرفروش سراسری عمل کند.

    خوشه‌ی A (پردرآمد): محصولات a1..a6 که top-5 پرفروش سراسری را کامل اشغال
    می‌کنند؛ خوشه‌ی B فقط b1..b3 می‌خرد → پیش‌بینی «پرفروش» برای B همیشه غلط است
    ولی CF ترجیح خوشه را یاد می‌گیرد.
    """
    rows = []
    for i in range(60):  # خوشه‌ی A — هر سبد ۳ قلم از ۶ قلم خوشه
        for b in range(4):  # ۴ سبد؛ آخرین سبد پنهان می‌شود
            date = pd.Timestamp("2024-01-01") + pd.Timedelta(days=(b * 30 + i % 10))
            for k in range(3):
                rows.append((f"A{i}", date, 500.0, f"a{(i + b + k) % 6 + 1}"))
    for i in range(50):  # خوشه‌ی B
        for b in range(4):
            date = pd.Timestamp("2024-01-01") + pd.Timedelta(days=(b * 30 + i % 10))
            for p in ("b1", "b2", "b3"):
                rows.append((f"B{i}", date, 20.0, p))
    df = pd.DataFrame(rows, columns=["customer_id", "date", "revenue", "product"])
    df["date"] = pd.to_datetime(df["date"])
    return df


def test_eval_returns_metrics_and_beats_nothing_weird():
    ev = evaluate_recommender(_two_cluster_frame(), max_customers=200)
    assert ev is not None
    assert ev.n_eval >= 30
    for v in (ev.hitrate_at_5, ev.recall_at_5,
              ev.popularity_hitrate_at_5, ev.heuristic_hitrate_at_5):
        assert 0.0 <= v <= 1.0


def test_model_beats_popularity_on_clustered_data():
    ev = evaluate_recommender(_two_cluster_frame(), max_customers=200)
    assert ev is not None
    # پرفروش سراسری فقط خوشه‌ی A را پوشش می‌دهد؛ مدل هر دو خوشه را
    assert ev.hitrate_at_5 > ev.popularity_hitrate_at_5


def test_eval_none_on_tiny_data():
    df = pd.DataFrame({
        "customer_id": ["a", "a", "b"],
        "date": pd.to_datetime(["2024-01-01", "2024-02-01", "2024-01-05"]),
        "revenue": [10.0, 20.0, 30.0],
        "product": ["x", "y", "x"],
    })
    assert evaluate_recommender(df) is None
