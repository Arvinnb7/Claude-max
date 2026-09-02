"""§۲۰.۳ بند ۱: طبقه‌ی «تمام‌قیمت‌خری» — و بند ۵: هرگز آن را علّی جا نزن.

قاعده‌ی این فایل: **NaN یعنی نمی‌دانیم.** فایلی که ستون تخفیف ندارد، همه‌ی
مشتریانش را «وفادارِ تمام‌قیمت» نمی‌کند؛ و «۱۰۰٪ از یک خرید» طبقه نیست.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import select

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.analysis.kpis import compute_kpis  # noqa: E402
from mktcore.db import session_scope  # noqa: E402
from mktcore.db.migrations import reset_ensure_cache  # noqa: E402
from mktcore.db.models import Customer, CustomerFeature  # noqa: E402
from mktcore.db.repo_features import write_customer_features  # noqa: E402
from mktcore.db.repo_import import write_import  # noqa: E402
from mktcore.features.discount import (  # noqa: E402
    NON_CAUSAL_NOTE_FA,
    TIER_HIGH,
    TIER_LOW,
    TIER_MID,
    full_price_share_bp,
    full_price_tier,
)
from mktcore.ingest.cleaning import clean_frame  # noqa: E402
from mktcore.ingest.mapper import SchemaMapper  # noqa: E402
from mktcore.pipeline import run_analysis  # noqa: E402

from .test_golden_scenarios import (  # noqa: E402
    _COLS,
    _COLS_DISC,
    _MAPPING,
    _MAPPING_DISC,
    _discount_rows,
)


@pytest.fixture(autouse=True)
def _isolate():
    reset_ensure_cache()
    yield
    reset_ensure_cache()


# ═══════════════════════════════════════════════ کمک‌تابعِ خالص
def test_share_is_nan_without_any_discount_column():
    frame = pd.DataFrame({"customer_id": [1, 1, 2], "revenue_rial": [1, 2, 3]})
    share = full_price_share_bp(frame)
    assert set(share.index) == {1, 2}
    assert share.isna().all()


def test_share_reads_both_amount_and_rate_columns():
    frame = pd.DataFrame({
        "customer_id": [1, 1, 1, 1, 2, 2],
        "discount_rial": [0, 50_000, None, None, None, None],
        "discount_rate_bp": [None, None, 0, 1_000, 0, 0],
    })
    share = full_price_share_bp(frame)
    assert share[1] == 5_000    # دو از چهار خط بدون تخفیف
    assert share[2] == 10_000


@pytest.mark.parametrize(("share", "n_lines", "expected"), [
    (None, 10, None),           # فایل بدون ستون تخفیف
    (float("nan"), 10, None),
    (10_000, 2, None),          # «۱۰۰٪ از دو خرید» طبقه نیست
    (10_000, 3, TIER_HIGH),
    (9_000, 3, TIER_HIGH),      # مرزِ بالا شامل است
    (8_999, 3, TIER_MID),
    (5_000, 3, TIER_LOW),       # مرزِ پایین شامل است
    (5_001, 3, TIER_MID),
    (0, 3, TIER_LOW),
])
def test_tier_thresholds_and_unknowns(share, n_lines, expected):
    assert full_price_tier(share, n_lines) == expected


# ═══════════════════════════════════════════ عکسِ ویژگی و پرونده‌ی مشتری
def _ingest_and_snapshot(db: Path, rows, cols, mapping) -> None:
    raw = pd.DataFrame(rows, columns=cols)
    clean = clean_frame(SchemaMapper().apply(raw, mapping))
    write_import(clean, kpis=compute_kpis(clean), db_path=db)
    bundle = run_analysis(clean, horizon=2, with_forecast=False)
    write_customer_features(clean, bundle, db_path=db)


def _share_by_key(db: Path) -> dict[str, int | None]:
    with session_scope(db) as session:
        rows = session.execute(
            select(Customer.canonical_key, CustomerFeature.full_price_share_bp)
            .join(CustomerFeature, CustomerFeature.customer_id == Customer.id)
        ).all()
    return dict(rows)


def test_snapshot_stores_the_share_and_keeps_null_without_a_discount_column(tmp_path):
    db = tmp_path / "app.db"
    _ingest_and_snapshot(db, [r[:-1] for r in _discount_rows(amount=False)], _COLS, _MAPPING)

    shares = _share_by_key(db)
    assert shares, "عکسِ ویژگی نوشته نشد"
    assert all(value is None for value in shares.values()), shares


@pytest.mark.parametrize("amount", [False, True], ids=["نسبتی", "مبلغی"])
def test_snapshot_share_matches_the_scenario(tmp_path, amount):
    db = tmp_path / "app.db"
    _ingest_and_snapshot(db, _discount_rows(amount=amount), _COLS_DISC, _MAPPING_DISC)

    shares = _share_by_key(db)
    assert shares["وفادار"] == 10_000
    assert 2_500 <= shares["تخفیفی"] <= 3_500


def test_customer_api_carries_the_non_causal_note_always():
    """بند ۵ی §۲۰.۳: متنِ «همبستگی است، نه علّیت» در پاسخِ API اجباری است."""
    from api.main import app
    from fastapi.testclient import TestClient

    from .conftest import poll_job

    client = TestClient(app)
    listing = client.get("/api/v1/customers?limit=1").json()
    if not listing.get("items"):
        # دفتر کل را خودِ تست پر می‌کند؛ skipِ شرطی همان چیزی است که S0 حذف کرد
        sample = client.post("/api/sample").json()
        mapping = {x["role"]: x["suggested"] for x in sample["roles"] if x["suggested"]}
        job = client.post("/api/analyze", json={
            "session_id": sample["session_id"], "mapping": mapping, "horizon": 3,
        })
        poll_job(client, job.json()["job_id"])
        listing = client.get("/api/v1/customers?limit=1").json()
    assert listing["items"], "دفتر کل باید بعد از تحلیلِ نمونه پر باشد"
    body = client.get(f"/api/v1/customers/{listing['items'][0]['id']}").json()
    features = body["customer"]["features"]
    assert features is not None
    block = features["full_price"]
    assert set(block) >= {"share_bp", "tier", "thresholds", "note_fa"}
    assert NON_CAUSAL_NOTE_FA in block["note_fa"]
    if block["share_bp"] is None:
        assert block["tier"] is None
    assert block["tier"] in (None, TIER_HIGH, TIER_MID, TIER_LOW)
    assert not (isinstance(block["share_bp"], float) and math.isnan(block["share_bp"]))


# ═════════════════════════════ یافته‌های بازبینی: پوشش به‌ازای مشتری، بدون برگشتی
def test_a_customer_whose_rows_all_lack_discount_is_unknown_even_if_others_have_it():
    """دو آپلود: یکی با ستون تخفیف، یکی بدون. مشتریِ فایلِ دوم «نمی‌دانیم» است، نه ۱۰۰٪."""
    from mktcore.features.discount import full_price_stats

    frame = pd.DataFrame({
        "customer_id": [1, 1, 2, 2],
        "discount_rate_bp": [0, 1_000, None, None],
        "discount_rial": [None, None, None, None],
        "is_return": [False, False, False, False],
    })
    stats = full_price_stats(frame)

    assert stats.loc[1, "share_bp"] == 5_000 and stats.loc[1, "known_lines"] == 2
    assert math.isnan(stats.loc[2, "share_bp"]) and stats.loc[2, "known_lines"] == 0


def test_return_lines_do_not_count_toward_the_full_price_share():
    """۳ خریدِ تخفیف‌دار + ۷ برگشتی ⇒ سهمِ تمام‌قیمت ۰٪، نه ۷۰٪."""
    from mktcore.features.discount import full_price_stats

    frame = pd.DataFrame({
        "customer_id": [1] * 10,
        "discount_rate_bp": [1_000] * 3 + [None] * 7,
        "discount_rial": [None] * 10,
        "is_return": [False] * 3 + [True] * 7,
    })
    stats = full_price_stats(frame)

    assert stats.loc[1, "share_bp"] == 0
    assert stats.loc[1, "known_lines"] == 3


def test_snapshot_stores_the_basis_line_count(tmp_path):
    """آستانه‌ی کمینه‌ی خطوط روی خطوطِ مبنا اعمال می‌شود، نه خطوطِ همین آپلود."""
    db = tmp_path / "app.db"
    _ingest_and_snapshot(db, _discount_rows(amount=False), _COLS_DISC, _MAPPING_DISC)

    with session_scope(db) as session:
        rows = dict(session.execute(
            select(Customer.canonical_key, CustomerFeature.full_price_lines)
            .join(CustomerFeature, CustomerFeature.customer_id == Customer.id)
        ).all())
    assert rows["وفادار"] == 10 and rows["تخفیفی"] == 10
