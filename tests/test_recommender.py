"""تست‌های موتور پیشنهاد سبد (CF آیتم-آیتم + ترکیب سیگنال‌ها)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.analysis.market_basket import analyze_basket  # noqa: E402
from mktcore.analysis.next_purchase import predict_next_purchases  # noqa: E402
from mktcore.analysis.purchase_cycle import analyze_purchase_cycles  # noqa: E402
from mktcore.analysis.recommender import (  # noqa: E402
    REASON_CF,
    REASON_CYCLE,
    REASON_POPULAR,
    build_recommender,
)


def _frame(rows) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["customer_id", "date", "revenue", "product"])
    df["date"] = pd.to_datetime(df["date"])
    return df


def _cluster_rows(n_pad: int = 60):
    """۶۰ مشتری padding (برای رد شدن از گیت ۵۰ مشتری) + خوشه‌ی شامپو/نرم‌کننده."""
    rows = []
    for i in range(n_pad):
        rows.append((f"pad{i}", "2024-01-05", 10.0, f"جانبی{i % 7}"))
    for i in range(10):
        rows.append((f"s{i}", "2024-02-01", 100.0, "شامپو"))
        rows.append((f"s{i}", "2024-02-01", 80.0, "نرم‌کننده"))
    rows.append(("هدف", "2024-03-01", 100.0, "شامپو"))
    return rows


def test_cf_recommends_cobought_item():
    df = _frame(_cluster_rows())
    rec = build_recommender(df)
    assert rec.available
    recs = rec.recommend("هدف", n=5)
    products = {r.product: r.reason for r in recs}
    assert "نرم‌کننده" in products
    assert products["نرم‌کننده"] == REASON_CF


def test_min_cobuyers_guard():
    """جفتی که فقط ۲ هم‌خریدار دارد نباید edge CF بسازد."""
    rows = [(f"pad{i}", "2024-01-05", 10.0, f"ج{i % 8}") for i in range(60)]
    for i in range(2):  # فقط ۲ هم‌خریدار < min_cobuyers=3
        rows.append((f"d{i}", "2024-02-01", 50.0, "الف"))
        rows.append((f"d{i}", "2024-02-01", 50.0, "ب"))
    rows.append(("هدف", "2024-03-01", 50.0, "الف"))
    rec = build_recommender(_frame(rows))
    recs = rec.recommend("هدف", n=5)
    assert all(not (r.product == "ب" and r.reason == REASON_CF) for r in recs)


def test_consumable_rerecommended_onetime_excluded():
    rows = []
    # «قهوه» مصرفی: خریداران زیاد با بازخرید منظم
    for i in range(55):
        for m in (1, 2, 3):
            rows.append((f"c{i}", f"2024-0{m}-01", 30.0, "قهوه"))
        rows.append((f"c{i}", "2024-01-20", 5.0, f"متفرقه{i % 6}"))  # گیت ≥۵ محصول
    # «ماشین قهوه» تک‌خریدی: هر مشتری فقط یک بار
    for i in range(20):
        rows.append((f"c{i}", "2024-01-15", 900.0, "ماشین قهوه"))
    # ساعتِ داده: تاریخ آخر دیتاست را جلو می‌برد تا c0 از چرخه عقب بیفتد
    rows.append(("clock", "2024-05-01", 1.0, "قهوه"))
    df = _frame(rows)
    basket = analyze_basket(df)
    cycles = analyze_purchase_cycles(df, basket)
    rec = build_recommender(df, cycles=cycles, basket=basket)
    assert rec.available
    # c0 هر دو را خریده و از چرخه‌ی قهوه عقب است → قهوه مجاز، ماشین قهوه هرگز
    recs = rec.recommend("c0", n=5)
    products = [r.product for r in recs]
    assert "ماشین قهوه" not in products
    if any(n.customer_id == "c0" for n in cycles.notifications):
        assert "قهوه" in products
        reason = next(r.reason for r in recs if r.product == "قهوه")
        assert reason == REASON_CYCLE


def test_cold_customer_gets_popularity():
    rows = _cluster_rows()
    rows.append(("سرد", "2024-03-01", 5.0, "قلم‌ناشناخته"))
    rec = build_recommender(_frame(rows))
    recs = rec.recommend("سرد", n=5)
    assert recs, "مشتری سرد باید پیشنهاد پرفروش بگیرد"
    assert any(r.reason == REASON_POPULAR for r in recs)


def test_determinism():
    df = _frame(_cluster_rows())
    rec = build_recommender(df)
    ids = ["هدف"] + [f"s{i}" for i in range(10)]
    a = rec.recommend_many(ids, n=5)
    b = rec.recommend_many(ids, n=5)
    assert {k: [(r.product, r.reason, r.score) for r in v] for k, v in a.items()} == \
           {k: [(r.product, r.reason, r.score) for r in v] for k, v in b.items()}


def test_small_data_gate_falls_back():
    rows = [("a", "2024-01-01", 10.0, "x"), ("b", "2024-01-02", 20.0, "y")]
    rec = build_recommender(_frame(rows))
    assert not rec.available
    assert rec.recommend("a") == []


def test_predict_without_recommender_backward_compat():
    df = _frame(_cluster_rows())
    res = predict_next_purchases(df)
    for c in res.customers:
        assert c.recommendations == []
        assert isinstance(c.likely_products, list)


def test_predict_with_recommender_fills_both_fields():
    rows = []
    for i in range(55):
        for m in (1, 2, 3):
            rows.append((f"c{i}", f"2024-0{m}-01", 30.0, "قهوه"))
        rows.append((f"c{i}", "2024-02-01", 15.0, f"فیلتر{i % 5}"))
    # جلو بردن تاریخ دیتاست تا مشتریان قهوه سررسید شوند
    rows.append(("clock", "2024-05-10", 1.0, "قهوه"))
    df = _frame(rows)
    basket = analyze_basket(df)
    cycles = analyze_purchase_cycles(df, basket)
    rec = build_recommender(df, cycles=cycles, basket=basket)
    res = predict_next_purchases(df, basket, cycles=cycles, recommender=rec)
    due = res.due_now(20)
    assert due
    filled = [c for c in due if c.recommendations]
    assert filled, "مشتریان سررسیدشده باید recommendations داشته باشند"
    for c in filled:
        assert c.likely_products == [r.product for r in c.recommendations]
        assert len(c.likely_products) <= 5


def test_runtime_smoke_20k_rows():
    rng = np.random.default_rng(7)
    n = 20_000
    rows = pd.DataFrame({
        "customer_id": [f"c{int(x)}" for x in rng.integers(0, 2000, n)],
        "date": pd.to_datetime("2024-01-01") + pd.to_timedelta(rng.integers(0, 365, n), unit="D"),
        "revenue": rng.uniform(10, 500, n),
        "product": [f"p{int(x)}" for x in rng.integers(0, 300, n)],
    })
    t0 = time.monotonic()
    rec = build_recommender(rows)
    ids = [f"c{i}" for i in range(500)]
    rec.recommend_many(ids, n=5)
    elapsed = time.monotonic() - t0
    assert rec.available
    assert elapsed < 10, f"خیلی کند: {elapsed:.1f}s"
