"""فیلترهای نامزد فرصت — با ثبتِ صریحِ «اجرا نشد».

هر فیلتر یک یادداشت ثبت می‌کند، حتی وقتی کاری نمی‌کند. این عمدی و مهم است:
فیلتر «قابلیت تأمین» بدون داده‌ی موجودی چیزی را رد نمی‌کند، ولی اگر بی‌صدا رد
شود، کاربر گمان می‌کند موجودی بررسی شده است. پس با `filter_skip` و دلیل صریح
ثبت می‌شود و در UI هم همان‌طور دیده می‌شود.

فیلترها **رد نمی‌کنند مگر شواهد رد داشته باشند**. نبودِ داده دلیل رد نیست؛
دلیلِ برچسبِ صریح است.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from mktcore.catalog.normalize import normalize_product_name

from .contract import (
    FILTER_CODES,
    OUTCOME_BLOCK,
    OUTCOME_PASS,
    OUTCOME_SKIP,
    OpportunityCandidate,
    OpportunityFactorNote,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

logger = logging.getLogger("mktcore.opportunities.filters")

# کمترین ارزشی که ساختن یک فرصت را توجیه می‌کند. صفر و منفی معنا ندارند.
MIN_VALUE_DISPLAY = 1.0


def filter_eligibility(candidate: OpportunityCandidate, ctx: dict) -> OpportunityFactorNote:
    """شرایط پایه: مشتریِ شناسایی‌شده و ارزشِ مثبت."""
    if not candidate.customer_key:
        return OpportunityFactorNote(
            "eligibility", FILTER_CODES["eligibility"], OUTCOME_BLOCK,
            "این نامزد مشتری مشخصی ندارد، پس قابل واگذاری به کسی نیست.",
        )
    if candidate.expected_value_display < MIN_VALUE_DISPLAY:
        return OpportunityFactorNote(
            "eligibility", FILTER_CODES["eligibility"], OUTCOME_BLOCK,
            "ارزش مورد انتظار عملاً صفر است؛ صرف وقت تیم فروش را توجیه نمی‌کند.",
            value_text=str(round(candidate.expected_value_display)),
        )
    return OpportunityFactorNote(
        "eligibility", FILTER_CODES["eligibility"], OUTCOME_PASS,
        "مشتری مشخص است و ارزش مورد انتظار مثبت است.",
    )


def filter_consent(candidate: OpportunityCandidate, ctx: dict) -> OpportunityFactorNote:
    """رضایت تماس. «نامعلوم» رد نمی‌شود — با یادداشت عبور می‌کند.

    رد کردنِ «نامعلوم» یعنی حذف تقریباً همه‌ی مشتریان، چون داده‌ی رضایت در
    فایل فروش وجود ندارد. رد کردنِ «نه» اما قطعی است.
    """
    denied: set[str] = ctx.get("consent_denied") or set()
    if candidate.customer_key in denied:
        return OpportunityFactorNote(
            "consent", FILTER_CODES["consent"], OUTCOME_BLOCK,
            "این مشتری تماس بازاریابی را رد کرده است.",
        )
    if not ctx.get("has_consent_data"):
        return OpportunityFactorNote(
            "consent", FILTER_CODES["consent"], OUTCOME_SKIP,
            "داده‌ی رضایت تماس در دست نیست؛ این فرصت بدون بررسی رضایت ساخته شده است.",
        )
    return OpportunityFactorNote(
        "consent", FILTER_CODES["consent"], OUTCOME_PASS, "رضایت تماس ثبت شده است.",
    )


def filter_fatigue(candidate: OpportunityCandidate, ctx: dict) -> OpportunityFactorNote:
    """خستگی تماس: اگر همین اواخر با مشتری تماس گرفته‌ایم، فرصت را نمی‌سازیم.

    از همان outbox موجود می‌خواند — زیرساخت تازه‌ای لازم نیست.
    """
    recent: set[str] = ctx.get("recently_contacted") or set()
    window = ctx.get("fatigue_window_days")
    if candidate.customer_key in recent:
        return OpportunityFactorNote(
            "fatigue", FILTER_CODES["fatigue"], OUTCOME_BLOCK,
            f"در {window} روز گذشته با این مشتری تماس گرفته شده است.",
        )
    if window is None:
        return OpportunityFactorNote(
            "fatigue", FILTER_CODES["fatigue"], OUTCOME_SKIP,
            "تاریخچه‌ی تماس در دسترس نبود؛ خستگی تماس بررسی نشد.",
        )
    return OpportunityFactorNote(
        "fatigue", FILTER_CODES["fatigue"], OUTCOME_PASS,
        f"در {window} روز گذشته تماسی با این مشتری ثبت نشده است.",
    )


def filter_compatibility(candidate: OpportunityCandidate, ctx: dict) -> OpportunityFactorNote:
    """سازگاری کالا با مشتری.

    کسب‌وکار چنددامنه است، پس هیچ قاعده‌ی سازگاریِ hardcode‌شده‌ای وجود ندارد
    (فرضِ دامنه‌ای غلط، بدتر از نبودِ فیلتر است). تا وقتی کاربر قاعده تعریف
    نکند، این فیلتر صریحاً اجرا نمی‌شود.
    """
    rules = ctx.get("compatibility_rules")
    if not rules:
        return OpportunityFactorNote(
            "compatibility", FILTER_CODES["compatibility"], OUTCOME_SKIP,
            "قاعده‌ی سازگاری تعریف نشده است؛ تناسب کالا با مشتری بررسی نشد.",
        )
    blocked = rules.get(candidate.customer_key, set())
    if candidate.product_name and candidate.product_name in blocked:
        return OpportunityFactorNote(
            "compatibility", FILTER_CODES["compatibility"], OUTCOME_BLOCK,
            "این کالا طبق قواعد تعریف‌شده برای این مشتری مناسب نیست.",
        )
    return OpportunityFactorNote(
        "compatibility", FILTER_CODES["compatibility"], OUTCOME_PASS,
        "طبق قواعد تعریف‌شده، منعی برای این کالا وجود ندارد.",
    )


def filter_inventory(candidate: OpportunityCandidate, ctx: dict) -> OpportunityFactorNote:
    """قابلیت تأمین — بدون داده‌ی موجودی، **no-op صریح**.

    این فیلتر عمداً چیزی را رد نمی‌کند. اگر بی‌صدا عبور می‌داد، کاربر فرض
    می‌کرد موجودی بررسی شده و به کالای ناموجود پیشنهاد می‌داد.
    """
    if not ctx.get("has_inventory_data"):
        return OpportunityFactorNote(
            "inventory", FILTER_CODES["inventory"], OUTCOME_SKIP,
            "موجودی بررسی نشد — داده‌ی انبار در سیستم وجود ندارد.",
        )
    out_of_stock: set[str] = ctx.get("out_of_stock") or set()
    if candidate.product_name and candidate.product_name in out_of_stock:
        return OpportunityFactorNote(
            "inventory", FILTER_CODES["inventory"], OUTCOME_BLOCK,
            "این کالا موجود نیست.",
        )
    return OpportunityFactorNote(
        "inventory", FILTER_CODES["inventory"], OUTCOME_PASS, "کالا موجود است.",
    )


def filter_margin_floor(candidate: OpportunityCandidate, ctx: dict) -> OpportunityFactorNote:
    """کف حاشیه — به دو چیز نیاز دارد: بهای تمام‌شده **و** کفِ تعیین‌شده.

    داشتن ستون بها به‌تنهایی کافی نیست: تا وقتی معنای آن ستون (خرید؟ تمام‌شده؟
    با سربار؟) و کفِ قابل‌قبول از کاربر پرسیده نشده، محاسبه‌ی حاشیه حدس است.
    پس «قبول» ثبت نمی‌شود — «اجرا نشد» با دلیلِ درست ثبت می‌شود.
    """
    if not ctx.get("has_cost_data"):
        return OpportunityFactorNote(
            "margin_floor", FILTER_CODES["margin_floor"], OUTCOME_SKIP,
            "کف حاشیه بررسی نشد — بهای تمام‌شده در داده وجود ندارد، پس سود محاسبه‌شدنی نیست.",
        )
    floor_bp = ctx.get("margin_floor_bp")
    if floor_bp is None:
        return OpportunityFactorNote(
            "margin_floor", FILTER_CODES["margin_floor"], OUTCOME_SKIP,
            "بهای تمام‌شده در داده هست، ولی کف حاشیه‌ی قابل‌قبول تعیین نشده؛ "
            "پس این پیشنهاد از نظر حاشیه بررسی نشده است.",
        )
    margins = ctx.get("margin_by_product") or {}
    name = candidate.product_name
    # نامِ پیشنهاد ممکن است نمایشی باشد و دفتر کل نامِ نرمال‌شده را بشناسد؛
    # نبودِ تطبیق نباید به «حاشیه محاسبه نشده» ترجمه شود وقتی فقط شکلِ نوشتاری
    # فرق دارد.
    margin_bp = margins.get(name)
    if margin_bp is None and name:
        margin_bp = margins.get(normalize_product_name(name))
    if margin_bp is None:
        return OpportunityFactorNote(
            "margin_floor", FILTER_CODES["margin_floor"], OUTCOME_SKIP,
            "حاشیه‌ی این کالا محاسبه نشده است.",
        )
    if margin_bp < floor_bp:
        return OpportunityFactorNote(
            "margin_floor", FILTER_CODES["margin_floor"], OUTCOME_BLOCK,
            "حاشیه‌ی این پیشنهاد زیر کف تعیین‌شده است.",
            value_text=f"{margin_bp / 100:.1f}٪",
        )
    return OpportunityFactorNote(
        "margin_floor", FILTER_CODES["margin_floor"], OUTCOME_PASS,
        "حاشیه‌ی این پیشنهاد بالای کف تعیین‌شده است.",
        value_text=f"{margin_bp / 100:.1f}٪",
    )


def filter_uplift(candidate: OpportunityCandidate, ctx: dict) -> OpportunityFactorNote:
    """حذفِ گروه‌هایی که **اندازه‌گیری نشان داده** تماس با آن‌ها بی‌فایده است.

    با کانال انبوه، هزینه‌ی هر پیام نزدیک صفر است — ولی حوصله‌ی مشتری نه. هر
    پیامِ بی‌اثر کمی از آن را خرج می‌کند و کانال را فرسوده. پس دانستن اینکه به
    چه کسی **نباید** پیام داد، همان‌قدر ارزش دارد که دانستن اینکه به چه کسی باید.

    شرط سخت‌گیرانه است: کل بازه‌ی اطمینان باید ≤ صفر باشد. «احتمالاً بی‌فایده»
    کافی نیست، چون حذفِ یک گروه از تماس، فروشِ ازدست‌رفته‌ی بالقوه است.
    """
    table = ctx.get("uplift_table")
    if table is None:
        return OpportunityFactorNote(
            "uplift", FILTER_CODES["uplift"], OUTCOME_SKIP,
            "هنوز داده‌ی آزمایشی وجود ندارد؛ اثر تماس با این گروه اندازه‌گیری نشده است.",
        )

    state = ctx.get("lifecycle_of", {}).get(candidate.customer_key)
    cell = table.is_useless(candidate.kind, state)
    if cell is not None:
        return OpportunityFactorNote(
            "uplift", FILTER_CODES["uplift"], OUTCOME_BLOCK,
            "اندازه‌گیری نشان داده تماس با این گروه نتیجه را بهتر نمی‌کند؛ "
            "پیام فقط حوصله‌ی مشتری را خرج می‌کند.",
            value_text=f"{round(cell.raw_uplift * 100, 1)} واحد درصد",
        )

    uplift, basis = table.lookup(candidate.kind, state)
    if basis == "none":
        return OpportunityFactorNote(
            "uplift", FILTER_CODES["uplift"], OUTCOME_SKIP,
            "برای این ترکیبِ اقدام و حالت مشتری، داده‌ی آزمایشی کافی وجود ندارد.",
        )
    return OpportunityFactorNote(
        "uplift", FILTER_CODES["uplift"], OUTCOME_PASS,
        "اندازه‌گیری نشان می‌دهد تماس با این گروه اثر مثبت دارد.",
        value_text=f"{round(uplift * 100, 1)} واحد درصد",
    )


def filter_conflict(candidate: OpportunityCandidate, ctx: dict) -> OpportunityFactorNote:
    """تداخل: یک مشتری نباید هم‌زمان با چند پیام متضاد هدف گرفته شود."""
    cap = ctx.get("per_customer_open_cap", 3)
    counts: dict[str, int] = ctx.setdefault("_customer_counts", {})
    used = counts.get(candidate.customer_key, 0)
    if used >= cap:
        return OpportunityFactorNote(
            "conflict", FILTER_CODES["conflict"], OUTCOME_BLOCK,
            f"این مشتری از قبل {used} فرصت باز دارد (سقف {cap}).",
        )
    counts[candidate.customer_key] = used + 1
    return OpportunityFactorNote(
        "conflict", FILTER_CODES["conflict"], OUTCOME_PASS,
        f"شمار فرصت‌های باز این مشتری زیر سقف {cap} است.",
    )


def filter_offer_policy(candidate: OpportunityCandidate, ctx: dict) -> OpportunityFactorNote:
    """سیاست آفر: تخفیف پیشنهادی توسط سیستم تولید نمی‌شود.

    هیچ‌جای این موتور تخفیف پیشنهاد نمی‌دهد، چون حساسیت قیمت اندازه‌گیری نشده و
    عددِ حدسی روی تخفیف مستقیماً درآمد را می‌سوزاند.
    """
    return OpportunityFactorNote(
        "offer_policy", FILTER_CODES["offer_policy"], OUTCOME_SKIP,
        "هیچ تخفیفی پیشنهاد نشده است؛ حساسیت قیمت اندازه‌گیری نشده و عدد حدسی مجاز نیست.",
    )


# ترتیب مهم است: ارزان‌ترین و قطعی‌ترین ردها اول، تداخل آخر (چون حالت دارد).
FILTER_CHAIN: tuple[Callable[[OpportunityCandidate, dict], OpportunityFactorNote], ...] = (
    filter_eligibility,
    filter_consent,
    filter_fatigue,
    filter_compatibility,
    filter_inventory,
    filter_margin_floor,
    filter_offer_policy,
    filter_uplift,
    filter_conflict,
)


def apply_filters(
    candidates: Iterable[OpportunityCandidate], ctx: dict,
) -> tuple[list[OpportunityCandidate], list[OpportunityCandidate]]:
    """اجرای زنجیره روی نامزدها → (پذیرفته‌شده‌ها، ردشده‌ها).

    نامزدها **به ترتیب ارزش نزولی** پردازش می‌شوند تا وقتی سقفِ تداخل می‌خورد،
    ارزشمندترین فرصت‌ها بمانند نه تصادفی‌ها.
    """
    ordered = sorted(candidates, key=lambda c: -c.expected_value_display)
    accepted: list[OpportunityCandidate] = []
    rejected: list[OpportunityCandidate] = []
    for candidate in ordered:
        for check in FILTER_CHAIN:
            note = check(candidate, ctx)
            candidate.add_factor(note)
            if note.blocking:
                break
        (rejected if candidate.blocked_by else accepted).append(candidate)
    return accepted, rejected


__all__ = [
    "FILTER_CHAIN",
    "MIN_VALUE_DISPLAY",
    "apply_filters",
]
