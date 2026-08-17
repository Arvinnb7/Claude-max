"""محاسبه‌ی اثر افزوده به‌صورت سلولی، با انقباض به‌سمت والد.

## چرا انقباض لازم است

سلولی با ۶ نفر آزمایش و ۲ نفر کنترل ممکن است اثر «۵۰٪» نشان دهد. آن عدد نوفه
است، نه یافته. اگر خام استفاده شود، رتبه‌بندی روی تصادف سوار می‌شود و هر بار
تکان می‌خورد.

راه‌حل استاندارد: **انقباض به‌سمت تخمینِ والد** به‌نسبتِ اندازه‌ی نمونه:

```
اثر_نهایی = w × اثر_سلول + (1−w) × اثر_والد
w = n / (n + k)
```

سلول کوچک ⇒ `w→0` ⇒ تقریباً همان والد. سلول بزرگ ⇒ `w→1` ⇒ اثر خودش.
هیچ آستانه‌ی سخت و پرشی وجود ندارد؛ انتقال نرم است.

همین الگو از قبل در `analysis/purchase_cycle.py` برای مدل گاما به‌کار رفته —
سبک آماریِ موجودِ پروژه، نه چیز تازه.

## سلسله‌مراتب

```
(نوع فرصت × حالت چرخه‌ی عمر)  →  (نوع فرصت)  →  کل  →  بدون تعدیل
```

آخرین پله مهم است: وقتی هیچ داده‌ی آزمایشی نیست، ضریب **۱٫۰** است و رتبه‌بندی
**دقیقاً** مثل امروز کار می‌کند. یعنی این قابلیت هرگز چیزی را بدتر نمی‌کند.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# ثابت انقباض: اندازه‌ی نمونه‌ای که در آن، وزنِ سلول و والد برابر می‌شود.
# ۵۰ انتخاب شده چون در همین حدود است که یک نسبت با نرخ پایه‌ی معمول (~۳۰٪)
# خطای استانداردی به‌قدر کافی کوچک پیدا می‌کند که سیگنالش از نوفه بیشتر باشد.
SHRINKAGE_K = 50.0

# کمینه‌ی مشاهده برای اینکه یک سلول اصلاً تخمین بدهد (در هر بازو).
# زیر این عدد، سلول کاملاً به والد واگذار می‌شود.
MIN_CELL_OBSERVATIONS = 10

# پایه‌ی تخمین — در شواهد هر فرصت ثبت می‌شود تا هیچ جابه‌جایی‌ای بی‌توضیح نباشد
BASIS_CELL = "cell"
BASIS_KIND = "kind"
BASIS_GLOBAL = "global"
BASIS_NONE = "none"

BASIS_LABELS_FA = {
    BASIS_CELL: "اندازه‌گیری‌شده برای همین گروه",
    BASIS_KIND: "اندازه‌گیری‌شده برای همین نوع اقدام",
    BASIS_GLOBAL: "میانگین همه‌ی کمپین‌ها",
    BASIS_NONE: "بدون داده‌ی آزمایشی — رتبه‌بندی مثل قبل",
}

_Z = 1.959963985

# جمله‌ی توضیحیِ ضریب مرجع — در پاسخ API می‌آید تا عدد «ضریب» بی‌توضیح نماند
UPLIFT_REFERENCE_NOTE_FA = (
    "ضریب رتبه‌بندی نسبت به یک اثرِ مرجعِ ۱۰ واحد درصدی سنجیده می‌شود: گروهی با "
    "اثرِ ۲۰ واحد درصد، ضریب ۲ می‌گیرد. ارزشِ ریالیِ گزارش‌شده هرگز با این ضریب "
    "تغییر نمی‌کند — فقط ترتیب فهرست عوض می‌شود."
)


@dataclass(frozen=True)
class Observation:
    """یک مشاهده‌ی آزمایشی: یک مشتری در یک بازو، خرید کرد یا نکرد."""

    kind: str
    lifecycle_state: str | None
    arm: str
    converted: bool
    revenue_rial: int = 0

    @property
    def cell_key(self) -> tuple[str, str]:
        return (self.kind, self.lifecycle_state or "—")


@dataclass
class UpliftCell:
    """اثر اندازه‌گیری‌شده‌ی یک گروه، با شواهد و عدم‌قطعیتش."""

    kind: str
    lifecycle_state: str
    n_treatment: int = 0
    n_control: int = 0
    conv_treatment: int = 0
    conv_control: int = 0

    # پس از انقباض پر می‌شوند
    raw_uplift: float = 0.0
    shrunk_uplift: float = 0.0
    basis: str = BASIS_NONE
    ci: tuple[float, float] | None = None

    @property
    def rate_treatment(self) -> float:
        return self.conv_treatment / self.n_treatment if self.n_treatment else 0.0

    @property
    def rate_control(self) -> float:
        return self.conv_control / self.n_control if self.n_control else 0.0

    @property
    def has_enough_data(self) -> bool:
        return (self.n_treatment >= MIN_CELL_OBSERVATIONS
                and self.n_control >= MIN_CELL_OBSERVATIONS)

    @property
    def significantly_useless(self) -> bool:
        """آیا با اطمینان می‌دانیم تماس با این گروه بی‌فایده (یا مضر) است؟

        شرط سخت‌گیرانه است: کل بازه‌ی اطمینان باید ≤ صفر باشد. حدسِ «احتمالاً
        بی‌فایده» کافی نیست — حذفِ یک گروه از تماس، تصمیم پرهزینه‌ای است.
        """
        return bool(self.has_enough_data and self.ci and self.ci[1] <= 0)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "lifecycle_state": self.lifecycle_state,
            "n_treatment": self.n_treatment,
            "n_control": self.n_control,
            "rate_treatment": round(self.rate_treatment, 4),
            "rate_control": round(self.rate_control, 4),
            "raw_uplift": round(self.raw_uplift, 4),
            "uplift": round(self.shrunk_uplift, 4),
            "basis": self.basis,
            "basis_label": BASIS_LABELS_FA.get(self.basis, self.basis),
            "ci": list(self.ci) if self.ci else None,
            "has_enough_data": self.has_enough_data,
            "useless": self.significantly_useless,
        }


@dataclass
class UpliftTable:
    """جدول اثرِ آموخته‌شده + تخمین‌های والد برای بازگشت."""

    cells: dict[tuple[str, str], UpliftCell] = field(default_factory=dict)
    by_kind: dict[str, float] = field(default_factory=dict)
    global_uplift: float | None = None
    n_observations: int = 0

    @property
    def available(self) -> bool:
        return self.n_observations > 0

    def lookup(self, kind: str, lifecycle_state: str | None) -> tuple[float, str]:
        """اثرِ قابل‌استفاده برای این ترکیب + پایه‌ی آن.

        بازگشت پله‌پله تا برسیم به «بدون تعدیل» که همان رفتار امروز است.
        """
        cell = self.cells.get((kind, lifecycle_state or "—"))
        if cell is not None and cell.has_enough_data:
            return cell.shrunk_uplift, cell.basis
        if kind in self.by_kind:
            return self.by_kind[kind], BASIS_KIND
        if self.global_uplift is not None:
            return self.global_uplift, BASIS_GLOBAL
        return 0.0, BASIS_NONE

    def is_useless(self, kind: str, lifecycle_state: str | None) -> UpliftCell | None:
        """اگر با اطمینان می‌دانیم تماس با این گروه بی‌فایده است، سلولش را بده."""
        cell = self.cells.get((kind, lifecycle_state or "—"))
        return cell if cell is not None and cell.significantly_useless else None

    def to_dict(self) -> dict:
        return {
            "available": self.available,
            "n_observations": self.n_observations,
            "global_uplift": (
                None if self.global_uplift is None else round(self.global_uplift, 4)
            ),
            "by_kind": {k: round(v, 4) for k, v in sorted(self.by_kind.items())},
            "cells": [
                c.to_dict() for c in sorted(
                    self.cells.values(), key=lambda x: -x.shrunk_uplift,
                )
            ],
        }


def _diff_ci(rate_t: float, n_t: int, rate_c: float, n_c: int) -> tuple[float, float]:
    """بازه‌ی اطمینان اختلاف دو نسبت — همان ریاضیِ `campaigns/analysis.py`."""
    if not n_t or not n_c:
        return (0.0, 0.0)
    se = math.sqrt(rate_t * (1 - rate_t) / n_t + rate_c * (1 - rate_c) / n_c)
    diff = rate_t - rate_c
    return (diff - _Z * se, diff + _Z * se)


def _shrink(raw: float, parent: float, n: int, k: float = SHRINKAGE_K) -> float:
    """انقباض تخمین سلول به‌سمت والد، به‌نسبت اندازه‌ی نمونه."""
    weight = n / (n + k)
    return weight * raw + (1 - weight) * parent


def compute_uplift_table(observations: list[Observation]) -> UpliftTable:
    """ساخت جدول اثر از مشاهده‌های آزمایشی.

    تابع خالص: ورودی فهرست مشاهده، خروجی جدول. هیچ I/O و هیچ وابستگی به دیتابیس.
    """
    table = UpliftTable(n_observations=len(observations))
    if not observations:
        return table

    # ۱) تخمین کل (والدِ نهایی)
    table.global_uplift = _pooled_uplift(observations)

    # ۲) تخمین به‌ازای نوع اقدام (والدِ میانی)
    by_kind: dict[str, list[Observation]] = {}
    for obs in observations:
        by_kind.setdefault(obs.kind, []).append(obs)
    for kind, group in by_kind.items():
        estimate = _pooled_uplift(group)
        if estimate is not None:
            # خودِ تخمین نوع هم به‌سمت کل منقبض می‌شود
            n_min = _min_arm_size(group)
            table.by_kind[kind] = _shrink(
                estimate, table.global_uplift or 0.0, n_min,
            )

    # ۳) سلول‌ها
    by_cell: dict[tuple[str, str], list[Observation]] = {}
    for obs in observations:
        by_cell.setdefault(obs.cell_key, []).append(obs)

    for (kind, state), group in by_cell.items():
        cell = UpliftCell(kind=kind, lifecycle_state=state)
        for obs in group:
            if obs.arm == "control":
                cell.n_control += 1
                cell.conv_control += int(obs.converted)
            else:
                cell.n_treatment += 1
                cell.conv_treatment += int(obs.converted)

        cell.raw_uplift = cell.rate_treatment - cell.rate_control
        cell.ci = _diff_ci(
            cell.rate_treatment, cell.n_treatment,
            cell.rate_control, cell.n_control,
        )
        parent = table.by_kind.get(kind, table.global_uplift or 0.0)
        if cell.has_enough_data:
            cell.shrunk_uplift = _shrink(
                cell.raw_uplift, parent, min(cell.n_treatment, cell.n_control),
            )
            cell.basis = BASIS_CELL
        else:
            # نمونه‌ی ناکافی → کاملاً به والد واگذار می‌شود
            cell.shrunk_uplift = parent
            cell.basis = BASIS_KIND if kind in table.by_kind else BASIS_GLOBAL
        table.cells[(kind, state)] = cell

    return table


def _pooled_uplift(observations: list[Observation]) -> float | None:
    """اثر تجمیعی یک گروه؛ None اگر یکی از بازوها خالی باشد."""
    n_t = n_c = c_t = c_c = 0
    for obs in observations:
        if obs.arm == "control":
            n_c += 1
            c_c += int(obs.converted)
        else:
            n_t += 1
            c_t += int(obs.converted)
    if not n_t or not n_c:
        return None
    return c_t / n_t - c_c / n_c


def _min_arm_size(observations: list[Observation]) -> int:
    n_t = sum(1 for o in observations if o.arm != "control")
    n_c = sum(1 for o in observations if o.arm == "control")
    return min(n_t, n_c)


__all__ = [
    "UPLIFT_REFERENCE_NOTE_FA",
    "BASIS_CELL",
    "BASIS_GLOBAL",
    "BASIS_KIND",
    "BASIS_LABELS_FA",
    "BASIS_NONE",
    "MIN_CELL_OBSERVATIONS",
    "SHRINKAGE_K",
    "Observation",
    "UpliftCell",
    "UpliftTable",
    "compute_uplift_table",
]
