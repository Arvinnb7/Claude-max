"""تست‌های نگاشت ستون، پاک‌سازی و پروفایل."""

from __future__ import annotations

import pandas as pd

from mktcore.ingest.cleaning import clean_frame
from mktcore.ingest.mapper import SchemaMapper
from mktcore.ingest.profiler import profile_frame
from mktcore.ingest.schema import ColumnRole


def test_auto_detect_on_synthetic(raw_sales):
    sugg = SchemaMapper().auto_detect(raw_sales)
    assert sugg.is_valid, sugg.missing_required
    assert sugg.mapping[ColumnRole.DATE] == "تاریخ"
    assert sugg.mapping[ColumnRole.REVENUE] == "مبلغ کل"
    assert sugg.mapping[ColumnRole.QUANTITY] == "تعداد"
    assert sugg.mapping[ColumnRole.CUSTOMER_ID] == "کد مشتری"


def test_apply_renames_to_standard(raw_sales):
    mapper = SchemaMapper()
    sugg = mapper.auto_detect(raw_sales)
    std = mapper.apply(raw_sales, sugg.mapping)
    assert "date" in std.columns
    assert "revenue" in std.columns
    assert len(std) == len(raw_sales)


def test_messy_cleaning(messy_frame):
    mapper = SchemaMapper()
    sugg = mapper.auto_detect(messy_frame)
    std = mapper.apply(messy_frame, sugg.mapping)
    cleaned = clean_frame(std)

    # رقم فارسی و جداکننده درست تبدیل شده
    assert cleaned["revenue"].dtype.kind == "f"
    assert cleaned.loc[cleaned.index[0], "revenue"] == 2_400_000
    # تاریخ جلالی تجزیه شده (به Timestamp)
    assert pd.api.types.is_datetime64_any_dtype(cleaned["date"])
    # سفارش تکراری A-2 حذف شده
    assert cleaned["order_id"].is_unique
    # درآمد گم‌شده از تعداد×قیمت مشتق شده (ردیف A-3: 3×500000)
    a3 = cleaned[cleaned["order_id"] == "A-3"]
    assert not a3.empty
    assert a3.iloc[0]["revenue"] == 1_500_000


def test_profiler_warnings(messy_frame):
    mapper = SchemaMapper()
    std = mapper.apply(messy_frame, mapper.auto_detect(messy_frame).mapping)
    cleaned = clean_frame(std)
    rep = profile_frame(cleaned)
    assert rep.n_rows == 3  # یکی تکراری حذف شد
    assert rep.dropped_duplicates == 1
    assert any("کم" in w or "کوتاه" in w for w in rep.warnings)
