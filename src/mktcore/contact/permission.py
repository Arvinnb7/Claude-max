"""دروازه‌ی مجوز تماس — یک تصمیم، در یک جا.

پیش از این، سه مسیرِ تماس سه تصمیمِ متفاوت می‌گرفتند:

| مسیر | چه بررسی می‌کرد |
|---|---|
| موتور فرصت (`filter_fatigue`) | تماس اخیر — ولی فقط برای **ساختِ فرصت** |
| `run_cycle_scan` | هفت روز dedupe، فقط برای یک نوع پیام |
| `POST /api/sms/send` | **هیچ‌چیز** |

نتیجه‌ی این پراکندگی یک شکافِ واقعی بود: مسیرِ ارسال می‌توانست به عضوِ
**گروه کنترل** پیام بدهد و آزمایش را بی‌صدا نابود کند — بی‌صدا، چون هیچ‌جا ثبت
نمی‌شد که با کنترل تماس گرفته شده، پس خرابی بعداً هم قابل تشخیص نبود.

این ماژول **تابع خالص** است: مجموعه‌های ورودی را می‌گیرد و تصمیم می‌دهد، بدون
هیچ I/O. بارگذاری از دیتابیس در `register.py` جدا نگه داشته شده — همان
جداسازی‌ای که `uplift/empirical.py` و `uplift/snapshots.py` دارند.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from mktcore.opportunities.contract import (
    FILTER_CODES,
    OUTCOME_BLOCK,
    OUTCOME_PASS,
    OUTCOME_SKIP,
    OpportunityFactorNote,
)

# پنجره‌ی پیش‌فرضِ خستگی تماس. عددِ موتور فرصت (۱۴) مرجع است، نه عددِ
# `run_cycle_scan` (۷)؛ آن مسیر پنجره‌ی خودش را صریح پاس می‌دهد تا رفتار و
# تستِ فعلی‌اش دست‌نخورده بماند.
DEFAULT_FATIGUE_WINDOW_DAYS = 14

# دلیل‌ها. `consent` و `fatigue` از واژگانِ موجودِ فیلترها بازاستفاده می‌شوند تا
# کاربر دو نامِ متفاوت برای یک چیز نبیند.
REASON_CONTROL = "control_arm"
REASON_CONSENT = "consent"
REASON_FATIGUE = "fatigue"

# ترتیبِ گزارشِ دلیل، بر پایه‌ی **ماندگاری** نه شدت:
#   انصراف هرگز منقضی نمی‌شود · عضویت در کنترل با بسته‌شدن کمپین تمام می‌شود ·
#   خستگی چند روزه است.
# پس اگر مشتری هم منصرف شده و هم در کنترل است، «منصرف» گزارش می‌شود — چون بعد از
# بسته‌شدن کمپین هم همچنان نباید با او تماس گرفت.
REASON_PRIORITY = (REASON_CONSENT, REASON_CONTROL, REASON_FATIGUE)

REASON_LABELS_FA = {
    REASON_CONTROL: "عضو گروه کنترل آزمایش",
    REASON_CONSENT: FILTER_CODES["consent"],
    REASON_FATIGUE: FILTER_CODES["fatigue"],
}

_CONTROL_DETAIL_FA = (
    "این مشتری در گروه کنترلِ یک آزمایشِ فعال است؛ تماس با او نتیجه‌ی آزمایش را "
    "از بین می‌برد."
)
# متنِ انصراف عیناً همان چیزی است که `filter_consent` از قبل می‌گفت.
_CONSENT_DETAIL_FA = "این مشتری تماس بازاریابی را رد کرده است."


@dataclass(frozen=True)
class ContactGate:
    """عکسِ لحظه‌ای از «با چه کسی نباید تماس گرفت».

    مجموعه‌ها یک‌بار ساخته می‌شوند و N بار پرس‌وجو — نه یک query به‌ازای مشتری.
    همان الگوی `build_context` که از قبل در موتور فرصت هست.
    """

    control_arm: frozenset[str] = frozenset()
    opted_out: frozenset[str] = frozenset()
    opted_out_phones: frozenset[str] = frozenset()
    recently_contacted: frozenset[str] = frozenset()
    fatigue_window_days: int | None = None
    # آیا دفترِ انصراف در دسترس بود؟ اگر نه، «بررسی نشد» گزارش می‌شود نه «قبول».
    has_suppression_data: bool = False
    # آیا وضعیت بازوی کنترل خوانده شد؟ همان قاعده.
    has_campaign_data: bool = False

    def reason_for(self, customer_key: str | None, *, phone: str | None = None) -> str | None:
        """نخستین دلیلِ ممنوعیت به‌ترتیب ماندگاری، یا `None` اگر مجاز است."""
        key = str(customer_key) if customer_key is not None else None
        for reason in REASON_PRIORITY:
            if reason == REASON_CONSENT:
                if key is not None and key in self.opted_out:
                    return reason
                if phone and phone in self.opted_out_phones:
                    return reason
            elif reason == REASON_CONTROL:
                if key is not None and key in self.control_arm:
                    return reason
            elif reason == REASON_FATIGUE:
                if key is not None and key in self.recently_contacted:
                    return reason
        return None

    def check(self, customer_key: str | None, *, phone: str | None = None) -> OpportunityFactorNote:
        """تصمیم به‌صورت یک `OpportunityFactorNote` — واژگانِ موجودِ پروژه."""
        reason = self.reason_for(customer_key, phone=phone)
        if reason is not None:
            return OpportunityFactorNote(
                reason, REASON_LABELS_FA[reason], OUTCOME_BLOCK, self._detail_for(reason),
            )
        unchecked = self.unchecked_reasons()
        if unchecked:
            names = "، ".join(REASON_LABELS_FA[r] for r in unchecked)
            return OpportunityFactorNote(
                "contact_permission", "مجوز تماس", OUTCOME_SKIP,
                f"تماس منعی نداشت، ولی این بررسی‌ها انجام نشد: {names}.",
            )
        return OpportunityFactorNote(
            "contact_permission", "مجوز تماس", OUTCOME_PASS,
            "نه در فهرست لغو تماس است، نه در گروه کنترل، و تماس اخیری هم ندارد.",
        )

    def unchecked_reasons(self) -> tuple[str, ...]:
        """بررسی‌هایی که داده‌شان نبود. «بررسی نشد» هرگز «قبول» ثبت نمی‌شود."""
        missing: list[str] = []
        if not self.has_suppression_data:
            missing.append(REASON_CONSENT)
        if not self.has_campaign_data:
            missing.append(REASON_CONTROL)
        if self.fatigue_window_days is None:
            missing.append(REASON_FATIGUE)
        return tuple(missing)

    def _detail_for(self, reason: str) -> str:
        if reason == REASON_CONTROL:
            return _CONTROL_DETAIL_FA
        if reason == REASON_CONSENT:
            return _CONSENT_DETAIL_FA
        return f"در {self.fatigue_window_days} روز گذشته با این مشتری تماس گرفته شده است."

    def partition(
        self,
        items: Iterable[Any],
        *,
        key: Callable[[Any], str | None],
        phone: Callable[[Any], str | None] | None = None,
    ) -> GateResult:
        """جدا کردن مجاز از مسدود، همراه با شمارشِ دلیل‌ها.

        `key` و `phone` استخراج‌کننده‌اند تا این تابع برای `Recipient`،
        `CampaignMember` و نامزدِ فرصت یکسان کار کند.
        """
        allowed: list[Any] = []
        blocked: list[tuple[Any, str]] = []
        for item in items:
            reason = self.reason_for(key(item), phone=phone(item) if phone else None)
            if reason is None:
                allowed.append(item)
            else:
                blocked.append((item, reason))
        return GateResult(allowed=allowed, blocked=blocked, gate=self)


@dataclass
class GateResult:
    """نتیجه‌ی غربال، با گزارشِ صریح. حذفِ بی‌صدا ممنوع است."""

    allowed: list[Any] = field(default_factory=list)
    blocked: list[tuple[Any, str]] = field(default_factory=list)
    gate: ContactGate | None = None

    @property
    def suppressed_count(self) -> int:
        return len(self.blocked)

    def counts_by_reason(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for _item, reason in self.blocked:
            counts[reason] = counts.get(reason, 0) + 1
        return counts

    def to_dict(self) -> dict:
        """کلیدهای فارسیِ افزودنی برای پاسخ API."""
        counts = self.counts_by_reason()
        out: dict = {
            "مسدودشده": self.suppressed_count,
            "دلایل_مسدودی": [
                {"دلیل": REASON_LABELS_FA[reason], "تعداد": count}
                for reason, count in sorted(counts.items(), key=lambda kv: -kv[1])
            ],
        }
        unchecked = self.gate.unchecked_reasons() if self.gate else ()
        if unchecked:
            out["بررسی‌نشده"] = [REASON_LABELS_FA[r] for r in unchecked]
        return out

    def note_fa(self) -> str | None:
        """یک جمله برای کاربر — یا `None` وقتی چیزی مسدود نشده."""
        if not self.blocked:
            return None
        parts = [
            f"{REASON_LABELS_FA[reason]}: {count}"
            for reason, count in sorted(self.counts_by_reason().items(), key=lambda kv: -kv[1])
        ]
        return f"{self.suppressed_count} مخاطب از فهرست حذف شد ({' · '.join(parts)})."


__all__ = [
    "DEFAULT_FATIGUE_WINDOW_DAYS",
    "REASON_CONSENT",
    "REASON_CONTROL",
    "REASON_FATIGUE",
    "REASON_LABELS_FA",
    "REASON_PRIORITY",
    "ContactGate",
    "GateResult",
]
