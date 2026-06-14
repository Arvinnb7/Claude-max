"""قرارداد پایه‌ی کانکتورهای داده.

همه‌ی منابع (اکسل، CRM، دیتابیس، فروشگاه) یک DataFrame خام برمی‌گردانند؛
نگاشت ستون و پاک‌سازی در مرحله‌ی بعد و به‌صورت یکسان انجام می‌شود تا همه‌ی
منابع از یک مسیر واحد عبور کنند.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import pandas as pd


@dataclass
class ConnectorResult:
    """نتیجه‌ی خواندن از یک منبع داده."""

    dataframe: pd.DataFrame
    source_name: str
    meta: dict = field(default_factory=dict)


class DataConnector(ABC):
    """رابط مشترک همه‌ی کانکتورها."""

    name: str = "base"

    @abstractmethod
    def list_sources(self) -> list[str]:
        """فهرست منابع قابل خواندن (مثلاً نام شیت‌ها یا جدول‌ها)."""

    @abstractmethod
    def read(self, source: str | None = None, **kwargs) -> ConnectorResult:
        """خواندن یک منبع و بازگرداندن DataFrame خام."""

    def describe(self) -> dict:
        """توضیح کوتاه درباره‌ی این کانکتور (برای UI)."""
        return {"name": self.name}
