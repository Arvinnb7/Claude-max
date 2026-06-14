"""اسکلت کانکتور سایت فروشگاهی (WooCommerce / Shopify / خروجی عمومی).

پیاده‌سازی واقعی نیازمند کلید API فروشگاه است. خروجی export این پلتفرم‌ها را
می‌توان فعلاً از طریق کانکتور اکسل/CSV هم بارگذاری کرد.
"""

from __future__ import annotations

from .base import ConnectorResult, DataConnector


class EcommerceConnector(DataConnector):
    """خواندن سفارش‌ها از یک پلتفرم فروشگاهی (اسکلت)."""

    name = "ecommerce"

    SUPPORTED = ("woocommerce", "shopify", "digikala_seller", "generic")

    def __init__(self, platform: str = "generic", api_key: str | None = None,
                 store_url: str | None = None) -> None:
        self.platform = platform
        self.api_key = api_key
        self.store_url = store_url

    def list_sources(self) -> list[str]:  # pragma: no cover - اسکلت
        return ["orders"]

    def read(self, source: str | None = None, **kwargs) -> ConnectorResult:  # pragma: no cover - اسکلت
        raise NotImplementedError(
            f"کانکتور فروشگاهی برای platform='{self.platform}' هنوز پیاده‌سازی نشده است. "
            "تا آن زمان می‌توانید خروجی CSV/Excel فروشگاه را مستقیماً بارگذاری کنید."
        )

    def describe(self) -> dict:
        return {
            "name": self.name,
            "platform": self.platform,
            "status": "اسکلت — فعلاً از خروجی CSV/Excel استفاده کنید",
            "supported": list(self.SUPPORTED),
        }
