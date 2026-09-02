"""قرارداد مشترک مولدها و فیلترها.

هر مولد یک `OpportunityCandidate` می‌دهد و هر فیلتر یک `OpportunityFactorNote`
برمی‌گرداند. نتیجه: هر فرصتِ ذخیره‌شده یک زنجیره‌ی کامل از شواهد دارد — چرا
ساخته شد و از کدام بررسی‌ها گذشت یا نگذشت.

قاعده‌ای که به‌عمد سخت‌گیرانه است: فیلترهایی که به‌دلیل **نبودِ داده** کاری
نمی‌کنند، «قبول» ثبت نمی‌شوند؛ با `filter_skip` و دلیل صریح ثبت می‌شوند. وگرنه
کاربر گمان می‌کند موجودی یا حاشیه بررسی شده، در حالی که اصلاً داده‌اش نبوده.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

# نوعِ ارزشِ فرصت. دو تای اول ریالی‌اند؛ سومی عمداً عدد ندارد.
#
# **چرا یک نوعِ بدون عدد لازم است.** اقدامِ رابطه‌ای (§۱۸.۵) خدمت است نه فروش:
# «تماس آشناسازی» درآمدِ مشخصی ندارد و هر عددی برایش بگذاریم، عددِ ساختگی است.
# سند هم در نمونه‌ی خروجی روزانه (§۳۸) این گروه را تنها گروهی می‌کند که **فقط
# تعداد مشتری** دارد، نه مبلغ. پس به‌جای گذاشتنِ صفر یا حدس، نوعش را صریح
# می‌کنیم تا هر لایه‌ای بداند اینجا عدد نباید نشان داده شود.
VALUE_RELATIONSHIP = "بدون عدد ریالی"

# نتیجه‌ی یک فیلتر
OUTCOME_EVIDENCE = "evidence"
OUTCOME_PASS = "filter_pass"
OUTCOME_SKIP = "filter_skip"      # فیلتر اجرا نشد (داده‌اش نیست) — صریح
OUTCOME_BLOCK = "filter_block"    # نامزد رد شد

FILTER_CODES = {
    "eligibility": "شرایط پایه (مشتری و ارزش معتبر)",
    "consent": "رضایت تماس",
    "fatigue": "خستگی تماس (تماس اخیر)",
    "compatibility": "سازگاری کالا با مشتری",
    "inventory": "قابلیت تأمین (موجودی)",
    "margin_floor": "کف حاشیه‌ی سود",
    "conflict": "تداخل با فرصت باز دیگر",
    "offer_policy": "سیاست آفر و تخفیف",
    "uplift": "اثر اندازه‌گیری‌شده‌ی تماس",
    "operator_capacity": "ظرفیت پیگیری تیم",
}


@dataclass
class OpportunityFactorNote:
    """یک شاهد یا نتیجه‌ی یک فیلتر روی یک نامزد."""

    code: str
    label_fa: str
    outcome: str
    detail_fa: str | None = None
    value_text: str | None = None

    @property
    def blocking(self) -> bool:
        return self.outcome == OUTCOME_BLOCK


@dataclass
class OpportunityCandidate:
    """نامزد فرصت — خروجی یک مولد، پیش از فیلتر و ماندگارسازی.

    `expected_value_display` در **واحد نمایش** است (همان که تحلیل تولید می‌کند)؛
    تبدیل به ریالِ صحیح فقط در مرز نوشتن انجام می‌شود، دقیقاً مثل خطوط فروش.
    """

    kind: str
    generator: str
    generator_version: int
    customer_key: str
    title_fa: str
    action_fa: str
    reason_fa: str
    expected_value_display: float
    value_kind: str
    product_name: str | None = None
    message_fa: str | None = None
    probability: float | None = None
    confidence: str | None = None
    owner_hint: str | None = None
    phone: str | None = None
    due_date: str | None = None
    expires_at: str | None = None
    # پیشنهادِ تخفیف (§۲۰.۳) — فقط `filter_offer_policy` پرش می‌کند. `None` یعنی
    # «بررسی نشد»؛ صفر یعنی تصمیمِ صریحِ «بدون تخفیف». هیچ‌کدام وارد `fields`ِ
    # فرصت نمی‌شوند؛ در `opportunity_offers` می‌نشینند تا تأییدِ انسان با
    # اجرای بعدی پاک نشود.
    suggested_discount_bp: int | None = None
    offer_tier: str | None = None
    offer_margin_bp: int | None = None
    offer_floor_bp: int | None = None
    factors: list[OpportunityFactorNote] = field(default_factory=list)

    def dedupe_key(self) -> str:
        """کلید یکتای «همین فرصت».

        عمداً شامل ارزش یا تاریخ **نیست**: اگر ارزش کمی جابه‌جا شود، این باید
        همان فرصت بماند و تازه‌سازی شود، نه اینکه فرصتِ دومی ساخته شود و کاربر
        دو بار همان کار را ببیند.
        """
        raw = f"{self.generator}|{self.kind}|{self.customer_key}|{self.product_name or ''}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:48]

    def add_factor(self, note: OpportunityFactorNote) -> None:
        self.factors.append(note)

    @property
    def blocked_by(self) -> OpportunityFactorNote | None:
        for note in self.factors:
            if note.blocking:
                return note
        return None


__all__ = [
    "VALUE_RELATIONSHIP",
    "FILTER_CODES",
    "OUTCOME_BLOCK",
    "OUTCOME_EVIDENCE",
    "OUTCOME_PASS",
    "OUTCOME_SKIP",
    "OpportunityCandidate",
    "OpportunityFactorNote",
]
