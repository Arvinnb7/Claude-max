"""اجرای موتور فرصت‌ها و ماندگارسازی با چرخه‌ی حیات.

قواعد چرخه‌ی حیات (تصمیم‌های صریح، نه پیش‌فرضِ اتفاقی):

* فرصتِ تازه → `open`.
* فرصتی که دوباره تولید شد → **تازه‌سازی** می‌شود (ارزش، متن، شواهد)، ولی
  **وضعیت انسانی بازنویسی نمی‌شود**: اگر کسی آن را پذیرفته یا رد کرده، تصمیمش
  با اجرای بعدیِ موتور پاک نمی‌شود.
* فرصتِ بازی که دیگر تولید نشد → `superseded` («دیگر مصداق ندارد»)، نه حذف.
  حذف یعنی از دست دادن تاریخچه‌ای که برای سنجش اثر لازم است.
* فرصتی که از تاریخ انقضا گذشت → `expired`.
* هر تغییر وضعیت یک رخداد append-only ثبت می‌کند.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pandas as pd
from sqlalchemy import func, select

from mktcore.db.base import now_ts
from mktcore.db.engine import session_scope, write_lock
from mktcore.db.leases import job_lease
from mktcore.db.lookup import (
    customer_ids_by_raw_key,
    product_ids_by_raw_name,
    resolve_business_id,
)
from mktcore.db.migrations import ensure_schema
from mktcore.db.models import (
    Business,
    CustomerFeature,
    JobLease,
    Opportunity,
    OpportunityEvent,
    OpportunityFactor,
    OpportunityRun,
)
from mktcore.money import to_basis_points, to_rial_int
from mktcore.uplift.empirical import BASIS_LABELS_FA, BASIS_NONE

from .contract import (
    OUTCOME_EVIDENCE,
    VALUE_RELATIONSHIP,
    OpportunityCandidate,
    OpportunityFactorNote,
)
from .filters import apply_filters
from .generators import (
    WHALE_MAX_PER_RUN,
    generate_candidates,
    generate_whale_relationship,
)
from .offers import upsert_offer

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.orm import Session

logger = logging.getLogger("mktcore.opportunities.engine")

ENGINE_VERSION = 1

STATUS_OPEN = "open"
STATUS_ACCEPTED = "accepted"
STATUS_DISMISSED = "dismissed"
STATUS_SNOOZED = "snoozed"
STATUS_DONE = "done"
STATUS_EXPIRED = "expired"
STATUS_SUPERSEDED = "superseded"

# وضعیت‌هایی که انسان تعیین کرده و موتور حق بازنویسی‌شان را ندارد
_HUMAN_STATUSES = frozenset({STATUS_ACCEPTED, STATUS_DISMISSED, STATUS_SNOOZED, STATUS_DONE})
# وضعیت‌هایی که «هنوز روی میز» محسوب می‌شوند
_LIVE_STATUSES = frozenset({STATUS_OPEN, STATUS_ACCEPTED, STATUS_SNOOZED})

# اعتبار پیش‌فرض یک فرصت. فرصتِ بی‌انقضا صندوق را از کارهای کهنه پر می‌کند.
DEFAULT_TTL_DAYS = 45

# سقف فرصت‌هایی که در هر اجرا ماندگار می‌شوند.
# نامزدها گسترده تولید می‌شوند (تا مقایسه‌ی رتبه‌بندی معنادار باشد) ولی صندوقی
# با هزاران کارت برای تیم فروش بی‌فایده است — و نوشتنِ همه‌ی آن‌ها در هر تحلیل
# هزینه‌ی واقعی دارد. ارزشمندترین‌ها می‌مانند و **تعداد حذف‌شده‌ها صریحاً
# گزارش می‌شود** (سقفِ بی‌صدا ممنوع است).
MAX_PERSISTED_PER_RUN = 500


@dataclass
class OpportunityRunResult:
    run_id: int
    generated: int
    filtered_out: int
    created: int
    refreshed: int
    superseded: int
    expired: int
    capped_out: int = 0
    skipped_filters: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        payload = {
            "run_id": self.run_id,
            "generated": self.generated,
            "filtered_out": self.filtered_out,
            "created": self.created,
            "refreshed": self.refreshed,
            "superseded": self.superseded,
            "expired": self.expired,
            "capped_out": self.capped_out,
            "skipped_filters": self.skipped_filters,
        }
        if self.capped_out:
            payload["cap_note_fa"] = (
                f"{self.capped_out} فرصتِ کم‌ارزش‌تر ذخیره نشد؛ سقف هر اجرا "
                f"{MAX_PERSISTED_PER_RUN} فرصت است."
            )
        return payload


def _as_of(clean: pd.DataFrame) -> str:
    if "date" in clean.columns and len(clean):
        stamp = pd.Timestamp(clean["date"].max())
        if not pd.isna(stamp):
            return stamp.date().isoformat()
    return pd.Timestamp.now().date().isoformat()


def _recently_contacted(
    window_days: int, now: float | None = None,
) -> tuple[set[str], int | None]:
    """مشتریانی که اخیراً پیام گرفته‌اند — از همان outbox موجود.

    خواندنِ فقط‌خواندنی از لایه‌ی legacy است و آن را تغییر نمی‌دهد. `now` مرجعِ
    زمانیِ پنجره است (پیش‌فرض ساعتِ دیوار) و در اجرا ثبت می‌شود.
    """
    try:
        from api.persistence import store

        return set(store.recent_contact_customer_ids(window_days, now=now)), window_days
    except Exception:  # noqa: BLE001 - نبودِ تاریخچه نباید موتور را بخواباند
        logger.debug("تاریخچه‌ی تماس در دسترس نبود؛ فیلتر خستگی رد شد", exc_info=True)
        return set(), None


# ضریب رتبه‌بندی هرگز صفر یا منفی نمی‌شود؛ فرصت با اثرِ ضعیف باید **پایین**
# فهرست برود، نه اینکه از رتبه‌بندی حذف شود (حذف کارِ فیلتر است، نه امتیاز).
MIN_UPLIFT_MULTIPLIER = 0.05
# اثری که ضریب ۱٫۰ می‌دهد. اثرهای بالاتر تقویت و پایین‌تر تضعیف می‌شوند.
# مبنا: نرخ پایه‌ی معمولِ پاسخ به یادآوری در این دامنه.
UPLIFT_REFERENCE = 0.10


def uplift_multiplier(uplift: float | None) -> float:
    """اثرِ اندازه‌گیری‌شده → ضریب رتبه‌بندی.

    نسبت به یک اثرِ مرجع نرمال می‌شود تا مقیاسِ ارزش‌ها به‌هم نریزد: گروهی با
    اثرِ دوبرابرِ مرجع، ضریب ۲ می‌گیرد. ضریب هرگز به صفر نمی‌رسد چون امتیازِ
    صفر یعنی «هرگز نشان نده»، و آن تصمیمِ فیلتر است نه رتبه‌بندی.
    """
    if uplift is None:
        return 1.0
    return max(MIN_UPLIFT_MULTIPLIER, uplift / UPLIFT_REFERENCE)


def _opted_out_keys(business_slug: str, db_path: Path | None) -> set[str]:
    """کلیدهای مشتریانی که تماس را رد کرده‌اند — از دفترِ انصراف.

    مثل `_recently_contacted`، شکست اینجا نباید موتور را بخواباند: مجموعه‌ی خالی
    برمی‌گردد و `filter_consent` همان `filter_skip` همیشگی را ثبت می‌کند.
    """
    try:
        from mktcore.contact.register import load_gate

        return set(load_gate(business_slug=business_slug, db_path=db_path).opted_out)
    except Exception:  # noqa: BLE001 - نبودِ دفتر نباید موتور را بخواباند
        logger.debug("دفترِ انصراف در دسترس نبود؛ فیلتر رضایت رد شد", exc_info=True)
        return set()


def _policy_settings(
    business_slug: str, db_path: Path | None,
) -> tuple[int | None, dict[str, int], int | None]:
    """سیاست‌هایی که **کاربر** تعیین می‌کند: کف حاشیه، حاشیه‌ی کالاها، ظرفیت.

    مثل بقیه‌ی خواندن‌های کمکی، شکست اینجا موتور را نمی‌خواباند: خالی برمی‌گردد
    و فیلترها همان «بررسی نشد» صادقانه را ثبت می‌کنند.
    """
    try:
        from mktcore.costs.register import margin_lookup
        from mktcore.db.engine import session_scope
        from mktcore.db.lookup import resolve_business_id
        from mktcore.settings_store import daily_capacity, margin_floor_bp

        with session_scope(db_path) as session:
            business_id = resolve_business_id(session, business_slug)
            if business_id is None:
                return None, {}, None
            return (
                margin_floor_bp(session, business_id),
                margin_lookup(session, business_id),
                daily_capacity(session, business_id),
            )
    except Exception:  # noqa: BLE001 - نبودِ سیاست نباید موتور را بخواباند
        logger.debug("سیاستِ کاربر در دسترس نبود؛ فیلترهایش رد شدند", exc_info=True)
        return None, {}, None


def _campaign_recent_keys(
    business_slug: str, db_path: Path | None, window_days: int, now: float | None = None,
) -> set[str]:
    """مهرِ تماسِ کمپین‌ها (اکسل یا پیامکِ واقعی) به‌صورت کلیدهای خامِ موتور."""
    try:
        from mktcore.contact.register import recent_contact_keys

        with session_scope(db_path) as session:
            business_id = resolve_business_id(session, business_slug)
            if business_id is None:
                return set()
            return recent_contact_keys(
                session, business_id, window_days=window_days, now=now,
            )
    except Exception:  # noqa: BLE001 - نبودِ دفتر نباید موتور را بخواباند
        logger.debug("مهرِ تماسِ کمپین‌ها در دسترس نبود", exc_info=True)
        return set()


def build_context(
    clean: pd.DataFrame,
    *,
    fatigue_window_days: int = 14,
    per_customer_open_cap: int = 3,
    consent_denied: set[str] | None = None,
    recently_contacted_extra: set[str] | None = None,
    margin_floor_bp: int | None = None,
    margin_by_product: dict[str, int] | None = None,
    daily_capacity: int | None = None,
    offer_ladder_bp: tuple[int, ...] | None = None,
    full_price_tier_of: dict[str, str | None] | None = None,
    customer_margin_bp_of: dict[str, int] | None = None,
    fatigue_now: float | None = None,
) -> dict:
    """ساخت زمینه‌ی فیلترها از آنچه **واقعاً** در دست است.

    هر کلیدِ «has_*» صادقانه از داده خوانده می‌شود؛ هیچ‌کدام فرضِ خوش‌بینانه
    ندارند. `fatigue_now` مرجعِ زمانیِ پنجره‌ی خستگی است (پیش‌فرض ساعتِ دیوار).
    """
    recent, window = _recently_contacted(fatigue_window_days, fatigue_now)
    if recently_contacted_extra:
        # تماسِ کمپین (اکسل/پیامک) هم تماس است — تا دیروز فیلترِ خستگی فقط outbox
        # را می‌دید و عضوِ تازه‌تماس‌گرفته‌ی کمپین دوباره فرصت می‌ساخت.
        # مهرِ کمپین اضافه می‌شود ولی «بررسی شد» فقط وقتی outbox هم خوانده شده؛
        # وگرنه فیلتر همچنان «بررسی نشد» ثبت می‌کند (نیمه‌بررسی قبول نیست).
        recent = set(recent) | set(recently_contacted_extra)
    has_cost = bool(
        "cost" in clean.columns and clean["cost"].notna().any()
    )
    # حاشیه از دفتر کل محاسبه می‌شود، ولی داشتنِ بها به‌تنهایی برای فیلتر کافی
    # نیست: ستون بها ممکن است در خودِ فایل فروش نباشد و از تاریخچه آمده باشد.
    margins = margin_by_product or {}
    return {
        "has_cost_data": has_cost or bool(margins),
        # کفِ حاشیه را **کاربر** تعیین می‌کند؛ `None` یعنی تعیین نشده و آن‌وقت
        # فیلتر «بررسی نشد» ثبت می‌کند، نه «قبول».
        "margin_floor_bp": margin_floor_bp,
        "margin_by_product": margins,
        # ظرفیت پیگیری تیم؛ `None` یعنی کاربر نگفته و فیلتر «بررسی نشد» ثبت
        # می‌کند. حدس‌زدنِ یک سقفِ پیش‌فرض یعنی قیچی‌کردنِ فرصت‌های واقعی با
        # عددی که هیچ‌کس نگفته است.
        "daily_capacity": daily_capacity,
        # نردبانِ تخفیف (§۲۰.۳). `None` یعنی کاربر نردبانی نگفته و فیلترِ آفر
        # همان «بررسی نشد» امروز را ثبت می‌کند — هیچ پله‌ای حدس زده نمی‌شود.
        "offer_ladder_bp": tuple(offer_ladder_bp) if offer_ladder_bp else None,
        "full_price_tier_of": full_price_tier_of or {},
        # حاشیه‌ی سبدِ خودِ مشتری — مبنای سقفِ تخفیف وقتی فرصت کالای مشخصی ندارد
        "customer_margin_bp_of": customer_margin_bp_of or {},
        "has_inventory_data": False,   # هیچ مسیر ورودِ موجودی وجود ندارد
        # ⚠️ عمداً `False` می‌ماند، حتی حالا که دفترِ انصراف وجود دارد.
        # دفترِ انصراف می‌گوید **چه کسی «نه» گفته**، نه اینکه چه کسی «بله» گفته.
        # نبودنِ نام کسی در فهرستِ لغو، «رضایت» نیست. پس `filter_consent` برای
        # مشتریِ عادی همان `filter_skip` صادقانه را ثبت می‌کند، و فقط برای کسی که
        # صریحاً رد کرده `filter_block` می‌دهد.
        "has_consent_data": False,
        "consent_denied": consent_denied or set(),
        "compatibility_rules": None,   # قاعده‌ی دامنه‌ای تعریف نشده است
        "recently_contacted": recent,
        "fatigue_window_days": window,
        "per_customer_open_cap": per_customer_open_cap,
    }


def run_opportunity_engine(
    bundle: Any,
    clean: pd.DataFrame,
    *,
    session_id: str | None = None,
    display_currency: str = "تومان",
    business_slug: str = "default",
    db_path: Path | None = None,
    fatigue_now: float | None = None,
) -> OpportunityRunResult | None:
    """یک اجرای کامل: تولید → فیلتر → ماندگارسازی → چرخه‌ی حیات.

    §۲۸: برای هر `(کسب‌وکار، تاریخ)` **یک** اجرا. اگر اجرای دیگری در جریان
    باشد، این یکی `LeaseBusyError` می‌اندازد — نه اینکه هر دو بنویسند و
    فرصت‌های همدیگر را «ناپدید» اعلام کنند.

    `fatigue_now` (§۳۵ فاز ۲ — بازتولیدپذیری): مرجعِ زمانیِ پنجره‌ی خستگیِ تماس.
    پیش‌فرض ساعتِ دیوار است (تماس رویدادِ زمانِ واقعی است، نه `as_of`ِ داده)،
    ولی مقدارِ به‌کاررفته در `OpportunityRun.notes_json["fatigue_reference_ts"]`
    ثبت می‌شود تا همان اجرا با همان ورودی‌ها بازپخش‌پذیر باشد.
    """
    ensure_schema(db_path)
    as_of = _as_of(clean)
    reference = now_ts() if fatigue_now is None else float(fatigue_now)
    with job_lease(
        JobLease.JOB_OPPORTUNITY_ENGINE, f"{business_slug}|{as_of}", db_path=db_path,
    ):
        return _run_engine_locked(
            bundle, clean, as_of=as_of, session_id=session_id,
            display_currency=display_currency, business_slug=business_slug,
            db_path=db_path, fatigue_now=reference,
        )


def _run_engine_locked(
    bundle: Any,
    clean: pd.DataFrame,
    *,
    as_of: str,
    session_id: str | None,
    display_currency: str,
    business_slug: str,
    db_path: Path | None,
    fatigue_now: float | None = None,
) -> OpportunityRunResult | None:
    """بدنه‌ی اجرا، با این فرض که اجاره گرفته شده است."""
    if fatigue_now is None:
        fatigue_now = now_ts()
    candidates = generate_candidates(bundle, clean)
    # این مولد برخلاف بقیه به دفتر کل نگاه می‌کند (امتیازِ مدلِ فعال)، پس اینجا
    # صدا زده می‌شود که `business_slug` و مسیر دیتابیس در دست است.
    candidates += generate_whale_relationship(
        business_slug=business_slug, db_path=db_path,
    )
    uplift_table = _load_uplift_table(db_path)
    floor_bp, margins, capacity = _policy_settings(business_slug, db_path)
    ladder, tier_thresholds = _offer_policy(business_slug, db_path)
    # طبقه‌ی مشتری فقط وقتی خوانده می‌شود که نردبانی باشد؛ بدون نردبان، اجرا
    # بیت‌به‌بیت مثل قبل است.
    tier_of = _full_price_tier_by_customer_key(
        candidates, business_slug=business_slug, db_path=db_path,
        thresholds=tier_thresholds,
    ) if ladder else {}
    customer_margins = _customer_margin_by_key(
        candidates, business_slug=business_slug, db_path=db_path,
    ) if ladder else {}
    ctx = build_context(
        clean,
        consent_denied=_opted_out_keys(business_slug, db_path),
        recently_contacted_extra=_campaign_recent_keys(business_slug, db_path, 14, fatigue_now),
        fatigue_now=fatigue_now,
        margin_floor_bp=floor_bp,
        margin_by_product=margins,
        daily_capacity=capacity,
        offer_ladder_bp=ladder,
        full_price_tier_of=tier_of,
        customer_margin_bp_of=customer_margins,
    )
    ctx["uplift_table"] = uplift_table
    # حالت چرخه‌ی عمر پیش از فیلتر لازم است، چون فیلترِ اثر بر پایه‌ی سلولِ
    # (نوع اقدام × حالت) تصمیم می‌گیرد.
    ctx["lifecycle_of"] = _lifecycle_by_customer_key(
        candidates, business_slug=business_slug, db_path=db_path,
    ) if uplift_table is not None else {}
    accepted, rejected = apply_filters(candidates, ctx)

    # `apply_filters` خروجی را بر پایه‌ی ارزش نزولی پردازش می‌کند، پس بریدنِ
    # انتها یعنی حذف کم‌ارزش‌ترین‌ها — نه تصادفی‌ها.
    #
    # ⚠️ اقدام‌های رابطه‌ای عمداً ارزش ریالی ندارند، پس در همان مرتب‌سازی همیشه
    # ته صف می‌افتند و دقیقاً همان‌ها بریده می‌شوند. سهمیه‌ی جدا این را درست
    # می‌کند و **بدون هیچ اقدام رابطه‌ای، حسابش دقیقاً مثل قبل است**.
    money = [c for c in accepted if c.value_kind != VALUE_RELATIONSHIP]
    rapport = [c for c in accepted if c.value_kind == VALUE_RELATIONSHIP]
    overflow = money[MAX_PERSISTED_PER_RUN:] + rapport[WHALE_MAX_PER_RUN:]
    capped_out = len(overflow)
    if capped_out:
        accepted = money[:MAX_PERSISTED_PER_RUN] + rapport[:WHALE_MAX_PER_RUN]
        logger.info(
            "سقف صندوق: %s فرصتِ کم‌ارزش‌تر از %s نامزدِ واجد شرایط ذخیره نشد",
            capped_out, capped_out + len(accepted),
        )
    # فرصت‌هایی که فقط به‌خاطر سقف کنار ماندند هنوز **مصداق دارند**؛ اگر
    # «ناپدید» حساب شوند، هر اجرا بین باز و بی‌مصداق نوسان می‌کنند.
    still_valid = {c.dedupe_key() for c in overflow}

    skipped: dict[str, int] = {}
    for candidate in accepted:
        for note in candidate.factors:
            if note.outcome == "filter_skip":
                skipped[note.code] = skipped.get(note.code, 0) + 1

    with write_lock, session_scope(db_path) as session:
        business_id = resolve_business_id(session, business_slug)
        business = session.get(Business, business_id) if business_id else None
        if business is None:
            logger.warning("کسب‌وکار «%s» وجود ندارد؛ موتور فرصت‌ها اجرا نشد.", business_slug)
            return None

        run = OpportunityRun(
            business_id=business.id,
            session_id=session_id,
            as_of_date=as_of,
            engine_version=ENGINE_VERSION,
            candidates_generated=len(candidates),
            candidates_filtered=len(rejected),
            notes_json=json.dumps(
                {
                    "skipped_filters": skipped, "capped_out": capped_out,
                    # مرجعِ زمانیِ پنجره‌ی خستگی — ورودیِ پنهانِ زمان، صریح و بازپخش‌پذیر
                    "fatigue_reference_ts": fatigue_now,
                    "fatigue_window_days": ctx.get("fatigue_window_days"),
                },
                ensure_ascii=False,
            ),
        )
        session.add(run)
        session.flush()

        customer_ids = _customer_ids(session, business.id, accepted)
        product_ids = _product_ids(session, business.id, accepted)
        multipliers = _uplift_multipliers(
            session, business.id, accepted, customer_ids, uplift_table,
        )

        created, refreshed, seen_keys = _persist(
            session, business.id, run.id, accepted,
            customer_ids=customer_ids, product_ids=product_ids,
            display_currency=display_currency, as_of=as_of,
            uplift_multipliers=multipliers,
        )
        superseded = _supersede_missing(
            session, business.id, run.id, seen_keys | still_valid,
        )
        expired = _expire_overdue(session, business.id, as_of)

        run.opportunities_created = created
        run.opportunities_refreshed = refreshed
        run.opportunities_superseded = superseded
        run.opportunities_expired = expired
        run_id = run.id

    result = OpportunityRunResult(
        run_id=run_id,
        generated=len(candidates),
        filtered_out=len(rejected),
        created=created,
        refreshed=refreshed,
        superseded=superseded,
        expired=expired,
        capped_out=capped_out,
        skipped_filters=skipped,
    )
    logger.info("موتور فرصت‌ها: %s", result.to_dict())
    return result


# ------------------------------------------------------------- اثر افزوده
def _load_uplift_table(db_path: Path | None):
    """جدول اثرِ آموخته‌شده. خطا یا خاموشی → None (رتبه‌بندی مثل قبل)."""
    from mktcore.config import get_settings

    if not get_settings().mkt_uplift_ranking:
        logger.info("رتبه‌بندی مبتنی بر اثر خاموش است؛ ترتیب مثل قبل می‌ماند.")
        return None
    try:
        from mktcore.uplift import build_uplift_table

        table = build_uplift_table(db_path=db_path)
        return table if table.available else None
    except Exception:  # noqa: BLE001 - یادگیری نباید تولید فرصت را بخواباند
        logger.exception("ساخت جدول اثر ناموفق بود؛ رتبه‌بندی مثل قبل ادامه می‌دهد")
        return None


def _offer_policy(business_slug: str, db_path: Path | None) -> tuple[tuple[int, ...] | None, dict]:
    """نردبانِ تخفیف و آستانه‌های طبقه — تنظیمِ کاربر. جدا از `_policy_settings`
    تا امضای سه‌تاییِ آن (که تست‌ها unpack می‌کنند) دست نخورد.

    شکست ⇒ `(None, پیش‌فرض‌ها)`: بدون نردبان، فیلترِ آفر همان «بررسی نشد» را
    ثبت می‌کند.
    """
    from mktcore.features.discount import (
        DEFAULT_HIGH_BP,
        DEFAULT_LOW_BP,
        DEFAULT_MIN_LINES,
    )

    defaults = {"high_bp": DEFAULT_HIGH_BP, "low_bp": DEFAULT_LOW_BP, "min_lines": DEFAULT_MIN_LINES}
    try:
        from mktcore.settings_store import full_price_thresholds, offer_ladder_bp

        with session_scope(db_path) as session:
            business_id = resolve_business_id(session, business_slug)
            if business_id is None:
                return None, defaults
            thresholds = full_price_thresholds(session, business_id)
            thresholds.pop("configured", None)
            return offer_ladder_bp(session, business_id), thresholds
    except Exception:  # noqa: BLE001 - نبودِ سیاست نباید موتور را بخواباند
        logger.debug("سیاستِ آفر در دسترس نبود؛ فیلتر آفر رد شد", exc_info=True)
        return None, defaults


def _customer_margin_by_key(
    candidates: list[OpportunityCandidate],
    *,
    business_slug: str,
    db_path: Path | None,
) -> dict[str, int]:
    """کلید خامِ مشتری → حاشیه‌ی وزنیِ خریدهای خودش (پایه‌ی هزارم).

    مبنای سقفِ تخفیف برای فرصت‌های بی‌کالا (نجات از ریزش، بازگشت). مشتریِ بدون
    پوششِ کاملِ بها اینجا نیست و فیلتر برایش «بررسی نشد» ثبت می‌کند.
    """
    keys = {c.customer_key for c in candidates if c.customer_key and not c.product_name}
    if not keys:
        return {}
    try:
        from mktcore.costs.register import margin_by_customer

        with session_scope(db_path) as session:
            business_id = resolve_business_id(session, business_slug)
            if business_id is None:
                return {}
            id_of = customer_ids_by_raw_key(session, business_id, keys)
            margins = margin_by_customer(session, business_id)
        return {key: margins[cid] for key, cid in id_of.items() if cid in margins}
    except Exception:  # noqa: BLE001 - نبودِ حاشیه نباید موتور را بخواباند
        logger.exception("خواندن حاشیه‌ی مشتری ناموفق بود")
        return {}


def _full_price_tier_by_customer_key(
    candidates: list[OpportunityCandidate],
    *,
    business_slug: str,
    db_path: Path | None,
    thresholds: dict,
) -> dict[str, str | None]:
    """کلید خامِ مشتری → طبقه‌ی «تمام‌قیمت‌خری» از آخرین عکسِ ویژگی.

    مشتریِ بدون عدد (فایل بدون ستون تخفیف، یا خطوطِ کم) `None` می‌گیرد و فیلتر
    برایش «بررسی نشد» ثبت می‌کند — نه «تمام‌قیمت» و نه «وابسته به تخفیف».
    """
    from mktcore.features.discount import full_price_tier

    keys = {c.customer_key for c in candidates if c.customer_key}
    if not keys:
        return {}
    try:
        with session_scope(db_path) as session:
            business_id = resolve_business_id(session, business_slug)
            if business_id is None:
                return {}
            id_of = customer_ids_by_raw_key(session, business_id, keys)
            latest = session.scalar(
                select(func.max(CustomerFeature.as_of_date))
                .where(CustomerFeature.business_id == business_id)
            )
            if latest is None:
                return {}
            rows = session.execute(
                select(CustomerFeature.customer_id, CustomerFeature.full_price_share_bp,
                       # کمینه‌ی خطوط روی خطوطِ **مبنای سهم** (کلِ دفتر کل) اعمال می‌شود،
                       # نه خطوطِ همین آپلود؛ وگرنه مشتریِ ۴۰خطی با ۲ خط در فایلِ این
                       # ماه «نامعلوم» می‌شد.
                       func.coalesce(CustomerFeature.full_price_lines, CustomerFeature.n_lines)).where(
                    CustomerFeature.business_id == business_id,
                    CustomerFeature.as_of_date == latest,
                    CustomerFeature.customer_id.in_(sorted(set(id_of.values()))),
                )
            ).all()
        tier_of_id = {
            int(cid): full_price_tier(share, n_lines, **thresholds)
            for cid, share, n_lines in rows
        }
        return {key: tier_of_id.get(cid) for key, cid in id_of.items()}
    except Exception:  # noqa: BLE001 - نبودِ طبقه نباید موتور را بخواباند
        logger.exception("خواندن طبقه‌ی خرید تمام‌قیمت ناموفق بود")
        return {}


def _lifecycle_by_customer_key(
    candidates: list[OpportunityCandidate],
    *,
    business_slug: str,
    db_path: Path | None,
) -> dict[str, str | None]:
    """کلید خامِ مشتری → حالت چرخه‌ی عمر. برای فیلترها که کلید خام دارند."""
    keys = {c.customer_key for c in candidates if c.customer_key}
    if not keys:
        return {}
    try:
        with session_scope(db_path) as session:
            business_id = resolve_business_id(session, business_slug)
            if business_id is None:
                return {}
            id_of = customer_ids_by_raw_key(session, business_id, keys)
            states = _lifecycle_states(session, business_id, set(id_of.values()))
        return {key: states.get(cid) for key, cid in id_of.items()}
    except Exception:  # noqa: BLE001 - نبودِ حالت نباید موتور را بخواباند
        logger.exception("خواندن حالت چرخه‌ی عمر برای فیلتر اثر ناموفق بود")
        return {}


def _lifecycle_states(
    session: Session, business_id: int, customer_ids: set[int],
) -> dict[int, str | None]:
    """آخرین حالت چرخه‌ی عمر هر مشتری — کلیدِ سلولِ اثر."""
    if not customer_ids:
        return {}
    latest = session.scalar(
        select(func.max(CustomerFeature.as_of_date))
        .where(CustomerFeature.business_id == business_id)
    )
    if latest is None:
        return {}
    rows = session.execute(
        select(CustomerFeature.customer_id, CustomerFeature.lifecycle_state).where(
            CustomerFeature.business_id == business_id,
            CustomerFeature.as_of_date == latest,
            CustomerFeature.customer_id.in_(sorted(customer_ids)),
        )
    ).all()
    return {int(cid): (str(state) if state else None) for cid, state in rows}


def _uplift_multipliers(
    session: Session,
    business_id: int,
    candidates: list[OpportunityCandidate],
    customer_ids: dict[str, int],
    table,
) -> dict[str, float]:
    """ضریب رتبه‌بندی هر نامزد + ثبت شواهدش روی خودِ نامزد.

    شواهد اجباری است: اگر فرصتی به‌خاطر یادگیری جابه‌جا شد، کاربر باید بتواند
    ببیند چرا. جابه‌جاییِ بی‌توضیح، اعتماد را از بین می‌برد.
    """
    if table is None:
        return {}

    resolved = {customer_ids[c.customer_key] for c in candidates
                if c.customer_key in customer_ids}
    states = _lifecycle_states(session, business_id, resolved)

    out: dict[str, float] = {}
    for candidate in candidates:
        customer_id = customer_ids.get(candidate.customer_key)
        state = states.get(customer_id) if customer_id else None
        uplift, basis = table.lookup(candidate.kind, state)
        if basis == BASIS_NONE:
            continue  # بدون داده → ضریب ۱٫۰ (رفتار امروز)

        multiplier = uplift_multiplier(uplift)
        out[candidate.dedupe_key()] = multiplier
        candidate.add_factor(OpportunityFactorNote(
            code="uplift_estimate",
            label_fa="اثر افزوده‌ی اندازه‌گیری‌شده",
            outcome=OUTCOME_EVIDENCE,
            value_text=f"{round(uplift * 100, 1)} واحد درصد",
            detail_fa=(
                f"{BASIS_LABELS_FA.get(basis, basis)} — امتیاز رتبه‌بندی با ضریب "
                f"{multiplier:.2f} تعدیل شد. ارزشِ گزارش‌شده تغییر نکرده است."
            ),
        ))
    return out


# ------------------------------------------------------------------ کمکی‌ها
def _customer_ids(
    session: Session, business_id: int, candidates: list[OpportunityCandidate],
) -> dict[str, int]:
    return customer_ids_by_raw_key(
        session, business_id, (c.customer_key for c in candidates if c.customer_key),
    )


def _product_ids(
    session: Session, business_id: int, candidates: list[OpportunityCandidate],
) -> dict[str, int]:
    return product_ids_by_raw_name(
        session, business_id, (c.product_name for c in candidates if c.product_name),
    )


def _expiry_date(as_of: str, ttl_days: int = DEFAULT_TTL_DAYS) -> str:
    return (pd.Timestamp(as_of) + pd.Timedelta(days=ttl_days)).date().isoformat()


def _persist(
    session: Session,
    business_id: int,
    run_id: int,
    candidates: list[OpportunityCandidate],
    *,
    customer_ids: dict[str, int],
    product_ids: dict[str, int],
    display_currency: str,
    as_of: str,
    uplift_multipliers: dict[str, float] | None = None,
) -> tuple[int, int, set[str]]:
    uplift_multipliers = uplift_multipliers or {}
    keys = [c.dedupe_key() for c in candidates]
    existing: dict[str, Opportunity] = {}
    for start in range(0, len(keys), 2000):
        rows = session.scalars(
            select(Opportunity).where(
                Opportunity.business_id == business_id,
                Opportunity.dedupe_key.in_(keys[start:start + 2000]),
            )
        ).all()
        existing.update({o.dedupe_key: o for o in rows})

    created = refreshed = 0
    seen: set[str] = set()
    for candidate in candidates:
        key = candidate.dedupe_key()
        if key in seen:
            # دو نامزد با کلید یکسان در یک اجرا (مثلاً دو مولد که به یک
            # پیشنهاد رسیده‌اند): اولی برنده است. بدون این گارد، دومی به قید
            # یکتایی می‌خورد و کل اجرا rollback می‌شد.
            continue
        seen.add(key)
        value_rial = to_rial_int(candidate.expected_value_display, display_currency) or 0
        # ارزشِ گزارش‌شده دست‌نخورده می‌ماند؛ فقط **امتیازِ رتبه‌بندی** با اثرِ
        # اندازه‌گیری‌شده تعدیل می‌شود. بدون داده‌ی آزمایشی ضریب ۱٫۰ است، پس
        # ترتیب دقیقاً مثل قبل درمی‌آید.
        score_rial = round(value_rial * uplift_multipliers.get(key, 1.0))
        fields = {
            "customer_id": customer_ids.get(candidate.customer_key),
            "product_id": product_ids.get(candidate.product_name) if candidate.product_name else None,
            "kind": candidate.kind,
            "generator": candidate.generator,
            "generator_version": candidate.generator_version,
            "title_fa": candidate.title_fa,
            "action_fa": candidate.action_fa,
            "reason_fa": candidate.reason_fa,
            "message_fa": candidate.message_fa,
            "expected_value_rial": value_rial,
            "score_rial": score_rial,
            "value_kind": candidate.value_kind,
            "probability_bp": to_basis_points(candidate.probability),
            "confidence": candidate.confidence,
            "owner_hint": candidate.owner_hint,
            "due_date": candidate.due_date,
            "expires_at": candidate.expires_at or _expiry_date(as_of),
            "last_seen_run_id": run_id,
            "updated_at": now_ts(),
        }

        opportunity = existing.get(key)
        if opportunity is None:
            opportunity = Opportunity(
                business_id=business_id, dedupe_key=key,
                status=STATUS_OPEN, first_seen_run_id=run_id, seen_count=1,
                **fields,
            )
            session.add(opportunity)
            session.flush()
            _add_event(session, opportunity.id, "created", None, STATUS_OPEN,
                       note="فرصت تازه توسط موتور ساخته شد.")
            created += 1
        else:
            for name, value in fields.items():
                setattr(opportunity, name, value)
            opportunity.seen_count += 1
            # وضعیت انسانی دست‌نخورده می‌ماند؛ فقط فرصتی که **موتور** خودش کنار
            # گذاشته بود دوباره باز می‌شود. شرط بر پایه‌ی «انسانی نبودن» نوشته
            # شده، نه فهرست وضعیت‌های ماشینی: افزودن وضعیت ماشینیِ تازه در
            # آینده نباید بی‌صدا تصمیم کاربر را بازنویسی کند.
            if opportunity.status not in _HUMAN_STATUSES and opportunity.status != STATUS_OPEN:
                previous = opportunity.status
                opportunity.status = STATUS_OPEN
                opportunity.status_reason_fa = None
                _add_event(session, opportunity.id, "reopened", previous, STATUS_OPEN,
                           note="این فرصت دوباره مصداق پیدا کرد.")
            _add_event(session, opportunity.id, "refreshed", opportunity.status,
                       opportunity.status, note="شواهد و ارزش با تحلیل تازه به‌روز شد.")
            refreshed += 1

        _replace_factors(session, opportunity.id, candidate)
        # پیشنهادِ تخفیف در جدولِ جدا می‌نشیند — نه در `fields` (که هر اجرا
        # بازنویسی می‌شود) و نه در عامل‌ها (که هر اجرا پاک می‌شوند). تصمیمِ انسان
        # آنجا زنده می‌ماند.
        upsert_offer(session, business_id, opportunity, candidate, run_id)

    session.flush()
    return created, refreshed, seen


def _replace_factors(
    session: Session, opportunity_id: int, candidate: OpportunityCandidate,
) -> None:
    """شواهد همیشه بازتاب آخرین اجرا هستند، پس جایگزین می‌شوند نه انباشته."""
    session.query(OpportunityFactor).filter(
        OpportunityFactor.opportunity_id == opportunity_id
    ).delete(synchronize_session=False)
    seen_codes: set[str] = set()
    for note in candidate.factors:
        if note.code in seen_codes:
            continue
        seen_codes.add(note.code)
        session.add(OpportunityFactor(
            opportunity_id=opportunity_id,
            code=note.code,
            label_fa=note.label_fa,
            outcome=note.outcome,
            detail_fa=note.detail_fa,
            value_text=note.value_text,
        ))


def _supersede_missing(
    session: Session, business_id: int, run_id: int, seen_keys: set[str],
) -> int:
    """فرصت‌های بازی که این بار تولید نشدند → «دیگر مصداق ندارد».

    فرصتی که انسان پذیرفته یا اسنوز کرده دست‌نخورده می‌ماند: ممکن است تیم فروش
    روی آن کار کند و ناپدیدشدنش از خروجی مدل، دلیل لغو کارِ در جریان نیست.
    """
    live = session.scalars(
        select(Opportunity).where(
            Opportunity.business_id == business_id,
            Opportunity.status == STATUS_OPEN,
        )
    ).all()
    count = 0
    for opportunity in live:
        if opportunity.dedupe_key in seen_keys:
            continue
        opportunity.status = STATUS_SUPERSEDED
        opportunity.status_reason_fa = "در تحلیل تازه دیگر مصداق ندارد."
        opportunity.updated_at = now_ts()
        opportunity.last_seen_run_id = run_id
        _add_event(session, opportunity.id, "superseded", STATUS_OPEN, STATUS_SUPERSEDED,
                   note="تحلیل تازه این فرصت را دیگر تولید نکرد.")
        count += 1
    return count


def expire_overdue_opportunities(
    *,
    business_slug: str = "default",
    as_of: str | None = None,
    db_path: Path | None = None,
) -> dict:
    """انقضای فرصت‌های از تاریخ‌گذشته، **بدون** اجرای کاملِ موتور (§۲۸ بند ۷).

    تا امروز انقضا فقط به‌عنوان یک گامِ فرعیِ اجرای موتور اتفاق می‌افتاد. یعنی
    اگر یک هفته فایلِ تازه‌ای وارد نمی‌شد، فرصت‌های منقضی همچنان «باز» نشان داده
    می‌شدند — و کاربر روی چیزی وقت می‌گذاشت که دیگر مصداق نداشت.

    idempotent است: اجرای دوباره چیزی برای انقضا پیدا نمی‌کند و صفر برمی‌گرداند.
    """
    ensure_schema(db_path)
    today = as_of or pd.Timestamp.now().date().isoformat()
    with write_lock, session_scope(db_path) as session:
        business_id = resolve_business_id(session, business_slug)
        if business_id is None:
            return {"expired": 0, "note_fa": "کسب‌وکاری با این نام وجود ندارد."}
        expired = _expire_overdue(session, business_id, today)
    return {"expired": expired, "as_of": today}


def _expire_overdue(session: Session, business_id: int, as_of: str) -> int:
    overdue = session.scalars(
        select(Opportunity).where(
            Opportunity.business_id == business_id,
            Opportunity.status.in_(sorted(_LIVE_STATUSES)),
            Opportunity.expires_at.isnot(None),
            Opportunity.expires_at < as_of,
        )
    ).all()
    for opportunity in overdue:
        previous = opportunity.status
        opportunity.status = STATUS_EXPIRED
        opportunity.status_reason_fa = "از تاریخ اعتبار گذشت."
        opportunity.updated_at = now_ts()
        _add_event(session, opportunity.id, "expired", previous, STATUS_EXPIRED,
                   note=f"تاریخ اعتبار ({opportunity.expires_at}) گذشته است.")
    return len(overdue)


def _add_event(
    session: Session,
    opportunity_id: int,
    event_type: str,
    from_status: str | None,
    to_status: str | None,
    *,
    actor: str | None = None,
    note: str | None = None,
    payload: dict | None = None,
) -> None:
    session.add(OpportunityEvent(
        opportunity_id=opportunity_id,
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        actor=actor or "system",
        note_fa=note,
        payload_json=json.dumps(payload, ensure_ascii=False) if payload else None,
    ))


__all__ = [
    "DEFAULT_TTL_DAYS",
    "ENGINE_VERSION",
    "STATUS_ACCEPTED",
    "STATUS_DISMISSED",
    "STATUS_DONE",
    "STATUS_EXPIRED",
    "STATUS_OPEN",
    "STATUS_SNOOZED",
    "STATUS_SUPERSEDED",
    "OpportunityRunResult",
    "build_context",
    "expire_overdue_opportunities",
    "run_opportunity_engine",
]
