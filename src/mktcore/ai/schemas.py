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


__all__ = ["StrategyReport", "Recommendation", "FactorAnalysis", "FactorAnalysis"]
