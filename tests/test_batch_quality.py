"""§۸.۵ «به‌ازای هر دسته»: ابعادِ کیفیت کنارِ خودِ بارگذاری ثبت می‌شوند.

`GET /data-quality` هفت بُعد را از کلِ دفتر کل می‌گیرد و بارگذاریِ خراب در میانگین گم
می‌شود. حالا هر بارگذاری ابعادِ خودش را در `notes_json` دارد و `GET /imports/{id}` و
فهرستِ بارگذاری‌ها آن را برمی‌گردانند. قراردادِ `GET /data-quality` بیت‌به‌بیت همان است.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from api.v1 import _batch_quality, data_quality, get_import, list_imports  # noqa: E402

from mktcore.analysis.kpis import compute_kpis  # noqa: E402
from mktcore.db import session_scope  # noqa: E402
from mktcore.db.migrations import reset_ensure_cache  # noqa: E402
from mktcore.db.models import ImportBatch  # noqa: E402
from mktcore.db.repo_import import write_import  # noqa: E402
from mktcore.ingest.cleaning import clean_frame  # noqa: E402
from mktcore.ingest.mapper import SchemaMapper  # noqa: E402
from mktcore.ingest.schema import ColumnRole  # noqa: E402

_COLS = ["تاریخ", "مبلغ", "مشتری", "فاکتور", "کالا", "شعبه"]
_MAPPING = {
    ColumnRole.DATE: "تاریخ", ColumnRole.REVENUE: "مبلغ", ColumnRole.CUSTOMER_ID: "مشتری",
    ColumnRole.ORDER_ID: "فاکتور", ColumnRole.PRODUCT: "کالا", ColumnRole.BRANCH: "شعبه",
}
_MAPPING_NO_CUSTOMER = {k: v for k, v in _MAPPING.items() if k is not ColumnRole.CUSTOMER_ID}


@pytest.fixture
def isolated_ledger(tmp_path, monkeypatch):
    from mktcore.config import get_settings

    reset_ensure_cache()
    monkeypatch.setenv("MKT_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()
    reset_ensure_cache()


def _rows(month: int, n: int = 20) -> list[tuple]:
    return [(f"1402/{month:02d}/{(i % 27) + 1:02d}", 100_000 + i, f"C{i % 5}", f"F{month}-{i}",
             f"کالای {i % 3}", "الف" if i % 2 else "") for i in range(n)]


def _clean(rows: list[tuple], mapping=_MAPPING) -> pd.DataFrame:
    return clean_frame(SchemaMapper().apply(pd.DataFrame(rows, columns=_COLS), mapping))


def _dims(payload: dict) -> dict[str, dict]:
    return {d["id"]: d for d in payload["quality_dimensions"]}


# ═══════════════════════════ دو فایلِ ماهانه؛ دومی بدون ستون مشتری
def test_each_batch_reports_its_own_dimensions_and_the_dashboard_is_unchanged(isolated_ledger):
    first = _clean(_rows(1))
    second = _clean(_rows(2), _MAPPING_NO_CUSTOMER)
    a = write_import(first, kpis=compute_kpis(first), dataset_key="m1")
    b = write_import(second, kpis=compute_kpis(second), dataset_key="m2")

    detail_a, detail_b = get_import(a.batch_id), get_import(b.batch_id)
    assert detail_a["quality_basis"] == detail_b["quality_basis"] == "ledger"
    assert _dims(detail_a)["customer_identifier_rate"]["value"] == 1.0
    assert _dims(detail_b)["customer_identifier_rate"]["value"] == 0.0
    assert _dims(detail_b)["customer_identifier_rate"]["severity"] == "warning"
    # شعبه فقط برای نیمی از خطوط ⇒ پوششِ شعبه به‌ازای سفارش‌های همین دسته
    assert 0 < _dims(detail_a)["branch_coverage"]["value"] < 1
    assert _dims(detail_a)["date_range_consistency"]["value"] == 1.0
    assert detail_a["quality_summary"]["dimensions_total"] == 9
    assert detail_a["quality_summary"]["dimensions_measured"] >= 8

    # داشبورد همان ترکیبِ کلِ دفتر کل را می‌دهد: ۲۰ خطِ با مشتری از ۴۰ خط
    dashboard = data_quality()
    combined = {d["id"]: d for d in dashboard["dimensions"]}
    assert combined["customer_identifier_rate"]["value"] == 0.5
    # و `latest_batch` همان کلیدهای قبلی را دارد — بدون ابعادِ به‌ازای دسته
    assert "quality_dimensions" not in dashboard["latest_batch"]
    assert "quality_summary" not in dashboard["latest_batch"]

    items = {item["id"]: item for item in list_imports(limit=10)["items"]}
    assert {a.batch_id, b.batch_id} <= set(items)
    assert _dims(items[b.batch_id])["customer_identifier_rate"]["value"] == 0.0
    assert _dims(items[a.batch_id])["customer_identifier_rate"]["value"] == 1.0


def test_dimensions_are_persisted_in_the_batch_notes(isolated_ledger):
    clean = _clean(_rows(3))
    result = write_import(clean, kpis=compute_kpis(clean))
    with session_scope() as session:
        notes = json.loads(session.get(ImportBatch, result.batch_id).notes_json)
    assert notes["quality_basis"] == "ledger"
    assert {d["id"] for d in notes["quality_dimensions"]} == {
        "completeness", "validity", "uniqueness", "product_match_rate",
        "customer_identifier_rate", "cost_coverage", "branch_coverage", "return_clarity",
        "date_range_consistency",
    }
    assert notes["quality_summary"]["dimensions_total"] == 9


# ═══════════════════════════ دسته‌ی مسدود: ابعاد از فریم
def test_blocked_batch_reports_dimensions_from_the_frame(isolated_ledger):
    clean = _clean(_rows(4))
    result = write_import(
        clean, kpis=compute_kpis(clean),
        posting_blockers=[{"check_id": "C04", "title": "قرارداد علامت", "detail": "مبهم"}],
    )
    detail = get_import(result.batch_id)
    assert detail["posted"] is False
    assert detail["quality_basis"] == "frame"
    dims = _dims(detail)
    assert dims["customer_identifier_rate"]["value"] == 1.0
    assert dims["product_match_rate"]["value"] == 1.0
    assert dims["cost_coverage"]["value"] == 0.0 and dims["cost_coverage"]["severity"] == "blocking"
    assert 0 < dims["branch_coverage"]["value"] < 1
    assert dims["date_range_consistency"]["value"] is None, "بازه‌ی اعلام‌شده برای دسته‌ی مسدود ثبت نمی‌شود"


# ═══════════════════════════ بارگذاریِ قدیمی بدون ابعاد ⇒ None، نه بازمحاسبه
def test_a_batch_without_recorded_dimensions_reports_none(isolated_ledger):
    clean = _clean(_rows(5))
    result = write_import(clean, kpis=compute_kpis(clean))
    with session_scope() as session:
        batch = session.get(ImportBatch, result.batch_id)
        batch.notes_json = json.dumps({"customers_created": 5})
    with session_scope() as session:
        quality = _batch_quality(session.get(ImportBatch, result.batch_id))
    assert quality == {"quality_basis": None, "quality_dimensions": None, "quality_summary": None}
    assert get_import(result.batch_id)["quality_dimensions"] is None
