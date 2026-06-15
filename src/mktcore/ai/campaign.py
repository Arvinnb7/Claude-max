"""تولید برنامه‌ی کمپین و پیام‌های شخصی‌سازی‌شده با مدل Claude."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..config import get_settings
from .client import get_client
from .metrics_payload import build_payload, payload_to_json
from .prompts import CAMPAIGN_SYSTEM, build_campaign_message
from .schemas import CampaignPlan

if TYPE_CHECKING:
    from ..pipeline import MetricsBundle


def generate_campaigns(
    bundle: MetricsBundle,
    *,
    client: Any | None = None,
    model: str | None = None,
    effort: str | None = None,
    max_tokens: int | None = None,
) -> CampaignPlan:
    """تبدیل متریک‌ها به برنامه‌ی کمپین کامل (مخاطب‌ها، پیام‌های چندکاناله، برنامه‌ی هفتگی)."""
    settings = get_settings()
    model = model or settings.mkt_model
    effort = effort or settings.mkt_effort
    max_tokens = max_tokens or settings.mkt_max_tokens
    cli = client or get_client()

    payload = build_payload(bundle, currency=settings.mkt_currency)
    user_message = build_campaign_message(payload_to_json(payload))

    system_blocks = [
        {"type": "text", "text": CAMPAIGN_SYSTEM, "cache_control": {"type": "ephemeral"}}
    ]

    response = cli.messages.parse(
        model=model,
        max_tokens=max_tokens,
        system=system_blocks,
        thinking={"type": "adaptive"},
        output_config={"effort": effort},
        messages=[{"role": "user", "content": user_message}],
        output_format=CampaignPlan,
    )
    parsed = getattr(response, "parsed_output", None)
    if parsed is None:
        text = next((b.text for b in response.content if getattr(b, "type", None) == "text"), "{}")
        parsed = CampaignPlan.model_validate_json(text)
    return parsed


__all__ = ["generate_campaigns"]
