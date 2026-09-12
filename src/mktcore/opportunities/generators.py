"""مولدهای نامزد فرصت.

قاعده‌ی سختِ این فایل: **هیچ ریاضی جدیدی اینجا نوشته نمی‌شود.** محاسبه‌ی ارزش،
احتمال و رتبه‌بندی همان‌جا می‌ماند که هست و تست دارد. اینجا فقط خروجی‌های موجود
به قرارداد مشترک ترجمه می‌شوند.

به‌طور مشخص `analysis/actions.py` **دست نمی‌خورد**: همان تابع با سقفِ بازتر
(`per_customer_cap=3, limit=5000`) بار دوم صدا زده می‌شود. `bundle.actions`
(با سقف ۱) برای کارت داشبورد و خروجی اکسل دست‌نخورده می‌ماند، چون تست‌های موجود
به آن پین‌اند.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from mktcore.analysis.actions import build_action_list

from .contract import (
    OUTCOME_EVIDENCE,
    VALUE_RELATIONSHIP,
    OpportunityCandidate,
    OpportunityFactorNote,
)

logger = logging.getLogger("mktcore.opportunities.generators")

ACTION_GENERATOR = "action_list"
ACTION_GENERATOR_VERSION = 1

# سقف بازتر از داشبورد: آنجا هدف «یک اقدام برجسته به‌ازای مشتری» است، اینجا
# صندوق کاری تیم فروش که می‌تواند چند فرصت هم‌زمان برای یک مشتری داشته باشد.
WIDE_PER_CUSTOMER_CAP = 3
WIDE_LIMIT = 5000


def generate_from_action_list(
    bundle: Any,
    clean: pd.DataFrame,
    *,
    per_customer_cap: int = WIDE_PER_CUSTOMER_CAP,
    limit: int = WIDE_LIMIT,
    as_of: str | None = None,
) -> list[OpportunityCandidate]:
    """ترجمه‌ی فهرست اقدام موجود به نامزدهای فرصت.

    ارزش‌ها از قبل در احتمال ضرب شده‌اند؛ اینجا **دوباره ضرب نمی‌شوند**.
    `as_of` (§۱۲ `generate(as_of)`) اینجا عمداً خوانده نمی‌شود: این مولد همان فهرستِ
    اقدامِ داشبورد است که «آخرین روزِ داده» را خودش می‌داند؛ پارامتر برای مولدهای
    مدعی است که باید بازپخش‌پذیر باشند.
    """
    try:
        plan = build_action_list(bundle, clean, per_customer_cap=per_customer_cap, limit=limit)
    except Exception:  # noqa: BLE001 - یک مولد خراب نباید کل موتور را بخواباند
        logger.exception("ساخت فهرست اقدام برای موتور فرصت‌ها ناموفق بود")
        return []

    candidates: list[OpportunityCandidate] = []
    for action in plan.actions:
        candidate = OpportunityCandidate(
            kind=action.kind,
            generator=ACTION_GENERATOR,
            generator_version=ACTION_GENERATOR_VERSION,
            customer_key=str(action.customer_id),
            title_fa=_title(action),
            action_fa=action.action_fa,
            reason_fa=action.reason_fa,
            expected_value_display=float(action.value_rial),
            value_kind=action.value_kind,
            product_name=action.product,
            message_fa=action.message_fa,
            probability=action.probability,
            confidence=action.confidence,
            owner_hint=action.owner,
            phone=action.phone,
            due_date=action.predicted_next_date,
        )
        candidate.add_factor(OpportunityFactorNote(
            code="source_rank",
            label_fa="رتبه در فهرست اقدام",
            outcome=OUTCOME_EVIDENCE,
            value_text=str(action.rank),
            detail_fa="رتبه‌بندی بر پایه‌ی ارزش مورد انتظار (ارزش × احتمال) است.",
        ))
        if action.last_purchase:
            candidate.add_factor(OpportunityFactorNote(
                code="last_purchase",
                label_fa="آخرین خرید",
                outcome=OUTCOME_EVIDENCE,
                value_text=str(action.last_purchase),
            ))
        if action.probability is not None:
            candidate.add_factor(OpportunityFactorNote(
                code="probability",
                label_fa="احتمال تحقق",
                outcome=OUTCOME_EVIDENCE,
                value_text=f"{round(action.probability * 100, 1)}٪",
                detail_fa="احتمال از مدل کالیبره‌شده می‌آید و در ارزش ضرب شده است.",
            ))
        candidate.add_factor(OpportunityFactorNote(
            code="value_kind",
            label_fa="نوع ارزش",
            outcome=OUTCOME_EVIDENCE,
            value_text=action.value_kind,
            detail_fa=(
                "«ارزش در معرض خطر» یعنی درآمدی که ممکن است از دست برود، نه درآمد تازه."
                if action.value_kind == "ارزش در معرض خطر"
                else "«ارزش فرصت» درآمد بالقوه است، نه سود و نه درآمد قطعی."
            ),
        ))
        candidates.append(candidate)
    return candidates


def _title(action: Any) -> str:
    if action.product:
        return f"{action.kind} — {action.product}"
    return str(action.kind)


# ------------------------------------------------- مولد شکاف توسعه‌ی درآمد
KIND_EXPANSION = "توسعه‌ی سبد خرید"
EXPANSION_GENERATOR = "expansion_gap"
EXPANSION_GENERATOR_VERSION = 1

# ارزش شکاف، **درآمد بالقوه** است نه درآمد قطعی. برای رتبه‌بندی در کنار
# فرصت‌هایی که ارزششان از قبل در احتمال ضرب شده، باید تخفیف بخورد وگرنه
# فرصت‌های حدسی، فرصت‌های مبتنی بر رفتار واقعی را کنار می‌زنند.
_CONFIDENCE_WEIGHT = {"بالا": 0.5, "متوسط": 0.3, "کم": 0.15}


def generate_from_expansion_gap(
    bundle: Any, clean: pd.DataFrame, *, top_per_customer: int = 2,
    as_of: str | None = None,
) -> list[OpportunityCandidate]:
    """نامزدهای «این دسته را از ما نمی‌خرد» بر پایه‌ی مقایسه‌ی همتایان."""
    try:
        from mktcore.analysis.expansion_gap import compute_expansion_gap

        segments = getattr(getattr(bundle, "segments", None), "rfm_table", None)
        result = compute_expansion_gap(
            clean, segments, top_per_customer=top_per_customer,
        )
    except Exception:  # noqa: BLE001 - یک مولد خراب نباید کل موتور را بخواباند
        logger.exception("محاسبه‌ی شکاف توسعه‌ی درآمد ناموفق بود")
        return []

    if not result.available:
        logger.info("شکاف توسعه‌ی درآمد گزارش نشد: %s", result.skipped_reason_fa)
        return []

    candidates: list[OpportunityCandidate] = []
    for gap in result.gaps:
        weight = _CONFIDENCE_WEIGHT.get(gap.confidence, 0.15)
        candidate = OpportunityCandidate(
            kind=KIND_EXPANSION,
            generator=EXPANSION_GENERATOR,
            generator_version=EXPANSION_GENERATOR_VERSION,
            customer_key=gap.customer_id,
            product_name=gap.category,
            title_fa=f"{KIND_EXPANSION} — {gap.category}",
            action_fa=(
                f"به این مشتری «{gap.category}» را معرفی کنید؛ مشتریان مشابهش "
                "این دسته را می‌خرند ولی او نه."
            ),
            reason_fa=gap.evidence_fa,
            expected_value_display=gap.gap_value * weight,
            value_kind="ارزش فرصت",
            confidence=gap.confidence,
        )
        candidate.add_factor(OpportunityFactorNote(
            code="peer_comparison",
            label_fa="مقایسه با همتایان",
            outcome=OUTCOME_EVIDENCE,
            value_text=f"{gap.peer_count} همتا",
            detail_fa=gap.evidence_fa,
        ))
        candidate.add_factor(OpportunityFactorNote(
            code="peer_adoption",
            label_fa="نفوذ دسته در گروه همتا",
            outcome=OUTCOME_EVIDENCE,
            value_text=f"{round(gap.peer_adoption * 100)}٪",
        ))
        candidate.add_factor(OpportunityFactorNote(
            code="value_basis",
            label_fa="پایه‌ی ارزش",
            outcome=OUTCOME_EVIDENCE,
            value_text=f"{round(weight * 100)}٪ از میانه‌ی همتایان",
            detail_fa=(
                "این عدد **پتانسیل** است نه درآمد قطعی: میانه‌ی خرید همتایان با "
                "ضریب اطمینان تخفیف خورده تا در کنار فرصت‌های رفتاری منصفانه "
                "رتبه‌بندی شود."
            ),
        ))
        candidates.append(candidate)
    return candidates


# ------------------------------------------- مولد اقدامِ رابطه‌ای (نهنگ آینده)
KIND_WHALE_RELATIONSHIP = "اقدام رابطه‌ای با مشتری کلیدی آینده"
WHALE_GENERATOR = "future_whale"
WHALE_GENERATOR_VERSION = 1

# آستانه‌ی احتمال. عمداً بالاست: این اقدام وقتِ انسان می‌برد و فهرستِ بلندِ
# «شاید نهنگ باشد» همان چیزی است که تیم را بی‌اعتماد می‌کند.
WHALE_MIN_PROBABILITY_BP = 6_000
# سقفِ این نوع فرصت در هر اجرا — جدا از سقفِ فرصت‌های ریالی
WHALE_MAX_PER_RUN = 150

# §۱۸.۵: خدمت، دسترسی و رابطه — **نه تخفیف**. جمله‌ی آخرِ آن بخش صریح است:
# «Do not immediately train these customers to wait for discounts.»
WHALE_ACTIONS_FA = (
    "تماس آشناسازی و معرفی مسئول اختصاصی پیگیری",
    "پیشنهاد یادآوری خودکار برای اقلام مصرفی‌اش",
    "اطلاع‌رسانی زودهنگام از رسیدن کالای دسته‌های موردعلاقه‌اش",
    "بررسی رضایت پس از خرید و رفع اشکال",
)


def generate_whale_relationship(
    *, business_slug: str = "default", db_path: Any = None,
) -> list[OpportunityCandidate]:
    """اقدام‌های رابطه‌ای برای مشتریانی که مدلِ **فعال** نهنگ نشانشان کرده.

    بدون مدلِ فعال، این مولد **هیچ‌چیز** برنمی‌گرداند. جایگزین‌کردنش با «دهک
    بالای CLV» وسوسه‌انگیز است ولی همان اشتباهی است که یک‌بار در حسابرسی ثبت شد:
    «ویژه» برچسبِ امروز است و «نهنگ آینده» پیش‌بینیِ فردا؛ یکی جای دیگری
    نمی‌نشیند.
    """
    try:
        from sqlalchemy import func, select

        from mktcore.db.engine import session_scope
        from mktcore.db.lookup import resolve_business_id
        from mktcore.db.models import CustomerFeature, CustomerKey
        from mktcore.ml.registry import promoted_run

        with session_scope(db_path) as session:
            business_id = resolve_business_id(session, business_slug)
            if business_id is None:
                return []
            run = promoted_run(session, business_id, "whale")
            if run is None:
                logger.info("مدلِ نهنگی فعال نیست؛ اقدام رابطه‌ای ساخته نشد.")
                return []

            latest = session.scalar(
                select(func.max(CustomerFeature.as_of_date)).where(
                    CustomerFeature.business_id == business_id
                )
            )
            rows = session.execute(
                select(
                    CustomerFeature.customer_id,
                    CustomerFeature.whale_probability_bp,
                    CustomerFeature.clv_gp_365d_rial,
                    CustomerFeature.lifecycle_state,
                    CustomerKey.key_value,
                )
                .join(
                    CustomerKey,
                    (CustomerKey.customer_id == CustomerFeature.customer_id)
                    & (CustomerKey.key_type == "raw_key"),
                )
                .where(
                    CustomerFeature.business_id == business_id,
                    CustomerFeature.as_of_date == latest,
                    CustomerFeature.whale_probability_bp >= WHALE_MIN_PROBABILITY_BP,
                )
                .order_by(CustomerFeature.whale_probability_bp.desc())
                .limit(WHALE_MAX_PER_RUN)
            ).all()
            model_version = run.model_version
    except Exception:  # noqa: BLE001 - یک مولد خراب نباید کل موتور را بخواباند
        logger.exception("ساخت اقدام رابطه‌ای نهنگ ناموفق بود")
        return []

    candidates: list[OpportunityCandidate] = []
    seen: set[str] = set()
    for _customer_id, probability_bp, profit_clv, lifecycle_state, raw_key in rows:
        key = str(raw_key)
        if key in seen:
            continue
        seen.add(key)
        share = round(int(probability_bp) / 100)
        candidate = OpportunityCandidate(
            kind=KIND_WHALE_RELATIONSHIP,
            generator=WHALE_GENERATOR,
            generator_version=WHALE_GENERATOR_VERSION,
            customer_key=key,
            title_fa=KIND_WHALE_RELATIONSHIP,
            action_fa=" · ".join(WHALE_ACTIONS_FA),
            reason_fa=(
                f"مدل (نسخه {model_version}) با احتمال {share}٪ این مشتری را در "
                "مسیر تبدیل‌شدن به مشتریِ پرارزش می‌بیند. مبنا رفتارِ همان "
                "روزهای نخستِ خودش است، نه خریدِ بزرگِ گذشته."
            ),
            # عمداً صفر: ارزشِ این اقدام رابطه است و عددِ ریالی برایش ساختگی
            # می‌شد. §۳۸ هم این گروه را فقط با «تعداد مشتری» نشان می‌دهد.
            expected_value_display=0.0,
            value_kind=VALUE_RELATIONSHIP,
            probability=int(probability_bp) / 10_000,
            confidence="مدل‌محور",
        )
        candidate.add_factor(OpportunityFactorNote(
            code="whale_probability",
            label_fa="احتمال مشتری کلیدی آینده",
            outcome=OUTCOME_EVIDENCE,
            value_text=f"{share}٪",
            detail_fa=f"از مدلِ فعالِ نهنگ، نسخه {model_version}.",
        ))
        if profit_clv:
            candidate.add_factor(OpportunityFactorNote(
                code="profit_clv",
                label_fa="سود ناخالص ۱۲ ماه آینده (پیش‌بینی)",
                outcome=OUTCOME_EVIDENCE,
                value_text=str(profit_clv),
                detail_fa=(
                    "این عدد **پیش‌بینی** است، نه اثر اثبات‌شده؛ برای همین در "
                    "ارزش این فرصت نیامده."
                ),
            ))
        if lifecycle_state:
            candidate.add_factor(OpportunityFactorNote(
                code="lifecycle",
                label_fa="حالت چرخه‌ی عمر",
                outcome=OUTCOME_EVIDENCE,
                value_text=str(lifecycle_state),
            ))
        candidates.append(candidate)
    return candidates


# ─────────────────────────────── مدعیِ چرخه‌ی خریدِ شخصی (§۱۳.۲) — فقط پشتِ اجرای فعال
REPLENISH_GENERATOR = "replenish_personal"
REPLENISH_GENERATOR_VERSION = 1
REPLENISH_MAX_PER_RUN = 3000
# پنجره‌ی «نزدیک» همان قاعده‌ی قهرمان (`purchase_cycle.analyze_purchase_cycles`): تا
# ۲۰٪ فاصله (کمینه ۳ روز) پیش از سررسید هم یادآوری معنا دارد.
REPLENISH_NEAR_FRACTION = 0.2
REPLENISH_TTL_DAYS = (7, 45)


def generate_replenishment_personal(
    bundle: Any,
    clean: pd.DataFrame,
    *,
    as_of: str | None = None,
    business_slug: str = "default",
    db_path: Any = None,
) -> list[OpportunityCandidate]:
    """یادآورِ تکرارِ خرید با آهنگِ **شخصیِ** جفتِ (مشتری، کالا) — قهرمان/مدعی.

    بدونِ اجرای فعالِ `replenish` در رجیستری `[]` برمی‌گرداند و موتور بیت‌به‌بیت مثلِ
    قبل می‌ماند. با اجرای فعال، برای هر جفتِ واجد (≥ ۲ فاصله) که در پنجره‌ی نزدیکِ
    سررسیدِ شخصی‌اش است و جدولِ سررسید برایش احتمالِ کالیبره دارد، یک نامزدِ
    `KIND_CYCLE` می‌سازد که پله‌ی شواهد، فاصله‌ی شخصی، عدم‌قطعیت، نسبتِ عقب‌افتادگی،
    تعدیلِ بسته و مبنای ارزش را در عواملش می‌گوید (§۱۳.۶ / §۲۶.۶).
    """
    if as_of is None or clean is None or clean.empty:
        return []
    try:
        import numpy as np

        from mktcore.analysis.actions import KIND_CYCLE, VALUE_OPPORTUNITY, _phone_map
        from mktcore.analysis.replenish_personal import personal_cadence_table
        from mktcore.db.engine import session_scope
        from mktcore.db.lookup import resolve_business_id
        from mktcore.ml.replenish import promoted_due_table, score_due_table

        with session_scope(db_path) as session:
            business_id = resolve_business_id(session, business_slug)
            if business_id is None:
                return []
            active = promoted_due_table(session, business_id)
            if active is None:
                logger.info("مدلِ replenish فعال نیست؛ یادآورِ شخصی ساخته نشد.")
                return []
            run, table = active
            model_version = int(run.model_version)
        cadence = personal_cadence_table(
            clean, as_of=as_of, min_gaps=int(table.get("min_gaps", 2)),
            decay=float(table.get("decay", 0.75)),
        )
    except Exception:  # noqa: BLE001 - یک مولد خراب نباید کل موتور را بخواباند
        logger.exception("ساخت یادآورِ شخصیِ تکرارِ خرید ناموفق بود")
        return []
    if cadence.empty:
        return []

    probabilities = score_due_table(
        table, cadence["overdue_ratio"].to_numpy(dtype=float),
        cadence["uncertainty"].fillna(0.0).to_numpy(dtype=float),
    )
    phones = _phone_map(clean)
    reference = pd.Timestamp(as_of)
    candidates: list[OpportunityCandidate] = []
    for (customer, product), row, probability in zip(
        cadence.index, cadence.to_dict("records"), probabilities, strict=False,
    ):
        if probability is None or np.isnan(probability) or probability <= 0:
            # جدولِ سررسید برای این سلول شاهدِ کافی ندارد (بی‌امتیاز، نه حدس) یا در گذشته
            # هیچ‌کس در این وضعیت نخریده؛ کارتی با احتمالِ صفر یادآوری نیست.
            continue
        interval = float(row["pack_adjusted_interval_days"])
        elapsed = float(row["elapsed_days"])
        near = max(3.0, REPLENISH_NEAR_FRACTION * interval)
        if elapsed < interval - near:
            continue
        spend = row["median_spend"]
        if spend is None or not np.isfinite(spend):
            continue
        offset = int(round(elapsed - interval))
        gaps_fa = "، ".join(str(g) for g in row["gaps_days"])
        due = pd.Timestamp(row["last_purchase"]) + pd.Timedelta(days=interval)
        ttl = int(min(max(round(interval), REPLENISH_TTL_DAYS[0]), REPLENISH_TTL_DAYS[1]))
        reason = (
            f"{len(row['gaps_days'])} بار با فاصله‌های {gaps_fa} روز خریده؛ فاصله‌ی شخصی‌اش "
            f"{round(interval)} روز است و {int(elapsed)} روز از آخرین خرید گذشته "
            + (f"({offset} روز عقب‌افتاده)" if offset > 0 else f"({-offset} روز مانده)")
            + "."
        )
        candidate = OpportunityCandidate(
            kind=KIND_CYCLE,
            generator=REPLENISH_GENERATOR,
            generator_version=REPLENISH_GENERATOR_VERSION,
            customer_key=str(customer),
            title_fa=f"یادآوری خرید «{product}» (آهنگ شخصی)",
            action_fa=f"تماس/پیام یادآوری خرید «{product}»",
            reason_fa=reason,
            expected_value_display=float(spend) * float(probability),
            value_kind=VALUE_OPPORTUNITY,
            product_name=str(product),
            message_fa=(
                f"سلام، طبق آهنگِ خریدِ خودتان ({round(interval)} روزه) زمان تهیه‌ی «{product}» رسیده است."
            ),
            probability=float(probability),
            confidence=str(row["confidence_fa"]),
            phone=phones.get(str(customer)),
            due_date=due.date().isoformat(),
            expires_at=(reference + pd.Timedelta(days=ttl)).date().isoformat(),
        )
        evidence = [
            ("evidence_level", "پله‌ی شواهد", str(row["evidence_level_fa"]),
             "آهنگ از خریدهای خودِ این مشتری برای همین کالا است، نه میانه‌ی جمعیت (§۱۳.۲)."),
            ("expected_interval", "فاصله‌ی شخصیِ خرید", f"{round(interval)} روز",
             f"میانه‌ی وزنیِ فاصله‌های {gaps_fa} روز (وزنِ تازگی ۰٫۷۵)."),
            ("interval_uncertainty", "عدم‌قطعیتِ آهنگ",
             f"{round(float(row['uncertainty'] or 0.0), 2)}", "MAD ÷ فاصله (§۱۳.۳)."),
            ("overdue_ratio", "نسبتِ عقب‌افتادگی", f"{round(float(row['overdue_ratio']), 2)}",
             "گذشته از آخرین خرید ÷ فاصله‌ی موردانتظار."),
            ("pack_adjustment", "تعدیلِ اندازه‌ی خرید",
             str(row["pack_reason_fa"] or "مقدارِ معمول؛ بدون تعدیل"), None),
            ("probability", "احتمال خرید در بازه‌ی ادعا", f"{round(float(probability) * 100, 1)}٪",
             f"از جدولِ سررسیدِ کالیبره‌ی مدلِ فعالِ replenish نسخه {model_version}؛ در ارزش ضرب شده است."),
            ("champion_replaced", "جایگزینِ یادآورِ جمعیتی", "بله",
             "میانه‌ی جمعیتِ کالا برای این جفت کنار گذاشته شد (قهرمان/مدعی، با holdout)."),
            ("value_basis", "مبنای ارزش", "درآمد",
             "ارزش = میانه‌ی مبلغِ خریدهای همین کالا × احتمال؛ درآمدی است نه سود."),
        ]
        for code, label, value, detail in evidence:
            candidate.add_factor(OpportunityFactorNote(
                code=code, label_fa=label, outcome=OUTCOME_EVIDENCE, value_text=value, detail_fa=detail,
            ))
        candidates.append(candidate)
        if len(candidates) >= REPLENISH_MAX_PER_RUN:
            break
    return candidates


def replace_champion_cycle(
    candidates: list[OpportunityCandidate], challenger: list[OpportunityCandidate],
) -> tuple[list[OpportunityCandidate], dict[str, str]]:
    """یادآورِ قهرمان (`action_list` × `KIND_CYCLE`) برای جفت‌های پوشش‌داده‌شده حذف می‌شود.

    بدونِ مدعی هیچ‌چیز حذف نمی‌شود؛ جفت‌های بی‌پوشش یادآورِ قهرمان (پله‌ی ۵) را نگه می‌دارند.
    برمی‌گرداند (نامزدهای نهایی، نگاشتِ کلیدِ کارتِ قهرمانِ حذف‌شده → کلیدِ کارتِ جایگزین) تا
    موتور کارتِ بازِ قبلی را با دلیلِ «جایگزین شد» و پیوند به جانشین ببندد، نه «دیگر مصداق ندارد».
    """
    if not challenger:
        return candidates, {}
    from mktcore.analysis.actions import KIND_CYCLE

    covered = {(c.customer_key, c.product_name): c.dedupe_key() for c in challenger}
    kept: list[OpportunityCandidate] = []
    replaced: dict[str, str] = {}
    for candidate in candidates:
        pair = (candidate.customer_key, candidate.product_name)
        if candidate.generator == ACTION_GENERATOR and candidate.kind == KIND_CYCLE and pair in covered:
            replaced[candidate.dedupe_key()] = covered[pair]
            continue
        kept.append(candidate)
    return kept + challenger, replaced


def active_replenish_version(*, business_slug: str = "default", db_path: Any = None) -> int | None:
    """نسخه‌ی اجرای فعالِ `replenish`، یا `None` — برای یادداشتِ اجرا (فعال ولی بی‌کارت ≠ غیرفعال)."""
    try:
        from mktcore.db.engine import session_scope
        from mktcore.db.lookup import resolve_business_id
        from mktcore.ml.replenish import promoted_due_table

        with session_scope(db_path) as session:
            business_id = resolve_business_id(session, business_slug)
            if business_id is None:
                return None
            active = promoted_due_table(session, business_id)
            return None if active is None else int(active[0].model_version)
    except Exception:  # noqa: BLE001 - نبودِ رجیستری نباید موتور را بخواباند
        return None


# فهرست مولدهای فعال. افزودن مولد تازه یعنی افزودن یک تابع به این تاپل؛
# موتور به نامِ مولد وابسته نیست.
GENERATORS = (generate_from_action_list, generate_from_expansion_gap)


def generate_candidates(
    bundle: Any, clean: pd.DataFrame, *, as_of: str | None = None,
) -> list[OpportunityCandidate]:
    """همه‌ی مولدهای فعال با یک تاریخِ مرجعِ مشترک (§۱۲ `generate(as_of)`).

    `as_of` = آخرین روزِ داده‌ی همین تحلیل (همان `engine._as_of`)؛ مولدهای امروزی آن
    را نادیده می‌گیرند (خروجی بیت‌به‌بیت)، مولدِ مدعی با آن بازپخش‌پذیر می‌شود.
    """
    out: list[OpportunityCandidate] = []
    for generator in GENERATORS:
        out.extend(generator(bundle, clean, as_of=as_of))
    return out


__all__ = [
    "ACTION_GENERATOR",
    "ACTION_GENERATOR_VERSION",
    "EXPANSION_GENERATOR",
    "EXPANSION_GENERATOR_VERSION",
    "GENERATORS",
    "KIND_EXPANSION",
    "KIND_WHALE_RELATIONSHIP",
    "WHALE_ACTIONS_FA",
    "WHALE_GENERATOR",
    "WHALE_GENERATOR_VERSION",
    "WHALE_MAX_PER_RUN",
    "WHALE_MIN_PROBABILITY_BP",
    "generate_candidates",
    "generate_whale_relationship",
    "generate_from_action_list",
    "generate_from_expansion_gap",
]
