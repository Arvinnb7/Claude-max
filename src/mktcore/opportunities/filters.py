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
    VALUE_RELATIONSHIP,
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
    if candidate.value_kind == VALUE_RELATIONSHIP:
        # این نوع فرصت عمداً عدد ریالی ندارد (§۱۸.۵)؛ سنجیدنش با آستانه‌ی ارزش،
        # یعنی حذفِ همان چیزی که قرار بود بدون عدد باشد.
        return OpportunityFactorNote(
            "eligibility", FILTER_CODES["eligibility"], OUTCOME_PASS,
            "این فرصت عمداً عدد ریالی ندارد؛ ارزشش رابطه است، نه یک سفارش مشخص.",
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


def _product_margin_bp(candidate: OpportunityCandidate, ctx: dict) -> int | None:
    """حاشیه‌ی کالای این پیشنهاد، با هر نامی که ممکن است در پیشنهاد بیاید.

    نامِ پیشنهاد ممکن است نمایشی باشد و دفتر کل نامِ نرمال‌شده را بشناسد؛ نبودِ
    تطبیق نباید به «حاشیه محاسبه نشده» ترجمه شود وقتی فقط شکلِ نوشتاری فرق
    دارد. مشترک بین کف حاشیه و نردبان تخفیف تا دو تعریف از «حاشیه‌ی کالا» از هم
    فاصله نگیرند.
    """
    margins = ctx.get("margin_by_product") or {}
    name = candidate.product_name
    margin_bp = margins.get(name)
    if margin_bp is None and name:
        margin_bp = margins.get(normalize_product_name(name))
    return None if margin_bp is None else int(margin_bp)


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
    margin_bp = _product_margin_bp(candidate, ctx)
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


# سقفِ اقدامِ رابطه‌ای به‌ازای هر مشتری. عمداً ۱ است: دو «تماس آشناسازی» در یک
# زمان بی‌معناست، ولی یک اقدامِ خدمتی با یک یادآوری چرخه تداخل ندارد.
RELATIONSHIP_CAP = 1


def filter_conflict(candidate: OpportunityCandidate, ctx: dict) -> OpportunityFactorNote:
    """تداخل: یک مشتری نباید هم‌زمان با چند پیام متضاد هدف گرفته شود.

    شمارش **به‌تفکیک نوعِ ارزش** انجام می‌شود: فرصت‌های فروشی با هم رقابت
    می‌کنند، ولی اقدامِ رابطه‌ای (که پیشنهاد فروش نیست) نباید جای یک یادآوری
    چرخه را بگیرد — و برعکس.
    """
    relationship = candidate.value_kind == VALUE_RELATIONSHIP
    bucket = "relationship" if relationship else "money"
    cap = RELATIONSHIP_CAP if relationship else ctx.get("per_customer_open_cap", 3)
    counts: dict[tuple[str, str], int] = ctx.setdefault("_customer_counts", {})
    key = (candidate.customer_key, bucket)
    used = counts.get(key, 0)
    if used >= cap:
        return OpportunityFactorNote(
            "conflict", FILTER_CODES["conflict"], OUTCOME_BLOCK,
            f"این مشتری از قبل {used} فرصت باز از همین نوع دارد (سقف {cap}).",
        )
    counts[key] = used + 1
    return OpportunityFactorNote(
        "conflict", FILTER_CODES["conflict"], OUTCOME_PASS,
        f"شمار فرصت‌های باز این مشتری زیر سقف {cap} است.",
    )


# ------------------------------------------------------------ نردبان تخفیف (§۲۰.۳)
_BP = 10_000

_NO_LADDER_NOTE_FA = (
    "هیچ تخفیفی پیشنهاد نشده است؛ نردبانِ تخفیف تعیین نشده و عدد حدسی مجاز نیست."
)


def post_discount_margin_bp(margin_bp: int, discount_bp: int) -> int | None:
    """حاشیه‌ی **پس از** تخفیف، به پایه‌ی هزارم.

    قیمت ۱۰۰، بها ۷۶ ⇒ حاشیه ۲۴٪. با ۵٪ تخفیف قیمت ۹۵ می‌شود و سود ۱۹ ⇒
    حاشیه‌ی واقعی ۱۹/۹۵ = ۲۰٪، نه ۲۴ − ۵ = ۱۹٪. فرمول: (m − d) / (1 − d).
    این تفاوتِ کوچک دقیقاً روی مرزِ کف تصمیم را عوض می‌کند، پس با تستِ مرزی پین
    شده است.
    """
    if discount_bp >= _BP:
        return None
    return round((margin_bp - discount_bp) * _BP / (_BP - discount_bp))


def pick_rung(
    ladder: tuple[int, ...] | list[int], margin_bp: int, floor_bp: int,
) -> int | None:
    """**کوچک‌ترین** پله‌ای که حاشیه‌ی پس از تخفیف را روی کف نگه دارد.

    §۲۰.۱: «کمترین مشوقِ مؤثر». پله‌های بالاتر تا یادگیری با گروه کنترل موکول‌اند.
    """
    for rung in sorted(int(r) for r in ladder):
        post = post_discount_margin_bp(margin_bp, rung)
        if post is not None and post >= floor_bp:
            return rung
    return None


OFFER_BASIS_NAME = "name"          # کالا یا دسته، با کلیدِ نام
OFFER_BASIS_CUSTOMER = "customer"  # سبدِ خودِ مشتری


def _offer_margin_bp(candidate: OpportunityCandidate, ctx: dict) -> tuple[int | None, str]:
    """مبنای حاشیه برای سقفِ تخفیف: کالا/دسته اگر نامش هست، وگرنه سبدِ خودِ مشتری.

    فرصتِ بی‌کالا (نجات از ریزش، بازگشت) تخفیف را روی هرچه مشتری بخرد اعمال
    می‌کند؛ پس مبنای درست حاشیه‌ی وزنیِ خریدهای همان مشتری است — نه یک عدد
    سراسری. مبنا و کلیدش روی نامزد می‌ماند تا **تأیید همان را بازخوانی کند**:
    فرصتِ «شکاف دسته» `product_id` ندارد ولی نامِ دسته دارد؛ بازخوانی با
    `product_id` آن را به مبنای مشتری می‌انداخت و تأییدِ درست را رد می‌کرد.
    """
    if candidate.product_name:
        margin = _product_margin_bp(candidate, ctx)
        candidate.offer_margin_basis = OFFER_BASIS_NAME
        candidate.offer_margin_key = candidate.product_name
        return margin, "بر پایه‌ی حاشیه‌ی کالا"
    margin = (ctx.get("customer_margin_bp_of") or {}).get(candidate.customer_key)
    candidate.offer_margin_basis = OFFER_BASIS_CUSTOMER
    candidate.offer_margin_key = None
    return (None if margin is None else int(margin)), "بر پایه‌ی حاشیه‌ی خریدهای خودِ مشتری"


def filter_offer_policy(candidate: OpportunityCandidate, ctx: dict) -> OpportunityFactorNote:
    """سیاست آفر: نردبانِ تخفیفِ قاعده‌مند با کفِ حاشیه‌ی سخت — §۲۰.۳.

    ## قاعده‌ها، به ترتیب

    1. **نردبان تعیین‌نشده ⇒ «بررسی نشد».** دقیقاً رفتارِ پیش از این گام: هیچ
       تخفیفی پیشنهاد نمی‌شود و هیچ عددی حدس زده نمی‌شود.
    2. **اقدامِ رابطه‌ای هرگز تخفیف نمی‌گیرد** (§۱۸.۵) — این مشتریان را به انتظارِ
       تخفیف عادت ندهید.
    3. **مشتریِ تمام‌قیمت‌خر ⇒ بدون تخفیف** (§۲۰.۳ بند ۲). طبقه‌ی میانی هم در گامِ
       اول بدون تخفیف؛ فقط طبقه‌ی «وابسته به تخفیف» کاندیدِ پله است.
    4. **طبقه‌ی نامعلوم / بها نیست / کف نیست / حاشیه‌ی کالا نیست ⇒ «بررسی نشد».**
       نه «قبول»، نه رد.
    5. **کوچک‌ترین** پله‌ای که حاشیه‌ی پس از تخفیف ≥ کف بماند؛ اگر هیچ پله‌ای نماند
       ⇒ بدون تخفیف، با دلیل.

    این فیلتر **هرگز رد نمی‌کند** و به `score_rial` دست نمی‌زند: تخفیف فقط
    **پیشنهاد** است و بدون تأییدِ انسان (`opportunity_offers.status == approved`)
    هیچ‌جا ارسال نمی‌شود.
    """
    code, label = "offer_policy", FILTER_CODES["offer_policy"]
    ladder = ctx.get("offer_ladder_bp")
    if not ladder:
        return OpportunityFactorNote(code, label, OUTCOME_SKIP, _NO_LADDER_NOTE_FA)

    def _no_discount(reason_fa: str, *, tier: str | None) -> OpportunityFactorNote:
        candidate.suggested_discount_bp = 0
        candidate.offer_tier = tier
        return OpportunityFactorNote(code, label, OUTCOME_PASS, reason_fa, value_text="0٪")

    if candidate.value_kind == VALUE_RELATIONSHIP:
        return _no_discount(
            "بدون تخفیف — اقدامِ رابطه‌ای عمداً بی‌آفر است (§۱۸.۵).", tier=None,
        )

    tier = (ctx.get("full_price_tier_of") or {}).get(candidate.customer_key)
    if tier is None:
        return OpportunityFactorNote(
            code, label, OUTCOME_SKIP,
            "طبقه‌ی خریدِ تمام‌قیمتِ این مشتری نامعلوم است (ستون تخفیف یا خطوطِ کافی "
            "نیست)؛ پیشنهادی داده نشد.",
        )
    if tier == "high":
        return _no_discount(
            "این مشتری تمام‌قیمت می‌خرد؛ بدون تخفیف (§۲۰.۳ بند ۲).", tier=tier,
        )
    if tier != "low":
        return _no_discount("طبقه‌ی میانی؛ در گامِ اول بدون تخفیف.", tier=tier)

    if not ctx.get("has_cost_data"):
        return OpportunityFactorNote(
            code, label, OUTCOME_SKIP,
            "بهای تمام‌شده در داده نیست؛ سقفِ تخفیف محاسبه‌شدنی نیست، پس پیشنهادی داده نشد.",
        )
    floor_bp = ctx.get("margin_floor_bp")
    if floor_bp is None:
        return OpportunityFactorNote(
            code, label, OUTCOME_SKIP,
            "کف حاشیه تعیین نشده است؛ بدون کف هیچ پله‌ای پیشنهاد نمی‌شود.",
        )
    margin_bp, basis_fa = _offer_margin_bp(candidate, ctx)
    if margin_bp is None:
        return OpportunityFactorNote(
            code, label, OUTCOME_SKIP,
            "حاشیه‌ی این کالا محاسبه نشده است؛ پیشنهادی داده نشد."
            if candidate.product_name else
            "این فرصت کالای مشخصی ندارد و حاشیه‌ی خریدهای خودِ مشتری هم محاسبه‌شدنی "
            "نیست (پوششِ بها ناقص)؛ پیشنهادی داده نشد.",
        )

    candidate.offer_margin_bp = margin_bp
    candidate.offer_floor_bp = int(floor_bp)
    rung = pick_rung(ladder, margin_bp, int(floor_bp))
    if rung is None:
        return _no_discount(
            f"هیچ پله‌ای کفِ حاشیه ({floor_bp / 100:g}٪) را حفظ نمی‌کند "
            f"(حاشیه‌ی کالا {margin_bp / 100:g}٪)؛ بدون تخفیف.",
            tier=tier,
        )
    candidate.suggested_discount_bp = rung
    candidate.offer_tier = tier
    post = post_discount_margin_bp(margin_bp, rung)
    return OpportunityFactorNote(
        code, label, OUTCOME_PASS,
        f"پیشنهادِ {rung / 100:g}٪ تخفیف — کوچک‌ترین پله‌ای که حاشیه‌ی پس از تخفیف "
        f"({post / 100:g}٪، {basis_fa}) بالای کف ({floor_bp / 100:g}٪) می‌ماند. تا تأییدِ "
        "انسان ارسال نمی‌شود.",
        value_text=f"{rung / 100:g}٪",
    )


# ترتیب مهم است: ارزان‌ترین و قطعی‌ترین ردها اول، تداخل آخر (چون حالت دارد).
def filter_operator_capacity(
    candidate: OpportunityCandidate, ctx: dict,
) -> OpportunityFactorNote:
    """ظرفیت پیگیری تیم (§۲۵).

    ## چرا این فیلتر لازم است

    صندوقی با ۳۰۰ فرصت وقتی تیم روزی ۲۰ تماس می‌گیرد، عملاً یک صندوقِ ۲۰تایی
    است به‌اضافه‌ی ۲۸۰ ردیفِ نویز. بدترش این است که کاربر نمی‌داند کدام ۲۰تا،
    پس از بالای فهرست شروع می‌کند و بقیه بی‌صدا کهنه می‌شوند.

    ## چرا بدون تنظیم، «قبول» ثبت نمی‌شود

    اگر کاربر ظرفیت را نگفته باشد، هیچ عددی حدس زده نمی‌شود — ولی «بررسی نشد»
    هم ثبت می‌شود تا کسی گمان نکند ظرفیت لحاظ شده است. همان قاعده‌ی
    `filter_margin_floor`.

    ⚠️ **این فیلتر باید آخرِ زنجیره باشد.** شمارشش فقط وقتی درست است که همه‌ی
    فیلترهای قبلی پاس شده باشند؛ وگرنه ظرفیت را با نامزدهایی پر می‌کند که
    اصلاً پذیرفته نمی‌شوند.
    """
    capacity = ctx.get("daily_capacity")
    if capacity is None:
        return OpportunityFactorNote(
            "operator_capacity", FILTER_CODES["operator_capacity"], OUTCOME_SKIP,
            "ظرفیت پیگیری تیم بررسی نشد — عددش تنظیم نشده است. "
            "با تنظیمش، فرصت‌های بیش از توانِ پیگیری کنار گذاشته می‌شوند.",
        )
    # اقدامِ رابطه‌ای سهمیه‌ی جدا دارد و نباید جای تماس‌های فروش را بگیرد؛
    # شمارشِ مشترک یعنی هر اقدام رابطه‌ای یک فرصتِ ریالی را بیرون می‌اندازد.
    bucket = "relationship" if candidate.value_kind == VALUE_RELATIONSHIP else "money"
    used: dict[str, int] = ctx.setdefault("_capacity_used", {})
    taken = used.get(bucket, 0)
    if taken >= capacity:
        return OpportunityFactorNote(
            "operator_capacity", FILTER_CODES["operator_capacity"], OUTCOME_BLOCK,
            f"ظرفیت پیگیری تیم ({capacity} مورد) پر شد؛ این فرصت کم‌ارزش‌تر از "
            "مواردی است که جا گرفتند.",
            value_text=str(capacity),
        )
    used[bucket] = taken + 1
    return OpportunityFactorNote(
        "operator_capacity", FILTER_CODES["operator_capacity"], OUTCOME_PASS,
        f"در ظرفیت پیگیری تیم جا دارد ({taken + 1} از {capacity}).",
    )


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
    # ⚠️ ظرفیت **آخر** می‌آید: شمارشش فقط وقتی معنا دارد که بقیه پاس شده باشند.
    filter_operator_capacity,
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
    "OFFER_BASIS_CUSTOMER",
    "OFFER_BASIS_NAME",
    "pick_rung",
    "post_discount_margin_bp",
    "filter_operator_capacity",
    "MIN_VALUE_DISPLAY",
    "RELATIONSHIP_CAP",
    "apply_filters",
]
