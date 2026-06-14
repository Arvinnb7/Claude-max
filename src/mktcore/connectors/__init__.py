"""کانکتورهای منابع داده: اکسل/CSV (کامل) و اسکلت SQL/CRM/فروشگاهی."""

from .base import ConnectorResult, DataConnector
from .excel_csv import ExcelCsvConnector

__all__ = ["DataConnector", "ConnectorResult", "ExcelCsvConnector"]
