"""تنظیمات سراسری برنامه — از متغیرهای محیطی / فایل .env خوانده می‌شود."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_data_dir() -> Path:
    """مسیر پیش‌فرض داده، لنگرانداخته به ریشه‌ی مخزن.

    پیش‌تر مسیر نسبی «data» بود و نسبت به پوشه‌ی اجرا حل می‌شد؛ اجرای سرور از
    پوشه‌ی دیگر یک ذخیره‌گاه خالی جدید می‌ساخت و کاربر فکر می‌کرد حافظه پاک شده.
    وقتی نشانه‌ی مخزن (pyproject.toml) نباشد (نصب به‌عنوان پکیج) رفتار قبلی می‌ماند.
    """
    root = Path(__file__).resolve().parents[2]
    return root / "data" if (root / "pyproject.toml").exists() else Path("data")


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
    mkt_data_dir: Path = Field(default_factory=lambda: _default_data_dir())
    # سیاست نگه‌داری — در همه‌ی این کلیدها ۰ به‌معنی «هرگز» است.
    # نتیجه‌ی تحلیل (داشبورد) هرگز خودکار حذف نمی‌شود؛ فقط فایل‌های سنگین هرس
    # می‌شوند: raw.pkl فقط برای «تحلیل مجدد» لازم است و clean/bundle برای
    # گزارش PDF و خروجی اکسل.
    mkt_retention_raw_days: int = 30
    mkt_retention_heavy_days: int = 180
    mkt_retention_delete_days: int = 0  # حذف کامل نشست — پیش‌فرض: هرگز
    mkt_retention_jobs_days: int = 14  # پاک‌سازی رکورد jobهای تمام‌شده
    # منسوخ: قبلاً نشست‌ها را بعد از این مدت حذف می‌کرد. دیگر اثری ندارد و فقط
    # برای هشدار مهاجرت خوانده می‌شود (None = کاربر تنظیمش نکرده است).
    mkt_session_ttl_hours: int | None = None
    mkt_max_upload_mb: int = 100
    # سقف ردیف خواندن فایل (محافظ حافظه در برابر used-range بادکرده)
    mkt_max_rows: int = 400_000
    # سقفِ ردیف برای نگه‌داشتنِ «نمایشِ خام» (§۷.۱). بالاتر از این، ردیف‌های
    # پذیرفته‌شده ذخیره نمی‌شوند و همین در یادداشتِ بارگذاری **گفته می‌شود**.
    # ردیف‌های ردشده همیشه در قرنطینه می‌مانند، بی‌توجه به این سقف.
    mkt_raw_rows_cap: int = 50_000
    # اگر job در حال اجرا این‌قدر ثانیه بدون ضربان بماند → خطای شفاف (watchdog)
    mkt_job_stale_seconds: int = 300

    # رتبه‌بندی مبتنی بر اثرِ اندازه‌گیری‌شده. ۰ یعنی رتبه‌بندی دقیقاً مثل قبل
    # (ارزش × احتمال خرید) — کلید فرار اگر یادگیری نتیجه‌ی نامطلوب داد.
    mkt_uplift_ranking: bool = True

    # دفتر کل canonical (هویت پایدار مشتری/کالا بین بارگذاری‌ها).
    # کلید فرار عملیاتی: ۰ یعنی هیچ نوشتنی در جداول جدید انجام نشود — تحلیل و
    # داشبورد دقیقاً مثل قبل کار می‌کنند.
    mkt_canonical_enable: bool = True

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
    # هزینه‌ی هر **قطعه** پیامک به ریال (۳۰۰ تومان = ۳۰۰۰ ریال).
    # قابل تغییر بدون دست‌زدن به کد، چون تعرفه‌ی پنل عوض می‌شود.
    mkt_sms_cost_per_segment_rial: int = 3_000
    kavenegar_api_key: str | None = None
    # توکنِ مشترک برای مسیرهای نوشتنی و پرخرج. خالی = بدون گارد (رفتار قبلی)،
    # ولی در `/api/health` و لاگ صریح هشدار داده می‌شود.
    mkt_api_token: str | None = None

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

    @property
    def data_dir_abs(self) -> Path:
        """مسیر مطلق داده — برای لاگ و تشخیص «حافظه کجاست»."""
        return Path(self.mkt_data_dir).expanduser().resolve()

    @property
    def retention_policy(self) -> dict:
        """سیاست نگه‌داری برای نمایش در API و لاگ (۰ = هرگز)."""
        return {
            "raw_days": self.mkt_retention_raw_days,
            "heavy_days": self.mkt_retention_heavy_days,
            "delete_days": self.mkt_retention_delete_days,
            "jobs_days": self.mkt_retention_jobs_days,
            "policy_fa": (
                "تحلیل‌ها تا زمانی که خودتان حذف نکنید نگه داشته می‌شوند؛ "
                f"فایل خام بعد از {self.mkt_retention_raw_days} روز و فایل‌های سنگین "
                f"بعد از {self.mkt_retention_heavy_days} روز بایگانی می‌شوند "
                "(داشبورد باقی می‌ماند)."
            ),
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """نمونه‌ی واحد (singleton) تنظیمات."""
    return Settings()
