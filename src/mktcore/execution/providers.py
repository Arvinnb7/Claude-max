"""ارائه‌دهنده‌های پنل پیامکی: حالت dry-run امن + اسکلت پنل‌های ایرانی.

طبق سیاست امنیتی، حالت پیش‌فرض dry-run است و هیچ پیامی واقعاً ارسال نمی‌شود مگر
اینکه صراحتاً ارائه‌دهنده‌ی واقعی با کلید پیکربندی و dry_run=False داده شود.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from .audience import RenderedMessage


@dataclass
class SendResult:
    total: int
    sent: int
    failed: int
    dry_run: bool
    provider: str
    details: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "تعداد_کل": self.total,
            "ارسال‌شده": self.sent,
            "ناموفق": self.failed,
            "حالت_آزمایشی": self.dry_run,
            "ارائه‌دهنده": self.provider,
            "نمونه": self.details[:10],
        }


class SMSProvider(ABC):
    name: str = "base"

    @abstractmethod
    def send(self, messages: list[RenderedMessage], *, sender: str | None = None) -> SendResult:
        """ارسال فهرست پیام‌ها."""


class DryRunSMSProvider(SMSProvider):
    """شبیه‌سازی ارسال بدون تماس با شبکه — برای پیش‌نمایش و تست امن."""

    name = "dry-run"

    def send(self, messages: list[RenderedMessage], *, sender: str | None = None) -> SendResult:
        details = [
            {"مشتری": m.customer_id, "گیرنده": m.phone or "—", "متن": m.text,
             "وضعیت": "آماده‌ی ارسال" if m.phone else "بدون شماره"}
            for m in messages
        ]
        valid = sum(1 for m in messages if m.phone)
        return SendResult(
            total=len(messages), sent=valid, failed=len(messages) - valid,
            dry_run=True, provider=self.name, details=details,
        )


class KavenegarProvider(SMSProvider):
    """اسکلت اتصال به پنل پیامک کاوه‌نگار (نیازمند کلید و گروه اختیاری connectors)."""

    name = "kavenegar"
    BASE = "https://api.kavenegar.com/v1/{key}/sms/send.json"

    def __init__(self, api_key: str, sender: str | None = None) -> None:
        self.api_key = api_key
        self.sender = sender

    def send(self, messages: list[RenderedMessage], *, sender: str | None = None) -> SendResult:  # pragma: no cover - نیازمند شبکه/کلید
        try:
            import httpx
        except ImportError as e:
            raise NotImplementedError("نیازمند نصب گروه connectors: pip install '.[connectors]'") from e

        sent, failed, details = 0, 0, []
        url = self.BASE.format(key=self.api_key)
        with httpx.Client(timeout=20) as client:
            for m in messages:
                if not m.phone:
                    failed += 1
                    continue
                try:
                    r = client.post(url, data={"receptor": m.phone,
                                               "sender": sender or self.sender or "",
                                               "message": m.text})
                    ok = r.status_code == 200
                    sent += int(ok)
                    failed += int(not ok)
                    details.append({"مشتری": m.customer_id, "گیرنده": m.phone,
                                    "وضعیت": "ارسال شد" if ok else f"خطا {r.status_code}"})
                except Exception as ex:
                    failed += 1
                    details.append({"مشتری": m.customer_id, "گیرنده": m.phone, "وضعیت": str(ex)})
        return SendResult(total=len(messages), sent=sent, failed=failed,
                          dry_run=False, provider=self.name, details=details)


def get_sms_provider(
    provider: str = "dry-run", *, api_key: str | None = None, sender: str | None = None
) -> SMSProvider:
    """انتخاب ارائه‌دهنده. پیش‌فرض dry-run (امن)."""
    if provider in ("dry-run", "dryrun", None):
        return DryRunSMSProvider()
    if provider == "kavenegar":
        if not api_key:
            raise ValueError("برای کاوه‌نگار کلید API لازم است.")
        return KavenegarProvider(api_key, sender)
    raise ValueError(f"ارائه‌دهنده‌ی ناشناخته: {provider}")


def send_campaign(
    messages: list[RenderedMessage],
    *,
    provider: str = "dry-run",
    api_key: str | None = None,
    sender: str | None = None,
    dry_run: bool = True,
) -> SendResult:
    """ارسال یک کمپین. تا زمانی که dry_run=True باشد یا کلید نباشد، چیزی واقعاً ارسال نمی‌شود."""
    if dry_run or not api_key:
        return DryRunSMSProvider().send(messages, sender=sender)
    prov = get_sms_provider(provider, api_key=api_key, sender=sender)
    return prov.send(messages, sender=sender)


__all__ = ["SMSProvider", "DryRunSMSProvider", "KavenegarProvider", "SendResult",
           "get_sms_provider", "send_campaign"]
