"""نگاشتِ نسخه‌دارِ منبع (§۸.۲ — برشِ اول).

ادعاها: همان فایل با دو نگاشت ⇒ دو نسخه؛ تحلیلِ دوباره با همان نگاشت نسخه‌ی تازه
نمی‌سازد؛ دسته‌ی هر تحلیل (حتی مسدود) نسخه‌اش را می‌داند؛ `GET /source-mappings`
تاریخچه را با ترتیب می‌دهد؛ جدولِ legacy `mapping_profiles` دست نمی‌خورد.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import func, select, text

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from api.canonical_hook import record_analysis  # noqa: E402
from api.v1 import get_import, list_imports, source_mappings  # noqa: E402

from mktcore.analysis.kpis import compute_kpis  # noqa: E402
from mktcore.db import session_scope  # noqa: E402
from mktcore.db.engine import get_engine  # noqa: E402
from mktcore.db.migrations import (  # noqa: E402
    _MIGRATION_TABLE,
    _MIGRATION_TABLE_DDL,
    _MIGRATIONS,
    CANONICAL_SCHEMA_VERSION,
    ensure_schema,
    reset_ensure_cache,
)
from mktcore.db.models import ImportBatch, MappingProfileVersion  # noqa: E402
from mktcore.db.repo_import import write_import  # noqa: E402
from mktcore.db.repo_mappings import mapping_hash, mapping_history  # noqa: E402
from mktcore.ingest.cleaning import clean_frame  # noqa: E402
from mktcore.ingest.mapper import SchemaMapper, header_signature  # noqa: E402
from mktcore.ingest.schema import ColumnRole  # noqa: E402
from mktcore.pipeline import run_analysis  # noqa: E402

from .test_offer_ledger import _insert_minimal  # noqa: E402

_COLS = ["تاریخ", "مبلغ", "مشتری", "فاکتور", "کالا", "کد"]
_MAPPING_A = {
    ColumnRole.DATE: "تاریخ", ColumnRole.REVENUE: "مبلغ", ColumnRole.CUSTOMER_ID: "مشتری",
    ColumnRole.ORDER_ID: "فاکتور", ColumnRole.PRODUCT: "کالا",
}
# همان فایل، ولی «کد» به‌جای «مشتری» شناسه‌ی مشتری است
_MAPPING_B = {**_MAPPING_A, ColumnRole.CUSTOMER_ID: "کد"}


@pytest.fixture(autouse=True)
def _isolate_schema_cache():
    reset_ensure_cache()
    yield
    reset_ensure_cache()


def _rows(n: int = 20) -> list[tuple]:
    return [(f"1402/{(i % 9) + 1:02d}/05", 100_000 + i, f"C{i % 5}", f"F{i}", "کالا", f"K{i % 4}")
            for i in range(n)]


def _clean(mapping) -> pd.DataFrame:
    return clean_frame(SchemaMapper().apply(pd.DataFrame(_rows(), columns=_COLS), mapping))


def _profile(mapping, *, file_currency="تومان") -> dict:
    return {
        "signature": header_signature(_COLS), "columns": list(_COLS),
        "mapping": {r.value: c for r, c in mapping.items()},
        "file_currency": file_currency, "display_currency": "تومان",
    }


def _versions(db: Path) -> list[tuple[int, str]]:
    with session_scope(db) as session:
        return [
            (v.version, v.mapping_hash)
            for v in session.scalars(
                select(MappingProfileVersion).order_by(MappingProfileVersion.version)
            ).all()
        ]


# ═══════════════════════════════════ دو نگاشت ⇒ دو نسخه؛ همان نگاشت ⇒ همان نسخه
def test_same_file_with_two_mappings_gets_two_versions_and_a_rerun_reuses_one(tmp_path):
    db = tmp_path / "app.db"
    clean_a = _clean(_MAPPING_A)
    first = write_import(clean_a, kpis=compute_kpis(clean_a), db_path=db, dataset_key="f",
                         mapping_profile=_profile(_MAPPING_A))
    clean_b = _clean(_MAPPING_B)
    second = write_import(clean_b, kpis=compute_kpis(clean_b), db_path=db, dataset_key="f",
                          mapping_profile=_profile(_MAPPING_B))
    third = write_import(clean_a, kpis=compute_kpis(clean_a), db_path=db, dataset_key="f",
                         mapping_profile=_profile(_MAPPING_A))
    # واحدِ پولِ متفاوت با همان نقش‌ها هم نگاشتِ متفاوتی است (ضریبِ ۱۰)
    fourth = write_import(clean_a, kpis=compute_kpis(clean_a), db_path=db, dataset_key="f",
                          mapping_profile=_profile(_MAPPING_A, file_currency="ریال"))

    assert [v for v, _ in _versions(db)] == [1, 2, 3]
    with session_scope(db) as session:
        by_id = {b.id: (b.mapping_signature, b.mapping_version)
                 for b in session.scalars(select(ImportBatch)).all()}
    sig = header_signature(_COLS)
    assert by_id[first.batch_id] == (sig, 1)
    assert by_id[second.batch_id] == (sig, 2)
    assert by_id[third.batch_id] == (sig, 1), "تحلیلِ دوباره با همان نگاشت نسخه‌ی تازه نمی‌سازد"
    assert by_id[fourth.batch_id] == (sig, 3)
    assert mapping_hash({"a": "x"}, "تومان", "تومان") == mapping_hash({"a": "x"}, "تومان", "تومان")
    assert mapping_hash({"a": "x"}, "تومان", "تومان") != mapping_hash({"a": "x"}, "ریال", "تومان")

    with session_scope(db) as session:
        history = mapping_history(session, 1)
    assert len(history) == 1 and history[0]["signature"] == sig
    assert history[0]["versions"] == 3 and history[0]["latest_version"] == 3
    assert [h["version"] for h in history[0]["history"]] == [1, 2, 3]
    assert history[0]["history"][0]["mapping"]["CUSTOMER_ID"] == "مشتری"
    assert history[0]["history"][1]["mapping"]["CUSTOMER_ID"] == "کد"
    assert history[0]["history"][0]["batch_ids"] == [first.batch_id, third.batch_id]
    assert history[0]["history"][2]["file_currency"] == "ریال"
    assert history[0]["history"][0]["columns"] == _COLS


def test_a_batch_without_a_profile_has_no_version(tmp_path):
    db = tmp_path / "app.db"
    clean = _clean(_MAPPING_A)
    result = write_import(clean, kpis=compute_kpis(clean), db_path=db)
    with session_scope(db) as session:
        batch = session.get(ImportBatch, result.batch_id)
        assert (batch.mapping_signature, batch.mapping_version) == (None, None)
        assert session.scalar(select(func.count()).select_from(MappingProfileVersion)) == 0


# ═══════════════════════════════════ مسیرِ واقعی: هوک + API + دسته‌ی مسدود
def test_hook_records_the_version_and_the_api_lists_history(tmp_path, monkeypatch):
    from mktcore.config import get_settings

    monkeypatch.setenv("MKT_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    reset_ensure_cache()
    try:
        assert source_mappings(signature=None)["items"] == []

        clean = _clean(_MAPPING_A)
        bundle = run_analysis(clean, horizon=2, with_forecast=False)
        sig = header_signature(_COLS)
        out = record_analysis(
            clean, bundle, session_id="s1", filename="f.xlsx", dataset_key="d1",
            display_currency="تومان", file_currency="تومان",
            mapping={r.value: c for r, c in _MAPPING_A.items()},
            header_signature=sig, source_columns=list(_COLS),
        )
        assert out["posted"] is True
        detail = get_import(out["batch_id"])
        assert (detail["mapping_signature"], detail["mapping_version"]) == (sig, 1)
        assert list_imports(limit=5)["items"][0]["mapping_version"] == 1

        # همان فایل با نگاشتِ دوم — و این بار مسدود (§۸.۵): نسخه باز هم ثبت می‌شود
        clean_b = _clean(_MAPPING_B)
        blocked = write_import(
            clean_b, kpis=compute_kpis(clean_b), dataset_key="d1",
            posting_blockers=[{"check_id": "C04", "title": "قرارداد علامت", "detail": "مبهم"}],
            mapping_profile=_profile(_MAPPING_B),
        )
        assert blocked.posted is False
        assert get_import(blocked.batch_id)["mapping_version"] == 2

        body = source_mappings(signature=None)
        assert body["available"] is True and len(body["items"]) == 1
        assert [h["version"] for h in body["items"][0]["history"]] == [1, 2]
        assert body["items"][0]["history"][1]["batch_ids"] == [blocked.batch_id]
        assert source_mappings(signature="nope")["items"] == []
        assert source_mappings(signature=sig)["items"][0]["latest_version"] == 2
    finally:
        get_settings.cache_clear()
        reset_ensure_cache()


# ═══════════════════════════════════ مهاجرت ۱۹ روی دفترِ v18
def test_migration_19_adds_the_table_and_columns_idempotently(tmp_path):
    db = tmp_path / "v18.db"
    engine = get_engine(db)
    with engine.begin() as conn:
        conn.execute(text(_MIGRATION_TABLE_DDL))
        for version, name, fn in _MIGRATIONS:
            if version > 18:
                break
            fn(conn)
            conn.execute(
                text(f"INSERT INTO {_MIGRATION_TABLE} (version, name, applied_at) "
                     "VALUES (:v, :n, :t)"),
                {"v": version, "n": name, "t": 0.0},
            )
        _insert_minimal(conn, "businesses", slug="default", name="آزمون",
                        display_currency="تومان", created_at=0.0)
        _insert_minimal(conn, "import_batches", business_id=1, dataset_key="A",
                        revision=1, created_at=0.0)
        # مهاجرت ۱ با `create_all` از مدل‌های **امروز** می‌سازد؛ برای شبیه‌سازیِ دفترِ
        # واقعیِ v18، جدول و ستون‌های تازه را برمی‌داریم.
        conn.exec_driver_sql("DROP TABLE mapping_profile_versions")
        conn.exec_driver_sql("DROP INDEX IF EXISTS ix_import_batches_mapping_signature")
        conn.exec_driver_sql("ALTER TABLE import_batches DROP COLUMN mapping_signature")
        conn.exec_driver_sql("ALTER TABLE import_batches DROP COLUMN mapping_version")
        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(import_batches)")}
        assert "mapping_version" not in columns
        tables = {row[0] for row in conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "mapping_profile_versions" not in tables

    assert ensure_schema(db, force=True) == CANONICAL_SCHEMA_VERSION == 19
    with engine.begin() as conn:
        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(import_batches)")}
        assert {"mapping_signature", "mapping_version"} <= columns
        tables = {row[0] for row in conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "mapping_profile_versions" in tables
        assert conn.exec_driver_sql(
            "SELECT mapping_version FROM import_batches WHERE id = 1").scalar() is None
    ensure_schema(db, force=True)  # اجرای دوباره بی‌اثر
    with session_scope(db) as session:
        assert session.scalar(select(func.count()).select_from(ImportBatch)) == 1


def test_legacy_mapping_profiles_table_is_untouched():
    """جدولِ legacy در metadata نیست و مهاجرت ۱۹ به آن دست نمی‌زند."""
    from mktcore.db.models import Base

    assert "mapping_profiles" not in Base.metadata.tables
    assert "mapping_profile_versions" in Base.metadata.tables
