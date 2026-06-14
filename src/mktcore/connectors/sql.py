"""اسکلت کانکتور دیتابیس/نرم‌افزار فروش (SQL).

پیاده‌سازی کامل نیازمند نصب گروه اختیاری `connectors` (SQLAlchemy) و رشته‌ی
اتصال است. این اسکلت قرارداد مشترک DataConnector را رعایت می‌کند.
"""

from __future__ import annotations

from .base import ConnectorResult, DataConnector


class SQLConnector(DataConnector):
    """اتصال به دیتابیس SQL و خواندن جدول/کوئری فروش (اسکلت)."""

    name = "sql"

    def __init__(self, connection_string: str | None = None) -> None:
        self.connection_string = connection_string

    def _require_engine(self):
        try:
            from sqlalchemy import create_engine
        except ImportError as e:  # pragma: no cover
            raise NotImplementedError(
                "کانکتور SQL نیازمند نصب گروه اختیاری است: pip install '.[connectors]'"
            ) from e
        if not self.connection_string:
            raise NotImplementedError("رشته‌ی اتصال (connection_string) تنظیم نشده است.")
        return create_engine(self.connection_string)

    def list_sources(self) -> list[str]:  # pragma: no cover - اسکلت
        engine = self._require_engine()
        from sqlalchemy import inspect

        return list(inspect(engine).get_table_names())

    def read(self, source: str | None = None, *, query: str | None = None, **kwargs) -> ConnectorResult:  # pragma: no cover - اسکلت
        import pandas as pd

        engine = self._require_engine()
        if query is None and source is None:
            raise ValueError("باید source (نام جدول) یا query داده شود.")
        sql = query or f"SELECT * FROM {source}"
        df = pd.read_sql(sql, engine)
        return ConnectorResult(dataframe=df, source_name=source or "query", meta={"format": "sql"})

    def describe(self) -> dict:
        return {"name": self.name, "status": "اسکلت — نیازمند پیکربندی اتصال"}
