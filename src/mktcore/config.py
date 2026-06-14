"""تنظیمات سراسری برنامه — از متغیرهای محیطی / فایل .env خوانده می‌شود."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """پیکربندی برنامه با پیشوند MKT_ (به‌جز کلید API انتروپیک).

    مقادیر از محیط یا فایل `.env` خوانده می‌شوند. کلید API هرگز در کد
    نوشته نمی‌شود؛ SDK انتروپیک خودش `ANTHROPIC_API_KEY` را می‌خواند، اما
    آن را اینجا هم نگه می‌داریم تا بتوان وجودش را بررسی کرد.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # کلید API (بدون پیشوند MKT_ تا با نام استاندارد SDK یکی باشد)
    anthropic_api_key: str | None = None

    # تنظیمات مدل و استدلال
    mkt_model: str = "claude-opus-4-8"
    mkt_draft_model: str = "claude-haiku-4-5"
    mkt_effort: str = "high"
    mkt_max_tokens: int = 16000

    # نمایش
    mkt_currency: str = "تومان"

    # تست واقعی هوش مصنوعی (فقط محلی)
    mkt_live_ai: bool = False

    # مسیر خروجی‌ها
    mkt_output_dir: Path = Path("outputs")

    @property
    def has_api_key(self) -> bool:
        return bool(self.anthropic_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """نمونه‌ی واحد (singleton) تنظیمات."""
    return Settings()
