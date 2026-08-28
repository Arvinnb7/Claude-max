"""آهنگ خریدِ مقاوم — MAD، میانه‌ی وزنی، و تعدیلِ اندازه‌ی بسته (§۱۳.۳ و §۱۳.۴).

قاعده‌ی این گام: **مدلِ فعلی آهنگ خرید دست نمی‌خورد.** ترکیبِ موجود (میانگین
نمایی‌وزن‌دار + میانه + انقباض سلسله‌مراتبی) از «میانه‌ی ساده»ی سند بهتر است و
سرِ جایش می‌ماند؛ این ابزارها **کنارش** به ویژگی‌های مدل اضافه می‌شوند.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.analysis.cadence_robust import (  # noqa: E402
    EVIDENCE_NONE,
    EVIDENCE_PERSONAL,
    EVIDENCE_PERSONAL_PRODUCT,
    EVIDENCE_POPULATION,
    dispersion_ratio,
    evidence_level,
    mad,
    pack_adjusted_gap,
    weighted_median,
)
from mktcore.analysis.kpis import compute_kpis  # noqa: E402
from mktcore.analysis.next_purchase import predict_next_purchases  # noqa: E402
from mktcore.db import session_scope  # noqa: E402
from mktcore.db.lookup import resolve_business_id  # noqa: E402
from mktcore.db.migrations import reset_ensure_cache  # noqa: E402
from mktcore.db.repo_import import write_import  # noqa: E402
from mktcore.features import PointInTimeSpec, compute_point_in_time_features  # noqa: E402
from mktcore.features.ledger_frame import load_line_frame  # noqa: E402
from mktcore.ingest.cleaning import clean_frame  # noqa: E402
from mktcore.ingest.mapper import SchemaMapper  # noqa: E402
from mktcore.ingest.schema import ColumnRole  # noqa: E402
from mktcore.synthetic import generate_synthetic_sales  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate():
    reset_ensure_cache()
    yield
    reset_ensure_cache()


# ═══════════════════════════════════ ریاضیِ خالص
def test_mad_is_robust_to_a_single_outlier():
    """یک فاصله‌ی پرت نباید سنجه‌ی پراکندگی را منفجر کند."""
    steady = [30.0, 31.0, 29.0, 30.0]
    with_outlier = [*steady, 400.0]

    assert mad(steady) == pytest.approx(0.5, abs=0.6)
    assert mad(with_outlier) <= 2.0, "MAD باید مقاوم بماند"
    assert pd.Series(with_outlier).std() > 100, "انحراف معیار منفجر می‌شود"


def test_weighted_median_leans_toward_recent_gaps():
    """§۱۳.۳: فاصله‌ی تازه‌تر وزن بیشتری دارد، ولی میانه است نه میانگین."""
    values = [90.0, 90.0, 30.0, 30.0]
    recent_heavy = [0.42, 0.56, 0.75, 1.0]

    assert weighted_median(values, recent_heavy) == 30.0
    assert weighted_median(values, [1.0, 1.0, 1.0, 1.0]) in (30.0, 90.0)


def test_weighted_median_ignores_zero_weight_and_empty_input():
    assert weighted_median([], []) is None
    assert weighted_median([10.0], [0.0]) is None


def test_dispersion_ratio_is_none_without_a_base():
    assert dispersion_ratio(5.0, None) is None
    assert dispersion_ratio(None, 30.0) is None
    assert dispersion_ratio(6.0, 30.0) == pytest.approx(0.2)


def test_bulk_purchase_extends_the_expected_gap():
    """§۱۳.۴: کسی که سه برابر می‌خرد، دیرتر برمی‌گردد."""
    adjusted, reason = pack_adjusted_gap(
        30.0, quantity_milli=3_000, baseline_quantity_milli=1_000,
    )

    assert adjusted == pytest.approx(90.0)
    assert "بیشتر" in reason


def test_missing_quantity_returns_the_unadjusted_gap_and_says_so():
    """تعدیلِ حدسی بدترین حالت است: عددی می‌سازد که شبیه دانستن است."""
    adjusted, reason = pack_adjusted_gap(30.0, quantity_milli=None)

    assert adjusted == 30.0
    assert "تعدیلِ اندازه انجام نشد" in reason


def test_pack_size_normalises_heterogeneous_units():
    """۲ بسته‌ی ۵۰۰ گرمی با ۱ بسته‌ی ۱ کیلویی یکی نیست."""
    small, _ = pack_adjusted_gap(
        30.0, quantity_milli=2_000, baseline_quantity_milli=1_000,
        pack_size_milli=500,
    )
    plain, _ = pack_adjusted_gap(
        30.0, quantity_milli=2_000, baseline_quantity_milli=1_000,
    )

    assert small > plain, "با بسته‌ی کوچک، مقدارِ واقعی بیشتر شمرده می‌شود"


def test_evidence_ladder_falls_back_explicitly():
    """§۱۳.۲: با یک خرید، آهنگِ شخصی ادعا نمی‌شود — صریح پایین می‌آید."""
    assert evidence_level(personal_product_gaps=3)[0] == EVIDENCE_PERSONAL_PRODUCT
    assert evidence_level(personal_gaps=2)[0] == EVIDENCE_PERSONAL
    assert evidence_level(population_gap=42.0)[0] == EVIDENCE_POPULATION
    assert evidence_level()[0] == EVIDENCE_NONE
    assert evidence_level()[1] == "کم"


# ═══════════════════════════════════ اتصال به ویژگی‌ها و عدم رگرسیون
_COLS = ["تاریخ", "مبلغ", "مشتری", "فاکتور", "کالا", "تعداد"]
_MAPPING = {
    ColumnRole.DATE: "تاریخ",
    ColumnRole.REVENUE: "مبلغ",
    ColumnRole.CUSTOMER_ID: "مشتری",
    ColumnRole.ORDER_ID: "فاکتور",
    ColumnRole.PRODUCT: "کالا",
    ColumnRole.QUANTITY: "تعداد",
}


def test_features_expose_pack_adjusted_cadence(tmp_path):
    db = tmp_path / "app.db"
    rows = []
    for index in range(6):
        day = (pd.Timestamp("2024-01-01") + pd.Timedelta(days=30 * index)).date()
        rows.append((day.isoformat(), 1_000, "C1", f"A{index}", "کالای الف", 1))
        rows.append((day.isoformat(), 4_000, "C2", f"B{index}", "کالای الف", 4))
    clean = clean_frame(SchemaMapper().apply(pd.DataFrame(rows, columns=_COLS), _MAPPING))
    write_import(clean, kpis=compute_kpis(clean), db_path=db)

    with session_scope(db) as session:
        lines = load_line_frame(session, resolve_business_id(session, "default"))
    out = compute_point_in_time_features(lines, PointInTimeSpec(as_of="2024-12-01"))

    assert "pack_adjusted_gap_days" in out.columns
    assert "weighted_median_gap_days" in out.columns
    bulk = out["units_per_order_milli"].idxmax()
    light = out["units_per_order_milli"].idxmin()
    assert out.loc[bulk, "pack_adjusted_gap_days"] > out.loc[light, "pack_adjusted_gap_days"]


def test_next_purchase_predictions_are_unchanged():
    """قهرمانِ فعلی دست‌نخورده: همان اعداد، همان ترتیب."""
    raw = generate_synthetic_sales(seed=7, days=360)
    clean = clean_frame(SchemaMapper().apply(raw, SchemaMapper().auto_detect(raw).mapping))

    first = predict_next_purchases(clean)
    second = predict_next_purchases(clean)

    assert [c.customer_id for c in first.customers] == [
        c.customer_id for c in second.customers
    ]
    assert [c.avg_interval_days for c in first.customers] == [
        c.avg_interval_days for c in second.customers
    ]
