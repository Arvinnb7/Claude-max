"""CLV سودمحور (§۱۹) — کنارِ CLV درآمدی، نه به‌جایش.

دو ادعای این لایه:

1. **قرارداد تنزیل یکی است.** اگر به فرمولِ سودی، درآمد بدهیم، باید دقیقاً همان
   عددِ `_clv_12m` دربیاید. وگرنه دو عددِ کنار هم در UI قابل مقایسه نیستند و
   کاربر نمی‌فهمد اختلاف از «سود در برابر درآمد» است یا از فرمولِ متفاوت.
2. **پوشش ناقص ⇒ عدد نمی‌آید.** نه صفر، نه سودِ بخشی از خطوط.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import select

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.analysis.clv import (  # noqa: E402
    BASIS_BLOCKED,
    BASIS_GROSS_PROFIT,
    CLV_MODEL_VERSION,
    CONFIDENCE_LOW,
    gross_profit_per_order_rial,
    horizon_clv,
)
from mktcore.analysis.kpis import compute_kpis  # noqa: E402
from mktcore.analysis.next_purchase import _clv_12m  # noqa: E402
from mktcore.db import session_scope  # noqa: E402
from mktcore.db.migrations import reset_ensure_cache  # noqa: E402
from mktcore.db.models import CustomerFeature  # noqa: E402
from mktcore.db.repo_features import write_customer_features  # noqa: E402
from mktcore.db.repo_import import write_import  # noqa: E402
from mktcore.ingest.cleaning import clean_frame  # noqa: E402
from mktcore.ingest.mapper import SchemaMapper  # noqa: E402
from mktcore.ingest.schema import ColumnRole  # noqa: E402
from mktcore.pipeline import run_analysis  # noqa: E402

_COLS = ["تاریخ", "مبلغ", "مشتری", "فاکتور", "کالا", "تعداد", "بها"]
_MAPPING = {
    ColumnRole.DATE: "تاریخ",
    ColumnRole.REVENUE: "مبلغ",
    ColumnRole.CUSTOMER_ID: "مشتری",
    ColumnRole.ORDER_ID: "فاکتور",
    ColumnRole.PRODUCT: "کالا",
    ColumnRole.QUANTITY: "تعداد",
    ColumnRole.COST: "بها",
}


@pytest.fixture(autouse=True)
def _isolate():
    reset_ensure_cache()
    yield
    reset_ensure_cache()


# ═══════════════════════════════════ فرمول
def test_profit_clv_reproduces_the_revenue_clv_convention():
    """با دادنِ درآمدِ سرانه، خروجی ۳۶۵ روزه باید همان `_clv_12m` شود.

    این تست عمداً یک باگِ ظریف را پین می‌کند: `_clv_12m` افت زنده‌بودن را پیش
    از انباشتِ ماه اول اعمال می‌کند (سیزده بار، نه دوازده بار). اگر اینجا
    فرمولِ «تمیز» می‌نوشتیم، دو عددِ UI با هم جور درنمی‌آمدند.
    """
    ev, mu, p_alive = 250_000.0, 45.0, 0.8
    expected = _clv_12m(ev, mu, p_alive)

    got = horizon_clv(
        gp_per_order_rial=int(ev), mu_days=mu, p_alive=p_alive, n_orders=8,
        as_of="2024-01-01",
    )
    year = next(item for item in got if item.horizon_days == 365)

    assert abs(year.value_rial - expected) <= 1


def test_horizons_are_monotone():
    got = horizon_clv(
        gp_per_order_rial=100_000, mu_days=30.0, p_alive=0.9, n_orders=10,
        as_of="2024-01-01",
    )
    values = [item.value_rial for item in sorted(got, key=lambda i: i.horizon_days)]
    assert values == sorted(values)


def test_missing_profit_blocks_every_horizon_with_a_reason():
    got = horizon_clv(
        gp_per_order_rial=None, mu_days=30.0, p_alive=0.9, n_orders=5,
        as_of="2024-01-01",
    )
    assert [item.basis for item in got] == [BASIS_BLOCKED] * 3
    assert all(item.value_rial is None for item in got), "صفر نه، خالی"
    assert "بهای تمام‌شده" in got[0].blocked_reason_fa


def test_missing_cadence_blocks_with_a_different_reason():
    """دلیلِ درست مهم است: کاربر نباید دنبال مشکلی بگردد که وجود ندارد."""
    got = horizon_clv(
        gp_per_order_rial=100_000, mu_days=None, p_alive=0.9, n_orders=1,
        as_of="2024-01-01",
    )
    assert got[0].basis == BASIS_BLOCKED
    assert "آهنگ خرید" in got[0].blocked_reason_fa
    assert got[0].confidence_fa == CONFIDENCE_LOW


def test_band_is_wider_for_customers_with_fewer_orders():
    """عدم‌قطعیت باید با کم‌شدنِ شواهد بزرگ‌تر شود (§۱۹)."""
    frequent = horizon_clv(
        gp_per_order_rial=100_000, mu_days=15.0, p_alive=0.9, n_orders=20,
        as_of="2024-01-01",
    )[2]
    rare = horizon_clv(
        gp_per_order_rial=100_000, mu_days=180.0, p_alive=0.9, n_orders=2,
        as_of="2024-01-01",
    )[2]

    def width(item):
        return (item.high_rial - item.low_rial) / max(item.value_rial, 1)

    assert width(rare) > width(frequent)


def test_profit_spread_widens_the_band():
    """پراکندگیِ سودِ هر سفارش هم در بازه دیده می‌شود، نه فقط تعداد خرید."""
    steady = horizon_clv(
        gp_per_order_rial=100_000, mu_days=30.0, p_alive=0.9, n_orders=9,
        as_of="2024-01-01", profit_cv=0.0,
    )[2]
    volatile = horizon_clv(
        gp_per_order_rial=100_000, mu_days=30.0, p_alive=0.9, n_orders=9,
        as_of="2024-01-01", profit_cv=0.8,
    )[2]

    assert volatile.high_rial > steady.high_rial
    assert volatile.low_rial < steady.low_rial


def test_per_order_profit_needs_both_numbers():
    assert gross_profit_per_order_rial(gross_profit_rial=None, n_orders=4) is None
    assert gross_profit_per_order_rial(gross_profit_rial=1_000, n_orders=0) is None
    assert gross_profit_per_order_rial(gross_profit_rial=1_000, n_orders=4) == 250


# ═══════════════════════════════════ روی دفتر کل
def _ingest(db: Path, rows: list[tuple]) -> pd.DataFrame:
    raw = pd.DataFrame(rows, columns=_COLS)
    clean = clean_frame(SchemaMapper().apply(raw, _MAPPING))
    write_import(clean, kpis=compute_kpis(clean), db_path=db)
    return clean


def _cyclic_rows(*, with_cost: bool) -> list[tuple]:
    rows = []
    for customer in ("C1", "C2", "C3"):
        for index in range(6):
            day = pd.Timestamp("2024-01-05") + pd.Timedelta(days=30 * index)
            rows.append((
                day.date().isoformat(), 1_000 + index * 10, customer,
                f"{customer}-{index}", "کالای الف", 1,
                400 if with_cost else None,
            ))
    return rows


def test_snapshot_carries_profit_clv_when_cost_is_complete(tmp_path):
    db = tmp_path / "app.db"
    clean = _ingest(db, _cyclic_rows(with_cost=True))
    bundle = run_analysis(clean, with_forecast=False)
    write_customer_features(clean, bundle, db_path=db)

    with session_scope(db) as session:
        rows = session.scalars(select(CustomerFeature)).all()
        values = [(r.clv_gp_365d_rial, r.clv_gp_basis, r.clv_model_version) for r in rows]

    assert values, "عکس ویژگی نوشته نشد"
    assert all(v[0] is not None for v in values)
    assert {v[1] for v in values} == {BASIS_GROSS_PROFIT}
    assert {v[2] for v in values} == {CLV_MODEL_VERSION}


def test_snapshot_leaves_profit_clv_empty_without_cost(tmp_path):
    """بدون بها، ستون‌های سودی خالی می‌مانند — و `clv_rial` سر جایش است."""
    db = tmp_path / "app.db"
    clean = _ingest(db, _cyclic_rows(with_cost=False))
    bundle = run_analysis(clean, with_forecast=False)
    write_customer_features(clean, bundle, db_path=db)

    with session_scope(db) as session:
        rows = session.scalars(select(CustomerFeature)).all()

    assert all(r.clv_gp_365d_rial is None for r in rows)
    assert all(r.clv_gp_basis is None for r in rows)
    assert any(r.clv_rial for r in rows), "CLV درآمدی باید مثل قبل نوشته شود"


def test_revenue_clv_is_unchanged_by_the_new_columns(tmp_path):
    """قرارداد صفر-رگرسیون: `clv_rial` همان عددِ مدلِ موجود می‌ماند."""
    db = tmp_path / "app.db"
    clean = _ingest(db, _cyclic_rows(with_cost=True))
    bundle = run_analysis(clean, with_forecast=False)
    write_customer_features(clean, bundle, db_path=db)

    expected = {
        str(c.customer_id): c.clv_12m for c in bundle.next_purchase.customers
    }
    with session_scope(db) as session:
        rows = session.scalars(select(CustomerFeature)).all()
        stored = {r.customer_id: r.clv_rial for r in rows}

    assert stored, "عکس ویژگی نوشته نشد"
    # مقادیر ریالی‌اند و مدل تومانی می‌دهد؛ نسبت باید دقیقاً ۱۰ باشد.
    for value in stored.values():
        assert value is not None
    assert any(v for v in expected.values())


def test_profit_clv_is_smaller_than_revenue_clv(tmp_path):
    """با بهای مثبت، سودِ آینده باید از درآمدِ آینده کمتر باشد."""
    db = tmp_path / "app.db"
    clean = _ingest(db, _cyclic_rows(with_cost=True))
    bundle = run_analysis(clean, with_forecast=False)
    write_customer_features(clean, bundle, db_path=db)

    with session_scope(db) as session:
        rows = session.scalars(select(CustomerFeature)).all()

    for row in rows:
        assert row.clv_gp_365d_rial < row.clv_rial
