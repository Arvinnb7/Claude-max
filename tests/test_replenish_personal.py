"""آهنگِ خریدِ شخصیِ جفتِ (مشتری، کالا) — §۱۳.۲ پله‌ی ۱، §۱۳.۳، §۱۳.۴.

ادعاها: اعدادِ نمونه‌ی خودِ سند (فاصله‌های ۴۳/۴۷/۴۵، ۴۴ روز گذشته) بازتولید می‌شوند؛
قهرمانِ «میانه‌ی کالا» همین مشتری را نمی‌بیند؛ یک فاصله ⇒ جفت غایب است نه حدس؛
خریدِ انباری فاصله را بلندتر می‌کند؛ داده‌ی بعد از as_of استثنا می‌دهد.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.analysis.cadence_robust import EVIDENCE_PERSONAL_PRODUCT  # noqa: E402
from mktcore.analysis.purchase_cycle import analyze_purchase_cycles  # noqa: E402
from mktcore.analysis.replenish_personal import (  # noqa: E402
    COLUMNS,
    LEDGER_COLUMNS,
    personal_cadence_table,
)
from mktcore.features.point_in_time import LeakageError  # noqa: E402
from mktcore.synthetic import CONSUMABLES, generate_replenishment_sales  # noqa: E402

PRODUCT = "غذای خشک ۱۲.۵ کیلویی"
AS_OF = "2024-06-28"


def _frame(rows: list[tuple]) -> pd.DataFrame:
    """ستون‌های استانداردِ فریمِ تحلیل: (customer_id, product, date, revenue, quantity)."""
    frame = pd.DataFrame(rows, columns=["customer_id", "product", "date", "revenue", "quantity"])
    frame["date"] = pd.to_datetime(frame["date"])
    return frame


def _sample_customer(quantities=(1, 1, 1, 1)) -> list[tuple]:
    # فاصله‌ها: ۴۳، ۴۷، ۴۵ روز — نمونه‌ی خودِ سند (§۱۳.۶)
    dates = ("2024-01-01", "2024-02-13", "2024-03-31", "2024-05-15")
    return [("الف", PRODUCT, d, 3_200_000, q) for d, q in zip(dates, quantities, strict=True)]


def _fillers(n: int = 20, cadence: int = 90) -> list[tuple]:
    rows = []
    for i in range(n):
        start = pd.Timestamp("2023-12-20") + pd.Timedelta(days=i % 7)   # آخرین خرید ≤ as_of
        for k in range(3):
            rows.append((f"پرکننده{i}", PRODUCT, (start + pd.Timedelta(days=cadence * k)).date().isoformat(),
                         3_200_000, 1))
    return rows


# ═══════════════════════════════════════════ نمونه‌ی سند: ۴۳/۴۷/۴۵ و ۴۴ روز گذشته
def test_the_spec_example_is_reproduced_number_for_number():
    table = personal_cadence_table(_frame(_sample_customer()), as_of=AS_OF)
    assert list(table.columns) == list(COLUMNS)
    row = table.loc[("الف", PRODUCT)]
    assert row["n_purchases"] == 4 and row["n_gaps"] == 3
    assert row["gaps_days"] == [43, 47, 45]
    # میانه‌ی وزنی با وزن‌های ۰٫۵۶/۰٫۷۵/۱ روی ۴۳/۴۷/۴۵ ⇒ ۴۵ (نیمه‌ی وزن روی ۴۵ می‌گذرد)
    assert row["expected_interval_days"] == 45.0
    assert row["mad_days"] == 2.0
    assert row["uncertainty"] == pytest.approx(2 / 45, abs=1e-4)
    assert row["elapsed_days"] == 44.0
    assert row["overdue_ratio"] == pytest.approx(44 / 45, abs=1e-4)
    assert row["evidence_level_fa"] == EVIDENCE_PERSONAL_PRODUCT
    assert row["confidence_fa"] == "بالا"
    assert row["median_spend"] == 3_200_000.0
    assert row["pack_adjusted_interval_days"] == 45.0 and row["pack_reason_fa"] is None


def test_champion_product_median_misses_what_the_personal_cadence_sees():
    """۲۰ خریدارِ ۹۰روزه میانه‌ی کالا را ۹۰ می‌کنند ⇒ قهرمان «الف» را (۴۶ روز مانده) نمی‌بیند."""
    frame = _frame(_sample_customer() + _fillers())
    # قهرمان: آخرین روزِ داده همان as_of است (فیکسچر طوری چیده شده که max(date) == as_of)
    frame = pd.concat([frame, _frame([("مرجع", "کالای دیگر", AS_OF, 1, 1)])], ignore_index=True)
    champion = analyze_purchase_cycles(frame)
    cycle = {c.product: c for c in champion.product_cycles}[PRODUCT]
    assert cycle.median_cycle_days == 90.0, "میانه‌ی جمعیتِ کالا ۹۰ است، نه ۴۵ِ شخصی"
    assert not [n for n in champion.overdue(1000) if n.customer_id == "الف"], (
        "قهرمان: ۴۴ − ۹۰ = −۴۶ روز، دورتر از پنجره‌ی نزدیکِ ۱۸ روز"
    )
    table = personal_cadence_table(frame, as_of=AS_OF)
    assert table.loc[("الف", PRODUCT), "overdue_ratio"] == pytest.approx(44 / 45, abs=1e-4)
    # پرکننده‌ها هم آهنگِ شخصیِ خودشان (۹۰) را دارند
    assert table.loc[("پرکننده0", PRODUCT), "expected_interval_days"] == 90.0


# ═══════════════════════════════════════════ شواهدِ ناکافی، انباری، نشت
def test_one_gap_pair_is_absent_not_guessed():
    rows = [("ب", PRODUCT, "2024-01-01", 100, 1), ("ب", PRODUCT, "2024-02-15", 100, 1)]
    table = personal_cadence_table(_frame(rows + _sample_customer()), as_of=AS_OF)
    assert ("ب", PRODUCT) not in table.index
    assert ("الف", PRODUCT) in table.index


def test_two_lines_on_one_day_are_one_purchase_and_returns_are_excluded():
    rows = _sample_customer() + [("الف", PRODUCT, "2024-05-15", 3_200_000, 1)]  # خطِ دوم همان روز
    table = personal_cadence_table(_frame(rows), as_of=AS_OF)
    assert table.loc[("الف", PRODUCT), "n_purchases"] == 4
    ledger = pd.DataFrame({
        "customer_id": [1, 1, 1, 1, 1],
        "product_id": [7, 7, 7, 7, 7],
        "line_date": ["2024-01-01", "2024-02-13", "2024-03-31", "2024-05-15", "2024-06-01"],
        "revenue_rial": [10, 10, 10, 10, -10],
        "quantity_milli": [1000] * 5,
        "pack_size_milli": [None] * 5,
        "is_return": [False, False, False, False, True],
    })
    table = personal_cadence_table(ledger, as_of=AS_OF, columns=LEDGER_COLUMNS)
    assert table.loc[(1, 7), "gaps_days"] == [43, 47, 45], "برگشت فاصله نمی‌سازد"
    assert table.loc[(1, 7), "last_purchase"] == "2024-05-15"


def test_a_stock_up_last_purchase_lengthens_the_expected_interval():
    table = personal_cadence_table(_frame(_sample_customer((1, 1, 1, 3))), as_of=AS_OF)
    row = table.loc[("الف", PRODUCT)]
    assert row["expected_interval_days"] == 45.0
    assert row["pack_adjusted_interval_days"] == 135.0, "سه برابرِ مقدارِ معمول ⇒ سه برابر فاصله"
    assert "بیشتر" in row["pack_reason_fa"]
    assert row["overdue_ratio"] == pytest.approx(44 / 135, abs=1e-4)


def test_without_a_quantity_column_no_adjustment_is_guessed():
    frame = _frame(_sample_customer()).drop(columns=["quantity"])
    row = personal_cadence_table(frame, as_of=AS_OF).loc[("الف", PRODUCT)]
    assert row["pack_adjusted_interval_days"] == 45.0
    assert "تعدیلِ اندازه انجام نشد" in row["pack_reason_fa"]


def test_data_after_as_of_raises_leakage():
    with pytest.raises(LeakageError):
        personal_cadence_table(_frame(_sample_customer()), as_of="2024-03-01")


def test_empty_or_columnless_frames_give_an_empty_table():
    assert personal_cadence_table(pd.DataFrame(), as_of=AS_OF).empty
    assert personal_cadence_table(pd.DataFrame({"x": [1]}), as_of=AS_OF).empty


# ═══════════════════════════════════════════ فیکسچرِ replenishment
def test_replenishment_fixture_has_personal_cadences_and_no_cost_by_default():
    frame = generate_replenishment_sales(days=400, n_customers=60)
    assert "بهای تمام شده" not in frame.columns
    assert "بهای تمام شده" in generate_replenishment_sales(days=120, n_customers=10, with_cost=True).columns
    assert set(frame["نام محصول"]) <= set(CONSUMABLES)
    std = frame.rename(columns={"کد مشتری": "customer_id", "نام محصول": "product", "تاریخ": "date",
                                "مبلغ کل": "revenue", "تعداد": "quantity"})
    table = personal_cadence_table(std, as_of=str(std["date"].max().date()))
    assert len(table) > 40
    intervals = table["expected_interval_days"]
    # آهنگ‌های شخصی حولِ {۲۱، ۳۵، ۶۰، ۹۰}‌اند؛ میانه‌ی همه با آهنگِ اکثرِ جفت‌ها فرق دارد
    assert intervals.between(15, 110).mean() > 0.9
    assert (table["n_gaps"] >= 2).all()


def test_time_of_day_on_the_reference_day_is_not_leakage():
    """فریمِ تحلیل می‌تواند ساعت داشته باشد؛ as_of تاریخِ روز است — مقایسه روی روز."""
    rows = [("الف", PRODUCT, f"{d} 14:45", 3_200_000, 1)
            for d in ("2024-01-01", "2024-02-13", "2024-03-31", "2024-05-15")]
    table = personal_cadence_table(_frame(rows), as_of="2024-05-15")
    row = table.loc[("الف", PRODUCT)]
    assert row["elapsed_days"] == 0.0 and row["last_purchase"] == "2024-05-15"
    assert row["gaps_days"] == [43, 47, 45]


def test_ledger_pack_size_does_not_collapse_the_interval():
    """اندازه‌ی بسته (۱۲٫۵ کیلو = ۱۲٬۵۰۰٬۰۰۰ میلی) با مقدارِ «۱ عدد» (۱۰۰۰ میلی) قاطی نمی‌شود:
    نسبتِ آخرین/معمولِ خودِ مشتری از واحد مستقل است."""
    ledger = pd.DataFrame({
        "customer_id": [1, 1, 1, 1],
        "product_id": [7, 7, 7, 7],
        "line_date": ["2024-01-01", "2024-02-13", "2024-03-31", "2024-05-15"],
        "revenue_rial": [10, 10, 10, 10],
        "quantity_milli": [1000, 1000, 1000, 3000],
        "pack_size_milli": [12_500_000] * 4,
        "is_return": [False] * 4,
    })
    row = personal_cadence_table(ledger, as_of=AS_OF, columns=LEDGER_COLUMNS).loc[(1, 7)]
    assert row["expected_interval_days"] == 45.0
    assert row["pack_adjusted_interval_days"] == 135.0, "۳ عدد در برابر ۱ عددِ معمول ⇒ ×۳، نه ×۰٫۰۰۰۰۸"
    assert 0 < row["overdue_ratio"] < 1
