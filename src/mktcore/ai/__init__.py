"""لایه‌ی هوش مصنوعی: تبدیل متریک‌ها به استراتژی و کمپین فارسی با مدل Claude."""

from .campaign import generate_campaigns
from .schemas import CampaignPlan, Recommendation, StrategyReport
from .strategist import generate_strategy

__all__ = [
    "generate_strategy",
    "generate_campaigns",
    "StrategyReport",
    "CampaignPlan",
    "Recommendation",
]
