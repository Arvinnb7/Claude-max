"""مدیریت اتصال به Claude API (SDK رسمی انتروپیک)."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from ..config import get_settings


@lru_cache(maxsize=1)
def get_client() -> Any:
    """نمونه‌ی واحد کلاینت انتروپیک. کلید از محیط/.env خوانده می‌شود."""
    import anthropic

    settings = get_settings()
    # SDK خودش ANTHROPIC_API_KEY را می‌خواند؛ در صورت وجود در تنظیمات صریح می‌دهیم.
    if settings.anthropic_api_key:
        return anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return anthropic.Anthropic()


def api_key_available() -> bool:
    """آیا کلید API برای فراخوانی واقعی موجود است؟"""
    import os

    return bool(get_settings().anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY"))


__all__ = ["get_client", "api_key_available"]
