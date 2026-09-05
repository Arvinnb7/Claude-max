"""دفترِ انصراف روی دیتابیس، و ساختنِ دروازه از داده‌ی واقعی.

`permission.py` تابع خالص است؛ این ماژول تنها جایی است که به دیتابیس دست می‌زند.

**مسئله‌ی کلیدِ مشتری.** سه مسیرِ تماس، مشتری را با سه شکلِ متفاوت می‌شناسند:

| مسیر | کلیدی که در دست دارد |
|---|---|
| موتور فرصت | کلید خامِ فایل (`candidate.customer_key`) |
| `build_audience` / ارسال پیامک | همان کلید خام |
| اعضای کمپین | `customers.id` عددی |

اگر دروازه فقط یکی را بشناسد، بی‌صدا از کار می‌افتد. پس مجموعه‌های دروازه با
**همه‌ی شناسه‌های همان شخص** پر می‌شوند: `customers.id`، `canonical_key` و هر
کلیدی که در `customer_keys` به او وصل است. نتیجه: هر مسیری با هر کلیدی پرس‌وجو
کند، همان پاسخ را می‌گیرد.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import select

from mktcore.db.base import now_ts
from mktcore.db.engine import session_scope, write_lock
from mktcore.db.lookup import resolve_business_id
from mktcore.db.migrations import ensure_schema
from mktcore.db.models import (
    Campaign,
    CampaignMember,
    ContactSuppression,
    Customer,
    CustomerKey,
)
from mktcore.identity.phone import mask_phone, normalize_phone

from .permission import DEFAULT_FATIGUE_WINDOW_DAYS, ContactGate

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.orm import Session

logger = logging.getLogger("mktcore.contact.register")

CHUNK = 500

# کمپینِ بسته دیگر آزمایشِ فعالی نیست، پس عضوِ کنترلش آزاد می‌شود.
_OPEN_CAMPAIGN_STATES_EXCLUDED = ("closed",)


def _business_id(session: Session, business_slug: str) -> int | None:
    return resolve_business_id(session, business_slug)


def _expand_identifiers(session: Session, customer_ids: set[int]) -> set[str]:
    """هر `customers.id` → همه‌ی شناسه‌هایی که همان شخص را نشان می‌دهند."""
    if not customer_ids:
        return set()
    out: set[str] = {str(cid) for cid in customer_ids}
    ids = sorted(customer_ids)
    for start in range(0, len(ids), CHUNK):
        batch = ids[start:start + CHUNK]
        for key in session.scalars(
            select(Customer.canonical_key).where(Customer.id.in_(batch))
        ):
            if key:
                out.add(str(key))
        for value in session.scalars(
            select(CustomerKey.key_value).where(CustomerKey.customer_id.in_(batch))
        ):
            if value:
                out.add(str(value))
    return out


def _customer_ids_for_phones(session: Session, business_id: int, phones: set[str]) -> set[int]:
    wanted = sorted(phones)
    out: set[int] = set()
    for start in range(0, len(wanted), CHUNK):
        out.update(
            int(cid) for cid in session.scalars(
                select(Customer.id).where(
                    Customer.business_id == business_id,
                    Customer.phone_e164.in_(wanted[start:start + CHUNK]),
                )
            )
        )
    return out


def active_suppressions(
    session: Session, business_id: int, *, scope: str = ContactSuppression.SCOPE_ALL,
) -> tuple[set[int], set[str]]:
    """انصراف‌های فعال: (شناسه‌ی مشتری‌ها، شماره‌ها)."""
    rows = session.execute(
        select(ContactSuppression.customer_id, ContactSuppression.phone_e164).where(
            ContactSuppression.business_id == business_id,
            ContactSuppression.scope == scope,
            ContactSuppression.revoked_at.is_(None),
        )
    ).all()
    customer_ids = {int(cid) for cid, _phone in rows if cid is not None}
    phones = {str(phone) for _cid, phone in rows if phone}
    return customer_ids, phones


def control_arm_customer_ids(session: Session, business_id: int) -> set[int]:
    """اعضای گروه کنترلِ کمپین‌هایی که هنوز بسته نشده‌اند.

    فقط کمپینِ باز مهم است: بعد از بسته‌شدن، پنجره‌ی سنجش تمام شده و تماس با
    عضوِ کنترل دیگر چیزی را خراب نمی‌کند.
    """
    rows = session.execute(
        select(CampaignMember.customer_id)
        .join(Campaign, Campaign.id == CampaignMember.campaign_id)
        .where(
            Campaign.business_id == business_id,
            Campaign.status.notin_(_OPEN_CAMPAIGN_STATES_EXCLUDED),
            CampaignMember.arm == "control",
        )
    ).all()
    return {int(cid) for (cid,) in rows if cid is not None}


def recent_exposures(
    session: Session, business_id: int, *, window_days: int,
    exclude_campaign_id: int | None = None, now: float | None = None,
) -> set[int]:
    """مشتریانی که در `window_days` روزِ گذشته واقعاً از یک کمپین تماس گرفته‌اند.

    `exposure_at` فقط برای خروجیِ اکسل و ارسالِ واقعیِ موفق مهر می‌خورد (پیش‌نمایش
    هرگز)، پس همین ستون «تماسِ واقعی» است. کمپینِ خودِ عضو مستثنا می‌شود تا دانلودِ
    دوباره‌ی همان فهرست یا ارسالِ پیامکِ همان کمپین، اعضایش را «خسته» نشمارد.
    """
    cutoff = (now if now is not None else now_ts()) - window_days * 86400
    stmt = (
        select(CampaignMember.customer_id)
        .join(Campaign, Campaign.id == CampaignMember.campaign_id)
        .where(
            Campaign.business_id == business_id,
            CampaignMember.exposure_at.isnot(None),
            CampaignMember.exposure_at >= cutoff,
        )
    )
    if exclude_campaign_id is not None:
        stmt = stmt.where(CampaignMember.campaign_id != exclude_campaign_id)
    return {int(cid) for cid in session.scalars(stmt) if cid is not None}


def recent_contact_keys(
    session: Session, business_id: int, *, window_days: int,
    exclude_campaign_id: int | None = None, legacy_raw_keys: set[str] | None = None,
    now: float | None = None,
) -> set[str]:
    """همه‌ی شناسه‌های اشخاصی که اخیراً تماس گرفته‌اند — از کمپین‌ها و از outbox.

    خروجی هم `customers.id` (کلیدِ مسیرِ کمپین) و هم کلیدهای خام (کلیدِ موتورِ
    فرصت) را دارد، پس هر دو مسیر با یک مجموعه کار می‌کنند.
    """
    from mktcore.db.lookup import customer_ids_by_raw_key

    ids = recent_exposures(
        session, business_id, window_days=window_days, exclude_campaign_id=exclude_campaign_id,
        now=now,
    )
    raw = {str(k) for k in (legacy_raw_keys or set()) if k}
    if raw:
        ids |= set(customer_ids_by_raw_key(session, business_id, raw).values())
    return _expand_identifiers(session, ids) | raw


def build_gate(
    session: Session,
    business_id: int,
    *,
    fatigue_window_days: int | None = DEFAULT_FATIGUE_WINDOW_DAYS,
    recently_contacted: set[str] | None = None,
) -> ContactGate:
    """ساخت دروازه از داده‌ی واقعی، با شناسه‌های گسترش‌یافته.

    `recently_contacted` از بیرون داده می‌شود چون منبعش لایه‌ی legacy است
    (`outbox`) و این ماژول عمداً به آن وابسته نیست.
    """
    suppressed_ids, phones = active_suppressions(session, business_id)
    # انصرافِ فقط-شماره («لغو ۱۱» پیش از شناختِ مشتری) باید مشتریِ شناخته‌شده‌ی
    # همان شماره را هم بگیرد: مسیرِ کمپین با شناسه‌ی مشتری غربال می‌کند، نه شماره.
    if phones:
        suppressed_ids = set(suppressed_ids) | _customer_ids_for_phones(session, business_id, phones)
    control_ids = control_arm_customer_ids(session, business_id)
    return ContactGate(
        control_arm=frozenset(_expand_identifiers(session, control_ids)),
        opted_out=frozenset(_expand_identifiers(session, suppressed_ids)),
        opted_out_phones=frozenset(phones),
        recently_contacted=frozenset(recently_contacted or set()),
        fatigue_window_days=fatigue_window_days if recently_contacted is not None else None,
        has_suppression_data=True,
        has_campaign_data=True,
    )


def load_gate(
    *,
    business_slug: str = "default",
    db_path: Path | None = None,
    fatigue_window_days: int | None = DEFAULT_FATIGUE_WINDOW_DAYS,
    recently_contacted: set[str] | None = None,
) -> ContactGate:
    """نقطه‌ی ورودِ مسیرهای ارسال. **هرگز خطا پرت نمی‌کند.**

    اگر لایه‌ی canonical در دسترس نباشد، دروازه‌ی خالی برمی‌گردد — که همان رفتارِ
    پیش از این ارتقا است، ولی `unchecked_reasons()` صریح می‌گوید چه بررسی‌ای
    انجام نشده. «بررسی نشد» هرگز به‌جای «قبول» ثبت نمی‌شود.
    """
    try:
        ensure_schema(db_path)
        with session_scope(db_path) as session:
            business_id = _business_id(session, business_slug)
            if business_id is None:
                # هنوز هیچ داده‌ای بارگذاری نشده؛ چیزی برای مسدود کردن نیست، ولی
                # دفتر در دسترس است.
                return ContactGate(
                    recently_contacted=frozenset(recently_contacted or set()),
                    fatigue_window_days=(
                        fatigue_window_days if recently_contacted is not None else None
                    ),
                    has_suppression_data=True,
                    has_campaign_data=True,
                )
            merged = recently_contacted
            if recently_contacted is not None and fatigue_window_days is not None:
                # تماسِ کمپین (اکسل/پیامک) هم تماس است: مسیرِ legacy تا اینجا فقط
                # outbox را می‌دید و عضوِ تازه‌تماس‌گرفته‌ی کمپین دوباره پیام می‌گرفت.
                merged = recent_contact_keys(
                    session, business_id, window_days=fatigue_window_days,
                    legacy_raw_keys=set(recently_contacted),
                )
            return build_gate(
                session, business_id,
                fatigue_window_days=fatigue_window_days,
                recently_contacted=merged,
            )
    except Exception:  # noqa: BLE001 - نبودِ دفتر نباید ارسال را بخواباند
        logger.warning("دفترِ مجوز تماس در دسترس نبود؛ بررسی‌ها انجام نشد", exc_info=True)
        return ContactGate(
            recently_contacted=frozenset(recently_contacted or set()),
            fatigue_window_days=(
                fatigue_window_days if recently_contacted is not None else None
            ),
        )


# ------------------------------------------------------------ نوشتن دفتر


def record_opt_out(
    *,
    customer_id: int | None = None,
    phone: str | None = None,
    reason_fa: str,
    reason_code: str = "manual",
    source: str = "manual",
    scope: str = ContactSuppression.SCOPE_ALL,
    created_by: str | None = None,
    business_slug: str = "default",
    db_path: Path | None = None,
) -> dict:
    """ثبت انصراف. دلیل **اجباری** است تا بعداً «چرا؟» پاسخ داشته باشد.

    idempotent: ثبتِ دوباره‌ی همان مشتری ردیف تازه نمی‌سازد، و اگر قبلاً پس گرفته
    شده بود دوباره فعال می‌شود.
    """
    if customer_id is None and not phone:
        raise ValueError("برای ثبت انصراف، شناسه‌ی مشتری یا شماره لازم است.")
    if not (reason_fa or "").strip():
        raise ValueError("دلیل انصراف اجباری است.")

    normalized = normalize_phone(phone) if phone else None
    if customer_id is None and normalized is None:
        # ردیفی که نه شناسه دارد نه شماره‌ی نرمال‌شدنی، هیچ‌کس را مسدود نمی‌کند؛
        # «موفق» گزارش‌کردنش یعنی شخصی که «نه» گفته همچنان پیام می‌گیرد.
        raise ValueError("شماره‌ی نامعتبر است؛ انصراف بدون شناسه یا شماره‌ی معتبر ثبت نمی‌شود.")
    ensure_schema(db_path)
    with write_lock, session_scope(db_path) as session:
        business_id = _business_id(session, business_slug)
        if business_id is None:
            raise ValueError("کسب‌وکاری ثبت نشده است؛ اول داده بارگذاری کنید.")
        return _record_opt_out_in_session(
            session, business_id, customer_id=customer_id, normalized=normalized,
            reason_fa=reason_fa, reason_code=reason_code, source=source, scope=scope,
            created_by=created_by,
        )


def record_opt_outs_bulk(
    rows: list[dict], *, reason_fa: str, reason_code: str = "provider", source: str = "provider",
    scope: str = ContactSuppression.SCOPE_ALL, created_by: str | None = None,
    business_slug: str = "default", db_path: Path | None = None,
) -> dict:
    """ثبتِ چند انصراف با شماره در **یک** تراکنش (لیستِ سیاهِ پنل).

    هر ردیف `{"phone", "reason_fa"?}`؛ شماره‌ی نامعتبر صریح در `rejected` گزارش
    می‌شود، نه بی‌صدا. یک قفلِ نوشتن، یک نشست — نه یکی به‌ازای هر ردیف.
    """
    created = reactivated = unchanged = 0
    rejected: list[dict] = []
    ensure_schema(db_path)
    with write_lock, session_scope(db_path) as session:
        business_id = _business_id(session, business_slug)
        if business_id is None:
            raise ValueError("کسب‌وکاری ثبت نشده است؛ اول داده بارگذاری کنید.")
        for index, row in enumerate(rows):
            normalized = normalize_phone(row.get("phone"))
            if normalized is None:
                rejected.append({"row": index, "phone_masked": mask_phone(row.get("phone")),
                                 "reason_fa": "شماره‌ی نامعتبر"})
                continue
            result = _record_opt_out_in_session(
                session, business_id, customer_id=None, normalized=normalized,
                reason_fa=(row.get("reason_fa") or reason_fa), reason_code=reason_code,
                source=source, scope=scope, created_by=created_by,
            )
            if result["created"]:
                created += 1
            elif result["reactivated"]:
                reactivated += 1
            else:
                unchanged += 1
    return {"created": created, "reactivated": reactivated, "unchanged": unchanged,
            "rejected": rejected}


def _record_opt_out_in_session(
    session: Session, business_id: int, *, customer_id: int | None, normalized: str | None,
    reason_fa: str, reason_code: str, source: str, scope: str, created_by: str | None,
) -> dict:
    """بدنه‌ی ثبت، درونِ نشستی که صدازننده باز کرده (تک یا انبوه)."""
    if True:  # تورفتگیِ بدنه‌ی قبلی حفظ شده تا دیف خوانا بماند

        if customer_id is not None and normalized is None:
            normalized = session.scalar(
                select(Customer.phone_e164).where(Customer.id == customer_id)
            )
        if customer_id is None and normalized is not None:
            # شماره‌ای که همین حالا به مشتریِ شناخته‌شده‌ای تعلق دارد، به او وصل
            # می‌شود؛ شناخته‌نشده هم با خودِ شماره در دروازه دیده می‌شود.
            customer_id = session.scalar(
                select(Customer.id).where(
                    Customer.business_id == business_id, Customer.phone_e164 == normalized,
                ).order_by(Customer.id)
            )

        existing = _find_row(session, business_id, customer_id, normalized, scope)
        stamp = now_ts()
        if existing is None:
            row = ContactSuppression(
                business_id=business_id, customer_id=customer_id, phone_e164=normalized,
                scope=scope, source=source, reason_code=reason_code, reason_fa=reason_fa,
                opted_out_at=stamp, created_by=created_by, updated_at=stamp,
            )
            session.add(row)
            session.flush()
            return {"id": row.id, "created": True, "reactivated": False}

        reactivated = existing.revoked_at is not None
        existing.revoked_at = None
        existing.opted_out_at = existing.opted_out_at or stamp
        existing.reason_fa = reason_fa
        existing.reason_code = reason_code
        existing.source = source
        existing.updated_at = stamp
        if normalized and not existing.phone_e164:
            existing.phone_e164 = normalized
        if customer_id is not None and existing.customer_id is None:
            existing.customer_id = customer_id
        return {"id": existing.id, "created": False, "reactivated": reactivated}


def revoke_opt_out(
    *,
    customer_id: int | None = None,
    phone: str | None = None,
    scope: str = ContactSuppression.SCOPE_ALL,
    business_slug: str = "default",
    db_path: Path | None = None,
) -> bool:
    """پس گرفتن انصراف. ردیف پاک نمی‌شود تا تاریخش بماند."""
    normalized = normalize_phone(phone) if phone else None
    ensure_schema(db_path)
    with write_lock, session_scope(db_path) as session:
        business_id = _business_id(session, business_slug)
        if business_id is None:
            return False
        row = _find_row(session, business_id, customer_id, normalized, scope)
        if row is None or row.revoked_at is not None:
            return False
        row.revoked_at = now_ts()
        row.updated_at = now_ts()
        return True


def list_suppressions(
    *, business_slug: str = "default", db_path: Path | None = None, active_only: bool = True,
) -> list[dict]:
    """فهرست دفتر برای UI."""
    ensure_schema(db_path)
    with session_scope(db_path) as session:
        business_id = _business_id(session, business_slug)
        if business_id is None:
            return []
        stmt = (
            select(ContactSuppression, Customer.display_name)
            .outerjoin(Customer, Customer.id == ContactSuppression.customer_id)
            .where(ContactSuppression.business_id == business_id)
        )
        if active_only:
            stmt = stmt.where(ContactSuppression.revoked_at.is_(None))
        rows = session.execute(stmt.order_by(ContactSuppression.updated_at.desc())).all()
        return [
            {
                "id": row.id,
                "customer_id": row.customer_id,
                "customer_name": display_name,
                # شماره در نمای API ماسک می‌شود؛ دفتر همان E.164 کامل را دارد.
                "phone": mask_phone(row.phone_e164) if row.phone_e164 else None,
                "scope": row.scope,
                "source": row.source,
                "reason_fa": row.reason_fa,
                "opted_out_at": row.opted_out_at,
                "revoked_at": row.revoked_at,
                "active": row.revoked_at is None,
            }
            for row, display_name in rows
        ]


def _find_row(
    session: Session,
    business_id: int,
    customer_id: int | None,
    phone: str | None,
    scope: str,
) -> ContactSuppression | None:
    """ردیفِ موجود را با شناسه یا شماره پیدا می‌کند — هر کدام که در دست است."""
    if customer_id is not None:
        row = session.scalar(
            select(ContactSuppression).where(
                ContactSuppression.business_id == business_id,
                ContactSuppression.customer_id == customer_id,
                ContactSuppression.scope == scope,
            )
        )
        if row is not None:
            return row
    if phone:
        return session.scalar(
            select(ContactSuppression).where(
                ContactSuppression.business_id == business_id,
                ContactSuppression.phone_e164 == phone,
                ContactSuppression.scope == scope,
            )
        )
    return None


__all__ = [
    "active_suppressions",
    "build_gate",
    "control_arm_customer_ids",
    "recent_contact_keys",
    "recent_exposures",
    "record_opt_outs_bulk",
    "list_suppressions",
    "load_gate",
    "record_opt_out",
    "revoke_opt_out",
]
