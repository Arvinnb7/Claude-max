"""قرارداد خروجی ساختاریافته‌ی استراتژی (Pydantic) — متن فارسی، قالب ماشین‌خوان."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Priority = Literal["بحرانی", "بالا", "متوسط", "پایین"]
EffortLevel = Literal["کم", "متوسط", "زیاد"]


class FactorAnalysis(BaseModel):
    """تحلیل یک عامل مؤثر بر فروش."""

    factor: str = Field(description="نام عامل (مثلاً کانال، محصول، فصل، سگمنت مشتری)")
    finding: str = Field(description="یافته‌ی مبتنی بر داده درباره‌ی این عامل")
    impact: str = Field(description="میزان و جهت تأثیر بر فروش")


class Recommendation(BaseModel):
    """یک توصیه‌ی عملیاتی اولویت‌بندی‌شده."""

    title: str = Field(description="عنوان کوتاه توصیه")
    priority: Priority = Field(description="اولویت اجرا")
    rationale: str = Field(description="چرایی این توصیه بر پایه‌ی داده")
    expected_impact: str = Field(description="اثر مورد انتظار بر فروش/مارکتینگ")
    effort: EffortLevel = Field(description="میزان تلاش/منابع لازم")


class StrategyReport(BaseModel):
    """گزارش کامل استراتژی مارکتینگ تولیدشده توسط مدل."""

    executive_summary: str = Field(description="خلاصه‌ی مدیریتی وضعیت فروش و جهت‌گیری")
    factor_analysis: list[FactorAnalysis] = Field(
        description="تحلیل تک‌تک عوامل مؤثر بر فروش", default_factory=list
    )
    target_rationale: str = Field(description="توجیه تارگت پیشنهادی و سناریوی توصیه‌شده")
    recommendations: list[Recommendation] = Field(
        description="فهرست توصیه‌های عملیاتی اولویت‌بندی‌شده", default_factory=list
    )
    risks: list[str] = Field(description="ریسک‌ها و نکات احتیاطی", default_factory=list)


# ---------------------------------------------------------------------------
# لایه‌ی کمپین و اجرای مارکتینگ (مدیر مارکتینگ خودمختار)
# ---------------------------------------------------------------------------

Channel = Literal["پیامک", "ایمیل", "مسنجر", "تماس تلفنی"]


class ChannelMessage(BaseModel):
    """پیام شخصی‌سازی‌شده برای یک کانال ارتباطی."""

    channel: Channel = Field(description="کانال ارتباطی")
    subject: str | None = Field(default=None, description="موضوع (مخصوص ایمیل)")
    body: str = Field(
        description="متن پیام شخصی‌سازی‌شده با متغیرهای جای‌گذاری مثل {نام} {محصول} {تخفیف}"
    )
    call_script: str | None = Field(
        default=None, description="اسکریپت کامل مکالمه (مخصوص تماس تلفنی)"
    )
    timing: str = Field(description="بهترین زمان/روز ارسال")
    personalization_vars: list[str] = Field(
        default_factory=list, description="فهرست متغیرهای شخصی‌سازی استفاده‌شده در پیام"
    )


class AudienceCampaign(BaseModel):
    """یک کمپین اختصاصی برای یک مخاطب/سگمنت مشخص با پیام‌های چندکاناله."""

    segment_name: str = Field(description="نام سگمنت/مخاطب هدف")
    audience_definition: str = Field(description="تعریف دقیق اینکه چه کسانی در این مخاطب هستند")
    objective: str = Field(description="هدف کمپین (مثلاً فعال‌سازی مجدد، فروش مکمل، تکمیل الگو)")
    offer: str = Field(description="پیشنهاد/مشوق کمپین")
    estimated_size: int | None = Field(default=None, description="برآورد اندازه‌ی مخاطب")
    channels: list[ChannelMessage] = Field(
        default_factory=list, description="پیام‌های شخصی‌سازی‌شده برای هر کانال"
    )
    success_kpi: str = Field(description="شاخص سنجش موفقیت کمپین")


class WeeklyAction(BaseModel):
    """اقدامات تاکتیکی یک روز از هفته در راستای تارگت ماهانه."""

    day: str = Field(description="روز هفته")
    focus: str = Field(description="تمرکز اصلی روز")
    actions: list[str] = Field(default_factory=list, description="اقدامات مشخص و اجرایی روز")


class CampaignPlan(BaseModel):
    """خروجی کامل مدیر مارکتینگ: کمپین‌ها، پیام‌ها و برنامه‌ی هفتگی اجرایی."""

    summary: str = Field(description="خلاصه‌ی رویکرد کمپین‌ها و منطق هدف‌گیری")
    audiences: list[AudienceCampaign] = Field(
        default_factory=list, description="کمپین‌های اختصاصی به تفکیک مخاطب"
    )
    weekly_actions: list[WeeklyAction] = Field(
        default_factory=list, description="برنامه‌ی اجرایی روزبه‌روز هفته"
    )


__all__ = [
    "StrategyReport",
    "Recommendation",
    "FactorAnalysis",
    "CampaignPlan",
    "AudienceCampaign",
    "ChannelMessage",
    "WeeklyAction",
]
