"""کانکتور کامل اکسل/CSV: تشخیص encoding و جداکننده، چندشیت، هدر چندردیفه."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pandas as pd

from .base import ConnectorResult, DataConnector

_EXCEL_EXT = {".xlsx", ".xlsm", ".xls", ".xlsb"}
_CSV_EXT = {".csv", ".txt", ".tsv"}


def _excel_engine(ext: str) -> str:
    """انتخاب موتور مناسب خواندن اکسل بر اساس پسوند."""
    if ext == ".xls":
        return "xlrd"
    if ext == ".xlsb":
        return "pyxlsb"  # اکسل باینری (نیازمند بسته‌ی pyxlsb)
    return "openpyxl"


def _sniff_csv(raw: bytes) -> tuple[str, str]:
    """تشخیص encoding و جداکننده‌ی یک فایل متنی."""
    encoding = "utf-8"
    for enc in ("utf-8-sig", "utf-8", "cp1256", "latin-1"):
        try:
            raw.decode(enc)
            encoding = enc
            break
        except UnicodeDecodeError:
            continue
    text_sample = raw[:8192].decode(encoding, errors="ignore")
    try:
        dialect = csv.Sniffer().sniff(text_sample, delimiters=",;\t|")
        sep = dialect.delimiter
    except csv.Error:
        # شمارش ساده‌ی نامزدها
        counts = {d: text_sample.count(d) for d in [",", ";", "\t", "|"]}
        sep = max(counts, key=counts.get) if any(counts.values()) else ","
    return encoding, sep


class ExcelCsvConnector(DataConnector):
    """خواندن فایل‌های اکسل و CSV از مسیر یا بایت‌های آپلودشده."""

    name = "excel_csv"

    def __init__(self, *, path: str | Path | None = None, content: bytes | None = None,
                 filename: str | None = None) -> None:
        if path is None and content is None:
            raise ValueError("باید path یا content داده شود.")
        self.path = Path(path) if path else None
        self.content = content
        self.filename = filename or (self.path.name if self.path else "uploaded")
        self._ext = Path(self.filename).suffix.lower()

    def _bytes(self) -> bytes:
        if self.content is not None:
            return self.content
        assert self.path is not None
        return self.path.read_bytes()

    def list_sources(self) -> list[str]:
        """نام شیت‌ها (اکسل) یا نام فایل (CSV)."""
        if self._ext in _EXCEL_EXT:
            xls = pd.ExcelFile(io.BytesIO(self._bytes()), engine=_excel_engine(self._ext))
            return list(xls.sheet_names)
        return [self.filename]

    def read(self, source: str | None = None, *, header_row: int = 0, **kwargs) -> ConnectorResult:
        """خواندن یک شیت/فایل و بازگرداندن DataFrame خام.

        Args:
            source: نام شیت (اکسل) — در نبود، اولین شیت.
            header_row: شماره‌ی ردیف هدر (۰-مبنا) برای فایل‌های با هدر چندردیفه.
        """
        raw = self._bytes()
        if self._ext in _EXCEL_EXT:
            df = pd.read_excel(
                io.BytesIO(raw),
                sheet_name=source if source else 0,
                header=header_row,
                engine=_excel_engine(self._ext),
            )
            meta = {"format": "excel", "sheet": source}
        elif self._ext in _CSV_EXT:
            encoding, sep = _sniff_csv(raw)
            df = pd.read_csv(io.BytesIO(raw), encoding=encoding, sep=sep, header=header_row)
            meta = {"format": "csv", "encoding": encoding, "sep": sep}
        else:
            raise ValueError(f"پسوند پشتیبانی‌نشده: {self._ext}")

        # حذف ستون‌های کاملاً بی‌نام/خالی
        df = df.dropna(axis=1, how="all")
        df.columns = [str(c).strip() for c in df.columns]
        return ConnectorResult(dataframe=df, source_name=source or self.filename, meta=meta)
