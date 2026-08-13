"""پل دفتر کل: باید بنویسد، و اگر نتوانست باید بی‌صدا کنار برود.

مهم‌ترین ادعا: هیچ خطایی در لایه‌ی جدید نمی‌تواند تحلیل و داشبورد را بشکند.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from api.canonical_hook import record_analysis  # noqa: E402
from api.main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from mktcore.db.migrations import reset_ensure_cache  # noqa: E402
from mktcore.ingest.cleaning import clean_frame  # noqa: E402
from mktcore.ingest.mapper import SchemaMapper  # noqa: E402
from mktcore.pipeline import run_analysis  # noqa: E402
from mktcore.synthetic import generate_synthetic_sales  # noqa: E402

from .conftest import poll_job  # noqa: E402

client = TestClient(app)


@pytest.fixture
def analyzed():
    raw = generate_synthetic_sales(seed=5, days=200)
    mapper = SchemaMapper()
    clean = clean_frame(mapper.apply(raw, mapper.auto_detect(raw).mapping))
    bundle = run_analysis(clean, horizon=3, with_forecast=False)
    return clean, bundle


def test_hook_writes_and_reports(analyzed, tmp_path, monkeypatch):
    reset_ensure_cache()
    monkeypatch.setenv("MKT_DATA_DIR", str(tmp_path))
    from mktcore.config import get_settings
    get_settings.cache_clear()

    clean, bundle = analyzed
    out = record_analysis(clean, bundle, session_id="s-hook", filename="x.xlsx",
                          dataset_key="deadbeef", display_currency="تومان")
    get_settings.cache_clear()
    reset_ensure_cache()

    assert out is not None
    assert out["ok"] is True
    assert out["lines_inserted"] > 0
    assert out["reconcile_status"].startswith("RECONCILED")
    assert any(c["id"] == "L04" for c in out["checks"])


def test_hook_never_raises_on_internal_failure(analyzed, monkeypatch):
    """شکست دفتر کل باید به یک گزارش تبدیل شود، نه استثنا."""
    import mktcore.db.repo_import as repo

    def _boom(*_args, **_kwargs):
        raise RuntimeError("دیتابیس در دسترس نیست")

    monkeypatch.setattr(repo, "write_import", _boom)
    clean, bundle = analyzed
    out = record_analysis(clean, bundle, session_id="s-fail")

    assert out is not None
    assert out["ok"] is False
    assert "دست‌نخورده" in out["note_fa"]


def test_hook_can_be_switched_off(analyzed, monkeypatch):
    monkeypatch.setenv("MKT_CANONICAL_ENABLE", "0")
    from mktcore.config import get_settings
    get_settings.cache_clear()
    try:
        clean, bundle = analyzed
        assert record_analysis(clean, bundle, session_id="s-off") is None
    finally:
        monkeypatch.delenv("MKT_CANONICAL_ENABLE", raising=False)
        get_settings.cache_clear()


def test_analyze_endpoint_still_returns_the_same_contract():
    """قرارداد پاسخ تحلیل نباید تغییر کند؛ `canonical` فقط کلیدی افزوده است."""
    r = client.post("/api/sample")
    assert r.status_code == 200
    data = r.json()
    roles = {x["role"]: x["suggested"] for x in data["roles"]}
    mapping = {role: col for role, col in roles.items() if col}
    r = client.post("/api/analyze", json={
        "session_id": data["session_id"], "mapping": mapping, "horizon": 3,
    })
    assert r.status_code == 200, r.text
    payload = poll_job(client, r.json()["job_id"])

    for key in ("kpis", "quality", "manifest", "currency"):
        assert key in payload
    assert "canonical" in payload  # افزودنی
    assert isinstance(payload["canonical"]["ok"], bool)
