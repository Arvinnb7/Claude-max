"""اسکلت کانکتور CRM (HubSpot / Salesforce / CRMهای ایرانی).

پیاده‌سازی واقعی نیازمند کلید API و نگاشت endpointهای هر CRM است. این اسکلت
قرارداد مشترک را رعایت می‌کند تا UI و pipeline به‌صورت یکنواخت با آن کار کنند.
"""

from __future__ import annotations

from .base import ConnectorResult, DataConnector


class CRMConnector(DataConnector):
    """خواندن معاملات/فروش از یک CRM (اسکلت)."""

    name = "crm"

    SUPPORTED = ("hubspot", "salesforce", "didar", "payamgostar", "generic")

    def __init__(self, provider: str = "generic", api_key: str | None = None,
                 base_url: str | None = None) -> None:
        self.provider = provider
        self.api_key = api_key
        self.base_url = base_url

    def list_sources(self) -> list[str]:  # pragma: no cover - اسکلت
        # مثلاً: deals, contacts, orders
        return ["deals", "orders"]

    def read(self, source: str | None = None, **kwargs) -> ConnectorResult:  # pragma: no cover - اسکلت
        raise NotImplementedError(
            f"کانکتور CRM برای provider='{self.provider}' هنوز پیاده‌سازی نشده است. "
            "برای فعال‌سازی، کلید API و نگاشت فیلدهای CRM را اضافه کنید."
        )

    def describe(self) -> dict:
        return {
            "name": self.name,
            "provider": self.provider,
            "status": "اسکلت — نیازمند کلید API و پیکربندی",
            "supported": list(self.SUPPORTED),
        }
