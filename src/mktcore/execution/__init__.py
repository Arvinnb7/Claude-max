"""لایه‌ی اجرای مارکتینگ: ساخت مخاطب، شخصی‌سازی پیام و ارسال از طریق پنل پیامکی."""

from .audience import Recipient, build_audience, render_messages
from .providers import DryRunSMSProvider, SMSProvider, get_sms_provider, send_campaign

__all__ = [
    "Recipient",
    "build_audience",
    "render_messages",
    "SMSProvider",
    "DryRunSMSProvider",
    "get_sms_provider",
    "send_campaign",
]
