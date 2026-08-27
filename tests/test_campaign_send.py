"""ارسال مستقیم کمپین — گاردها، هزینه، و مهرِ تماس.

مهم‌ترین تست‌ها:

* `test_control_arm_can_never_receive_a_campaign_sms` — خطِ سرخ.
* `test_dry_run_never_stamps_exposure` — پیش‌نمایش نباید سنجش را آلوده کند.
* `test_a_member_is_never_sent_twice` — ارسالِ دوباره یعنی هزینه‌ی دوبرابر و
  مشتریِ آزرده.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from api.main import app  # noqa: E402

from mktcore.campaigns.assign import ARM_CONTROL, ARM_TREATMENT  # noqa: E402
from mktcore.config import get_settings  # noqa: E402
from mktcore.db import session_scope  # noqa: E402
from mktcore.db.models import CampaignMember, CampaignSend, Customer  # noqa: E402
from mktcore.execution.providers import SendResult  # noqa: E402

from .conftest import poll_job  # noqa: E402

client = TestClient(app)


@pytest.fixture(scope="module")
def analyzed() -> str:
    r = client.post("/api/sample")
    assert r.status_code == 200, r.text
    data = r.json()
    mapping = {x["role"]: x["suggested"] for x in data["roles"] if x["suggested"]}
    r = client.post("/api/analyze", json={
        "session_id": data["session_id"], "mapping": mapping, "horizon": 3,
    })
    assert r.status_code == 200, r.text
    poll_job(client, r.json()["job_id"])
    return data["session_id"]


def _new_campaign(name: str, holdout: int = 20) -> int:
    r = client.post("/api/v1/campaigns", json={
        "name": name, "holdout_pct": holdout,
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _arms(campaign_id: int) -> tuple[list[int], list[int]]:
    with session_scope() as session:
        rows = session.execute(
            select(CampaignMember.arm, CampaignMember.customer_id)
            .where(CampaignMember.campaign_id == campaign_id)
        ).all()
    control = [int(c) for a, c in rows if a == ARM_CONTROL]
    treatment = [int(c) for a, c in rows if a == ARM_TREATMENT]
    return control, treatment


def _fake_panel(monkeypatch, sink: list[str]):
    """پنلِ mock که به‌جای شبکه، گیرنده‌ها را ثبت می‌کند."""
    def _send(messages, **_kwargs):
        sink.extend(m.customer_id for m in messages)
        return SendResult(
            total=len(messages), sent=len(messages), failed=0,
            dry_run=False, provider="mock",
            details=[{"مشتری": m.customer_id, "وضعیت": "ارسال شد"} for m in messages],
        )
    monkeypatch.setattr("api.campaigns_api.send_campaign", _send)


def _enable_panel(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "mkt_sms_enable", True, raising=False)
    monkeypatch.setattr(settings, "kavenegar_api_key", "test-key", raising=False)


# ═══════════════════════════════════════════════ خطِ سرخ: گروه کنترل
def test_control_arm_can_never_receive_a_campaign_sms(analyzed, monkeypatch):
    campaign_id = _new_campaign("ارسال مستقیم")
    control, treatment = _arms(campaign_id)
    assert control and treatment

    sink: list[str] = []
    _fake_panel(monkeypatch, sink)
    _enable_panel(monkeypatch)

    r = client.post(f"/api/v1/campaigns/{campaign_id}/send", json={
        "dry_run": False, "confirm": True,
    })
    assert r.status_code == 200, r.text

    # ⚠️ تست باید **ناتهی** باشد: اگر اصلاً پیامی نرفته باشد، «نشتی نبود» چیزی
    # را اثبات نمی‌کند.
    assert sink, "هیچ پیامی ارسال نشد، پس این تست چیزی را اثبات نمی‌کند"
    assert {int(c) for c in sink} <= set(treatment)

    leaked = {int(c) for c in sink} & set(control)
    assert not leaked, f"گروه کنترل پیام گرفت: {sorted(leaked)[:5]}"


def test_control_arm_members_get_no_send_row(analyzed, monkeypatch):
    campaign_id = _new_campaign("بدون ردیف کنترل")
    control, _ = _arms(campaign_id)
    sink: list[str] = []
    _fake_panel(monkeypatch, sink)
    _enable_panel(monkeypatch)
    client.post(f"/api/v1/campaigns/{campaign_id}/send", json={
        "dry_run": False, "confirm": True,
    })
    with session_scope() as session:
        sent_ids = {
            int(c) for (c,) in session.execute(
                select(CampaignSend.customer_id)
                .where(CampaignSend.campaign_id == campaign_id)
            ).all()
        }
    assert not (sent_ids & set(control))


# ═══════════════════════════════════════ پیش‌نمایش ≠ تماس
def test_dry_run_never_stamps_exposure(analyzed):
    """پیش‌نمایش هیچ پیامی نمی‌فرستد، پس نباید سنجشِ اثر را آلوده کند."""
    campaign_id = _new_campaign("پیش‌نمایش")

    r = client.post(f"/api/v1/campaigns/{campaign_id}/send", json={"dry_run": True})
    assert r.status_code == 200, r.text
    assert r.json()["send"]["حالت_آزمایشی"] is True

    with session_scope() as session:
        stamped = session.scalars(
            select(CampaignMember.exposure_at).where(
                CampaignMember.campaign_id == campaign_id,
                CampaignMember.exposure_at.isnot(None),
            )
        ).all()
    assert not stamped, "ارسال آزمایشی نباید مهرِ تماس بزند"


def test_dry_run_costs_nothing(analyzed):
    campaign_id = _new_campaign("هزینه‌ی پیش‌نمایش")
    r = client.post(f"/api/v1/campaigns/{campaign_id}/send", json={"dry_run": True})
    body = r.json()["send"]
    assert body["هزینه"]["rial"] == 0
    assert body["قطعه"] == 0


def test_real_send_stamps_exposure(analyzed, monkeypatch):
    campaign_id = _new_campaign("ارسال واقعی")
    sink: list[str] = []
    _fake_panel(monkeypatch, sink)
    _enable_panel(monkeypatch)

    r = client.post(f"/api/v1/campaigns/{campaign_id}/send", json={
        "dry_run": False, "confirm": True,
    })
    assert r.status_code == 200, r.text
    assert r.json()["send"]["حالت_آزمایشی"] is False

    with session_scope() as session:
        rows = session.execute(
            select(CampaignMember.arm, CampaignMember.exposure_channel)
            .where(
                CampaignMember.campaign_id == campaign_id,
                CampaignMember.exposure_at.isnot(None),
            )
        ).all()
    assert rows, "ارسال واقعی باید مهرِ تماس بزند"
    assert all(arm == ARM_TREATMENT for arm, _ch in rows)
    assert all(channel == "sms" for _arm, channel in rows)


# ═══════════════════════════════════════ گیتِ سه‌لایه‌ی ارسال واقعی
def test_real_send_without_panel_config_falls_back_to_dry_run(analyzed, monkeypatch):
    campaign_id = _new_campaign("بدون کلید")
    settings = get_settings()
    monkeypatch.setattr(settings, "mkt_sms_enable", False, raising=False)

    r = client.post(f"/api/v1/campaigns/{campaign_id}/send", json={
        "dry_run": False, "confirm": True,
    })
    assert r.status_code == 200
    send = r.json()["send"]
    assert send["حالت_آزمایشی"] is True
    assert "توضیح" in send


def test_real_send_without_confirmation_falls_back_to_dry_run(analyzed, monkeypatch):
    campaign_id = _new_campaign("بدون تأیید")
    _enable_panel(monkeypatch)

    r = client.post(f"/api/v1/campaigns/{campaign_id}/send", json={
        "dry_run": False, "confirm": False,
    })
    send = r.json()["send"]
    assert send["حالت_آزمایشی"] is True
    assert "تأیید صریح" in send["توضیح"]


# ═══════════════════════════════════════════ ارسالِ دوباره ممنوع
def test_a_member_is_never_sent_twice(analyzed, monkeypatch):
    """ارسالِ دوباره یعنی هزینه‌ی دوبرابر و مشتریِ آزرده.

    ناوردای واقعی این است: **کسی که پیام گرفته، دوباره نمی‌گیرد.** کدِ وضعیت
    ۴۰۹ تنها وقتی درست است که همه‌ی اعضا در بار اول پیام گرفته باشند؛ اگر بخشی
    `skipped` شده باشند (بی‌شماره یا بی‌متن) تلاش دوباره **باید** مجاز باشد،
    وگرنه کاربر راهِ جبران ندارد.
    """
    campaign_id = _new_campaign("ارسال دوباره")
    sink: list[str] = []
    _fake_panel(monkeypatch, sink)
    _enable_panel(monkeypatch)

    first = client.post(f"/api/v1/campaigns/{campaign_id}/send", json={
        "dry_run": False, "confirm": True,
    })
    assert first.status_code == 200
    delivered = set(sink)
    assert delivered, "بار اول باید چیزی فرستاده باشد"

    sink.clear()
    second = client.post(f"/api/v1/campaigns/{campaign_id}/send", json={
        "dry_run": False, "confirm": True,
    })
    if second.status_code == 409:
        assert "قبلاً" in second.json()["detail"]
    else:
        assert second.status_code == 200, second.text
    assert not (set(sink) & delivered), (
        f"این افراد دو بار پیام گرفتند: {sorted(set(sink) & delivered)[:5]}"
    )


def test_fully_delivered_campaign_refuses_a_second_send(analyzed, monkeypatch):
    """اگر همه پیام گرفته باشند، تلاش دوباره باید صریح رد شود."""
    campaign_id = _new_campaign("همه فرستاده")
    sink: list[str] = []
    _fake_panel(monkeypatch, sink)
    _enable_panel(monkeypatch)

    client.post(f"/api/v1/campaigns/{campaign_id}/send", json={
        "template": "سلام {نام}", "dry_run": False, "confirm": True,
    })
    with session_scope() as session:
        statuses = {
            row.status for row in session.scalars(
                select(CampaignSend).where(CampaignSend.campaign_id == campaign_id)
            ).all()
        }
    if statuses != {CampaignSend.STATUS_SENT}:
        pytest.skip("بخشی از اعضا شماره نداشتند؛ این سناریو مصداق ندارد")

    second = client.post(f"/api/v1/campaigns/{campaign_id}/send", json={
        "template": "سلام {نام}", "dry_run": False, "confirm": True,
    })
    assert second.status_code == 409
    assert "قبلاً" in second.json()["detail"]


def test_send_rows_are_unique_per_member(analyzed, monkeypatch):
    campaign_id = _new_campaign("یکتایی ردیف")
    sink: list[str] = []
    _fake_panel(monkeypatch, sink)
    _enable_panel(monkeypatch)
    client.post(f"/api/v1/campaigns/{campaign_id}/send", json={
        "dry_run": False, "confirm": True,
    })
    with session_scope() as session:
        ids = [
            int(c) for (c,) in session.execute(
                select(CampaignSend.customer_id)
                .where(CampaignSend.campaign_id == campaign_id)
            ).all()
        ]
    assert len(ids) == len(set(ids))


# ═════════════════════════════════════════════════════════ هزینه
def test_cost_is_recorded_and_reported(analyzed, monkeypatch):
    campaign_id = _new_campaign("هزینه")
    sink: list[str] = []
    _fake_panel(monkeypatch, sink)
    _enable_panel(monkeypatch)

    r = client.post(f"/api/v1/campaigns/{campaign_id}/send", json={
        "template": "سلام {نام}، پیشنهاد ویژه‌ی این هفته آماده است.",
        "dry_run": False, "confirm": True,
    })
    send = r.json()["send"]
    assert send["ارسال‌شده"] > 0
    assert send["قطعه"] >= send["ارسال‌شده"], "هر پیام دست‌کم یک قطعه است"
    assert send["هزینه"]["rial"] == send["قطعه"] * 3_000
    assert send["یادداشت_هزینه"]


def test_cost_unblocks_cost_per_incremental_order(analyzed, monkeypatch):
    """پیش از ثبت هزینه، این سنجه صریحاً مسدود بود."""
    campaign_id = _new_campaign("باز شدن سنجه")

    before = client.get(f"/api/v1/campaigns/{campaign_id}").json()["report"]
    assert "cost_per_incremental_order" in before["blocked_metrics"]
    assert before["contact_cost_rial"] is None

    sink: list[str] = []
    _fake_panel(monkeypatch, sink)
    _enable_panel(monkeypatch)
    client.post(f"/api/v1/campaigns/{campaign_id}/send", json={
        "dry_run": False, "confirm": True,
    })

    after = client.get(f"/api/v1/campaigns/{campaign_id}").json()["report"]
    assert "cost_per_incremental_order" not in after["blocked_metrics"]
    assert after["contact_cost_rial"] is not None
    assert after["contact_cost"]["rial"] == after["contact_cost_rial"]


def test_dry_run_does_not_unblock_the_cost_metric(analyzed):
    """پیش‌نمایش پولی خرج نکرده، پس نباید سنجه را باز کند."""
    campaign_id = _new_campaign("پیش‌نمایش و سنجه")
    client.post(f"/api/v1/campaigns/{campaign_id}/send", json={"dry_run": True})

    report = client.get(f"/api/v1/campaigns/{campaign_id}").json()["report"]
    assert "cost_per_incremental_order" in report["blocked_metrics"]
    assert report["contact_cost_rial"] is None


# ═════════════════════════════════════════════ حالت‌های مرزی
def test_closed_campaign_rejects_sending(analyzed):
    campaign_id = _new_campaign("بسته")
    assert client.post(f"/api/v1/campaigns/{campaign_id}/close").status_code == 200
    r = client.post(f"/api/v1/campaigns/{campaign_id}/send", json={"dry_run": True})
    assert r.status_code == 409
    assert "بسته" in r.json()["detail"]


def test_unknown_campaign_is_404(analyzed):
    r = client.post("/api/v1/campaigns/999999/send", json={"dry_run": True})
    assert r.status_code == 404


def test_member_without_a_phone_is_skipped_not_failed(analyzed, monkeypatch):
    """نبودِ شماره خطا نیست؛ یک واقعیتِ داده است و باید جدا شمرده شود."""
    campaign_id = _new_campaign("بدون شماره")
    _, treatment = _arms(campaign_id)
    assert treatment

    with session_scope() as session:
        customer = session.get(Customer, treatment[0])
        original = customer.phone_e164
        customer.phone_e164 = None

    try:
        sink: list[str] = []
        _fake_panel(monkeypatch, sink)
        _enable_panel(monkeypatch)
        r = client.post(f"/api/v1/campaigns/{campaign_id}/send", json={
            "dry_run": False, "confirm": True,
        })
        send = r.json()["send"]
        assert send["بدون_شماره"] >= 1
        with session_scope() as session:
            row = session.scalar(
                select(CampaignSend).where(
                    CampaignSend.campaign_id == campaign_id,
                    CampaignSend.customer_id == treatment[0],
                )
            )
        assert row.status == CampaignSend.STATUS_SKIPPED
        assert row.cost_rial == 0, "پیامی نرفته، پس هزینه‌ای هم ندارد"
    finally:
        with session_scope() as session:
            session.get(Customer, treatment[0]).phone_e164 = original


def test_send_reports_gate_suppression(analyzed):
    campaign_id = _new_campaign("گزارش دروازه")
    r = client.post(f"/api/v1/campaigns/{campaign_id}/send", json={"dry_run": True})
    send = r.json()["send"]
    assert "مسدودشده" in send
    assert "دلایل_مسدودی" in send


# ═════════════════════════ متنِ پیام: هرگز راهنمای تیم فروش
def _expansion_only_campaign() -> int | None:
    """کمپینی فقط از فرصت‌های «توسعه‌ی سبد خرید» — که `message_fa` ندارند."""
    r = client.post("/api/v1/campaigns", json={
        "name": "فقط توسعه", "holdout_pct": 10, "kind": "توسعه‌ی سبد خرید",
    })
    if r.status_code != 200:
        return None
    return r.json()["id"]


def test_sales_instruction_is_never_sent_to_a_customer(analyzed, monkeypatch):
    """خطِ سرخ: `action_fa` متنِ تیم فروش است و نباید به مشتری برود.

    نمونه‌ی واقعیِ آنچه پیش از این رفع، ارسال می‌شد:
    «به این مشتری «X» را معرفی کنید؛ مشتریان مشابهش این دسته را می‌خرند ولی او نه.»
    """
    campaign_id = _expansion_only_campaign()
    if campaign_id is None:
        pytest.skip("فرصتِ «توسعه‌ی سبد خرید» در این داده وجود ندارد")

    sink: list[str] = []
    _fake_panel(monkeypatch, sink)
    _enable_panel(monkeypatch)

    r = client.post(f"/api/v1/campaigns/{campaign_id}/send", json={
        "dry_run": False, "confirm": True,
    })
    assert r.status_code == 200, r.text
    send = r.json()["send"]

    assert send["ارسال‌شده"] == 0, "بدون متنِ آماده نباید چیزی ارسال شود"
    assert send["بدون_متن"] >= 1
    assert not sink, "هیچ پیامی نباید به پنل رفته باشد"

    with session_scope() as session:
        rows = session.scalars(
            select(CampaignSend).where(CampaignSend.campaign_id == campaign_id)
        ).all()
        details = [row.status_detail_fa or "" for row in rows]
        statuses = {row.status for row in rows}
        texts = [row.message_text or "" for row in rows]

    assert statuses == {CampaignSend.STATUS_SKIPPED}
    assert any("قالب پیام" in d for d in details), "دلیل باید صریح و راهنما باشد"
    assert all("به این مشتری" not in t for t in texts), (
        "متنِ راهنمای تیم فروش نباید حتی ذخیره شود"
    )


def test_template_makes_a_textless_campaign_sendable(analyzed, monkeypatch):
    """راهِ جبران باید باز باشد: با قالب صریح، همان کمپین ارسال‌شدنی می‌شود."""
    campaign_id = _expansion_only_campaign()
    if campaign_id is None:
        pytest.skip("فرصتِ «توسعه‌ی سبد خرید» در این داده وجود ندارد")

    sink: list[str] = []
    _fake_panel(monkeypatch, sink)
    _enable_panel(monkeypatch)

    first = client.post(f"/api/v1/campaigns/{campaign_id}/send", json={
        "dry_run": False, "confirm": True,
    })
    assert first.json()["send"]["ارسال‌شده"] == 0

    second = client.post(f"/api/v1/campaigns/{campaign_id}/send", json={
        "template": "سلام {نام}، پیشنهاد ویژه‌ی این هفته را ببینید.",
        "dry_run": False, "confirm": True,
    })
    assert second.status_code == 200, second.text
    assert second.json()["send"]["ارسال‌شده"] > 0, (
        "عضوِ skipped باید با دادن قالب دوباره قابل ارسال باشد"
    )
    assert sink


def test_a_skipped_member_gets_no_exposure_stamp(analyzed, monkeypatch):
    campaign_id = _expansion_only_campaign()
    if campaign_id is None:
        pytest.skip("فرصتِ «توسعه‌ی سبد خرید» در این داده وجود ندارد")

    sink: list[str] = []
    _fake_panel(monkeypatch, sink)
    _enable_panel(monkeypatch)
    client.post(f"/api/v1/campaigns/{campaign_id}/send", json={
        "dry_run": False, "confirm": True,
    })

    with session_scope() as session:
        stamped = session.scalars(
            select(CampaignMember.exposure_at).where(
                CampaignMember.campaign_id == campaign_id,
                CampaignMember.exposure_at.isnot(None),
            )
        ).all()
    assert not stamped, "عضوی که پیام نگرفته نباید مهرِ تماس بخورد"


def test_skipped_member_costs_nothing(analyzed, monkeypatch):
    campaign_id = _expansion_only_campaign()
    if campaign_id is None:
        pytest.skip("فرصتِ «توسعه‌ی سبد خرید» در این داده وجود ندارد")

    sink: list[str] = []
    _fake_panel(monkeypatch, sink)
    _enable_panel(monkeypatch)
    r = client.post(f"/api/v1/campaigns/{campaign_id}/send", json={
        "dry_run": False, "confirm": True,
    })
    assert r.json()["send"]["هزینه"]["rial"] == 0

    with session_scope() as session:
        rows = session.scalars(
            select(CampaignSend).where(CampaignSend.campaign_id == campaign_id)
        ).all()
    assert all(row.cost_rial == 0 and row.segments == 0 for row in rows)


# ═══════════════════ شکستِ پنل: نه مهر، نه هزینه، نه ادعای ارسال
def test_panel_failure_stamps_nothing_and_costs_nothing(analyzed, monkeypatch):
    """کاوه‌نگار خطا را با HTTP ۲۰۰ برمی‌گرداند؛ مسیر ارسال باید آن را شکست ببیند.

    اگر شکست «موفق» ثبت شود سه چیز خراب می‌شود: عضوی که پیام نگرفته مهرِ تماس
    می‌خورد و در مخرجِ گروه آزمایش می‌ماند (اثر کمتر از واقع)، هزینه‌ای ثبت
    می‌شود که خرج نشده، و گزارش دروغ می‌گوید.
    """
    campaign_id = _new_campaign("شکست پنل")

    def _failing(messages, **_kwargs):
        from mktcore.execution.providers import SendResult

        return SendResult(
            total=len(messages), sent=0, failed=len(messages),
            dry_run=False, provider="mock",
            details=[
                {"مشتری": m.customer_id, "وضعیت": "خطا — خطای پنل 418: اعتبار کافی نیست",
                 "شناسه_پیام": None}
                for m in messages
            ],
        )

    monkeypatch.setattr("api.campaigns_api.send_campaign", _failing)
    _enable_panel(monkeypatch)

    r = client.post(f"/api/v1/campaigns/{campaign_id}/send", json={
        "template": "سلام {نام}", "dry_run": False, "confirm": True,
    })
    assert r.status_code == 200, r.text
    send = r.json()["send"]
    assert send["ارسال‌شده"] == 0
    assert send["ناموفق"] > 0
    assert send["هزینه"]["rial"] == 0, "پیامی نرفته، پس هزینه‌ای هم نیست"

    with session_scope() as session:
        stamped = session.scalars(
            select(CampaignMember.exposure_at).where(
                CampaignMember.campaign_id == campaign_id,
                CampaignMember.exposure_at.isnot(None),
            )
        ).all()
        rows = session.scalars(
            select(CampaignSend).where(CampaignSend.campaign_id == campaign_id)
        ).all()
    assert not stamped, "ارسال ناموفق نباید مهرِ تماس بزند"
    assert all(row.status == CampaignSend.STATUS_FAILED for row in rows)
    assert all(row.cost_rial == 0 for row in rows)


def test_failed_send_stays_retryable(analyzed, monkeypatch):
    """شکستِ پنل نباید عضو را برای همیشه از فهرست خارج کند."""
    campaign_id = _new_campaign("تلاش دوباره پس از شکست")

    def _failing(messages, **_kwargs):
        from mktcore.execution.providers import SendResult

        return SendResult(total=len(messages), sent=0, failed=len(messages),
                          dry_run=False, provider="mock",
                          details=[{"مشتری": m.customer_id, "وضعیت": "خطا — قطعی",
                                    "شناسه_پیام": None} for m in messages])

    monkeypatch.setattr("api.campaigns_api.send_campaign", _failing)
    _enable_panel(monkeypatch)
    client.post(f"/api/v1/campaigns/{campaign_id}/send", json={
        "template": "سلام {نام}", "dry_run": False, "confirm": True,
    })

    sink: list[str] = []
    _fake_panel(monkeypatch, sink)
    retry = client.post(f"/api/v1/campaigns/{campaign_id}/send", json={
        "template": "سلام {نام}", "dry_run": False, "confirm": True,
    })
    assert retry.status_code == 200, retry.text
    assert retry.json()["send"]["ارسال‌شده"] > 0, "پس از رفع مشکل باید بشود دوباره فرستاد"


def test_successful_send_records_the_provider_message_id(analyzed, monkeypatch):
    """بدون شناسه‌ی پیام، webhook تحویل در آینده راهی برای نسبت‌دادن ندارد."""
    campaign_id = _new_campaign("شناسه پیام")

    def _with_ids(messages, **_kwargs):
        from mktcore.execution.providers import SendResult

        return SendResult(
            total=len(messages), sent=len(messages), failed=0,
            dry_run=False, provider="mock",
            details=[
                {"مشتری": m.customer_id, "وضعیت": "ارسال شد",
                 "شناسه_پیام": f"MID-{m.customer_id}"}
                for m in messages
            ],
        )

    monkeypatch.setattr("api.campaigns_api.send_campaign", _with_ids)
    _enable_panel(monkeypatch)
    r = client.post(f"/api/v1/campaigns/{campaign_id}/send", json={
        "template": "سلام {نام}", "dry_run": False, "confirm": True,
    })
    assert r.status_code == 200, r.text

    with session_scope() as session:
        rows = session.scalars(
            select(CampaignSend).where(
                CampaignSend.campaign_id == campaign_id,
                CampaignSend.status == CampaignSend.STATUS_SENT,
            )
        ).all()
    assert rows
    assert all(row.provider_message_id for row in rows)


# ═════════════════════════════════ پیش‌نمایش متن پیش از ارسال
def test_dry_run_returns_a_message_preview(analyzed):
    """کاربر باید **پیش از** ارسال ببیند چه می‌فرستد.

    داده‌اش از قبل در `SendResult.details` بود ولی هیچ‌وقت به فرانت نمی‌رسید.
    """
    campaign_id = _new_campaign("پیش‌نمایش")
    r = client.post(f"/api/v1/campaigns/{campaign_id}/send", json={
        "template": "سلام {نام}، پیشنهاد این هفته آماده است.", "dry_run": True,
    })
    assert r.status_code == 200, r.text
    preview = r.json()["send"]["نمونه_پیام"]
    assert preview, "پیش‌نمایش نباید خالی باشد"
    assert all("متن" in row and "قطعه" in row for row in preview)
    assert any("پیشنهاد این هفته" in row["متن"] for row in preview)


def test_preview_masks_phone_numbers(analyzed):
    """پیش‌نمایش نباید شماره‌ی کامل را روی صفحه بریزد."""
    campaign_id = _new_campaign("ماسک شماره")
    r = client.post(f"/api/v1/campaigns/{campaign_id}/send", json={
        "template": "سلام {نام}", "dry_run": True,
    })
    for row in r.json()["send"]["نمونه_پیام"]:
        receiver = row["گیرنده"]
        assert receiver == "—" or "*" in receiver, f"شماره ماسک نشده: {receiver}"


def test_preview_reports_segment_count_per_message(analyzed):
    """هزینه‌ی کل بعد از ارسال دیر است؛ قطعه‌ی هر پیام باید قبلش معلوم باشد."""
    long_text = "سلام {نام}، " + "پیشنهاد ویژه‌ی این هفته را از دست ندهید. " * 4
    campaign_id = _new_campaign("چند قطعه")
    r = client.post(f"/api/v1/campaigns/{campaign_id}/send", json={
        "template": long_text, "dry_run": True,
    })
    preview = r.json()["send"]["نمونه_پیام"]
    assert preview
    assert any(row["قطعه"] > 1 for row in preview), (
        "پیام بلند باید بیش از یک قطعه گزارش شود"
    )
