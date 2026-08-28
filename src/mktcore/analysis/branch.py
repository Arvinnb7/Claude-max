"""شعبه‌ی محتملِ مشتری — §۲۴.۵.

## چه چیزی این ماژول می‌گوید و چه چیزی نمی‌گوید

می‌گوید: «این مشتری تا امروز بیشتر از کدام شعبه خرید کرده و چه سهمی از
خریدهایش آنجا بوده.» نمی‌گوید: «این مشتری دفعه‌ی بعد از آنجا می‌خرد.»
تفاوتشان مهم است — دومی یک پیش‌بینی است و شواهدش را نداریم.

## چرا سهم و شمار هر دو برمی‌گردند

«شعبه‌ی مرکزی» با ۹۰٪ از ۲۰ سفارش، با «شعبه‌ی مرکزی» با ۱۰۰٪ از ۱ سفارش زمین
تا آسمان فرق دارد. برگرداندنِ فقط نامِ شعبه، این دو را یکسان نشان می‌دهد. پس
درجه‌ی اتکا صریح است و اگر شواهد کم باشد، **صریحاً کم** گزارش می‌شود.

## نبودِ ستون شعبه

بسیاری از فایل‌های فروش اصلاً ستون شعبه ندارند. آن‌وقت `branch=None` با دلیلِ
فارسی برمی‌گردد — نه «شعبه‌ی نامشخص» که مثل یک شعبه‌ی واقعی به‌نظر برسد.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

__all__ = ["BranchAffinity", "likely_branch"]

# زیر این تعداد سفارش، سهمِ درصدی گمراه‌کننده است.
MIN_ORDERS_FOR_CONFIDENCE = 3
# سهمی که «غالب» حساب می‌شود.
DOMINANT_SHARE = 0.6


@dataclass(frozen=True)
class BranchAffinity:
    branch: str | None
    order_count: int
    total_orders: int
    share: float | None
    confidence: str          # "بالا" / "متوسط" / "پایین" / "نامشخص"
    note_fa: str

    def to_dict(self) -> dict:
        return {
            "branch": self.branch,
            "order_count": self.order_count,
            "total_orders": self.total_orders,
            "share": self.share,
            "confidence": self.confidence,
            "note_fa": self.note_fa,
        }


def likely_branch(branches: list[str | None]) -> BranchAffinity:
    """پرتکرارترین شعبه در سفارش‌های یک مشتری.

    ورودی فهرستِ شعبه‌ی هر سفارش است (با `None` برای سفارش‌های بی‌شعبه).
    """
    known = [str(b).strip() for b in branches if b and str(b).strip()]
    total = len(branches)

    if not known:
        return BranchAffinity(
            branch=None, order_count=0, total_orders=total, share=None,
            confidence="نامشخص",
            note_fa=(
                "ستون شعبه در داده‌ی این مشتری وجود ندارد یا خالی است، پس شعبه‌ی "
                "محتمل تعیین نشد."
            ),
        )

    counts = Counter(known)
    # تساوی با نامِ الفبایی شکسته می‌شود تا خروجی بین دو اجرا عوض نشود؛
    # ترتیبِ نامعین یعنی همان مشتری امروز «شعبه ۱» و فردا «شعبه ۲» باشد.
    top, count = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    share = count / len(known)

    if len(known) < MIN_ORDERS_FOR_CONFIDENCE:
        confidence = "پایین"
        note = (
            f"فقط {len(known)} سفارشِ دارای شعبه ثبت شده است؛ این عدد برای "
            "نتیجه‌گیری کم است."
        )
    elif share >= DOMINANT_SHARE:
        confidence = "بالا"
        note = (
            f"{count} از {len(known)} سفارشِ دارای شعبه از «{top}» بوده است."
        )
    else:
        confidence = "متوسط"
        note = (
            f"خریدها بین چند شعبه پخش‌اند؛ «{top}» با {count} از {len(known)} "
            "سفارش بیشترین سهم را دارد ولی غالب نیست."
        )

    if len(known) < total:
        note += f" ({total - len(known)} سفارش بدون شعبه ثبت شده است.)"

    return BranchAffinity(
        branch=top, order_count=count, total_orders=total,
        share=round(share, 4), confidence=confidence, note_fa=note,
    )
