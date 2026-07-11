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

    # ماندگاری و کارهای طولانی
    mkt_data_dir: Path = Path("data")
    mkt_session_ttl_hours: int = 72
    mkt_max_upload_mb: int = 100
    # سقف ردیف خواندن فایل (محافظ حافظه در برابر used-range بادکرده)
    mkt_max_rows: int = 400_000
    # اگر job در حال اجرا این‌قدر ثانیه بدون ضربان بماند → خطای شفاف (watchdog)
    mkt_job_stale_seconds: int = 300

    # امنیت شبکه
    mkt_cors_origins: str = "http://localhost:3000"

    # زمان‌بند خودکار
    mkt_scheduler_enable: bool = True
    mkt_schedule_hour: int = 8
    mkt_auto_sms: bool = False
    mkt_cycle_sms_template: str = (
        "سلام {نام} عزیز، طبق چرخه‌ی خریدتان زمان تهیه‌ی «{محصول}» رسیده است. منتظر شما هستیم!"
    )

    # پنل پیامکی (ارسال واقعی فقط با فعال‌سازی صریح)
    mkt_sms_enable: bool = False
    mkt_sms_provider: str = "kavenegar"
    mkt_sms_sender: str | None = None
    kavenegar_api_key: str | None = None

    @property
    def has_api_key(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def sms_configured(self) -> bool:
        """آیا ارسال واقعی پیامک مجاز و پیکربندی‌شده است؟"""
        return bool(self.mkt_sms_enable and self.kavenegar_api_key)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.mkt_cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """نمونه‌ی واحد (singleton) تنظیمات."""
    return Settings()
