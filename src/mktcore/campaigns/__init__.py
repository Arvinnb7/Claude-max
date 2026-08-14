"""کمپین به‌عنوان آزمایش — حلقه‌ی بستهٔ «پیشنهاد → اقدام → نتیجه».

تا پیش از این، سیستم پیشنهاد می‌داد و هرگز نمی‌فهمید پیشنهادش کار کرد یا نه.
مشکل این نیست که نمی‌شد شمرد؛ مشکل این است که شمردنِ «چند نفر از تماس‌شدگان
خرید کردند» **اثر را ثابت نمی‌کند**: بخشی از آن‌ها به‌هرحال خرید می‌کردند.

راه‌حل، همان راه‌حل همیشگی است: گروه کنترل. بخشی از واجدان شرایط عمداً تماس
نمی‌گیرند، و تفاوت دو گروه — نه عملکرد مطلقِ گروه تماس‌شده — اثر واقعی است.
"""

from .analysis import CampaignReport, analyze_campaign
from .assign import ArmAssignment, assign_arms
from .outcomes import compute_campaign_outcomes

__all__ = [
    "ArmAssignment",
    "CampaignReport",
    "analyze_campaign",
    "assign_arms",
    "compute_campaign_outcomes",
]
