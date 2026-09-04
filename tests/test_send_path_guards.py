"""گاردِ مسیرهای ارسال — خطِ سرخِ این فاز.

پیش از این فاز، `POST /api/sms/send` **هیچ** بررسی‌ای نداشت: با یک کلید کاوه‌نگار
واقعی می‌توانست به عضوِ گروه کنترلِ یک آزمایشِ فعال پیام بدهد. اگر آن اتفاق
می‌افتاد، هیچ‌جا ثبت نمی‌شد، پس بعداً هم قابل تشخیص نبود و همه‌ی گزارش‌های اثرِ
بعدی بی‌اعتبار می‌شدند بدون اینکه کسی بفهمد.

اینجا با پنلِ mock ارسالِ «واقعی» انجام می‌شود تا مسیرِ واقعی آزموده شود، نه
مسیرِ dry-run.
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
from api.persistence import store  # noqa: E402

from mktcore.campaigns.assign import ARM_CONTROL, ARM_TREATMENT  # noqa: E402
from mktcore.db import session_scope  # noqa: E402
from mktcore.db.models import CampaignMember, Customer  # noqa: E402

from .conftest import poll_job, reset_contact_history  # noqa: E402

client = TestClient(app)


def _upload_and_analyze() -> str:
    """یک نشست تحلیل‌شده‌ی واقعی، از همان مسیرِ کاربر و همان کمک‌تابع‌های موجود."""
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


@pytest.fixture(scope="module")
def session_id() -> str:
    sid = _upload_and_analyze()
    _close_open_campaigns()
    return sid


def _close_open_campaigns() -> None:
    """کمپین‌های بازِ ماژول‌های قبلی روی همین دفتر کل بسته می‌شوند.

    دروازه‌ی تماس عضوِ کنترلِ هر کمپینِ باز را کنار می‌گذارد؛ در سوئیتِ کامل
    آن‌قدر کمپینِ باز از تست‌های قبلی می‌ماند که مخاطبِ مجازِ این کمپین به چند
    نفر — هر کدام تنها در طبقه‌ی خودش — می‌رسد و گروه کنترل خالی می‌شود. این
    آزمون درباره‌ی نشتِ ارسال است، نه درباره‌ی هم‌پوشانیِ کمپین‌ها، پس از یک
    وضعیتِ آزمایشیِ تمیز شروع می‌کند.
    """
    from mktcore.db.base import now_ts
    from mktcore.db.models import Campaign

    with session_scope() as session:
        for campaign in session.scalars(select(Campaign).where(Campaign.status != "closed")):
            campaign.status = "closed"
            campaign.closed_at = now_ts()


def _control_and_treatment(campaign_id: int) -> tuple[list[str], list[str]]:
    """کلیدهای خامِ اعضای هر بازو — همان شکلی که مسیر ارسال می‌شناسد."""
    with session_scope() as session:
        rows = session.execute(
            select(CampaignMember.arm, Customer.canonical_key)
            .join(Customer, Customer.id == CampaignMember.customer_id)
            .where(CampaignMember.campaign_id == campaign_id)
        ).all()
    control = [str(key) for arm, key in rows if arm == ARM_CONTROL]
    treatment = [str(key) for arm, key in rows if arm == ARM_TREATMENT]
    return control, treatment


def test_control_arm_is_never_in_a_real_send(session_id, monkeypatch):
    """خطِ سرخ: با ارسالِ واقعی، هیچ عضوِ گروه کنترل پیام نمی‌گیرد."""
    created = client.post("/api/v1/campaigns", json={
        "name": "گاردِ ارسال", "holdout_pct": 20,
    })
    assert created.status_code == 200, created.text
    campaign_id = created.json()["id"]
    control, treatment = _control_and_treatment(campaign_id)
    assert control and treatment, "کمپین باید هر دو بازو را داشته باشد"

    # پنلِ mock: به‌جای تماس با شبکه، گیرنده‌ها را ثبت می‌کند
    sent_to: list[str] = []

    def _fake_send(messages, **_kwargs):
        from mktcore.execution.providers import SendResult

        sent_to.extend(m.customer_id for m in messages)
        return SendResult(
            total=len(messages), sent=len(messages), failed=0,
            dry_run=False, provider="mock", details=[],
        )

    monkeypatch.setattr("api.main.send_campaign", _fake_send)

    settings = __import__("mktcore.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "mkt_sms_enable", True, raising=False)
    monkeypatch.setattr(settings, "kavenegar_api_key", "test-key", raising=False)

    # ⚠️ این تست باید **ناتهی** باشد: اگر مخاطبِ خامْ هیچ عضوِ کنترلی نداشته
    # باشد، «نشتی نبود» چیزی را ثابت نمی‌کند. پس اول ثابت می‌شود که گارد واقعاً
    # چیزی برای جلوگیری داشت.
    from mktcore.execution.audience import build_audience

    bundle = store.load_bundle(session_id)
    clean = store.load_clean(session_id)
    raw_audience = {
        r.customer_id for r in build_audience(bundle, "سررسیدشده", df=clean, limit=500)
    }
    at_risk = raw_audience & set(control)
    assert at_risk, (
        "مخاطبِ خام هیچ عضوِ گروه کنترلی ندارد، پس این تست چیزی را اثبات نمی‌کند"
    )

    r = client.post("/api/sms/send", json={
        "session_id": session_id, "kind": "سررسیدشده",
        "template": "سلام {نام}", "limit": 500,
        "dry_run": False, "confirm": True,
    })
    assert r.status_code == 200, r.text

    leaked = set(sent_to) & set(control)
    assert not leaked, f"گروه کنترل پیام گرفت: {sorted(leaked)[:5]}"
    # و گزارش باید همان تعداد را صریح بگوید
    assert r.json()["مسدودشده"] >= len(at_risk)


def test_opted_out_customer_is_never_in_a_send(session_id, monkeypatch):
    with session_scope() as session:
        customer = session.scalar(select(Customer))
        customer_id, raw_key = customer.id, customer.canonical_key

    r = client.post(f"/api/v1/customers/{customer_id}/opt-out", json={
        "reason_fa": "تلفنی گفت پیام نفرستید",
    })
    assert r.status_code == 200, r.text

    sent_to: list[str] = []

    def _fake_send(messages, **_kwargs):
        from mktcore.execution.providers import SendResult

        sent_to.extend(m.customer_id for m in messages)
        return SendResult(total=len(messages), sent=len(messages), failed=0,
                          dry_run=False, provider="mock", details=[])

    monkeypatch.setattr("api.main.send_campaign", _fake_send)

    r = client.post("/api/sms/send", json={
        "session_id": session_id, "kind": "پیشنهاد_شخصی",
        "template": "سلام {نام}", "limit": 500, "dry_run": True,
    })
    assert r.status_code == 200, r.text
    assert str(raw_key) not in set(sent_to)

    # و پس گرفتن انصراف باید برش گرداند
    assert client.delete(f"/api/v1/customers/{customer_id}/opt-out").status_code == 200


def test_send_response_reports_suppression_and_never_hides_it(session_id):
    """حذفِ بی‌صدا ممنوع: پاسخ باید تعداد و دلیل را بگوید."""
    r = client.post("/api/sms/send", json={
        "session_id": session_id, "kind": "سررسیدشده",
        "template": "سلام {نام}", "limit": 200, "dry_run": True,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert "مسدودشده" in body
    assert isinstance(body["مسدودشده"], int)
    assert "دلایل_مسدودی" in body
    if body["مسدودشده"]:
        assert body["یادداشت_مجوز_تماس"]
        assert sum(d["تعداد"] for d in body["دلایل_مسدودی"]) == body["مسدودشده"]


def test_existing_sms_contract_is_untouched(session_id):
    """قرارداد صفر-رگرسیون: کلیدهای قبلی سر جایشان‌اند."""
    r = client.post("/api/sms/send", json={
        "session_id": session_id, "kind": "سررسیدشده",
        "template": "سلام {نام}", "limit": 10, "dry_run": True,
    })
    assert r.status_code == 200
    body = r.json()
    for key in ("audience_size", "حالت_آزمایشی", "تعداد_کل", "ارسال‌شده", "ناموفق"):
        assert key in body, f"کلید موجود {key} حذف شده است"


# ═════════════════════════════════════ باگِ رفع‌شده: پیش‌نمایش ≠ تماس
def test_dry_run_preview_does_not_make_a_customer_look_contacted():
    """باگِ پیش از این فاز: پیش‌نمایشِ آزمایشی هم ردیف outbox می‌نوشت و مشتری را
    ۱۴ روز «خسته از تماس» می‌کرد، پس فرصت‌هایش ساخته نمی‌شد — بدون اینکه پیامی
    برایش رفته باشد.
    """
    store.add_outbox(
        kind="campaign_sms", session_id="s-dry", audience="سررسیدشده",
        customer_id="DRYRUN-ONLY", phone="+989120000000", message="متن",
        status="آماده‌ی ارسال", provider="dry-run", dry_run=True,
    )
    store.add_outbox(
        kind="campaign_sms", session_id="s-real", audience="سررسیدشده",
        customer_id="REALLY-SENT", phone="+989120000001", message="متن",
        status="ارسال شد", provider="kavenegar", dry_run=False,
    )

    recent = store.recent_contact_customer_ids(14.0)
    assert "REALLY-SENT" in recent
    assert "DRYRUN-ONLY" not in recent, "پیش‌نمایش نباید «تماس» شمرده شود"


# ═══════════════════════════════════════ هم‌پوشانی کمپین‌ها در ساخت
def test_new_campaign_excludes_the_control_arm_of_an_open_campaign(session_id):
    """گروه کنترلِ کمپینِ فعال نباید در کمپین بعدی تماس بگیرد.

    وگرنه گروه کنترلِ کمپین اول دیگر کنترل نیست و اثرِ **هر دو** کمپین بی‌اعتبار
    می‌شود. حذف در لحظه‌ی ساخت انجام می‌شود، نه خروجی، تا اندازه‌ی بازوها بعد از
    تخصیص تغییر نکند.
    """
    reset_contact_history()
    first = client.post("/api/v1/campaigns", json={
        "name": "کمپین اول", "holdout_pct": 20,
    })
    assert first.status_code == 200, first.text
    first_control, _ = _control_and_treatment(first.json()["id"])
    assert first_control

    second = client.post("/api/v1/campaigns", json={
        "name": "کمپین دوم", "holdout_pct": 20,
    })
    assert second.status_code == 200, second.text
    second_id = second.json()["id"]
    second_control, second_treatment = _control_and_treatment(second_id)

    overlap = set(second_treatment) & set(first_control)
    assert not overlap, f"گروه کنترلِ کمپین اول در بازوی آزمایشِ دوم آمد: {overlap}"
    assert not (set(second_control) & set(first_control))

    body = second.json()
    assert "contact_gate" in body
    assert body["contact_gate"]["مسدودشده"] >= len(first_control) - len(second_control)


def test_export_stamps_exposure_only_for_members_actually_in_the_file(session_id):
    """مهرِ تماس نباید روی عضوی بخورد که دروازه کنارش گذاشته است.

    اگر بخورد، سنجش تماسی را می‌شمارد که هرگز انجام نشده و اثر را کمتر از واقع
    نشان می‌دهد.
    """
    reset_contact_history()
    created = client.post("/api/v1/campaigns", json={
        "name": "کمپین مهر", "holdout_pct": 10,
    })
    assert created.status_code == 200, created.text
    campaign_id = created.json()["id"]

    # یکی از اعضای بازوی آزمایش را منصرف می‌کنیم
    with session_scope() as session:
        member = session.scalar(
            select(CampaignMember).where(
                CampaignMember.campaign_id == campaign_id,
                CampaignMember.arm == ARM_TREATMENT,
            )
        )
        opted_out_id = member.customer_id

    r = client.post(f"/api/v1/customers/{opted_out_id}/opt-out", json={
        "reason_fa": "درخواست خودش",
    })
    assert r.status_code == 200, r.text

    export = client.get(f"/api/v1/campaigns/{campaign_id}/export")
    assert export.status_code == 200, export.text
    assert int(export.headers["X-Contact-Suppressed"]) >= 1

    with session_scope() as session:
        refreshed = session.scalar(
            select(CampaignMember).where(
                CampaignMember.campaign_id == campaign_id,
                CampaignMember.customer_id == opted_out_id,
            )
        )
        assert refreshed.exposure_at is None, "عضوِ کنارگذاشته‌شده نباید مهرِ تماس بخورد"

    client.delete(f"/api/v1/customers/{opted_out_id}/opt-out")


# ═════════════════════════════════════════════════════ دفترِ انصراف API
def test_suppression_register_endpoint_lists_and_explains(session_id):
    with session_scope() as session:
        customer_id = session.scalar(select(Customer.id))

    client.post(f"/api/v1/customers/{customer_id}/opt-out", json={
        "reason_fa": "نمونه برای فهرست",
    })
    r = client.get("/api/v1/contact-suppressions")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    assert body["note_fa"]
    assert any(item["customer_id"] == customer_id for item in body["items"])

    client.delete(f"/api/v1/customers/{customer_id}/opt-out")


def test_opt_out_requires_a_reason(session_id):
    with session_scope() as session:
        customer_id = session.scalar(select(Customer.id))
    r = client.post(f"/api/v1/customers/{customer_id}/opt-out", json={"reason_fa": ""})
    assert r.status_code == 422, "دلیل خالی باید رد شود"


def test_revoking_a_missing_opt_out_is_404(session_id):
    r = client.delete("/api/v1/customers/999999/opt-out")
    assert r.status_code == 404


# ═══════════════════════════════ خستگی تماس در مسیر کمپین (§۲۷.۵ — بازبینی)
def _campaign_members(campaign_id: int) -> dict[str, list[int]]:
    with session_scope() as session:
        rows = session.execute(
            select(CampaignMember.arm, CampaignMember.customer_id)
            .where(CampaignMember.campaign_id == campaign_id)
        ).all()
    out: dict[str, list[int]] = {}
    for arm, customer_id in rows:
        out.setdefault(arm, []).append(int(customer_id))
    return out


def test_exposed_members_are_fatigued_for_the_next_campaign(session_id, monkeypatch):
    """عضوی که این هفته از کمپین «الف» فهرستش دانلود شده، در «ب» دوباره تماس نمی‌گیرد."""
    from mktcore.config import get_settings

    monkeypatch.setattr(get_settings(), "mkt_api_token", "", raising=False)
    reset_contact_history()
    a = client.post("/api/v1/campaigns", json={"name": "الف", "holdout_pct": 20, "limit": 40})
    assert a.status_code == 200, a.text
    a_id = a.json()["id"]
    assert client.get(f"/api/v1/campaigns/{a_id}/export").status_code == 200
    exposed = set(_campaign_members(a_id).get(ARM_TREATMENT, []))
    assert exposed, "کمپین الف باید بازوی آزمایشِ تماس‌گرفته داشته باشد"

    # کمپینِ خودِ عضو مستثناست: دانلودِ دوباره‌ی همان فهرست مجاز می‌ماند
    assert client.get(f"/api/v1/campaigns/{a_id}/export").status_code == 200

    b = client.post("/api/v1/campaigns", json={"name": "ب", "holdout_pct": 20, "limit": 500})
    if b.status_code == 409:
        # همه‌ی نامزدها کنار گذاشته شدند — دلیلش باید همان خستگی تماس باشد
        assert "خستگی تماس" in b.json()["detail"]
        return
    assert b.status_code == 200, b.text
    body = b.json()
    b_members = _campaign_members(body["id"])
    all_b = set(b_members.get(ARM_TREATMENT, [])) | set(b_members.get(ARM_CONTROL, []))
    assert not (all_b & exposed), "عضوِ تماس‌گرفته‌ی «الف» نباید واردِ «ب» شود"
    reasons = {row["دلیل"]: row["تعداد"] for row in body["contact_gate"]["دلایل_مسدودی"]}
    assert reasons.get("خستگی تماس (تماس اخیر)", 0) >= 1
    assert "بررسی‌نشده" not in body["contact_gate"], "خستگی دیگر «بررسی‌نشده» نیست"
    assert "خستگی تماس" in body.get("contact_gate_note_fa", "")


def test_fatigue_does_not_trim_the_treatment_arm_after_randomisation(session_id):
    """خستگی فقط در ساخت اعمال می‌شود؛ خروجی/ارسال بازوی آزمایش را نمی‌تراشند (تعادلِ بازوها)."""
    from mktcore.db.base import now_ts

    reset_contact_history()
    a = client.post("/api/v1/campaigns", json={"name": "الف۲", "holdout_pct": 20, "limit": 40})
    assert a.status_code == 200, a.text
    b = client.post("/api/v1/campaigns", json={"name": "ب۲", "holdout_pct": 20, "limit": 40})
    assert b.status_code == 200, b.text
    # عضوِ آزمایشِ «ب» همین حالا از کمپینِ دیگری تماس می‌گیرد (مهرِ تماس روی «الف»)
    b_treatment = _campaign_members(b.json()["id"]).get(ARM_TREATMENT, [])
    assert b_treatment
    with session_scope() as session:
        members = session.scalars(
            select(CampaignMember).where(
                CampaignMember.campaign_id == a.json()["id"],
                CampaignMember.customer_id.in_(b_treatment[:5]),
            )
        ).all()
        stamped = 0
        for member in members:
            member.exposure_at = now_ts()
            member.exposure_channel = "excel_export"
            stamped += 1
    assert stamped, "دست‌کم یک عضوِ آزمایشِ «ب» باید در «الف» هم باشد تا مهر بخورد"
    export = client.get(f"/api/v1/campaigns/{b.json()['id']}/export")
    assert export.status_code == 200
    # فقط رضایت و گروه کنترل در خروجی سنجیده می‌شوند؛ مهرِ خستگی هیچ‌کس را کنار نمی‌گذارد
    assert export.headers.get("X-Contact-Suppressed") == "0", export.headers.get("X-Contact-Suppressed")


def test_recent_exposures_ignore_previews_and_the_campaign_itself(session_id):
    from mktcore.contact.register import recent_exposures
    from mktcore.db.lookup import active_business_id
    from mktcore.db.models import Campaign

    # مهرهای واقعیِ تست‌های قبلی (زمانِ حال) از پنجره‌ی ساختگیِ این تست «جدیدتر»ند؛
    # پس اول پاک می‌شوند تا فقط همین یک مهر سنجیده شود.
    reset_contact_history()
    with session_scope() as session:
        business_id = active_business_id(session)
        campaign = session.scalar(
            select(Campaign).where(Campaign.business_id == business_id).order_by(Campaign.id.desc())
        )
        assert campaign is not None
        member = session.scalar(
            select(CampaignMember).where(CampaignMember.campaign_id == campaign.id)
        )
        member.exposure_at = 1_000_000.0          # دیروزِ دور: بیرونِ پنجره
        session.flush()
        old = recent_exposures(session, business_id, window_days=14, now=1_000_000.0 + 20 * 86400)
        fresh = recent_exposures(session, business_id, window_days=14, now=1_000_000.0 + 3 * 86400)
        own = recent_exposures(
            session, business_id, window_days=14, now=1_000_000.0 + 3 * 86400,
            exclude_campaign_id=campaign.id,
        )
        member.exposure_at = None

    assert member.customer_id not in old
    assert member.customer_id in fresh
    assert member.customer_id not in own


def test_legacy_send_path_sees_campaign_exposures(session_id, monkeypatch):
    """/api/sms/send تا امروز فقط outbox را می‌دید؛ تماسِ کمپین هم تماس است."""
    from mktcore.db.base import now_ts

    reset_contact_history()
    created = client.post("/api/v1/campaigns", json={"name": "الف۳", "holdout_pct": 0, "limit": 60})
    assert created.status_code == 200, created.text
    treatment = _campaign_members(created.json()["id"]).get(ARM_TREATMENT, [])
    assert treatment
    with session_scope() as session:
        rows = session.scalars(
            select(CampaignMember).where(CampaignMember.campaign_id == created.json()["id"])
        ).all()
        for member in rows:
            member.exposure_at = now_ts()
            member.exposure_channel = "excel_export"
        raw_keys = {
            str(k) for k in session.scalars(
                select(Customer.canonical_key).where(Customer.id.in_(treatment))
            )
        }

    sent_to: list[str] = []

    def _fake_send(messages, **_kwargs):
        from mktcore.execution.providers import SendResult

        sent_to.extend(m.customer_id for m in messages)
        return SendResult(total=len(messages), sent=len(messages), failed=0,
                          dry_run=True, provider="mock", details=[])

    monkeypatch.setattr("api.main.send_campaign", _fake_send)
    r = client.post("/api/sms/send", json={
        "session_id": session_id, "kind": "پیشنهاد_شخصی", "template": "سلام {نام}",
        "limit": 500, "dry_run": True,
    })
    assert r.status_code == 200, r.text
    assert not (set(sent_to) & raw_keys), "عضوِ تازه‌تماس‌گرفته‌ی کمپین نباید از مسیرِ legacy پیام بگیرد"
    reasons = {row["دلیل"]: row["تعداد"] for row in r.json().get("دلایل_مسدودی", [])}
    assert reasons.get("خستگی تماس (تماس اخیر)", 0) >= 1
