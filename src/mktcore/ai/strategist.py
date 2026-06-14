"""تولید گزارش استراتژی مارکتینگ از متریک‌ها با مدل Claude."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..config import get_settings
from .client import get_client
from .metrics_payload import build_payload, payload_to_json
from .prompts import SYSTEM_PROMPT, build_user_message
from .schemas import StrategyReport

if TYPE_CHECKING:
    from ..pipeline import MetricsBundle


def generate_strategy(
    bundle: MetricsBundle,
    *,
    client: Any | None = None,
    model: str | None = None,
    effort: str | None = None,
    max_tokens: int | None = None,
) -> StrategyReport:
    """تبدیل متریک‌ها به گزارش استراتژی ساختاریافته‌ی فارسی.

    Args:
        bundle: خروجی `run_analysis`.
        client: کلاینت انتروپیک (برای تزریق/تست). در نبود، singleton ساخته می‌شود.
        model/effort/max_tokens: بازنویسی تنظیمات پیش‌فرض.

    Returns:
        نمونه‌ی اعتبارسنجی‌شده‌ی `StrategyReport`.
    """
    settings = get_settings()
    model = model or settings.mkt_model
    effort = effort or settings.mkt_effort
    max_tokens = max_tokens or settings.mkt_max_tokens
    cli = client or get_client()

    payload = build_payload(bundle, currency=settings.mkt_currency)
    metrics_json = payload_to_json(payload)
    user_message = build_user_message(metrics_json)

    system_blocks = [
        {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
    ]

    response = cli.messages.parse(
        model=model,
        max_tokens=max_tokens,
        system=system_blocks,
        thinking={"type": "adaptive"},
        output_config={"effort": effort},
        messages=[{"role": "user", "content": user_message}],
        output_format=StrategyReport,
    )
    parsed = getattr(response, "parsed_output", None)
    if parsed is None:
        # fallback: تلاش برای استخراج متن JSON از اولین بلوک متنی
        text = next((b.text for b in response.content if getattr(b, "type", None) == "text"), "{}")
        parsed = StrategyReport.model_validate_json(text)
    return parsed


__all__ = ["generate_strategy"]
