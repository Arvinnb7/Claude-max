"""§۷.۱: ردیفِ ردشده باید بماند — تنها جایی که داده فعالانه از بین می‌رفت.

## مسئله‌ای که این فایل پین می‌کند

ردیف‌های حذف‌شده‌ی فایل فقط در `exclusions.parquet` کنارِ نشست می‌ماندند. آن
فایل در فهرست `_HEAVY_FILES` است و سیاست نگه‌داری بعد از ۱۸۰ روز پاکش می‌کند.
یعنی پاسخِ «چرا فروشِ خردادِ پارسال کمتر از فاکتورها بود؟» بعد از شش ماه برای
همیشه از بین می‌رفت.

قاعده: ردیفِ ردشده در **دفتر کل** می‌نشیند، پس هرسِ فایل‌های نشست به آن
نمی‌رسد — و همراهش «چرا» و «چه کار کنم».
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

from mktcore.analysis.kpis import compute_kpis  # noqa: E402
from mktcore.db.engine import session_scope  # noqa: E402
from mktcore.db.migrations import reset_ensure_cache  # noqa: E402
from mktcore.db.models import ImportQuarantine, ImportRowRaw  # noqa: E402
from mktcore.db.repo_import import write_import  # noqa: E402
from mktcore.ingest.cleaning import (  # noqa: E402
    REASON_DUPLICATE,
    REASON_INVALID_AMOUNT,
    REASON_INVALID_DATE,
    clean_frame,
    get_exclusions,
)
from mktcore.ingest.mapper import SchemaMapper  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate():
    reset_ensure_cache()
    yield
    reset_ensure_cache()


def _dirty_frame() -> pd.DataFrame:
    """فایلی با هر سه نوع ردیفِ ردشدنی، کنارِ ردیف‌های سالم."""
    return pd.DataFrame({
        "تاریخ": [
            "1403/01/05", "1403/01/06", "چیزی که تاریخ نیست", "1403/01/07",
            "1403/01/08", "1403/01/08",
        ],
        "شماره سفارش": ["A-1", "A-2", "A-3", "A-4", "A-5", "A-5"],
        "کد مشتری": ["C1", "C2", "C3", "C4", "C5", "C5"],
        "نام محصول": ["الف", "ب", "ج", "د", "ه", "ه"],
        # ردیف چهارم عمداً **هیچ** راهی برای محاسبه‌ی مبلغ ندارد: نه مبلغ کل،
        # نه قیمت واحد. اگر فقط «مبلغ کل» خراب باشد، پاک‌سازی از تعداد×قیمت
        # بازسازی‌اش می‌کند و ردیف اصلاً رد نمی‌شود.
        "تعداد": ["1", "1", "1", "", "1", "1"],
        "قیمت واحد": ["100000", "200000", "300000", "", "500000", "500000"],
        "مبلغ کل": ["100000", "200000", "300000", "مبلغ ندارد", "500000", "500000"],
    })


def _ingest(db: Path) -> pd.DataFrame:
    raw = _dirty_frame()
    mapper = SchemaMapper()
    clean = clean_frame(mapper.apply(raw, mapper.auto_detect(raw).mapping))
    write_import(clean, kpis=compute_kpis(clean), db_path=db)
    return clean


def test_the_cleaner_now_records_a_code_next_to_the_persian_reason(tmp_path):
    """رشته‌ی آزاد با هر ویرایشِ متن می‌شکند؛ کد نمی‌شکند."""
    raw = _dirty_frame()
    mapper = SchemaMapper()
    clean = clean_frame(mapper.apply(raw, mapper.auto_detect(raw).mapping))

    excl = get_exclusions(clean)
    assert not excl.empty
    assert "کد دلیل" in excl.columns
    assert "دلیل" in excl.columns, "متنِ فارسی باید بماند (خروجی اکسل ممیزی)"
    assert set(excl["کد دلیل"]) <= {
        REASON_INVALID_DATE, REASON_INVALID_AMOUNT, REASON_DUPLICATE,
    }


def test_rejected_rows_land_in_the_ledger_with_a_reason_and_a_fix(tmp_path):
    db = tmp_path / "app.db"
    _ingest(db)

    with session_scope(db) as session:
        rows = session.scalars(select(ImportQuarantine)).all()
        payload = [
            (r.reason_code, r.reason_detail_fa, r.suggested_resolution_fa, r.row_number)
            for r in rows
        ]

    assert payload, "هیچ ردیفی قرنطینه نشد"
    codes = {code for code, _, _, _ in payload}
    assert REASON_INVALID_DATE in codes
    assert REASON_INVALID_AMOUNT in codes
    for _, detail, resolution, _ in payload:
        assert detail, "دلیلِ فارسی لازم است"
        assert resolution, "ردیفِ ردشده بدون «چه کار کنم؟» یک شکایت است، نه گزارش"


def test_the_raw_payload_of_a_rejected_row_is_kept(tmp_path):
    """بدون خودِ ردیف، «دلیل» به تنهایی قابل بررسی نیست."""
    import json

    db = tmp_path / "app.db"
    _ingest(db)

    with session_scope(db) as session:
        row = session.scalars(
            select(ImportQuarantine).where(
                ImportQuarantine.reason_code == REASON_INVALID_DATE
            )
        ).first()
        raw = json.loads(row.raw_payload_json)

    assert raw, "بارِ خامِ ردیف باید ذخیره شود"
    assert any("C3" == str(v) for v in raw.values()), raw


def test_quarantine_survives_the_retention_policy(tmp_path, monkeypatch):
    """دروازه‌ی پذیرش این گام: همان چیزی که امروز از بین می‌رود، بماند."""
    from api.persistence import store

    db = tmp_path / "app.db"
    _ingest(db)

    with session_scope(db) as session:
        before = session.scalar(select(ImportQuarantine).limit(1))
        before_id = before.id

    # سخت‌ترین حالتِ هرس: همه‌ی فایل‌های سنگینِ نشست پاک شوند
    store.run_retention(raw_days=1, heavy_days=1, jobs_days=1)

    with session_scope(db) as session:
        after = session.get(ImportQuarantine, before_id)

    assert after is not None, "ردیفِ قرنطینه نباید با هرس از بین برود"
    assert after.reason_detail_fa


def test_resolving_marks_the_row_instead_of_deleting_it(tmp_path):
    """تاریخ باید بماند: ردیفِ رسیدگی‌شده پاک نمی‌شود، بسته می‌شود."""
    from mktcore.db.base import now_ts

    db = tmp_path / "app.db"
    _ingest(db)

    with session_scope(db) as session:
        row = session.scalars(select(ImportQuarantine)).first()
        row.resolved_at = now_ts()
        row.resolved_by = "آزمون"
        row_id = row.id

    with session_scope(db) as session:
        still_there = session.get(ImportQuarantine, row_id)

    assert still_there is not None
    assert still_there.resolved_by == "آزمون"
    assert still_there.raw_payload_json


def test_reimporting_the_same_file_does_not_duplicate_quarantine_rows(tmp_path):
    """بارگذاری دوباره باید idempotent بماند — قرنطینه هم همین‌طور."""
    db = tmp_path / "app.db"
    _ingest(db)
    with session_scope(db) as session:
        first = len(session.scalars(select(ImportQuarantine)).all())

    _ingest(db)
    with session_scope(db) as session:
        rows = session.scalars(select(ImportQuarantine)).all()
        batches = {r.batch_id for r in rows}

    # هر بارگذاری یک `batch` تازه است، پس ردیف‌ها تکرار می‌شوند ولی **به‌تفکیک
    # بارگذاری** — یعنی تاریخچه، نه آشغال. درونِ یک بارگذاری تکرار ممنوع است.
    assert len(batches) == 2
    per_batch = {b: len([r for r in rows if r.batch_id == b]) for b in batches}
    assert set(per_batch.values()) == {first}


def test_raw_rows_are_captured_for_a_small_file(tmp_path):
    db = tmp_path / "app.db"
    clean = _ingest(db)

    with session_scope(db) as session:
        rows = session.scalars(select(ImportRowRaw)).all()

    assert len(rows) == len(clean)
    assert all(r.parse_status == ImportRowRaw.PARSE_OK for r in rows)
    assert all(r.row_hash for r in rows)


def test_a_file_over_the_cap_says_so_instead_of_pretending(tmp_path, monkeypatch):
    """«ذخیره نشد» باید گفته شود، وگرنه کاربر گمان می‌کند ممیزیِ کامل دارد."""
    import json

    from mktcore.config import get_settings
    from mktcore.db.models import ImportBatch

    monkeypatch.setattr(get_settings(), "mkt_raw_rows_cap", 2, raising=False)
    db = tmp_path / "app.db"
    _ingest(db)

    with session_scope(db) as session:
        assert session.scalars(select(ImportRowRaw)).all() == []
        batch = session.scalars(select(ImportBatch)).first()
        notes = json.loads(batch.notes_json)
        # ولی قرنطینه بی‌توجه به سقف نوشته می‌شود
        assert session.scalars(select(ImportQuarantine)).all()

    assert notes["raw_rows_captured"] == 0
    assert notes["raw_rows_skipped"] > 0
    assert "ذخیره نشد" in notes["raw_capture_note_fa"]
    assert "قرنطینه" in notes["raw_capture_note_fa"]


def test_a_catastrophically_broken_file_does_not_store_unbounded_detail(
    tmp_path, monkeypatch,
):
    """فایلِ به‌کل خراب نباید ده‌ها هزار JSON بنویسد — ولی شمارِ کل باید بماند."""
    import json

    from mktcore.db import repo_import
    from mktcore.db.models import ImportBatch

    monkeypatch.setattr(repo_import, "QUARANTINE_ROW_CAP", 2, raising=True)
    db = tmp_path / "app.db"
    _ingest(db)

    with session_scope(db) as session:
        rows = session.scalars(select(ImportQuarantine)).all()
        batch = session.scalars(select(ImportBatch)).first()
        notes = json.loads(batch.notes_json)
        rows_invalid = batch.rows_invalid
        rows_duplicate = batch.rows_duplicate

    assert len(rows) == 2, "جزئیات باید بریده شود"
    assert notes["quarantine_detail_truncated"] is True
    assert notes["rejected_rows_total"] > 2
    # شمارِ کل هرگز از بین نمی‌رود
    assert (rows_invalid or 0) + (rows_duplicate or 0) == notes["rejected_rows_total"]
