"""حلقه‌ی کامل فاز ۳: تحلیل → کمپین → خروجی اکسل → فایل بعدی → گزارش اثر.

این دروازه‌ی پذیرش فاز ۳ است. اگر بشکند، یعنی سیستم دوباره نمی‌داند پیشنهادش
کار کرد یا نه.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from api.main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from .conftest import close_open_campaigns, poll_job, reset_contact_history  # noqa: E402

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def _fresh_experiment_state():
    """کمپین‌های بازِ ماژول‌های قبلی بسته می‌شوند تا مخاطبِ این ماژول فرو نریزد."""
    close_open_campaigns()


@pytest.fixture(autouse=True)
def _fresh_contact_history():
    """هر تست از وضعیتِ «کسی تازه تماس نگرفته» شروع می‌کند (خستگیِ تماسِ کمپین)."""
    reset_contact_history()


def _analyze_sample() -> dict:
    r = client.post("/api/sample")
    assert r.status_code == 200
    data = r.json()
    roles = {x["role"]: x["suggested"] for x in data["roles"]}
    mapping = {role: col for role, col in roles.items() if col}
    r = client.post("/api/analyze", json={
        "session_id": data["session_id"], "mapping": mapping, "horizon": 3,
    })
    assert r.status_code == 200, r.text
    return poll_job(client, r.json()["job_id"])


@pytest.fixture(scope="module")
def analyzed() -> dict:
    return _analyze_sample()


def _create(name: str, **kwargs) -> dict:
    body = {"name": name, "holdout_pct": 10, "limit": 300}
    body.update(kwargs)
    r = client.post("/api/v1/campaigns", json=body)
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------ ساخت کمپین
def test_campaign_splits_into_two_arms(analyzed):
    campaign = _create("کمپین آزمایشی")

    assert campaign["treatment_size"] > 0
    assert campaign["control_size"] > 0
    total = campaign["treatment_size"] + campaign["control_size"]
    share = campaign["control_size"] / total
    assert 0.05 <= share <= 0.16  # حدود ۱۰٪، با گِرد کردن طبقه‌ای
    assert campaign["exposure_note_fa"]


def test_control_group_is_spread_across_strata(analyzed):
    campaign = _create("کمپین طبقه‌بندی")
    assert campaign["strata"]  # طبقه‌بندی ثبت شده است


def test_zero_holdout_is_allowed_and_reported(analyzed):
    """کمپین بدون گروه کنترل ممکن است — ولی گزارشش ادعای اثر نمی‌کند."""
    campaign = _create("بدون کنترل", holdout_pct=0)
    assert campaign["control_size"] == 0

    detail = client.get(f"/api/v1/campaigns/{campaign['id']}").json()
    assert detail["report"]["verdict"] == "attribution_only"
    assert detail["report"]["is_causal"] is False


def test_campaign_without_matching_opportunities_is_rejected(analyzed):
    r = client.post("/api/v1/campaigns", json={
        "name": "خالی", "kind": "نوعی که وجود ندارد",
    })
    assert r.status_code == 409
    assert "فرصتی" in r.json()["detail"]


# --------------------------------------------------- خروجی اکسل و ثبت تماس
def test_export_contains_only_treatment_and_stamps_exposure(analyzed):
    campaign = _create("کمپین خروجی")
    before = client.get(f"/api/v1/campaigns/{campaign['id']}").json()
    assert before["exposed_count"] == 0

    r = client.get(f"/api/v1/campaigns/{campaign['id']}/export")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument"
    )
    assert len(r.content) > 1000  # فایل واقعی اکسل

    after = client.get(f"/api/v1/campaigns/{campaign['id']}").json()
    assert after["exposed_count"] == after["treatment_size"]
    assert after["exported_at"] is not None

    # هیچ عضو گروه کنترل نباید تماس خورده باشد
    controls = [m for m in after["members"] if m["arm"] == "control"]
    assert controls
    assert all(m["exposure_date"] is None for m in controls)


def test_second_export_does_not_move_the_measurement_window(analyzed):
    campaign = _create("کمپین دو خروجی")
    client.get(f"/api/v1/campaigns/{campaign['id']}/export")
    first = client.get(f"/api/v1/campaigns/{campaign['id']}").json()
    first_dates = {m["customer_id"]: m["exposure_date"] for m in first["members"]}

    client.get(f"/api/v1/campaigns/{campaign['id']}/export")
    second = client.get(f"/api/v1/campaigns/{campaign['id']}").json()
    second_dates = {m["customer_id"]: m["exposure_date"] for m in second["members"]}

    assert first_dates == second_dates


def test_every_export_leaves_an_audit_trail(analyzed):
    """فهرستِ کاملِ شماره‌ها که بیرون می‌رود، باید ردی بگذارد — **هر بار**.

    `exported_at` فقط اولین دانلود را نگه می‌دارد؛ اگر همان فهرست ده بار
    گرفته شود، آن ستون هیچ‌چیز تازه‌ای نمی‌گوید. ممیزی باید هر بار را ببیند.
    """
    from mktcore.db.engine import session_scope
    from mktcore.db.models import AuditEvent
    from mktcore.db.repo_audit import recent_audit_events

    campaign = _create("کمپین ممیزی")
    for _ in range(2):
        assert client.get(
            f"/api/v1/campaigns/{campaign['id']}/export"
        ).status_code == 200

    with session_scope() as session:
        events = recent_audit_events(
            session,
            action=AuditEvent.ACTION_CAMPAIGN_EXPORT,
            entity_id=campaign["id"],
        )

    assert len(events) == 2, "دانلود دوم هم باید ثبت شود"
    for event in events:
        assert event.row_count and event.row_count > 0
        assert event.entity_type == "campaign"
        assert event.actor  # «چه کسی» را صادقانه می‌گوید، حتی وقتی نمی‌داند
        assert "شماره‌ی کامل" in (event.detail_fa or "")


# ------------------------------------------------------------ گزارش اثر
def test_report_is_present_and_always_carries_a_verdict(analyzed):
    campaign = _create("کمپین گزارش")
    detail = client.get(f"/api/v1/campaigns/{campaign['id']}").json()
    report = detail["report"]

    assert report["verdict"] in (
        "proven", "inconclusive", "attribution_only", "not_ready",
    )
    assert report["verdict_label"]
    assert report["verdict_reason_fa"]
    # سنجه‌های مسدود همیشه صریح‌اند
    assert "incremental_gross_profit" in report["blocked_metrics"]
    assert "بهای تمام‌شده" in report["blocked_metrics"]["incremental_gross_profit"]


def test_incremental_revenue_is_two_shaped_money(analyzed):
    campaign = _create("کمپین پول")
    # خروجی + بازخوانی تا حکمی واقعی (نه «هنوز آماده نیست») ساخته شود
    assert client.get(f"/api/v1/campaigns/{campaign['id']}/export").status_code == 200
    assert client.post(f"/api/v1/campaigns/{campaign['id']}/refresh").status_code == 200
    report = client.get(f"/api/v1/campaigns/{campaign['id']}").json()["report"]
    assert report["verdict"] not in ("not_ready", "attribution_only"), report["verdict"]
    # عددِ «افزوده» فقط با حکمِ اثبات‌شده می‌آید؛ وگرنه تفاوتِ مشاهده‌شده با نامِ
    # خودش. هر کدام که هست باید سه‌کلیدی باشد (هرگز float خام).
    money = report["incremental_revenue"] if report["is_causal"] else report["observed_difference"]["revenue"]
    assert money is not None
    assert set(money) == {"rial", "display_text", "display_currency"}
    assert money["rial"] is None or isinstance(money["rial"], int)
    if not report["is_causal"]:
        assert report["incremental_revenue"] is None


def test_outcomes_are_computed_from_the_ledger(analyzed):
    """پس از خروجی، پنجره‌ی سنجش باز می‌شود و نتیجه از دفتر کل خوانده می‌شود."""
    campaign = _create("کمپین نتیجه")
    client.get(f"/api/v1/campaigns/{campaign['id']}/export")

    r = client.post(f"/api/v1/campaigns/{campaign['id']}/refresh")
    assert r.status_code == 200
    detail = r.json()

    measured = [m for m in detail["members"] if m["outcome"] is not None]
    assert measured, "هیچ عضوی سنجیده نشد"
    sample = measured[0]
    assert sample["outcome"]["window"][0] < sample["outcome"]["window"][1]
    assert set(sample["outcome"]["revenue"]) == {
        "rial", "display_text", "display_currency",
    }


def test_measurement_window_respects_the_configured_length(analyzed):
    campaign = _create("کمپین پنجره", analysis_window_days=7)
    client.get(f"/api/v1/campaigns/{campaign['id']}/export")
    detail = client.post(f"/api/v1/campaigns/{campaign['id']}/refresh").json()

    measured = [m for m in detail["members"] if m["outcome"]]
    start, end = measured[0]["outcome"]["window"]
    assert (pd.Timestamp(end) - pd.Timestamp(start)).days == 7


def test_closing_a_campaign_freezes_it(analyzed):
    campaign = _create("کمپین بسته")
    r = client.post(f"/api/v1/campaigns/{campaign['id']}/close")
    assert r.status_code == 200
    assert r.json()["status"] == "closed"
    assert r.json()["closed_at"] is not None


def test_campaign_list_and_404s(analyzed):
    _create("کمپین فهرست")
    listing = client.get("/api/v1/campaigns").json()
    assert listing["available"] is True
    assert listing["items"]
    assert all("treatment_size" in c for c in listing["items"])

    assert client.get("/api/v1/campaigns/99999999").status_code == 404
    assert client.get("/api/v1/campaigns/99999999/export").status_code == 404
    assert client.post("/api/v1/campaigns/99999999/close").status_code == 404


def test_analysis_hook_refreshes_campaign_outcomes(analyzed):
    """تحلیل فایل بعدی باید حلقه را ببندد — بدون دخالت دستی."""
    campaign = _create("کمپین حلقه")
    client.get(f"/api/v1/campaigns/{campaign['id']}/export")

    payload = _analyze_sample()
    assert payload["canonical"]["ok"] is True
    outcomes = payload["canonical"]["campaign_outcomes"]
    assert outcomes is not None
    assert outcomes["campaigns"] >= 1
    assert outcomes["members"] > 0
