"""تصادفی‌سازی بازوی آزمایش — قطعی، طبقه‌بندی‌شده، در سطح مشتری.

## سه تصمیم و دلیلشان

**۱. واحد تصادفی‌سازی مشتری است، نه پیام.** اگر یک مشتری برای فرصت «الف» در
گروه آزمایش و برای فرصت «ب» در گروه کنترل باشد، تماسِ اول رفتار او را در
اندازه‌گیری دوم آلوده می‌کند و هر دو عدد بی‌معنا می‌شوند (§۲۲.۱).

**۲. تخصیص از هش ساخته می‌شود، نه از `random`.** با `random.shuffle` نتیجه به
ترتیب اجرا و وضعیت سراسری مولد تصادفی وابسته می‌شد؛ اجرای دوباره بازوها را
عوض می‌کرد و کمپینِ در جریان خراب می‌شد. هش `campaign|customer` همیشه همان
عدد را می‌دهد.

**۳. تخصیص درون طبقه انجام می‌شود.** گروه کنترلِ ۱۰٪ که تصادفاً همه‌اش از
مشتریان کم‌ارزش درآمده باشد، مقایسه را بی‌اعتبار می‌کند. تخصیص درون هر
طبقه (سگمنت/حالت) تضمین می‌کند هر دو گروه ترکیب مشابهی داشته باشند.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

ARM_TREATMENT = "treatment"
ARM_CONTROL = "control"

# دقت هش: عدد بزرگ‌تر یعنی نسبت‌های دقیق‌تر در گروه‌های کوچک
_HASH_BUCKETS = 10_000


@dataclass(frozen=True)
class ArmAssignment:
    customer_key: str
    arm: str
    stratum: str

    @property
    def is_control(self) -> bool:
        return self.arm == ARM_CONTROL


def _bucket(campaign_key: str, customer_key: str) -> int:
    """سطل قطعیِ ۰ تا ۹۹۹۹ برای این جفت کمپین/مشتری.

    کلیدِ کمپین در هش هست تا یک مشتری در کمپین‌های مختلف همیشه کنترل نشود —
    وگرنه همان چند نفر برای همیشه از همه‌ی تماس‌ها محروم می‌شدند.
    """
    raw = f"{campaign_key}|{customer_key}".encode()
    return int.from_bytes(hashlib.sha256(raw).digest()[:4], "big") % _HASH_BUCKETS


def assign_arms(
    customers: dict[str, str],
    *,
    campaign_key: str,
    holdout_pct: int = 10,
) -> list[ArmAssignment]:
    """تخصیص بازو به هر مشتری.

    `customers` نگاشت «کلید مشتری → طبقه» است (سگمنت یا حالت چرخه‌ی عمر).
    `holdout_pct` صفر یعنی همه در گروه آزمایش — یعنی «فقط انتساب، بدون ادعای
    اثر»؛ لایه‌ی گزارش این را صریح اعلام می‌کند.
    """
    holdout = max(0, min(100, int(holdout_pct)))
    if holdout == 0:
        return [
            ArmAssignment(key, ARM_TREATMENT, stratum)
            for key, stratum in sorted(customers.items())
        ]

    by_stratum: dict[str, list[str]] = {}
    for key, stratum in customers.items():
        by_stratum.setdefault(str(stratum or "—"), []).append(str(key))

    out: list[ArmAssignment] = []
    for stratum, keys in sorted(by_stratum.items()):
        # مرتب‌سازی بر پایه‌ی سطلِ هش: قطعی، ولی بی‌ارتباط با هر ترتیب معناداری
        ordered = sorted(keys, key=lambda k: (_bucket(campaign_key, k), k))
        # گِرد کردن به بالا تا در گروه‌های کوچک هم دست‌کم یک نفر کنترل بماند
        n_control = min(len(ordered) - 1, -(-len(ordered) * holdout // 100))
        n_control = max(0, n_control)
        for index, key in enumerate(ordered):
            arm = ARM_CONTROL if index < n_control else ARM_TREATMENT
            out.append(ArmAssignment(key, arm, stratum))
    return sorted(out, key=lambda a: a.customer_key)


def control_share(assignments: list[ArmAssignment]) -> float:
    if not assignments:
        return 0.0
    return sum(1 for a in assignments if a.is_control) / len(assignments)


__all__ = [
    "ARM_CONTROL",
    "ARM_TREATMENT",
    "ArmAssignment",
    "assign_arms",
    "control_share",
]
