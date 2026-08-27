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
             "وضعیت": "آماده‌ی ارسال" if m.phone else "بدون شماره",
             "شناسه_پیام": None}
            for m in messages
        ]
        valid = sum(1 for m in messages if m.phone)
        return SendResult(
            total=len(messages), sent=valid, failed=len(messages) - valid,
            dry_run=True, provider=self.name, details=details,
        )


# کاوه‌نگار وضعیت واقعی را **داخل بدنه** برمی‌گرداند، نه در کد HTTP.
KAVENEGAR_OK_STATUS = 200


def parse_kavenegar_response(status_code: int, body: object) -> tuple[bool, str, str | None]:
    """(موفق؟، توضیح فارسی، شناسه‌ی پیام) از پاسخ کاوه‌نگار.

    **چرا این تابع جدا و آزمودنی است.** نسخه‌ی اول فقط `r.status_code == 200` را
    می‌دید. ولی کاوه‌نگار خطاهای واقعی — اعتبار ناکافی، گیرنده‌ی نامعتبر،
    فرستنده‌ی مسدود — را با **HTTP ۲۰۰ و کد خطا داخل بدنه** برمی‌گرداند:

    ```json
    {"return": {"status": 411, "message": "دریافت کننده نامعتبر است"}, "entries": null}
    ```

    با قاعده‌ی قدیمی این «ارسال شد» ثبت می‌شد و سه چیز خراب می‌شد: مهرِ تماس روی
    عضوی می‌خورد که پیام نگرفته (و اثر را کمتر از واقع نشان می‌داد)، هزینه‌ای ثبت
    می‌شد که خرج نشده، و گزارش دروغ می‌گفت.

    `messageid` هم اینجا استخراج می‌شود؛ بدون آن، webhook تحویل در آینده راهی
    برای وصل‌کردن پاسخ به ردیفِ ارسال ندارد.
    """
    if status_code != 200:
        return False, f"خطای شبکه {status_code}", None
    if not isinstance(body, dict):
        return False, "پاسخ پنل قابل خواندن نبود.", None

    ret = body.get("return") or {}
    api_status = ret.get("status")
    if api_status != KAVENEGAR_OK_STATUS:
        reason = str(ret.get("message") or "").strip() or "خطای نامشخص پنل"
        return False, f"خطای پنل {api_status}: {reason}", None

    entries = body.get("entries") or []
    if not entries:
        # وضعیت ۲۰۰ ولی بدون entry یعنی چیزی در صف نرفته
        return False, "پنل وضعیت موفق داد ولی هیچ پیامی ثبت نکرد.", None

    entry = entries[0] if isinstance(entries, list) else entries
    message_id = entry.get("messageid") if isinstance(entry, dict) else None
    status_text = (entry.get("statustext") if isinstance(entry, dict) else None) or "ارسال شد"
    return True, str(status_text), None if message_id is None else str(message_id)


class KavenegarProvider(SMSProvider):
    """اتصال به پنل پیامک کاوه‌نگار (نیازمند کلید و گروه اختیاری connectors)."""

    name = "kavenegar"
    BASE = "https://api.kavenegar.com/v1/{key}/sms/send.json"

    def __init__(self, api_key: str, sender: str | None = None,
                 *, client: object | None = None) -> None:
        self.api_key = api_key
        self.sender = sender
        # تزریق کلاینت فقط برای تست؛ در تولید `None` است و کلاینت ساخته می‌شود.
        self._client = client

    def send(self, messages: list[RenderedMessage], *, sender: str | None = None) -> SendResult:
        if self._client is not None:
            return self._send_with(self._client, messages, sender=sender)
        try:
            import httpx
        except ImportError as e:
            raise NotImplementedError(
                "نیازمند نصب گروه connectors: pip install '.[connectors]'"
            ) from e
        with httpx.Client(timeout=20) as client:
            return self._send_with(client, messages, sender=sender)

    def _send_with(self, client, messages: list[RenderedMessage], *,
                   sender: str | None = None) -> SendResult:
        sent, failed, details = 0, 0, []
        url = self.BASE.format(key=self.api_key)
        for m in messages:
            if not m.phone:
                failed += 1
                details.append({"مشتری": m.customer_id, "گیرنده": "—",
                                "وضعیت": "خطا: شماره ندارد", "شناسه_پیام": None})
                continue
            try:
                r = client.post(url, data={"receptor": m.phone,
                                           "sender": sender or self.sender or "",
                                           "message": m.text})
                try:
                    body = r.json()
                except Exception:  # noqa: BLE001 - بدنه‌ی غیر JSON هم ممکن است
                    body = None
                ok, note, message_id = parse_kavenegar_response(r.status_code, body)
                sent += int(ok)
                failed += int(not ok)
                details.append({
                    "مشتری": m.customer_id, "گیرنده": m.phone,
                    "وضعیت": note if ok else f"خطا — {note}",
                    "شناسه_پیام": message_id,
                })
            except Exception as ex:  # noqa: BLE001 - قطعی شبکه نباید کل دسته را بخواباند
                failed += 1
                details.append({"مشتری": m.customer_id, "گیرنده": m.phone,
                                "وضعیت": f"خطا — {ex}", "شناسه_پیام": None})
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
           "get_sms_provider", "parse_kavenegar_response", "send_campaign"]
