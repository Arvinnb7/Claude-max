"""تخفیف مبلغی باید هم‌واحدِ بقیه‌ی مبالغ شود (باگ ۱۰ برابری حسابرسی).

پیش از این اصلاح، `currency.py` ستون `discount` را همیشه «نسبت» فرض می‌کرد و
تبدیل نمی‌کرد، ولی `kpis.py` تخفیفِ **مبلغی** را روی فریمِ تبدیل‌شده جمع می‌زد؛
نتیجه: وقتی واحد فایل ≠ واحد نمایش، `discount_total` به‌اندازه‌ی نسبت واحدها
غلط بود و با درآمد در یک صورت مالی جمع‌پذیر نبود.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.analysis.kpis import compute_kpis  # noqa: E402
from mktcore.ingest.cleaning import clean_frame, get_returns  # noqa: E402
from mktcore.ingest.currency import (  # noqa: E402
    conversion_factor,
    convert_monetary_columns,
    rial_per_unit,
)
from mktcore.ingest.mapper import SchemaMapper  # noqa: E402
from mktcore.ingest.schema import ColumnRole  # noqa: E402

_MAPPING = {
    ColumnRole.DATE: "تاریخ",
    ColumnRole.REVENUE: "مبلغ",
    ColumnRole.QUANTITY: "تعداد",
    ColumnRole.UNIT_PRICE: "قیمت واحد",
    ColumnRole.DISCOUNT: "تخفیف",
    ColumnRole.CUSTOMER_ID: "مشتری",
    ColumnRole.ORDER_ID: "فاکتور",
}


def _clean(discount: float | list[float], n: int = 12) -> pd.DataFrame:
    """فریم تمیز با تاریخ‌های متمایز (وگرنه حذف تکراری همه را یکی می‌کند)."""
    raw = pd.DataFrame({
        "تاریخ": [f"1402/01/{i + 1:02d}" for i in range(n)],
        "مبلغ": [""] * n,  # خالی → از تعداد×قیمت−تخفیف مشتق می‌شود
        "تعداد": [2] * n,
        "قیمت واحد": [10_000] * n,
        "تخفیف": discount if isinstance(discount, list) else [discount] * n,
        "مشتری": [f"C{i}" for i in range(n)],
        "فاکتور": [f"F{i}" for i in range(n)],
    })
    return clean_frame(SchemaMapper().apply(raw, _MAPPING))


# ------------------------------------------------------------- rial_per_unit
def test_rial_per_unit_values():
    assert rial_per_unit("ریال") == 1
    assert rial_per_unit("تومان") == 10
    assert isinstance(rial_per_unit("تومان"), int)  # مرز canonical عدد صحیح می‌خواهد


def test_rial_per_unit_rejects_unknown():
    with pytest.raises(ValueError, match="نامعتبر"):
        rial_per_unit("دلار")


def test_rial_per_unit_is_consistent_with_conversion_factor():
    for file_cur in ("ریال", "تومان"):
        for display_cur in ("ریال", "تومان"):
            expected = rial_per_unit(file_cur) / rial_per_unit(display_cur)
            assert conversion_factor(file_cur, display_cur) == expected


# --------------------------------------------------- تخفیف مبلغی تبدیل می‌شود
def test_amount_discount_is_converted_with_revenue():
    clean = _clean(5_000)
    assert clean.attrs["discount_is_amount"] is True
    before_disc = float(clean["discount"].sum())
    before_rev = float(clean["revenue"].sum())

    out = convert_monetary_columns(clean, conversion_factor("ریال", "تومان"))

    assert float(out["revenue"].sum()) == pytest.approx(before_rev * 0.1, rel=1e-12)
    # نکته‌ی باگ: پیش از اصلاح، این جمع بدون تغییر می‌ماند (۱۰ برابر درآمد)
    assert float(out["discount"].sum()) == pytest.approx(before_disc * 0.1, rel=1e-12)


def test_amount_discount_total_in_kpis_is_display_unit():
    """`discount_total` باید با `net_sales` هم‌واحد باشد تا جمع‌پذیر بماند."""
    clean = _clean(5_000)
    base = compute_kpis(clean)
    conv = compute_kpis(convert_monetary_columns(clean, conversion_factor("ریال", "تومان")))

    assert base.discount_total == 5_000.0 * 12
    assert conv.discount_total == pytest.approx(base.discount_total * 0.1, rel=1e-12)
    # اتحاد اقتصادی: ناخالصِ پیش از تخفیف در همان واحد
    gross_before_discount = conv.net_sales + conv.discount_total
    assert gross_before_discount == pytest.approx(
        (base.net_sales + base.discount_total) * 0.1, rel=1e-12,
    )


def test_ratio_discount_is_never_converted():
    """تخفیف نسبتی بی‌واحد است؛ تبدیل آن مقدار را بی‌معنا می‌کرد."""
    clean = _clean(0.1)
    assert clean.attrs["discount_is_amount"] is False
    before = clean["discount"].tolist()
    out = convert_monetary_columns(clean, conversion_factor("ریال", "تومان"))
    assert out["discount"].tolist() == before
    assert compute_kpis(out).discount_total is None


def test_amount_discount_converted_in_returns_frame():
    """فریم برگشت‌ها هم باید هم‌واحد بماند، وگرنه خالص‌سازی ناهمگون می‌شود."""
    n = 12
    raw = pd.DataFrame({
        "تاریخ": [f"1402/01/{i + 1:02d}" for i in range(n)],
        "مبلغ": [20_000] * (n - 3) + [-20_000] * 3,
        "تعداد": [2] * n,
        "قیمت واحد": [10_000] * n,
        "تخفیف": [5_000] * n,
        "مشتری": [f"C{i}" for i in range(n)],
        "فاکتور": [f"F{i}" for i in range(n)],
    })
    clean = clean_frame(SchemaMapper().apply(raw, _MAPPING))
    assert clean.attrs["discount_is_amount"] is True
    before = float(get_returns(clean)["discount"].sum())
    assert before > 0

    out = convert_monetary_columns(clean, conversion_factor("ریال", "تومان"))
    assert float(get_returns(out)["discount"].sum()) == pytest.approx(
        before * 0.1, rel=1e-12,
    )
