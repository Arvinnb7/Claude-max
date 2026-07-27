"""تست‌های Auto Mapping هوشمند: نام + نوع داده + نمونه مقادیر."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mktcore.ingest.mapper import AUTO_SELECT_THRESHOLD, SchemaMapper
from mktcore.ingest.schema import ColumnRole


@pytest.fixture
def jivan_like() -> pd.DataFrame:
    """فایل فروش واقع‌گرایانه با ستون‌های فارسی و ستون‌های گمراه‌کننده."""
    n = 60
    rng = np.random.default_rng(0)
    dates = pd.date_range("1403-01-01".replace("1403", "2024"), periods=n, freq="D")
    return pd.DataFrame({
        "تاریخ": [d.strftime("%Y/%m/%d") for d in dates],
        "شماره فاکتور": [f"INV-{1000+i}" for i in range(n)],
        "نام مشتری": [f"مشتری {i%20}" for i in range(n)],
        "موبایل مشتری": ["09" + "".join(str(d) for d in rng.integers(0, 10, 9)) for _ in range(n)],
        "کد کالا": [f"K{rng.integers(100,999)}" for _ in range(n)],
        "شرح کالا": [rng.choice(["غذای سگ", "باکس حمل", "قلاده", "تشویقی"]) for _ in range(n)],
        "تعداد": rng.integers(1, 5, n),
        "قیمت واحد": rng.integers(50000, 500000, n),
        "تخفیف": rng.choice([0, 0.1, 0.2], n),
        "قابل پرداخت": rng.integers(100000, 2000000, n),
        "نحوه برگشت از فروش": [rng.choice(["نقدی", "اعتباری", "—"]) for _ in range(n)],
        "نوع سند": [rng.choice(["فروش", "برگشت"]) for _ in range(n)],
        "وضعیت": [rng.choice(["تسویه", "بدهکار"]) for _ in range(n)],
        "فروشگاه": [rng.choice(["شعبه مرکزی", "شعبه شرق"]) for _ in range(n)],
        "فروشنده": [rng.choice(["احمدی", "رضایی"]) for _ in range(n)],
    })


def _m(df):
    return SchemaMapper().auto_detect(df)


def test_revenue_picks_payable_not_text(jivan_like):
    s = _m(jivan_like)
    assert s.mapping[ColumnRole.REVENUE] == "قابل پرداخت"


def test_revenue_never_maps_text_columns(jivan_like):
    s = _m(jivan_like)
    rev = s.mapping.get(ColumnRole.REVENUE)
    assert rev not in ("نحوه برگشت از فروش", "نوع سند", "وضعیت")
    # هیچ نقش عددی‌ای نباید این ستون‌های متنی را بگیرد
    numeric_roles = {ColumnRole.REVENUE, ColumnRole.UNIT_PRICE, ColumnRole.QUANTITY,
                     ColumnRole.COST, ColumnRole.DISCOUNT}
    for r in numeric_roles:
        assert s.mapping.get(r) not in ("نحوه برگشت از فروش", "نوع سند", "وضعیت")


def test_product_prefers_text_over_code(jivan_like):
    s = _m(jivan_like)
    assert s.mapping[ColumnRole.PRODUCT] == "شرح کالا"


def test_product_code_fallback_when_no_text():
    df = pd.DataFrame({
        "تاریخ": pd.date_range("2024-01-01", periods=10).strftime("%Y-%m-%d"),
        "قابل پرداخت": range(100000, 100000 + 10 * 1000, 1000),
        "کد کالا": [f"K{i}" for i in range(10)],
    })
    s = _m(df)
    assert s.mapping[ColumnRole.PRODUCT] == "کد کالا"


def test_date_only_real_date_column(jivan_like):
    s = _m(jivan_like)
    assert s.mapping[ColumnRole.DATE] == "تاریخ"
    # ستون متنی نباید date شود
    assert s.guesses[ColumnRole.DATE].column == "تاریخ"


def test_customer_phone_order_branch_salesperson(jivan_like):
    s = _m(jivan_like)
    assert s.mapping[ColumnRole.CUSTOMER_ID] == "نام مشتری"
    assert s.mapping[ColumnRole.PHONE] == "موبایل مشتری"
    assert s.mapping[ColumnRole.ORDER_ID] == "شماره فاکتور"
    assert s.mapping[ColumnRole.BRANCH] == "فروشگاه"
    assert s.mapping[ColumnRole.SALESPERSON] == "فروشنده"
    assert s.mapping[ColumnRole.QUANTITY] == "تعداد"
    assert s.mapping[ColumnRole.UNIT_PRICE] == "قیمت واحد"
    assert s.mapping[ColumnRole.DISCOUNT] == "تخفیف"


def test_optional_unmapped_when_absent(jivan_like):
    s = _m(jivan_like)
    # کانال/دسته/منطقه/هزینه/ایمیل در فایل نیستند → نباید انتخاب شوند
    for role in (ColumnRole.CHANNEL, ColumnRole.CATEGORY, ColumnRole.REGION,
                 ColumnRole.COST, ColumnRole.EMAIL):
        assert role not in s.mapping


def test_confidence_and_reason_present(jivan_like):
    s = _m(jivan_like)
    g = s.guesses[ColumnRole.REVENUE]
    assert g.column == "قابل پرداخت"
    assert g.confidence >= AUTO_SELECT_THRESHOLD
    assert "قابل پرداخت" in g.reason and "عددی" in g.reason


def test_string_numbers_do_not_crash():
    """مبلغ به‌صورت رشته با جداکننده/فارسی نباید تحلیل را با str>int بشکند."""
    from mktcore.ingest.cleaning import clean_frame
    from mktcore.pipeline import run_analysis

    df = pd.DataFrame({
        "تاریخ": pd.date_range("2024-01-01", periods=30, freq="2D").strftime("%Y/%m/%d"),
        "قابل پرداخت": ["۱٬۲۰۰٬۰۰۰ تومان"] * 15 + ["2,500,000"] * 15,
        "شرح کالا": ["غذای سگ", "قلاده"] * 15,
        "نام مشتری": [f"م{i%5}" for i in range(30)],
    })
    m = SchemaMapper()
    clean = clean_frame(m.apply(df, m.auto_detect(df).mapping))
    assert clean["revenue"].dtype.kind == "f"
    bundle = run_analysis(clean, with_forecast=True)
    assert bundle.kpis.total_revenue > 0


def test_doc_type_maps_and_gross_absent(jivan_like):
    s = _m(jivan_like)
    assert s.mapping.get(ColumnRole.DOC_TYPE) == "نوع سند"
    # «نحوه برگشت از فروش» هرگز نوع سند نیست (بلاک «نحوه»)
    assert s.mapping.get(ColumnRole.DOC_TYPE) != "نحوه برگشت از فروش"
    # این فایل ستون ناخالص ندارد
    assert ColumnRole.GROSS_AMOUNT not in s.mapping


def test_gross_amount_maps_when_present(jivan_like):
    df = jivan_like.copy()
    df["قیمت کل(تخفیف کسر نشده)"] = df["قابل پرداخت"] * 1.1
    s = _m(df)
    assert s.mapping[ColumnRole.REVENUE] == "قابل پرداخت"
    assert s.mapping.get(ColumnRole.GROSS_AMOUNT) == "قیمت کل(تخفیف کسر نشده)"


def test_single_total_column_stays_revenue():
    """فایلی که تنها ستون مبلغش «قیمت کل» است باید REVENUE بماند نه GROSS."""
    import numpy as np
    rng = np.random.default_rng(1)
    df = pd.DataFrame({
        "تاریخ": ["1403/01/01"] * 30,
        "قیمت کل": rng.integers(1000, 9000, 30),
        "نام مشتری": [f"م{i}" for i in range(30)],
    })
    s = _m(df)
    assert s.mapping.get(ColumnRole.REVENUE) == "قیمت کل"


def test_header_signature_stable_across_writing_variants():
    from mktcore.ingest.mapper import header_signature

    base = header_signature(["تاریخ", "مبلغ کل", "نام مشتری"])
    reordered = header_signature(["نام مشتری", "تاریخ", "مبلغ کل"])
    arabic_yk = header_signature(["تاريخ", "مبلغ كل", "نام مشتري"])
    spaced = header_signature(["  تاریخ ", "مبلغ  کل", "نام مشتری"])
    assert base == reordered == arabic_yk == spaced
    assert base != header_signature(["تاریخ", "مبلغ", "نام مشتری"])
