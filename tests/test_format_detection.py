"""تشخیص قالب فایل از امضای بایت‌ها، نه از پسوند.

پسوند دروغ می‌گوید: کاربر فایل `.xls` را با نام `.xlsx` ذخیره می‌کند، سامانه‌ی
مبدأ فایل بدون پسوند می‌فرستد، یا CSV با نام `.xls` می‌آید. پیش از این اصلاح،
هر کدام از این‌ها با parser اشتباه باز می‌شد و خطای نامفهوم می‌داد.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.connectors.excel_csv import ExcelCsvConnector  # noqa: E402


def _xlsx_bytes() -> bytes:
    buf = io.BytesIO()
    pd.DataFrame({"تاریخ": ["1402/01/01"], "مبلغ": [1000]}).to_excel(buf, index=False)
    return buf.getvalue()


def _csv_bytes() -> bytes:
    return "تاریخ,مبلغ\n1402/01/01,1000\n".encode()


def test_real_xlsx_named_csv_is_read_as_excel():
    """نام غلط نباید فایل سالم را غیرقابل‌خواندن کند."""
    conn = ExcelCsvConnector(content=_xlsx_bytes(), filename="فروش.csv")
    assert conn._ext == ".xlsx"
    result = conn.read()
    assert list(result.dataframe.columns) == ["تاریخ", "مبلغ"]


def test_csv_named_xlsx_is_read_as_csv():
    conn = ExcelCsvConnector(content=_csv_bytes(), filename="فروش.xlsx")
    assert conn._ext == ".csv"
    result = conn.read()
    assert list(result.dataframe.columns) == ["تاریخ", "مبلغ"]


def test_file_without_extension_is_detected():
    assert ExcelCsvConnector(content=_xlsx_bytes(), filename="report")._ext == ".xlsx"
    assert ExcelCsvConnector(content=_csv_bytes(), filename="report")._ext == ".csv"


def test_correct_extension_is_respected():
    """وقتی پسوند و امضا موافق‌اند، هیچ‌چیز عوض نمی‌شود."""
    assert ExcelCsvConnector(content=_xlsx_bytes(), filename="a.xlsx")._ext == ".xlsx"
    assert ExcelCsvConnector(content=_xlsx_bytes(), filename="a.xlsm")._ext == ".xlsm"
    assert ExcelCsvConnector(content=_csv_bytes(), filename="a.csv")._ext == ".csv"
    assert ExcelCsvConnector(content=_csv_bytes(), filename="a.tsv")._ext == ".tsv"


def test_ole2_signature_is_detected_as_legacy_xls():
    """امضای OLE2 یعنی اکسل قدیمی، حتی با نام xlsx."""
    ole2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64
    assert ExcelCsvConnector(content=ole2, filename="قدیمی.xlsx")._ext == ".xls"


def test_detection_reads_from_path_without_loading_whole_file(tmp_path):
    path = tmp_path / "بدون-پسوند"
    path.write_bytes(_xlsx_bytes())
    conn = ExcelCsvConnector(path=path)
    assert conn._ext == ".xlsx"
    assert list(conn.read().dataframe.columns) == ["تاریخ", "مبلغ"]


def test_list_sources_uses_detected_format():
    conn = ExcelCsvConnector(content=_xlsx_bytes(), filename="فروش.csv")
    sources = conn.list_sources()
    assert sources and sources[0] != "فروش.csv"  # نام شیت است، نه نام فایل
