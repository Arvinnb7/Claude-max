"""مسیرهای کمپین — ساخت آزمایش، خروجی تماس، و گزارش اثر.

جدا از `api/v1.py` نگه داشته شده چون منطقش سنگین‌تر است و مرزش روشن: اینجا
همه‌چیز درباره‌ی **آزمایش** است، نه گزارش وضعیت.

نکته‌ی مهم درباره‌ی «ثبت تماس»: چون کانال اجرا خروجی اکسل است، لحظه‌ی دانلود
فایل همان لحظه‌ی در معرض قرارگرفتن ثبت می‌شود. این یک تقریب است و صریحاً در
پاسخ گفته می‌شود؛ اگر فهرست را دانلود کنید و تماس نگیرید، اثر کمی
دست‌کم‌برآورد می‌شود (چون آن افراد در مخرج می‌مانند).
"""

from __future__ import annotations

import io
import json
import logging
from urllib.parse import quote

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from mktcore.campaigns.analysis import ArmStats, analyze_campaign
from mktcore.campaigns.assign import ARM_CONTROL, ARM_TREATMENT, assign_arms
from mktcore.campaigns.outcomes import arm_stats, compute_campaign_outcomes
from mktcore.config import get_settings
from mktcore.contact.permission import DEFAULT_FATIGUE_WINDOW_DAYS
from mktcore.contact.register import build_gate, recent_contact_keys
from mktcore.db.base import now_ts
from mktcore.db.engine import session_scope, write_lock
from mktcore.db.lookup import active_business_id
from mktcore.db.migrations import ensure_schema
from mktcore.db.models import (
    AuditEvent,
    Campaign,
    CampaignMember,
    CampaignOpportunity,
    CampaignOutcome,
    CampaignSend,
    Customer,
    CustomerFeature,
    Opportunity,
    OpportunityOffer,
)
from mktcore.db.repo_audit import record_audit_event
from mktcore.execution import send_campaign
from mktcore.execution.audience import RenderedMessage, render_template
from mktcore.execution.cost import cost_note_fa, message_cost_rial, segment_count
from mktcore.identity import mask_phone, normalize_phone
from mktcore.lifecycle import STATE_LABELS_FA
from mktcore.money import money_payload
from mktcore.security import require_token

from .audit_context import actor_fa, client_ip

logger = logging.getLogger("mktcore.api.campaigns")

router = APIRouter(prefix="/api/v1/campaigns", tags=["campaigns"])

OFFER_PLACEHOLDER = "{تخفیف}"
EXPOSURE_CHANNEL_EXCEL = "excel_export"
EXPOSURE_CHANNEL_SMS = "sms"
EXPOSURE_NOTE_FA = (
    "لحظه‌ی دانلود فهرست به‌عنوان «تماس گرفته شد» ثبت می‌شود. اگر فهرستی را "
    "دانلود کنید ولی تماس نگیرید، آن افراد در گروه آزمایش می‌مانند و اثر "
    "اندکی کمتر از واقع گزارش می‌شود."
)


class CreateCampaignRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    status: str = "open"                 # وضعیت فرصت‌هایی که وارد کمپین می‌شوند
    kind: str | None = None              # فیلتر نوع فرصت
    holdout_pct: int = Field(default=10, ge=0, le=50)
    analysis_window_days: int = Field(default=30, ge=1, le=365)
    limit: int = Field(default=500, ge=1, le=5000)


def _business_id(session) -> int | None:
    """همان کسب‌وکارِ فعالِ خواندن — کمپین باید روی داده‌ای بسته شود که کاربر می‌بیند."""
    return active_business_id(session)


def _campaign_gate(session, business_id: int, *, exclude_campaign_id: int | None = None):
    """دروازه‌ی مجوز تماس برای مسیرِ کمپین — با خستگیِ تماس (§۲۷.۵).

    تا پیش از این، سه مسیرِ کمپین `build_gate` را بدون تاریخچه‌ی تماس می‌ساختند و
    خستگی «بررسی نشد» بود: عضوی که همین هفته از کمپین «الف» پیامک گرفته بود، در
    کمپین «ب» دوباره تماس می‌گرفت. پنجره همان ۱۴ روزِ موتور فرصت است (تصمیمِ
    کاربر)؛ منبع: مهرِ تماسِ کمپین‌ها + outboxِ legacy. کمپینِ خودِ عضو مستثناست.
    """
    try:
        from api.persistence import store

        legacy = set(store.recent_contact_customer_ids(DEFAULT_FATIGUE_WINDOW_DAYS))
    except Exception:  # noqa: BLE001 - نبودِ تاریخچه‌ی legacy نباید کمپین را بخواباند
        legacy = set()
    recent = recent_contact_keys(
        session, business_id, window_days=DEFAULT_FATIGUE_WINDOW_DAYS,
        exclude_campaign_id=exclude_campaign_id, legacy_raw_keys=legacy,
    )
    return build_gate(
        session, business_id,
        fatigue_window_days=DEFAULT_FATIGUE_WINDOW_DAYS, recently_contacted=recent,
    )


def _no_ledger() -> dict:
    return {
        "available": False,
        "note_fa": "هنوز تحلیلی ثبت نشده است؛ ابتدا یک فایل را تحلیل کنید.",
    }


@router.post("", dependencies=[Depends(require_token)])
def create_campaign(req: CreateCampaignRequest) -> dict:
    """ساخت کمپین از فرصت‌های باز، با تخصیص تصادفیِ گروه کنترل."""
    ensure_schema()
    with write_lock, session_scope() as session:
        business_id = _business_id(session)
        if business_id is None:
            raise HTTPException(status_code=409, detail="هنوز داده‌ای تحلیل نشده است.")

        stmt = select(Opportunity).where(
            Opportunity.business_id == business_id,
            Opportunity.customer_id.isnot(None),
        )
        if req.status != "all":
            stmt = stmt.where(Opportunity.status == req.status)
        if req.kind:
            stmt = stmt.where(Opportunity.kind == req.kind)
        # حدِ اندازه‌ی کمپین **بعد از** دروازه اعمال می‌شود (پایین‌تر)، نه در
        # همین پرس‌وجو: وگرنه عضوِ کنترلِ کمپینِ دیگری که فرصتِ پرارزش‌تری دارد،
        # جای یکی از مجازها را می‌گیرد و بعد کنار گذاشته می‌شود — کمپین کوچک‌تر
        # از آنچه کاربر خواست می‌شود، یا با حدِ کوچک بی‌دلیل ۴۰۹ می‌گیرد.
        opportunities = session.scalars(
            stmt.order_by(Opportunity.score_rial.desc(), Opportunity.id)
        ).all()
        if not opportunities:
            raise HTTPException(
                status_code=409,
                detail="فرصتی با این فیلتر برای ساخت کمپین وجود ندارد.",
            )

        # دروازه‌ی مجوز تماس **پیش از تخصیص بازو**. اگر این حذف را به لحظه‌ی
        # خروجی موکول کنیم، اندازه‌ی بازوها و نسبت گروه کنترل بعد از تخصیص تغییر
        # می‌کند و کمپین با نسبتی غیر از آنچه کاربر خواسته اجرا می‌شود.
        #
        # مهم‌ترین موردش هم‌پوشانیِ کمپین‌هاست: مشتری‌ای که در کمپینِ فعالِ «الف»
        # گروه کنترل است، نباید در کمپین «ب» تماس بگیرد — وگرنه گروه کنترلِ «الف»
        # دیگر کنترل نیست و اثرِ اندازه‌گیری‌شده‌ی هر دو کمپین بی‌اعتبار می‌شود.
        gate = _campaign_gate(session, business_id)
        eligible = gate.partition(
            opportunities, key=lambda o: str(o.customer_id),
        )
        opportunities = eligible.allowed[: req.limit]
        if not opportunities:
            raise HTTPException(
                status_code=409,
                detail=(
                    "همه‌ی فرصت‌های این فیلتر با دروازه‌ی مجوز تماس کنار گذاشته شدند: "
                    f"{eligible.note_fa()}"
                ),
            )

        # طبقه‌بندی برای تصادفی‌سازی متوازن: حالت چرخه‌ی عمر، وگرنه سگمنت
        customer_ids = {o.customer_id for o in opportunities if o.customer_id}
        strata = _strata(session, business_id, customer_ids)

        campaign = Campaign(
            business_id=business_id,
            name=req.name,
            kind=req.kind,
            status="running",
            holdout_pct=req.holdout_pct,
            analysis_window_days=req.analysis_window_days,
            notes_json=json.dumps(
                {"source_status": req.status, "limit": req.limit}, ensure_ascii=False,
            ),
        )
        session.add(campaign)
        session.flush()

        assignments = assign_arms(
            {str(cid): strata.get(cid, "—") for cid in customer_ids},
            campaign_key=f"campaign-{campaign.id}",
            holdout_pct=req.holdout_pct,
        )
        today = pd.Timestamp.now().date().isoformat()
        value_by_customer: dict[int, int] = {}
        for opportunity in opportunities:
            if opportunity.customer_id:
                value_by_customer[opportunity.customer_id] = (
                    value_by_customer.get(opportunity.customer_id, 0)
                    + int(opportunity.expected_value_rial or 0)
                )

        for assignment in assignments:
            customer_id = int(assignment.customer_key)
            session.add(CampaignMember(
                campaign_id=campaign.id,
                customer_id=customer_id,
                arm=assignment.arm,
                stratum=assignment.stratum,
                assigned_date=today,
                expected_value_rial=value_by_customer.get(customer_id),
            ))
        for opportunity in opportunities:
            if opportunity.customer_id:
                session.add(CampaignOpportunity(
                    campaign_id=campaign.id,
                    opportunity_id=opportunity.id,
                    customer_id=opportunity.customer_id,
                ))
        session.flush()
        payload = _campaign_detail(session, campaign)
        # حذفِ بی‌صدا ممنوع: اگر کسی پیش از تخصیص کنار گذاشته شد، گفته می‌شود.
        payload["contact_gate"] = eligible.to_dict()
        gate_note = eligible.note_fa()
        if gate_note:
            payload["contact_gate_note_fa"] = gate_note
    return payload


def _strata(session, business_id: int, customer_ids: set[int]) -> dict[int, str]:
    """طبقه‌ی هر مشتری: حالت چرخه‌ی عمر، وگرنه سگمنت، وگرنه «—»."""
    if not customer_ids:
        return {}
    latest = session.scalar(
        select(func.max(CustomerFeature.as_of_date))
        .where(CustomerFeature.business_id == business_id)
    )
    rows = session.execute(
        select(
            CustomerFeature.customer_id,
            CustomerFeature.lifecycle_state,
            CustomerFeature.segment,
        ).where(
            CustomerFeature.business_id == business_id,
            CustomerFeature.as_of_date == latest,
            CustomerFeature.customer_id.in_(sorted(customer_ids)),
        )
    ).all()
    return {
        int(cid): str(state or segment or "—")
        for cid, state, segment in rows
    }


@router.get("")
def list_campaigns(limit: int = Query(50, ge=1, le=200)) -> dict:
    ensure_schema()
    with session_scope() as session:
        business_id = _business_id(session)
        if business_id is None:
            return {**_no_ledger(), "items": []}
        campaigns = session.scalars(
            select(Campaign)
            .where(Campaign.business_id == business_id)
            .order_by(Campaign.created_at.desc())
            .limit(limit)
        ).all()
        items = [_campaign_summary(session, c) for c in campaigns]
    return {"available": True, "items": items, "exposure_note_fa": EXPOSURE_NOTE_FA}


@router.get("/{campaign_id}")
def get_campaign(campaign_id: int, members_limit: int = Query(200, ge=1, le=2000)) -> dict:
    """جزئیات کمپین + گزارش اثر."""
    ensure_schema()
    with session_scope() as session:
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="این کمپین یافت نشد.")

        payload = _campaign_detail(session, campaign, members_limit)
    return payload


def _campaign_detail(session, campaign: Campaign, members_limit: int = 200) -> dict:
    """شکل کاملِ کمپین — همان چیزی که همه‌ی مسیرهای جزئیات برمی‌گردانند.

    مشترک نگه داشته شده تا `refresh` و `close` هم دقیقاً همان شکل را بدهند؛
    وگرنه کلاینت بعد از هر اقدام مجبور بود یک درخواست اضافه بزند.
    """
    payload = _campaign_summary(session, campaign)
    payload["report"] = _report(session, campaign.id)

    members = session.scalars(
        select(CampaignMember)
        .where(CampaignMember.campaign_id == campaign.id)
        .order_by(CampaignMember.expected_value_rial.desc())
        .limit(members_limit)
    ).all()
    names = _customer_names(session, {m.customer_id for m in members})
    outcomes = {
        o.customer_id: o
        for o in session.scalars(
            select(CampaignOutcome).where(CampaignOutcome.campaign_id == campaign.id)
        ).all()
    }
    payload["members"] = [
        {
            "customer_id": m.customer_id,
            "customer_name": names.get(m.customer_id),
            "arm": m.arm,
            "stratum": m.stratum,
            "exposure_date": m.exposure_date,
            "expected_value": money_payload(m.expected_value_rial or 0),
            "outcome": (
                {
                    "orders": outcomes[m.customer_id].orders_count,
                    "revenue": money_payload(outcomes[m.customer_id].revenue_rial),
                    "matched_product": outcomes[m.customer_id].matched_product,
                    "window": [
                        outcomes[m.customer_id].window_start,
                        outcomes[m.customer_id].window_end,
                    ],
                }
                if m.customer_id in outcomes else None
            ),
        }
        for m in members
    ]
    payload["exposure_note_fa"] = EXPOSURE_NOTE_FA
    return payload


@router.get("/{campaign_id}/export", dependencies=[Depends(require_token)])
def export_campaign(campaign_id: int, request: Request):
    """خروجی اکسل بازوی آزمایش — و ثبت لحظه‌ی تماس.

    گروه کنترل **عمداً** در فایل نیست؛ اگر بود، کاربر ناخواسته با آن‌ها تماس
    می‌گرفت و آزمایش از بین می‌رفت.
    """
    ensure_schema()
    with write_lock, session_scope() as session:
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="این کمپین یافت نشد.")

        members = session.scalars(
            select(CampaignMember).where(
                CampaignMember.campaign_id == campaign_id,
                CampaignMember.arm == ARM_TREATMENT,
            )
        ).all()
        if not members:
            raise HTTPException(
                status_code=409, detail="این کمپین عضوی در گروه آزمایش ندارد.",
            )

        # دروازه‌ی مجوز تماس روی بازوی آزمایش. مشتریِ منصرف نباید در فایل بیاید،
        # **و مهرِ تماس هم نباید بخورد** — وگرنه سنجش، تماسی را می‌شمارد که هرگز
        # انجام نشده و اثر را کمتر از واقع نشان می‌دهد.
        gate = _campaign_gate(session, campaign.business_id, exclude_campaign_id=campaign.id)
        screened = gate.partition(members, key=lambda m: str(m.customer_id))
        members = screened.allowed
        if not members:
            raise HTTPException(
                status_code=409,
                detail=(
                    "همه‌ی اعضای گروه آزمایش با دروازه‌ی مجوز تماس کنار گذاشته شدند: "
                    f"{screened.note_fa()}"
                ),
            )

        rows = _export_rows(session, campaign_id, members)
        today = pd.Timestamp.now().date().isoformat()
        stamp = now_ts()
        for member in members:
            # اولین تماس ملاک است؛ دانلود دوباره پنجره‌ی سنجش را جابه‌جا نمی‌کند
            if member.exposure_at is None:
                member.exposure_at = stamp
                member.exposure_date = today
                member.exposure_channel = EXPOSURE_CHANNEL_EXCEL
        if campaign.exported_at is None:
            campaign.exported_at = stamp
        name = campaign.name
        suppressed = screened.suppressed_count

        # این فایل فهرستِ **کاملِ** شماره‌ها را دارد (نه ماسک‌شده). تا پیش از
        # این، تنها ردِ ماجرا `exported_at` بود که فقط اولین دانلود را نگه
        # می‌داشت؛ دانلودهای بعدی هیچ اثری نمی‌گذاشتند.
        record_audit_event(
            session,
            action=AuditEvent.ACTION_CAMPAIGN_EXPORT,
            business_id=campaign.business_id,
            entity_type="campaign",
            entity_id=campaign_id,
            actor=actor_fa(request),
            source_ip=client_ip(request),
            row_count=len(rows),
            detail_fa=(
                f"خروجی اکسل کمپین «{name}»: {len(rows)} شماره‌ی کامل، "
                f"{suppressed} مورد با دروازه‌ی مجوز تماس کنار گذاشته شد."
            ),
        )

    content = _workbook(rows)
    filename = quote(f"کمپین-{name}.xlsx")
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
            # حذفِ بی‌صدا ممنوع: تعداد کنارگذاشته‌شده‌ها در هدر می‌آید تا فایلِ
            # کوتاه‌ترشده بی‌توضیح نماند.
            "X-Contact-Suppressed": str(suppressed),
        },
    )


class SendCampaignRequest(BaseModel):
    """درخواست ارسال مستقیم کمپین.

    پیش‌فرض **آزمایشی** است. ارسال واقعی سه شرط هم‌زمان لازم دارد:
    `dry_run=false` و `confirm=true` و پیکربندی‌شدن پنل در env — همان گیت
    سه‌لایه‌ی `/api/sms/send` که از قبل وجود داشت.
    """

    # اگر ندهید، متنِ پیشنهادیِ خودِ فرصت استفاده می‌شود
    template: str | None = Field(default=None, max_length=1000)
    dry_run: bool = True
    confirm: bool = False
    limit: int = Field(default=1000, ge=1, le=5000)


@router.post("/{campaign_id}/send", dependencies=[Depends(require_token)])
def send_campaign_sms(campaign_id: int, req: SendCampaignRequest) -> dict:
    """ارسال مستقیم پیامک به بازوی آزمایش.

    تفاوت بنیادی با `/api/sms/send` قدیمی: آن مسیر مخاطبش را از تحلیل می‌ساخت و
    از کمپین بی‌خبر بود. این مسیر از **اعضای کمپین** می‌خواند، پس:

    * گروه کنترل ساختاراً غیرممکن است که پیام بگیرد (فیلتر `arm` در پرس‌وجو).
    * لحظه‌ی تماس دقیق ثبت می‌شود، نه تقریبیِ «وقتی اکسل را گرفتم».
    * هزینه‌ی هر پیام ثبت می‌شود، پس «هزینه به‌ازای سفارش افزوده» باز می‌شود.

    ارسالِ دوباره امکان‌ناپذیر است: هر عضو حداکثر یک ردیف در `campaign_sends`
    دارد و اعضای فرستاده‌شده از فهرست کنار گذاشته می‌شوند.
    """
    ensure_schema()
    settings = get_settings()
    cost_per_segment = int(settings.mkt_sms_cost_per_segment_rial)

    wants_real = not req.dry_run
    real_send = wants_real and req.confirm and settings.sms_configured
    note = None
    if wants_real and not real_send:
        if not settings.sms_configured:
            note = (
                "ارسال واقعی غیرفعال است: MKT_SMS_ENABLE=1 و KAVENEGAR_API_KEY را در "
                "تنظیمات سرور بگذارید. نتیجه به‌صورت آزمایشی برگردانده شد."
            )
        else:
            note = "برای ارسال واقعی، تأیید صریح (confirm=true) لازم است. نتیجه آزمایشی است."

    with write_lock, session_scope() as session:
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="این کمپین یافت نشد.")
        if campaign.status == "closed":
            raise HTTPException(
                status_code=409, detail="این کمپین بسته شده است و ارسال تازه نمی‌پذیرد.",
            )

        members = session.scalars(
            select(CampaignMember).where(
                CampaignMember.campaign_id == campaign_id,
                CampaignMember.arm == ARM_TREATMENT,
            )
        ).all()
        if not members:
            raise HTTPException(
                status_code=409, detail="این کمپین عضوی در گروه آزمایش ندارد.",
            )

        # گاردِ ارسال دوباره — **فقط** ارسالِ موفق مانع تلاش دوباره است.
        # ردیفِ `skipped` یعنی هرگز چیزی نرفته (شماره نبود، یا متن نبود)؛ اگر آن
        # هم مانع می‌شد، کاربری که بعد از دیدنِ «متن ندارد» قالب می‌دهد، با
        # «قبلاً فرستاده شده» روبه‌رو می‌شد و راهِ جبران نداشت.
        prior = {
            int(cid): row for cid, row in session.execute(
                select(CampaignSend.customer_id, CampaignSend)
                .where(CampaignSend.campaign_id == campaign_id)
            ).all()
        }
        delivered = {
            cid for cid, row in prior.items() if row.status == CampaignSend.STATUS_SENT
        }
        pending = [m for m in members if int(m.customer_id) not in delivered]
        if not pending:
            raise HTTPException(
                status_code=409,
                detail="برای همه‌ی اعضای گروه آزمایش قبلاً پیام فرستاده شده است.",
            )

        # دروازه‌ی مجوز تماس — همان گاردی که خروجی اکسل هم از آن رد می‌شود
        gate = _campaign_gate(session, campaign.business_id, exclude_campaign_id=campaign.id)
        screened = gate.partition(pending, key=lambda m: str(m.customer_id))
        pending = screened.allowed[:req.limit]
        if not pending:
            raise HTTPException(
                status_code=409,
                detail=(
                    "همه‌ی اعضای باقی‌مانده با دروازه‌ی مجوز تماس کنار گذاشته شدند: "
                    f"{screened.note_fa()}"
                ),
            )

        drafts = _send_drafts(session, campaign_id, pending, req.template)
        # ارسال‌شدنی = هم شماره دارد، هم **متن**. متنِ خالی به پنل POST می‌شد و
        # هزینه هم ثبت می‌شد، بی‌آنکه چیزی به دست مشتری برسد.
        sendable = [d for d in drafts if d["phone"] and d["text"]]
        without_phone = [d for d in drafts if not d["phone"]]
        without_offer = [d for d in drafts if d["phone"] and d["blocked_by_offer"]]
        without_text = [
            d for d in drafts if d["phone"] and not d["text"] and not d["blocked_by_offer"]
        ]

        result = None
        if sendable:
            messages = [
                RenderedMessage(
                    customer_id=str(d["customer_id"]), phone=d["phone"], text=d["text"],
                )
                for d in sendable
            ]
            result = send_campaign(
                messages,
                provider=settings.mkt_sms_provider,
                api_key=settings.kavenegar_api_key if real_send else None,
                sender=settings.mkt_sms_sender,
                dry_run=not real_send,
            )

        status_of: dict[str, str] = {}
        message_id_of: dict[str, str | None] = {}
        if result is not None:
            for d in result.details:
                key = str(d.get("مشتری"))
                status_of[key] = str(d.get("وضعیت", ""))
                message_id_of[key] = d.get("شناسه_پیام")
        provider = result.provider if result is not None else "dry-run"

        stamp = now_ts()
        today = pd.Timestamp.now().date().isoformat()
        sent = failed = 0
        total_segments = total_cost = 0

        for draft in drafts:
            has_phone = bool(draft["phone"])
            has_text = bool(draft["text"])
            can_send = has_phone and has_text
            detail = status_of.get(str(draft["customer_id"]))
            ok = can_send and (result is not None) and "خطا" not in (detail or "")
            if not has_phone:
                status = CampaignSend.STATUS_SKIPPED
                detail = "شماره‌ی موبایل ثبت نشده است."
            elif draft["blocked_by_offer"]:
                status = CampaignSend.STATUS_SKIPPED
                detail = (
                    f"قالب پیام «{OFFER_PLACEHOLDER}» دارد ولی این فرصت تخفیفِ "
                    "تأییدشده ندارد. هیچ تخفیفی بدون تأییدِ انسان ارسال نمی‌شود؛ "
                    "در صندوق فرصت‌ها تأیید کنید یا قالبی بدون تخفیف بدهید."
                )
            elif not has_text:
                status = CampaignSend.STATUS_SKIPPED
                detail = (
                    "این فرصت متنِ آماده‌ی پیام ندارد. متنِ راهنمای تیم فروش برای "
                    "مشتری فرستاده نمی‌شود؛ برای ارسال، قالب پیام بدهید."
                )
            elif ok:
                status = CampaignSend.STATUS_SENT
            else:
                status = CampaignSend.STATUS_FAILED

            segments = segment_count(draft["text"]) if can_send else 0
            cost = (
                message_cost_rial(draft["text"], cost_per_segment_rial=cost_per_segment)
                if can_send else 0
            )
            # هزینه فقط برای ارسال واقعی جمع می‌شود؛ پیش‌نمایش پولی خرج نمی‌کند
            if real_send and status == CampaignSend.STATUS_SENT:
                total_segments += segments
                total_cost += cost
            if status == CampaignSend.STATUS_SENT:
                sent += 1
            elif status == CampaignSend.STATUS_FAILED:
                failed += 1

            # ردیفِ قبلیِ همین عضو (اگر `skipped` بود) به‌روز می‌شود، نه دوباره
            # ساخته — قید یکتاییِ (campaign, customer) اجازه‌ی ردیف دوم نمی‌دهد.
            row = prior.get(int(draft["customer_id"]))
            if row is None:
                row = CampaignSend(
                    business_id=campaign.business_id,
                    campaign_id=campaign_id,
                    customer_id=int(draft["customer_id"]),
                )
                session.add(row)
            row.phone_e164 = draft["phone"]
            row.message_text = draft["text"]
            row.segments = segments
            # هزینه فقط برای ارسالِ **واقعیِ موفق**. ردیفِ ناموفق یا آزمایشی
            # هزینه‌ی صفر می‌گیرد، وگرنه دفترِ هزینه پولی را ثبت می‌کند که
            # خرج نشده.
            billable = real_send and status == CampaignSend.STATUS_SENT
            row.cost_rial = cost if billable else 0
            row.provider = provider
            row.dry_run = not real_send
            row.status = status
            row.status_detail_fa = detail
            # شناسه‌ی پیام نزد پنل — پیش‌نیازِ webhook تحویل در گام بعد.
            row.provider_message_id = message_id_of.get(str(draft["customer_id"]))
            # §۲۰.۲ «کدام آفر نشان داده شد» — فقط آفرِ تأییدشده به اینجا می‌رسد
            row.offer_discount_bp = draft["offer_bp"] if status == CampaignSend.STATUS_SENT else None
            row.sent_at = stamp

            # ⚠️ مهرِ تماس **فقط** برای ارسالِ واقعیِ موفق.
            # پیش‌نمایش هیچ پیامی نفرستاده؛ اگر مهر بخورد، سنجشِ اثر تماسی را
            # می‌شمارد که رخ نداده و اثر را کمتر از واقع نشان می‌دهد.
            if real_send and status == CampaignSend.STATUS_SENT:
                member = draft["member"]
                if member.exposure_at is None:
                    member.exposure_at = stamp
                    member.exposure_date = today
                    member.exposure_channel = EXPOSURE_CHANNEL_SMS
                # مهرِ آفر جدا از «اولین تماس»: عضوی که اول فهرستش دانلود شده و
                # بعد با تخفیفِ تأییدشده پیامک گرفته، باید پله‌ی واقعاً ارسال‌شده
                # را داشته باشد؛ وگرنه در سنجش، شاهدِ بازوی بی‌تخفیف می‌شود.
                if draft["offer_bp"] is not None:
                    member.offer_discount_bp = draft["offer_bp"]

        session.flush()
        payload = _campaign_detail(session, campaign)

    money = money_payload(total_cost, get_settings().mkt_currency)
    payload["send"] = {
        "ارسال‌شده": sent,
        "ناموفق": failed,
        "بدون_شماره": len(without_phone),
        "بدون_متن": len(without_text),
        "بدون_تأیید_تخفیف": len(without_offer),
        "حالت_آزمایشی": not real_send,
        "ارائه‌دهنده": provider,
        "قطعه": total_segments,
        "هزینه": money,
        **screened.to_dict(),
    }
    # پیش‌نمایشِ متن: تا پیش از این، `SendResult.details` متن را داشت ولی هیچ‌وقت
    # به فرانت نمی‌رسید، پس کاربر تا لحظه‌ی ارسالِ واقعی نمی‌دید چه می‌فرستد.
    # شماره ماسک می‌شود؛ نمونه‌ی محدود چون هدف بازبینی است نه فهرست کامل.
    payload["send"]["نمونه_پیام"] = [
        {
            "مشتری": d["customer_id"],
            "گیرنده": mask_phone(d["phone"]) if d["phone"] else "—",
            "متن": d["text"],
            "قطعه": segment_count(d["text"]) if d["text"] else 0,
        }
        for d in drafts[:5]
    ]
    payload["send"]["یادداشت_هزینه"] = cost_note_fa(
        sent, total_segments, total_cost, display_text=money["display_text"],
    )
    if note:
        payload["send"]["توضیح"] = note
    gate_note = screened.note_fa()
    if gate_note:
        payload["send"]["یادداشت_مجوز_تماس"] = gate_note
    return payload


def _send_drafts(
    session, campaign_id: int, members: list[CampaignMember], template: str | None,
) -> list[dict]:
    """متن و شماره‌ی هر عضو.

    اگر قالبی داده نشود، **متن پیشنهادیِ خودِ فرصت** استفاده می‌شود — همان متنی
    که در خروجی اکسل هم می‌آمد، پس دو کانال یک پیام می‌فرستند.
    """
    ids = {int(m.customer_id) for m in members}
    customers = {
        c.id: c for c in session.scalars(
            select(Customer).where(Customer.id.in_(sorted(ids)))
        ).all()
    }
    rows = session.execute(
        select(
            CampaignOpportunity.customer_id,
            Opportunity.message_fa,
            Opportunity.action_fa,
            Opportunity.score_rial,
            OpportunityOffer.suggested_discount_bp,
            OpportunityOffer.status,
        ).join(Opportunity, Opportunity.id == CampaignOpportunity.opportunity_id)
        .outerjoin(OpportunityOffer, OpportunityOffer.opportunity_id == Opportunity.id)
        .where(CampaignOpportunity.campaign_id == campaign_id)
    ).all()

    # ارزشمندترین فرصتِ هر مشتری متنِ پیام را تعیین می‌کند — و آفرِ **همان**
    # فرصت، نه هر آفرِ تأییدشده‌ی این مشتری در جای دیگر.
    best: dict[int, tuple] = {}
    for customer_id, message_fa, action_fa, score, offer_bp, offer_status in rows:
        key = int(customer_id)
        current = best.get(key)
        if current is None or int(score or 0) > int(current[2] or 0):
            approved = offer_status == OpportunityOffer.STATUS_APPROVED and offer_bp
            best[key] = (message_fa, action_fa, score, int(offer_bp) if approved else None)

    drafts: list[dict] = []
    for member in members:
        customer_id = int(member.customer_id)
        customer = customers.get(customer_id)
        name = (customer.display_name if customer else None) or "مشتری گرامی"
        message_fa, action_fa, _score, offer_bp = best.get(
            customer_id, (None, None, None, None),
        )
        # قاعده‌ی سختِ §۲۰.۳ / تصمیمِ کاربر: `{تخفیف}` فقط از آفرِ **تأییدشده**
        # رندر می‌شود. قالبی که `{تخفیف}` دارد و آفرِ مصوبی نیست، برای این عضو
        # «قابل ارسال نیست» — نه اینکه «{تخفیف}» خام برای مشتری برود (رفتارِ
        # قبلی) و نه اینکه پیامِ بی‌تخفیف بی‌صدا فرستاده شود.
        source = template if template else (message_fa or "")
        needs_offer = OFFER_PLACEHOLDER in source
        blocked_by_offer = needs_offer and offer_bp is None
        variables = {"نام": name}
        if offer_bp is not None:
            variables["تخفیف"] = f"{offer_bp / 100:g}٪"
        if template:
            text = "" if blocked_by_offer else render_template(template, variables)
        else:
            # ⚠️ عمداً هیچ fallbackی به `action_fa` نیست.
            # `action_fa` طبق تعریفِ خودش «جمله‌ی امری برای تیم فروش» است، نه متنِ
            # مشتری — سوم‌شخص و درباره‌ی خودِ مشتری. فرستادنش یعنی پیامی مثل
            # «به این مشتری فلان را معرفی کنید؛ مشتریان مشابهش می‌خرند ولی او نه»
            # مستقیم برای همان مشتری برود، که هم بی‌معنا است هم پروفایلِ داخلی را
            # لو می‌دهد. نبودِ متن یعنی «قابل ارسال نیست»، نه «هرچه هست بفرست».
            text = "" if blocked_by_offer else render_template(
                (message_fa or "").strip(), variables,
            )
        drafts.append({
            "member": member,
            "customer_id": customer_id,
            "phone": normalize_phone(customer.phone_e164) if customer else None,
            "text": text,
            # پله‌ای که **واقعاً در متن رفت** — نه هر آفرِ تأییدشده‌ای. قالبِ
            # بی‌`{تخفیف}` یعنی مشتری تخفیفی ندیده و نباید مهرِ آفر بخورد؛ وگرنه
            # سنجه‌ی آمادگی مشاهده‌هایی می‌شمارد که هرگز اتفاق نیفتاده‌اند.
            "offer_bp": offer_bp if (needs_offer and not blocked_by_offer) else None,
            "blocked_by_offer": blocked_by_offer,
        })
    return drafts


def _export_rows(session, campaign_id: int, members: list[CampaignMember]) -> list[dict]:
    ids = {m.customer_id for m in members}
    customers = {
        c.id: c for c in session.scalars(
            select(Customer).where(Customer.id.in_(sorted(ids)))
        ).all()
    }
    opportunities = session.execute(
        select(
            CampaignOpportunity.customer_id,
            Opportunity.kind, Opportunity.action_fa, Opportunity.reason_fa,
            Opportunity.message_fa, Opportunity.due_date, Opportunity.expected_value_rial,
            OpportunityOffer.suggested_discount_bp, OpportunityOffer.status,
        ).join(Opportunity, Opportunity.id == CampaignOpportunity.opportunity_id)
        .outerjoin(OpportunityOffer, OpportunityOffer.opportunity_id == Opportunity.id)
        .where(CampaignOpportunity.campaign_id == campaign_id)
    ).all()

    by_customer: dict[int, list] = {}
    for row in opportunities:
        by_customer.setdefault(int(row[0]), []).append(row)

    rows: list[dict] = []
    for member in sorted(members, key=lambda m: -(m.expected_value_rial or 0)):
        customer = customers.get(member.customer_id)
        # فرصتِ **برگزیده‌ی** عضو همان است که مسیرِ پیامک انتخاب می‌کند
        # (بیشینه‌ی ارزش، با شکستِ تساویِ قطعی) — فقط آفرِ همان روی عضو مهر می‌خورد،
        # نه اولین ردیفِ approvedی که SQLite برگرداند.
        member_rows = sorted(
            by_customer.get(member.customer_id, []),
            key=lambda r: (-int(r[6] or 0), r[1] or ""),
        )
        for index, (_, kind, action, reason, message, due, value, offer_bp, offer_status) in (
            enumerate(member_rows)
        ):
            # همان قاعده‌ی مسیرِ پیامک: `{تخفیف}` فقط از آفرِ **تأییدشده** پر
            # می‌شود. در فایلِ انسانی، نبودِ تأیید پنهان نمی‌شود — صریح نوشته
            # می‌شود تا کسی با تلفن تخفیفی ندهد که کسی تأیید نکرده.
            approved = offer_status == OpportunityOffer.STATUS_APPROVED and offer_bp
            text = render_template(
                message or "",
                {"تخفیف": f"{int(offer_bp) / 100:g}٪" if approved else "(بدون تخفیفِ تأییدشده)"},
            )
            # مهرِ آفرِ عضو: فقط از فرصتِ برگزیده، و هرگز روی مهرِ پیامکی
            # نمی‌نویسد — پیامک می‌داند چه رفته، اکسل فقط می‌داند چه پیشنهاد شد.
            if (
                approved and index == 0
                and member.exposure_channel != EXPOSURE_CHANNEL_SMS
                and member.offer_discount_bp is None
            ):
                member.offer_discount_bp = int(offer_bp)
            rows.append({
                "مشتری": (customer.display_name if customer else None) or "—",
                "شماره تماس": normalize_phone(customer.phone_e164) if customer else None,
                "نوع اقدام": kind,
                "اقدام پیشنهادی": action,
                "دلیل": reason,
                "متن پیشنهادی": text,
                "تخفیف تأییدشده": f"{int(offer_bp) / 100:g}٪" if approved else "—",
                "سررسید": due or "",
                "ارزش مورد انتظار (ریال)": int(value or 0),
            })
    return rows


def _workbook(rows: list[dict]) -> bytes:
    frame = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["مشتری"])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="فهرست تماس", index=False)
        writer.book["فهرست تماس"].sheet_view.rightToLeft = True
    return buf.getvalue()


@router.post("/{campaign_id}/refresh")
def refresh_outcomes(campaign_id: int) -> dict:
    """محاسبه‌ی دوباره‌ی نتیجه‌ها از دفتر کل (بدون انتظار برای بارگذاری بعدی)."""
    ensure_schema()
    with session_scope() as session:
        if session.get(Campaign, campaign_id) is None:
            raise HTTPException(status_code=404, detail="این کمپین یافت نشد.")
    compute_campaign_outcomes()
    with session_scope() as session:
        campaign = session.get(Campaign, campaign_id)
        payload = _campaign_detail(session, campaign)
    return payload


@router.post("/{campaign_id}/close", dependencies=[Depends(require_token)])
def close_campaign(campaign_id: int) -> dict:
    """بستن کمپین — پنجره‌ی سنجش دیگر به‌روز نمی‌شود."""
    ensure_schema()
    with write_lock, session_scope() as session:
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="این کمپین یافت نشد.")
        campaign.status = "closed"
        campaign.closed_at = now_ts()
        payload = _campaign_detail(session, campaign)
    return payload


# ------------------------------------------------------------------ کمکی‌ها
def _customer_names(session, customer_ids: set[int]) -> dict[int, str]:
    if not customer_ids:
        return {}
    rows = session.execute(
        select(Customer.id, Customer.display_name).where(
            Customer.id.in_(sorted(customer_ids))
        )
    ).all()
    return {cid: name for cid, name in rows if name}


def _contact_cost_rial(session, campaign_id: int) -> int | None:
    """هزینه‌ی واقعیِ تماس این کمپین — فقط ارسال‌های **واقعیِ موفق**.

    `None` یعنی هیچ ارسالی از داخل سیستم انجام نشده (کانال، خروجی اکسل بوده)،
    و آن‌وقت «هزینه به‌ازای سفارش افزوده» صادقانه مسدود می‌ماند. صفر با `None`
    فرق دارد: صفر یعنی «فرستادیم و رایگان بود» که دروغ است.
    """
    total, rows = session.execute(
        select(func.sum(CampaignSend.cost_rial), func.count(CampaignSend.id)).where(
            CampaignSend.campaign_id == campaign_id,
            CampaignSend.dry_run.is_(False),
            CampaignSend.status == CampaignSend.STATUS_SENT,
        )
    ).one()
    if not rows:
        return None
    return int(total or 0)


def _report(session, campaign_id: int) -> dict:
    stats = arm_stats(session, campaign_id)
    treatment = ArmStats(arm=ARM_TREATMENT, **stats.get(ARM_TREATMENT, {}))
    control = ArmStats(arm=ARM_CONTROL, **stats.get(ARM_CONTROL, {}))
    cost = _contact_cost_rial(session, campaign_id)
    report = analyze_campaign(treatment, control, contact_cost_rial=cost).to_dict()
    report["incremental_revenue"] = (
        None if report["incremental_revenue_rial"] is None
        else money_payload(report["incremental_revenue_rial"])
    )
    observed = report["observed_difference"]
    observed["revenue"] = (
        None if observed["revenue_rial"] is None else money_payload(observed["revenue_rial"])
    )
    observed["gross_profit"] = (
        None if observed["gross_profit_rial"] is None
        else money_payload(observed["gross_profit_rial"])
    )
    report["contact_cost"] = (
        None if report["contact_cost_rial"] is None
        else money_payload(report["contact_cost_rial"])
    )
    report["cost_per_incremental_order"] = (
        None if report["cost_per_incremental_order_rial"] is None
        else money_payload(report["cost_per_incremental_order_rial"])
    )
    report["incremental_gross_profit"] = (
        None if report["incremental_gross_profit_rial"] is None
        else money_payload(report["incremental_gross_profit_rial"])
    )
    # مبالغ بازو هم سه‌کلیدی می‌شوند: قالب‌بندیِ ریالِ خام در UI همان اشتباهی
    # است که یک‌بار عدد را ده برابر نشان داد.
    for arm in report["arms"].values():
        for key in ("cost_rial", "gross_profit_rial", "profit_per_customer_rial"):
            value = arm.get(key)
            arm[key.removesuffix("_rial")] = (
                None if value is None else money_payload(value)
            )
    return report


def _campaign_summary(session, campaign: Campaign) -> dict:
    counts = dict(session.execute(
        select(CampaignMember.arm, func.count())
        .where(CampaignMember.campaign_id == campaign.id)
        .group_by(CampaignMember.arm)
    ).all())
    exposed = session.scalar(
        select(func.count()).select_from(CampaignMember).where(
            CampaignMember.campaign_id == campaign.id,
            CampaignMember.exposure_at.isnot(None),
        )
    ) or 0
    pipeline = session.scalar(
        select(func.sum(CampaignMember.expected_value_rial)).where(
            CampaignMember.campaign_id == campaign.id,
            CampaignMember.arm == ARM_TREATMENT,
        )
    ) or 0
    strata = dict(session.execute(
        select(CampaignMember.stratum, func.count())
        .where(CampaignMember.campaign_id == campaign.id)
        .group_by(CampaignMember.stratum)
    ).all())

    return {
        "id": campaign.id,
        "name": campaign.name,
        "kind": campaign.kind,
        "status": campaign.status,
        "holdout_pct": campaign.holdout_pct,
        "analysis_window_days": campaign.analysis_window_days,
        "created_at": campaign.created_at,
        "exported_at": campaign.exported_at,
        "closed_at": campaign.closed_at,
        "treatment_size": int(counts.get(ARM_TREATMENT, 0)),
        "control_size": int(counts.get(ARM_CONTROL, 0)),
        "exposed_count": int(exposed),
        "treatment_pipeline": money_payload(int(pipeline)),
        "strata": {
            STATE_LABELS_FA.get(str(k), str(k)): int(v) for k, v in strata.items()
        },
    }


__all__ = ["EXPOSURE_NOTE_FA", "router"]
