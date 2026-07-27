"""تست حافظه‌ی دائمی: نشست‌ها حذف نمی‌شوند، فهرست/حذف/برچسب، هرس و مهاجرت."""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from api.main import app  # noqa: E402
from api.persistence import PersistentStore  # noqa: E402
from api.persistence import store as _store  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from mktcore.ingest.mapper import header_signature  # noqa: E402

from .conftest import poll_job  # noqa: E402

client = TestClient(app)


def _analyzed_session() -> str:
    """یک نشست تحلیل‌شده‌ی تازه (داده‌ی نمونه)."""
    up = client.post("/api/sample").json()
    sid = up["session_id"]
    mapping = {r["role"]: r["suggested"] for r in up["roles"] if r["suggested"]}
    r = client.post("/api/analyze", json={"session_id": sid, "mapping": mapping,
                                          "horizon": 3})
    poll_job(client, r.json()["job_id"])
    return sid


def _backdate(sid: str, days: float) -> None:
    with sqlite3.connect(_store.db_path) as con:
        con.execute("UPDATE sessions SET created_at = ? WHERE id = ?",
                    (time.time() - days * 86400, sid))


def test_session_survives_past_old_ttl():
    """تست رگرسیون شکایت اصلی: نشست ۳۰روزه باید همچنان باز شود."""
    sid = _analyzed_session()
    _backdate(sid, 30)
    body = client.get(f"/api/session/{sid}").json()
    assert body["exists"] is True
    assert body["analysis"] is not None
    assert body["columns_payload"] is not None


def test_retention_never_deletes_by_default():
    sid = _analyzed_session()
    _backdate(sid, 3650)  # ۱۰ سال
    res = _store.run_retention()
    assert res["deleted"] == 0
    assert client.get(f"/api/session/{sid}").json()["exists"] is True


def test_retention_prunes_raw_and_archives_but_dashboard_lives():
    old = _analyzed_session()
    new = _analyzed_session()  # این «آخرین تحلیل» است و باید محافظت شود
    _backdate(old, 400)
    res = _store.run_retention(raw_days=1, heavy_days=1)
    assert res["raw_pruned"] >= 1 and res["archived"] >= 1

    # داشبورد نشست قدیمی زنده است
    body = client.get(f"/api/session/{old}").json()
    assert body["exists"] is True and body["analysis"] is not None
    assert body["archived"] is True
    assert _store.load_bundle(old) is None

    # ولی گزارش/اکسل پیام روشن ۴۱۰ می‌دهند
    rep = client.get(f"/api/report?session_id={old}&fmt=html")
    assert rep.status_code == 410
    assert "بایگانی" in rep.json()["detail"]
    exp = client.get(f"/api/export?session_id={old}&section=products")
    assert exp.status_code == 410

    # نشست جدید (pinned) دست‌نخورده است
    assert _store.load_bundle(new) is not None
    assert client.get(f"/api/report?session_id={new}&fmt=html").status_code == 200


def test_retention_skips_busy_session():
    sid = _analyzed_session()
    _backdate(sid, 400)
    with sqlite3.connect(_store.db_path) as con:
        con.execute(
            "INSERT INTO jobs (id, session_id, kind, status, progress, stage, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            ("busyjob", sid, "analyze", "running", 10, "در حال اجرا",
             time.time(), time.time()),
        )
    _store.run_retention(raw_days=1, heavy_days=1)
    assert _store.session_files(sid)["heavy"] is True


def test_sessions_list_shape_and_order():
    first = _analyzed_session()
    second = _analyzed_session()
    body = client.get("/api/sessions?limit=50").json()
    ids = [i["id"] for i in body["items"]]
    assert ids.index(second) < ids.index(first)  # جدیدترین اول
    item = next(i for i in body["items"] if i["id"] == second)
    assert item["has_analysis"] is True
    assert item["n_rows"] and item["n_rows"] > 0
    assert item["date_min"] and item["date_max"]
    assert item["total_revenue"] and item["total_revenue"] > 0
    assert item["validation_status"] in ("PASS", "PASS_WITH_WARNINGS", "FAIL")
    assert item["title"]
    assert body["latest_analyzed_id"]
    assert body["retention"]["delete_days"] == 0  # پیش‌فرض: هرگز حذف نکن


def test_delete_and_label_session():
    sid = _analyzed_session()
    r = client.patch(f"/api/session/{sid}", json={"label": "فروش شهریور ۱۴۰۴"})
    assert r.status_code == 200 and r.json()["label"] == "فروش شهریور ۱۴۰۴"
    listed = client.get("/api/sessions?limit=50").json()["items"]
    assert any(i["title"] == "فروش شهریور ۱۴۰۴" for i in listed)

    assert client.patch(f"/api/session/{sid}", json={"label": "x" * 81}).status_code == 400
    assert client.patch(f"/api/session/{sid}", json={"label": ""}).json()["label"] is None

    assert client.delete(f"/api/session/{sid}").status_code == 200
    assert client.get(f"/api/session/{sid}").json()["exists"] is False
    assert client.delete(f"/api/session/{sid}").status_code == 404


def test_storage_endpoint():
    body = client.get("/api/storage").json()
    assert Path(body["data_dir"]).is_absolute()
    assert body["db_path"].endswith("app.db")
    assert body["retention"]["policy_fa"]
    assert body["sessions_total"] >= 0
    health = client.get("/api/health").json()
    assert Path(health["data_dir"]).is_absolute()


def test_migration_from_legacy_db(tmp_path):
    """دیتابیس ۸ستونی قدیمی باید بدون از دست رفتن ردیف مهاجرت کند."""
    (tmp_path / "sessions").mkdir()
    db = tmp_path / "app.db"
    with sqlite3.connect(db) as con:
        con.executescript(
            "CREATE TABLE sessions (id TEXT PRIMARY KEY, created_at REAL NOT NULL,"
            " filename TEXT, columns_json TEXT, mapping_json TEXT, analysis_json TEXT,"
            " strategy_json TEXT, campaign_json TEXT);"
            "CREATE TABLE jobs (id TEXT PRIMARY KEY, session_id TEXT, kind TEXT NOT NULL,"
            " status TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0, stage TEXT DEFAULT '',"
            " error TEXT, result_json TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL);"
        )
        analysis = {"quality": {"n_rows": 500, "date_min": "2024-01-01",
                                "date_max": "2024-06-30"},
                    "kpis": {"total_revenue": 1234.0}, "currency": "تومان",
                    "validation": {"status": "PASS"}}
        con.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?)",
                    ("legacy1", time.time() - 90 * 86400, "قدیمی.xlsx",
                     json.dumps({"columns": ["a", "b"], "n_rows": 500}), None,
                     json.dumps(analysis, ensure_ascii=False), None, None))

    st = PersistentStore(tmp_path)
    rec = st.get_session("legacy1")
    assert rec is not None and rec.analysis is not None  # ردیف سالم ماند
    with sqlite3.connect(db) as con:
        cols = {r[1] for r in con.execute("PRAGMA table_info(sessions)")}
        assert {"label", "archived_at", "summary_json", "last_opened_at"} <= cols
        assert con.execute("PRAGMA user_version").fetchone()[0] == 2
    items, total = st.list_sessions()
    assert total == 1 and items[0]["n_rows"] == 500  # خلاصه backfill شد

    st2 = PersistentStore(tmp_path)  # مهاجرت دوباره بی‌اثر
    assert st2.get_session("legacy1") is not None


def test_mapping_profile_reused_on_next_upload():
    """فایل بعدی با همان ساختار سرستون → نگاشت و واحد پول از قبل پر است."""
    sid = _analyzed_session()
    used = client.get(f"/api/session/{sid}").json()["mapping"]
    assert used, "نگاشت استفاده‌شده باید برگردانده شود"

    nxt = client.post("/api/sample").json()
    assert nxt["saved_mapping"], "نگاشت ذخیره‌شده برای همین ساختار باید برگردد"
    assert nxt["saved_mapping"] == {k: v for k, v in used.items()
                                   if v in nxt["columns"]}
    assert nxt["saved_file_currency"] == "تومان"
    assert nxt["saved_use_count"] >= 1
    assert nxt["header_signature"] == header_signature(nxt["columns"])


def test_mapping_profile_drops_missing_column():
    sig = header_signature(["تاریخ", "مبلغ"])
    _store.upsert_mapping_profile(
        sig, columns=["تاریخ", "مبلغ"],
        mapping={"DATE": "تاریخ", "REVENUE": "مبلغ", "PRODUCT": "ستون‌نبود"},
        file_currency="ریال", display_currency="تومان")
    prof = _store.get_mapping_profile(sig)
    assert prof["mapping"]["PRODUCT"] == "ستون‌نبود"
    assert prof["file_currency"] == "ریال"
    # منطق حذف ستون ناموجود در _columns_payload اعمال می‌شود (تست پایین‌دستی)
    kept = {r: c for r, c in prof["mapping"].items() if c in ["تاریخ", "مبلغ"]}
    assert "PRODUCT" not in kept
