"""سنجه‌ی آمادگیِ فاز ۵ — «چقدر تا دروازه مانده»، صادقانه.

* «هیچ کمپینِ دوبازویی نداریم» ≠ «صفر مشاهده داریم».
* قیمتی که ستونش نیست ⇒ `None`، نه صفر.
* آستانه‌ی دروازه (§۲۹.۶) تنظیم‌پذیر است و در پاسخ گفته می‌شود پیش‌فرض است یا نه.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from api.main import app  # noqa: E402

from mktcore.analysis.kpis import compute_kpis  # noqa: E402
from mktcore.db.migrations import reset_ensure_cache  # noqa: E402
from mktcore.db.repo_import import write_import  # noqa: E402
from mktcore.experiments.readiness import phase5_readiness  # noqa: E402
from mktcore.ingest.cleaning import clean_frame  # noqa: E402
from mktcore.ingest.mapper import SchemaMapper  # noqa: E402
from mktcore.settings_store import set_data_gate_thresholds  # noqa: E402
from mktcore.uplift.empirical import MIN_CELL_OBSERVATIONS  # noqa: E402

from .conftest import poll_job  # noqa: E402
from .test_golden_scenarios import _COLS, _MAPPING, _discount_rows  # noqa: E402

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolate():
    reset_ensure_cache()
    yield
    reset_ensure_cache()


def test_no_ledger_is_reported_as_unavailable(tmp_path):
    body = phase5_readiness(db_path=tmp_path / "empty.db")
    assert body["available"] is False


def test_without_two_armed_campaigns_nothing_is_ready_and_it_says_why(tmp_path):
    db = tmp_path / "app.db"
    raw = pd.DataFrame([r[:-1] for r in _discount_rows(amount=False)], columns=_COLS)
    clean = clean_frame(SchemaMapper().apply(raw, _MAPPING))
    write_import(clean, kpis=compute_kpis(clean), db_path=db)

    body = phase5_readiness(db_path=db)

    assert body["available"] is True
    assert body["uplift"]["two_armed_campaigns"] == 0
    assert body["uplift"]["cells"] == []
    assert body["uplift"]["ready"] is False
    assert "دوبازویی" in body["uplift"]["note_fa"]
    assert body["overall"]["ready"] is False
    # این فایل ستون قیمت واحد ندارد ⇒ نامعلوم، نه صفر
    assert body["price_variation"]["ready"] is False
    assert body["price_variation"]["median_cv"] is None
    assert body["thresholds"] == {
        "min_cell_observations": MIN_CELL_OBSERVATIONS, "configured": False,
    }


def test_the_gate_threshold_is_configurable_and_bounded(tmp_path):
    db = tmp_path / "app.db"
    raw = pd.DataFrame([r[:-1] for r in _discount_rows(amount=False)], columns=_COLS)
    clean = clean_frame(SchemaMapper().apply(raw, _MAPPING))
    write_import(clean, kpis=compute_kpis(clean), db_path=db)

    gates = set_data_gate_thresholds(min_cell_observations=25, db_path=db)
    assert gates == {"min_cell_observations": 25, "configured": True}
    assert phase5_readiness(db_path=db)["thresholds"]["min_cell_observations"] == 25

    with pytest.raises(ValueError):
        set_data_gate_thresholds(min_cell_observations=2, db_path=db)
    assert set_data_gate_thresholds(min_cell_observations=None, db_path=db)["configured"] is False


def test_the_api_reports_readiness_on_the_sample_without_claiming_ready():
    """روی داده‌ی نمونه هیچ سلولی «آماده» نیست و اعداد با هم می‌خوانند."""
    listing = client.get("/api/v1/customers?limit=1").json()
    if not listing.get("items"):
        sample = client.post("/api/sample").json()
        mapping = {x["role"]: x["suggested"] for x in sample["roles"] if x["suggested"]}
        job = client.post("/api/analyze", json={
            "session_id": sample["session_id"], "mapping": mapping, "horizon": 3,
        })
        poll_job(client, job.json()["job_id"])

    body = client.get("/api/v1/phase5-readiness").json()

    assert body["available"] is True
    uplift = body["uplift"]
    assert uplift["cells_ready"] <= uplift["cells_total"]
    assert uplift["cells_with_offer"] <= uplift["cells_total"]
    assert body["overall"]["ready"] is False
    assert body["overall"]["note_fa"]
    # داده‌ی نمونه قیمت واحد دارد؛ پوشش باید عددِ واقعی باشد نه None
    assert body["price_variation"]["coverage"] is not None
    assert body["price_variation"]["note_fa"]

    gates = client.get("/api/v1/data-gates").json()
    assert gates["available"] is True
    assert gates["min_cell_observations"] >= 5
