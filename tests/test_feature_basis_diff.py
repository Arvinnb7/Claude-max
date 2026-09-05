"""پرونده‌ی ۳۶۰ از دفتر کل — مدعیِ سایه در برابر قهرمانِ فریمِ آپلود.

ادعاها:
1. روی **تک‌فایل** مدعی با قهرمان بیت‌به‌بیت یکی است (همه‌ی ستون‌های مقایسه‌شده و
   حالتِ چرخه‌ی عمر) ⇒ `identical=True`.
2. روی **دو فایلِ ماهانه** با یک مشتریِ غایب از ماهِ دوم، مدعی آن مشتری را می‌بیند
   (و گذارش را) در حالی که قهرمان برایش ردیفی ندارد؛ و برای مشتریانِ مشترک، جمع‌های
   بین‌فایلی اختلاف می‌سازند — همه در diff گزارش می‌شود.
3. هیچ‌چیز نوشته نمی‌شود.
4. مسیرِ `GET /api/v1/feature-basis-diff` توکن‌دار است و هوکِ ثبت خلاصه را در
   `notes_json`ِ اجرای موتور می‌گذارد.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import func, select

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from api.canonical_hook import record_analysis  # noqa: E402
from api.v1 import feature_basis_diff  # noqa: E402

from mktcore.analysis.kpis import compute_kpis  # noqa: E402
from mktcore.db import session_scope  # noqa: E402
from mktcore.db.migrations import reset_ensure_cache  # noqa: E402
from mktcore.db.models import (  # noqa: E402
    Customer,
    CustomerFeature,
    CustomerLifecycleEvent,
    OpportunityRun,
)
from mktcore.db.repo_features import _as_of_date, write_customer_features  # noqa: E402
from mktcore.db.repo_import import write_import  # noqa: E402
from mktcore.features.basis_diff import (  # noqa: E402
    CHALLENGER_BASIS,
    CHAMPION_BASIS,
    COMPARED_COLUMNS,
    compare_feature_bases,
    ledger_per_customer_frame,
)
from mktcore.ingest.cleaning import clean_frame  # noqa: E402
from mktcore.ingest.mapper import SchemaMapper  # noqa: E402
from mktcore.ingest.schema import ColumnRole  # noqa: E402
from mktcore.pipeline import run_analysis  # noqa: E402
from mktcore.security import EXTRA_GUARDED_ROUTES  # noqa: E402

_COLS = ["تاریخ", "مبلغ", "مشتری", "فاکتور", "کالا"]
_MAPPING = {
    ColumnRole.DATE: "تاریخ", ColumnRole.REVENUE: "مبلغ", ColumnRole.CUSTOMER_ID: "مشتری",
    ColumnRole.ORDER_ID: "فاکتور", ColumnRole.PRODUCT: "کالا",
}


@pytest.fixture(autouse=True)
def _isolate_schema_cache():
    reset_ensure_cache()
    yield
    reset_ensure_cache()


def _clean(rows: list[tuple]) -> pd.DataFrame:
    return clean_frame(SchemaMapper().apply(pd.DataFrame(rows, columns=_COLS), _MAPPING))


def _write(rows: list[tuple], db: Path, dataset_key: str = "a") -> pd.DataFrame:
    """همان مسیرِ قهرمان: دفتر کل + عکسِ ویژگی از فریمِ همین آپلود."""
    clean = _clean(rows)
    write_import(clean, kpis=compute_kpis(clean), db_path=db, dataset_key=dataset_key)
    bundle = run_analysis(clean, horizon=2, with_forecast=False)
    write_customer_features(clean, bundle, db_path=db)
    return clean


def _month_rows(month: int, customers: range, *, orders_per_customer: int = 2) -> list[tuple]:
    """هر مشتری در هر ماه چند فاکتور با کالاهای متمایز — بدون تساویِ درآمدِ کالا."""
    rows = []
    for c in customers:
        for k in range(orders_per_customer):
            day = 3 + k * 9 + (c % 3)
            rows.append((
                f"1402/{month:02d}/{day:02d}", 100_000 + c * 1_000 + k * 37_000,
                f"C{c}", f"F{month}-{c}-{k}", f"کالای {(c + k) % 4}",
            ))
    return rows


def _six_months(customers: range = range(12)) -> list[tuple]:
    rows: list[tuple] = []
    for m in range(1, 7):
        rows += _month_rows(m, customers)
    return rows


def _snapshot_counts(db: Path) -> tuple[int, int]:
    with session_scope(db) as session:
        return (
            int(session.scalar(select(func.count()).select_from(CustomerFeature))),
            int(session.scalar(select(func.count()).select_from(CustomerLifecycleEvent))),
        )


# ═══════════════════════════════════════════ ۱: هم‌ارزی روی تک‌فایل
def test_challenger_matches_champion_bit_for_bit_on_a_single_file(tmp_path):
    db = tmp_path / "app.db"
    clean = _write(_six_months(), db)
    as_of = _as_of_date(clean)
    before = _snapshot_counts(db)

    with session_scope(db) as session:
        diff = compare_feature_bases(session, 1, as_of=as_of)

    assert diff["as_of"] == as_of
    assert diff["champion"]["basis"] == CHAMPION_BASIS
    assert diff["challenger"]["basis"] == CHALLENGER_BASIS
    assert diff["champion"]["customers"] == diff["challenger"]["customers"] == 12
    assert diff["compared_customers"] == 12
    assert (diff["only_in_champion"], diff["only_in_challenger"]) == (0, 0)
    assert set(diff["columns"]) == set(COMPARED_COLUMNS)
    assert {k: v["mismatches"] for k, v in diff["columns"].items()} == dict.fromkeys(COMPARED_COLUMNS, 0)
    assert diff["lifecycle_changes"] == 0
    assert diff["identical"] is True and diff["written"] is False
    assert "بیت‌به‌بیت" in diff["note_fa"]
    assert _snapshot_counts(db) == before, "مقایسه چیزی ننوشت"


def test_ledger_frame_reproduces_the_champion_columns(tmp_path):
    """مقایسه‌ی مستقیمِ فریم با عکسِ نوشته‌شده — نه فقط شمارِ اختلاف."""
    db = tmp_path / "app.db"
    clean = _write(_six_months(range(6)), db)
    as_of = _as_of_date(clean)
    with session_scope(db) as session:
        frame = ledger_per_customer_frame(session, 1, as_of)
        snaps = {f.customer_id: f for f in session.scalars(select(CustomerFeature)).all()}
        assert set(frame.index) == set(snaps)
        for cid, row in frame.iterrows():
            snap = snaps[cid]
            assert (int(row["n_orders"]), int(row["n_lines"]), int(row["monetary_rial"])) == (
                snap.n_orders, snap.n_lines, snap.monetary_rial,
            ), cid
            assert row["top_product"] == snap.top_product, cid


# ═══════════════════════════════════════════ ۲: دو فایلِ ماهانه، مشتریِ غایب
def test_two_monthly_files_the_challenger_sees_the_absent_customer(tmp_path):
    db = tmp_path / "app.db"
    _write(_six_months(), db, dataset_key="h1")
    # ماهِ هفتم: همه می‌خرند جز C0
    later = _write(_month_rows(7, range(1, 12)), db, dataset_key="m7")
    as_of = _as_of_date(later)
    before = _snapshot_counts(db)

    with session_scope(db) as session:
        c0 = session.scalar(select(Customer.id).where(Customer.canonical_key == "C0"))
        champion_ids = set(session.scalars(
            select(CustomerFeature.customer_id).where(CustomerFeature.as_of_date == as_of)
        ).all())
        diff = compare_feature_bases(session, 1, as_of=as_of)

    assert c0 not in champion_ids, "قهرمان برای مشتریِ غایب از فایلِ ماهِ دوم ردیف ندارد"
    assert diff["only_in_challenger"] == 1 and diff["only_in_challenger_ids"] == [c0]
    assert diff["only_in_champion"] == 0
    assert diff["compared_customers"] == 11
    # مشتریِ غایب ۶ ماه قبل خرید کرده و حالا نه ⇒ مدعی گذارِ او را می‌بیند
    assert diff["challenger_transitions"] >= 1
    # مشتریانِ مشترک: قهرمان فقط ماهِ ۷ را می‌بیند، مدعی همه‌ی تاریخچه را
    assert diff["columns"]["n_orders"]["mismatches"] == 11
    assert diff["columns"]["monetary_rial"]["mismatches"] == 11
    assert diff["columns"]["tenure_days"]["mismatches"] == 11
    assert diff["columns"]["recency_days"]["mismatches"] == 0, "تازگی از آخرین خرید است و یکی است"
    example = diff["columns"]["n_orders"]["examples"][0]
    assert example["challenger"] > example["champion"]
    assert diff["identical"] is False and diff["written"] is False
    assert _snapshot_counts(db) == before, "مقایسه چیزی ننوشت"


# ═══════════════════════════════════════════ ۳: مسیر و هوک
def test_route_is_guarded_and_the_hook_records_a_summary(tmp_path, monkeypatch):
    from mktcore.config import get_settings

    assert "GET /api/v1/feature-basis-diff" in EXTRA_GUARDED_ROUTES

    monkeypatch.setenv("MKT_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    reset_ensure_cache()
    try:
        assert feature_basis_diff(as_of=None, examples=5)["available"] is False

        clean = _clean(_six_months())
        bundle = run_analysis(clean, horizon=2, with_forecast=False)
        out = record_analysis(
            clean, bundle, session_id="s-diff", filename="f.xlsx", dataset_key="d1",
            display_currency="تومان", file_currency="تومان",
        )
        assert out["posted"] is True
        summary = out["feature_basis_diff"]
        assert summary["identical"] is True and summary["written"] is False
        assert summary["columns"] == dict.fromkeys(COMPARED_COLUMNS, 0)
        assert "only_in_challenger_ids" not in summary

        body = feature_basis_diff(as_of=None, examples=5)
        assert body["available"] is True and body["as_of"] == _as_of_date(clean)
        assert body["identical"] is True
        assert feature_basis_diff(as_of="1999-01-01", examples=5)["challenger"]["customers"] == 0

        run_id = (out.get("opportunities") or {}).get("run_id")
        assert run_id, "موتور فرصت‌ها باید اجرا شده باشد"
        with session_scope() as session:
            notes = json.loads(session.get(OpportunityRun, run_id).notes_json)
        assert notes["feature_basis_diff"]["identical"] is True
        assert notes["feature_basis_diff"]["as_of"] == _as_of_date(clean)
    finally:
        get_settings.cache_clear()
        reset_ensure_cache()
