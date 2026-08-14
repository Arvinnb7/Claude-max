"""شکاف توسعه‌ی درآمد — تابع خالص روی DataFrame.

ادعای مرکزی: شکاف فقط وقتی گزارش می‌شود که **اکثریتِ گروه همتایِ به‌اندازه‌ی
کافی بزرگ** آن دسته را می‌خرند. در غیر این صورت سکوت — نه عددِ ضعیف.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from mktcore.analysis.expansion_gap import (  # noqa: E402
    MIN_PEERS,
    compute_expansion_gap,
)


def _frame(rows: list[tuple]) -> pd.DataFrame:
    """(مشتری، دسته، مبلغ) → فریم استاندارد."""
    return pd.DataFrame(rows, columns=["customer_id", "category", "revenue"])


def _uniform_market(
    n_customers: int, categories: tuple[str, ...], *, amount: float = 100_000,
) -> list[tuple]:
    return [
        (f"C{i}", cat, amount)
        for i in range(n_customers)
        for cat in categories
    ]


def test_customer_missing_a_universal_category_gets_a_gap():
    """۱۹ نفر هر دو دسته را می‌خرند، یک نفر فقط یکی → شکاف برای همان یک نفر."""
    rows = _uniform_market(19, ("لبنیات", "نوشیدنی"))
    rows.append(("C19", "لبنیات", 100_000))  # نوشیدنی نمی‌خرد
    result = compute_expansion_gap(_frame(rows))

    assert result.available
    gaps = result.for_customer("C19")
    assert len(gaps) == 1
    assert gaps[0].category == "نوشیدنی"
    assert gaps[0].gap_value == 100_000
    assert gaps[0].customer_revenue == 0.0


def test_no_gap_for_customers_who_buy_everything():
    rows = _uniform_market(20, ("لبنیات", "نوشیدنی"))
    result = compute_expansion_gap(_frame(rows))
    assert result.for_customer("C5") == []


def test_minority_category_is_taste_not_a_gap():
    """اگر فقط ۳ نفر از ۲۰ یک دسته را بخرند، نخریدنِ بقیه شکاف نیست."""
    rows = _uniform_market(20, ("لبنیات",))
    rows += [(f"C{i}", "خاویار", 5_000_000) for i in range(3)]
    result = compute_expansion_gap(_frame(rows))

    assert all(g.category != "خاویار" for g in result.gaps)


def test_small_peer_group_produces_no_gap():
    """با گروه همتای کوچک، میانه یک عدد اتفاقی است — سکوت بهتر از حدس است."""
    rows = _uniform_market(MIN_PEERS - 3, ("الف", "ب"))
    rows.append(("CX", "الف", 100_000))
    result = compute_expansion_gap(_frame(rows))

    assert not result.available
    assert "همتای به‌اندازه‌ی کافی بزرگ" in result.skipped_reason_fa


def test_median_resists_a_wholesale_outlier():
    """یک عمده‌فروش در گروه همتا نباید برای همه شکافِ جعلی بسازد."""
    rows = _uniform_market(19, ("لبنیات", "نوشیدنی"), amount=100_000)
    rows.append(("BULK", "لبنیات", 100_000))
    rows.append(("BULK", "نوشیدنی", 500_000_000))  # ناهنجاری
    rows.append(("C19", "لبنیات", 100_000))
    result = compute_expansion_gap(_frame(rows))

    gap = result.for_customer("C19")[0]
    # میانه نزدیک ۱۰۰ هزار می‌ماند، نه کشیده‌شده به سمت ۵۰۰ میلیون
    assert gap.gap_value == 100_000


def test_confidence_reflects_peer_size_and_adoption():
    strong = compute_expansion_gap(_frame(
        _uniform_market(40, ("الف", "ب")) + [("CX", "الف", 100_000)]
    ))
    assert strong.for_customer("CX")[0].confidence == "بالا"


def test_evidence_text_names_the_peer_group():
    rows = _uniform_market(19, ("الف", "ب"))
    rows.append(("CX", "الف", 100_000))
    gap = compute_expansion_gap(_frame(rows)).for_customer("CX")[0]

    assert "مشتری مشابه" in gap.evidence_fa
    assert "میانه" in gap.evidence_fa
    assert str(gap.peer_count) in gap.evidence_fa


def test_top_n_per_customer_is_capped():
    """فهرست بلندِ شکاف غیرقابل‌اقدام است."""
    categories = tuple(f"دسته{i}" for i in range(8))
    rows = _uniform_market(20, categories)
    rows.append(("CX", "دسته0", 100_000))  # هفت دسته را نمی‌خرد
    result = compute_expansion_gap(_frame(rows), top_per_customer=3)

    assert len(result.for_customer("CX", limit=99)) == 3


def test_gaps_are_ranked_by_value():
    rows = _uniform_market(20, ("ارزان",))
    rows += [(f"C{i}", "گران", 900_000) for i in range(20)]
    rows += [(f"C{i}", "متوسط", 400_000) for i in range(20)]
    rows.append(("CX", "ارزان", 50_000))
    gaps = compute_expansion_gap(_frame(rows)).for_customer("CX", limit=5)

    values = [g.gap_value for g in gaps]
    assert values == sorted(values, reverse=True)
    assert gaps[0].category == "گران"


def test_segments_split_the_peer_pool():
    """مشتری «قهرمان» با «خواب‌رفته» مقایسه نمی‌شود."""
    rows = _uniform_market(24, ("پایه",))
    rows += [(f"C{i}", "لوکس", 800_000) for i in range(12)]  # فقط نیمه‌ی اول
    frame = _frame(rows)
    segments = pd.DataFrame(
        {"segment_fa": ["قهرمان"] * 12 + ["خواب‌رفته"] * 12},
        index=[f"C{i}" for i in range(24)],
    )

    with_segments = compute_expansion_gap(frame, segments, min_peers=10)
    # درون گروه «قهرمان» همه لوکس می‌خرند → شکافی نیست؛
    # درون «خواب‌رفته» هیچ‌کس نمی‌خرد → پذیرش صفر، باز هم شکافی نیست
    assert all(g.category != "لوکس" for g in with_segments.gaps)


def test_falls_back_to_product_when_category_missing():
    rows = _uniform_market(19, ("کالای الف", "کالای ب"))
    rows.append(("CX", "کالای الف", 100_000))
    frame = _frame(rows).rename(columns={"category": "product"})

    result = compute_expansion_gap(frame)
    assert result.dimension == "کالا"
    assert result.for_customer("CX")


def test_empty_and_degenerate_inputs_are_safe():
    empty = compute_expansion_gap(pd.DataFrame())
    assert not empty.available
    assert empty.skipped_reason_fa

    single_category = compute_expansion_gap(_frame(_uniform_market(20, ("تنها",))))
    assert not single_category.available
    assert "دو دسته" in single_category.skipped_reason_fa
