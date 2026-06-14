"""تشخیص خودکار نگاشت ستون‌ها به نقش‌های استاندارد و اعمال آن.

این ماژول دفاع اصلی در برابر «ستون‌های متغیر / اکسل کثیف» است: ابتدا نام
ستون‌ها را با مترادف‌های فارسی/انگلیسی تطبیق می‌دهد، سپس با heuristic روی
مقادیر ستون حدس را تقویت یا تصحیح می‌کند. کاربر می‌تواند نگاشت پیشنهادی را
در رابط کاربری بازنویسی کند.
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field

import pandas as pd

from ..locale_fa import COLUMN_SYNONYMS, normalize_digits
from .schema import (
    CATEGORICAL_ROLES,
    NUMERIC_ROLES,
    REQUIRED_ROLES,
    ColumnRole,
    standard_column,
)

# نگاشت = نقش -> نام ستون اصلی در DataFrame ورودی
Mapping = dict[ColumnRole, str]


@dataclass
class MappingSuggestion:
    """نتیجه‌ی تشخیص خودکار نگاشت."""

    mapping: Mapping = field(default_factory=dict)
    scores: dict[ColumnRole, float] = field(default_factory=dict)
    unmapped_columns: list[str] = field(default_factory=list)

    @property
    def missing_required(self) -> list[ColumnRole]:
        return [r for r in REQUIRED_ROLES if r not in self.mapping]

    @property
    def is_valid(self) -> bool:
        return not self.missing_required


def _norm(text: str) -> str:
    """نرمال‌سازی نام ستون برای تطبیق: حروف کوچک، حذف فاصله‌های اضافی."""
    text = normalize_digits(str(text)).strip().lower()
    text = text.replace("ي", "ی").replace("ك", "ک")
    text = re.sub(r"[_\-/.]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def _name_score(col_norm: str, synonyms: list[str]) -> float:
    """امتیاز تطبیق نام ستون با فهرست مترادف‌ها (۰ تا ۱)."""
    best = 0.0
    for syn in synonyms:
        s = _norm(syn)
        if col_norm == s:
            best = max(best, 1.0)
        elif col_norm.startswith(s + " ") or col_norm.endswith(" " + s):
            best = max(best, 0.9)
        elif s in col_norm.split():
            best = max(best, 0.8)
        elif s in col_norm:
            best = max(best, 0.6)
    return best


def _looks_numeric(series: pd.Series) -> float:
    """نسبت مقادیری که پس از نرمال‌سازی عددی قابل تبدیل‌اند."""
    sample = series.dropna().astype(str).head(200)
    if sample.empty:
        return 0.0
    ok = 0
    for v in sample:
        cleaned = normalize_digits(v).replace(",", "").strip()
        cleaned = re.sub(r"[^\d.\-]", "", cleaned)
        if cleaned not in ("", "-", "."):
            try:
                float(cleaned)
                ok += 1
            except ValueError:
                pass
    return ok / len(sample)


def _looks_date(series: pd.Series) -> float:
    """نسبت مقادیری که به‌صورت تاریخ قابل تجزیه‌اند (میلادی یا جلالی)."""
    sample = series.dropna().astype(str).head(200)
    if sample.empty:
        return 0.0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        parsed = pd.to_datetime(sample, errors="coerce", dayfirst=False, format="mixed")
    rate = parsed.notna().mean()
    if rate < 0.5:
        # احتمال تاریخ جلالی به‌صورت متن YYYY/MM/DD
        jalali = sample.apply(
            lambda v: bool(re.match(r"^\s*1[34]\d{2}[/\-.]\d{1,2}[/\-.]\d{1,2}", normalize_digits(v)))
        ).mean()
        rate = max(rate, jalali)
    return float(rate)


def _value_role_hint(series: pd.Series, n_rows: int) -> dict[ColumnRole, float]:
    """امتیاز نقش بر اساس ویژگی مقادیر (heuristic)."""
    hints: dict[ColumnRole, float] = {}
    date_score = _looks_date(series)
    if date_score > 0.6:
        hints[ColumnRole.DATE] = date_score

    num_score = _looks_numeric(series)
    if num_score > 0.7:
        # تفکیک نقش‌های عددی با آماره‌ها
        cleaned = (
            series.dropna().astype(str).map(
                lambda v: re.sub(r"[^\d.\-]", "", normalize_digits(v).replace(",", ""))
            )
        )
        nums = pd.to_numeric(cleaned, errors="coerce").dropna()
        if not nums.empty:
            mx = nums.max()
            # مقادیر کوچک بین ۰ و ۱ → احتمال تخفیف (نسبت)
            if 0.0 <= nums.min() and mx <= 1.0:
                hints[ColumnRole.DISCOUNT] = 0.5 * num_score
            # اعداد صحیح کوچک → احتمال تعداد
            if (nums == nums.round()).mean() > 0.9 and mx < 1000:
                hints[ColumnRole.QUANTITY] = 0.55 * num_score
            # اعداد بزرگ → احتمال درآمد/قیمت/هزینه
            if mx >= 1000:
                hints[ColumnRole.REVENUE] = 0.45 * num_score

    # کاردینالیتی بالا با مقدار متنی → احتمال شناسه
    nunique = series.nunique(dropna=True)
    if n_rows > 0:
        uniqueness = nunique / n_rows
        if uniqueness > 0.9 and num_score < 0.8:
            hints[ColumnRole.ORDER_ID] = 0.4
        elif 0.05 < uniqueness < 0.9 and num_score < 0.5:
            hints[ColumnRole.CUSTOMER_ID] = 0.25
    return hints


class SchemaMapper:
    """تشخیص و اعمال نگاشت ستون‌ها."""

    NAME_WEIGHT = 0.7
    VALUE_WEIGHT = 0.3
    THRESHOLD = 0.35

    def auto_detect(self, df: pd.DataFrame) -> MappingSuggestion:
        """نگاشت پیشنهادی را بر اساس نام و مقدار ستون‌ها تولید می‌کند."""
        n_rows = len(df)
        # امتیاز هر (ستون، نقش)
        cell_scores: dict[str, dict[ColumnRole, float]] = {}
        for col in df.columns:
            col_norm = _norm(col)
            value_hints = _value_role_hint(df[col], n_rows)
            role_scores: dict[ColumnRole, float] = {}
            for role in ColumnRole:
                name_s = _name_score(col_norm, COLUMN_SYNONYMS.get(role.value, []))
                val_s = value_hints.get(role, 0.0)
                score = self.NAME_WEIGHT * name_s + self.VALUE_WEIGHT * val_s
                if score > 0:
                    role_scores[role] = round(score, 4)
            cell_scores[str(col)] = role_scores

        # تخصیص حریصانه: بالاترین امتیازها اول، هر نقش و هر ستون یک‌بار
        candidates: list[tuple[float, str, ColumnRole]] = []
        for col, roles in cell_scores.items():
            for role, score in roles.items():
                candidates.append((score, col, role))
        candidates.sort(reverse=True)

        mapping: Mapping = {}
        scores: dict[ColumnRole, float] = {}
        used_cols: set[str] = set()
        for score, col, role in candidates:
            if score < self.THRESHOLD:
                break
            if role in mapping or col in used_cols:
                continue
            mapping[role] = col
            scores[role] = score
            used_cols.add(col)

        unmapped = [str(c) for c in df.columns if str(c) not in used_cols]
        return MappingSuggestion(mapping=mapping, scores=scores, unmapped_columns=unmapped)

    def apply(self, df: pd.DataFrame, mapping: Mapping) -> pd.DataFrame:
        """نگاشت را اعمال می‌کند: انتخاب ستون‌ها و تغییرنام به نام‌های استاندارد.

        فقط نقش‌های موجود در نگاشت نگه داشته می‌شوند. اعتبارسنجی حداقل
        نقش‌های ضروری انجام می‌شود. (تبدیل نوع در ماژول cleaning است.)
        """
        missing = [r.value for r in REQUIRED_ROLES if r not in mapping]
        if missing:
            raise ValueError(
                f"نگاشت ناقص است؛ نقش‌های ضروری یافت نشدند: {', '.join(missing)}"
            )

        rename = {}
        for role, col in mapping.items():
            if col not in df.columns:
                raise ValueError(f"ستون «{col}» برای نقش {role.value} در داده وجود ندارد.")
            rename[col] = standard_column(role)

        out = df[list(rename.keys())].rename(columns=rename).copy()
        return out


__all__ = ["SchemaMapper", "MappingSuggestion", "Mapping", "NUMERIC_ROLES", "CATEGORICAL_ROLES"]
