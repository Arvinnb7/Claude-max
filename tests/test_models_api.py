"""مسیرهای `/api/v1/models` — §۲۶.۴.

نکته‌ی این فایل: «داده کافی نبود» و «فعال‌سازی مجاز نیست» هر دو باید **پاسخِ
صریح** بدهند، نه ۵۰۰ و نه سکوت.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from api.main import app  # noqa: E402

from mktcore.db.models import ModelRun  # noqa: E402
from mktcore.ml.registry import record_run  # noqa: E402
from mktcore.ml.serialize import calibration_to_json, linear_model_to_json  # noqa: E402

from .conftest import poll_job  # noqa: E402

client = TestClient(app)


@pytest.fixture(scope="module")
def analyzed() -> str:
    r = client.post("/api/sample")
    data = r.json()
    mapping = {x["role"]: x["suggested"] for x in data["roles"] if x["suggested"]}
    r = client.post("/api/analyze", json={
        "session_id": data["session_id"], "mapping": mapping, "horizon": 3,
    })
    poll_job(client, r.json()["job_id"])
    return data["session_id"]


def _model_json() -> dict:
    return linear_model_to_json(
        features=["monetary_rial"], indicator_features=[],
        impute_median=[1_000.0], center=[1_000.0], scale=[500.0],
        coef=[0.5], intercept=-0.4,
    )


def _validated() -> dict:
    return record_run(
        model_key="whale", status=ModelRun.STATUS_VALIDATED,
        coefficients_json=_model_json(),
        calibration_json=calibration_to_json(x=[0.0, 1.0], y=[0.0, 1.0]),
        metrics_json={"brier": 0.09, "topk_captured_gross_profit_rial": 12_000},
        label_basis="gross_profit",
    )


def test_listing_is_honest_about_what_is_active(analyzed):
    body = client.get("/api/v1/models").json()

    assert body["available"] is True
    assert set(body["active"]) >= {"whale", "churn", "replenish", "nbp_rank"}
    assert "فعال" in body["note_fa"]


def test_training_an_unknown_model_is_a_clear_404(analyzed):
    r = client.post("/api/v1/models/train", json={"model_key": "چیزی که نیست"})

    assert r.status_code == 404
    assert "آموزش‌دهنده" in r.json()["detail"]


def test_promote_requires_a_validated_run(analyzed):
    run = record_run(
        model_key="churn", status=ModelRun.STATUS_TRAINED,
        coefficients_json=_model_json(),
    )
    r = client.post(f"/api/v1/models/{run['id']}/promote")

    assert r.status_code == 409
    assert "اعتبارسنجی" in r.json()["detail"]


def test_promote_then_rollback_through_the_api(analyzed):
    first = _validated()
    assert client.post(f"/api/v1/models/{first['id']}/promote").status_code == 200
    second = _validated()
    assert client.post(f"/api/v1/models/{second['id']}/promote").status_code == 200

    restored = client.post(f"/api/v1/models/{second['id']}/rollback")
    assert restored.status_code == 200
    assert restored.json()["id"] == first["id"]
    assert restored.json()["promoted"] is True


def test_validate_endpoint_explains_why_a_run_is_not_promotable(analyzed):
    run = record_run(
        model_key="whale", status=ModelRun.STATUS_INSUFFICIENT,
        blocked_reason_code="span_too_short",
        blocked_reason_fa="بازه‌ی داده کوتاه است.",
    )
    body = client.post(f"/api/v1/models/{run['id']}/validate").json()

    assert body["validated"] is False
    assert "بازه" in body["note_fa"]


def test_metrics_endpoint_returns_the_recorded_numbers(analyzed):
    run = _validated()
    body = client.get(f"/api/v1/models/{run['id']}/metrics").json()

    assert body["metrics"]["brier"] == 0.09
    assert body["calibration"]["kind"] == "isotonic"


def test_drift_endpoint_says_unmeasured_rather_than_stable(analyzed):
    """«نسنجیده» را «پایدار» نامیدن، سنجه را بی‌اعتبار می‌کند."""
    run = _validated()
    body = client.get(f"/api/v1/models/{run['id']}/drift").json()

    assert body["measured"] is False
    assert "پایدار" in body["note_fa"]


def test_unknown_run_is_404(analyzed):
    assert client.get("/api/v1/models/999999").status_code == 404


def test_existing_endpoints_are_untouched(analyzed):
    """مسیرهای موجود نباید با افزودن روتر تازه جابه‌جا شوند."""
    for path in ("/api/v1/customers", "/api/v1/opportunities", "/api/v1/cost-coverage"):
        assert client.get(path).status_code == 200, path
