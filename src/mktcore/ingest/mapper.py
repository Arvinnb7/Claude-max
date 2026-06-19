"""تشخیص هوشمند نگاشت ستون‌ها بر اساس «نام + نوع داده + نمونه مقادیر».

برخلاف نسخه‌ی قبلی که عمدتاً به نام ستون تکیه می‌کرد، این نسخه برای هر ستون یک
پروفایل می‌سازد (درصد عددی/تاریخ/متن، یکتایی، شبیه‌موبایل/کد بودن و …) و سپس برای
هر نقش یک confidence و دلیل تولید می‌کند. ستون‌های متنی/وضعیتی هرگز به‌عنوان مبلغ
یا محصول انتخاب نمی‌شوند.
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field

import pandas as pd

from ..locale_fa import normalize_digits
from .schema import (
    CATEGORICAL_ROLES,
    NUMERIC_ROLES,
    REQUIRED_ROLES,
    ColumnRole,
    standard_column,
)

Mapping = dict[ColumnRole, str]

# آستانه‌ی auto-select؛ زیر این مقدار، نقش به‌صورت خودکار انتخاب نمی‌شود.
AUTO_SELECT_THRESHOLD = 0.65


# ---------------------------------------------------------------------------
# جدول کلیدواژه‌ها (نام نقش -> فهرست (کلیدواژه، وزن))؛ وزن بالاتر = اولویت بیشتر
# ---------------------------------------------------------------------------
REVENUE_KW = [
    ("قابل پرداخت", 1.0), ("خالص پرداختی", 0.98), ("مبلغ نهایی", 0.96),
    ("مبلغ کل", 0.94), ("جمع کل", 0.93), ("قیمت کل", 0.92), ("فروش خالص", 0.92),
    ("مبلغ فروش", 0.9), ("مبلغ فاکتور", 0.9), ("درآمد", 0.88), ("پرداختی", 0.86),
    ("مبلغ", 0.8), ("جمع", 0.7), ("amount", 0.85), ("revenue", 0.9),
    ("total", 0.75), ("net amount", 0.9), ("grand total", 0.9),
]
# نام‌هایی که حضورشان یک ستون را از revenue (و عددی‌بودن) رد می‌کند
REVENUE_BLOCK = ["نحوه", "روش", "نوع", "وضعیت", "برگشت", "مرجوع", "سند", "توضیح",
                 "شرح", "نام", "کد", "موبایل", "تلفن", "تاریخ", "واحد", "فی",
                 "اعتبار", "بروز", "کانال", "منطقه", "تخفیف"]

UNIT_PRICE_KW = [("قیمت واحد", 1.0), ("فی واحد", 0.98), ("بهای واحد", 0.95),
                 ("نرخ واحد", 0.9), ("unit price", 1.0), ("فی", 0.78), ("نرخ", 0.7)]

PRODUCT_TEXT_KW = [
    ("شرح کالا", 1.0), ("نام کالا", 0.98), ("نام محصول", 0.98), ("عنوان محصول", 0.96),
    ("عنوان کالا", 0.96), ("شرح محصول", 0.95), ("شرح کالا/خدمات", 1.0),
    ("محصول", 0.88), ("کالا", 0.85), ("آیتم", 0.8), ("عنوان", 0.66), ("شرح", 0.62),
    ("product", 0.9), ("item", 0.8), ("goods", 0.8),
]
PRODUCT_CODE_KW = [("کد کالا", 0.55), ("کد محصول", 0.55), ("sku", 0.6), ("بارکد", 0.5)]
PRODUCT_BLOCK = ["نحوه", "روش", "نوع سند", "وضعیت", "توضیح", "تاریخ", "مبلغ",
                 "قیمت", "تعداد", "تخفیف", "موبایل", "تلفن", "مشتری", "فروشنده",
                 "فروشگاه", "شعبه", "سند", "برگشت", "مرجوع", "اعتبار", "کانال", "منطقه"]

CUSTOMER_KW = [("نام مشتری", 1.0), ("نام خریدار", 0.96), ("کد مشتری", 0.82),
               ("شناسه مشتری", 0.82), ("مشتری", 0.85), ("خریدار", 0.85),
               ("طرف حساب", 0.8), ("customer", 0.9), ("client", 0.85), ("buyer", 0.85)]
CUSTOMER_BLOCK = ["موبایل", "تلفن", "شماره تماس", "همراه", "نحوه", "نوع", "وضعیت",
                  "سند", "تاریخ", "مبلغ", "قیمت", "تعداد", "برگشت", "اعتبار"]

PHONE_KW = [("شماره موبایل", 1.0), ("تلفن همراه", 1.0), ("موبایل", 1.0),
            ("شماره تماس", 0.9), ("همراه", 0.85), ("تلفن", 0.85),
            ("mobile", 1.0), ("phone", 0.9)]

DATE_KW = [("تاریخ", 1.0), ("date", 1.0), ("datetime", 0.95), ("زمان", 0.85),
           ("تاریخ فاکتور", 1.0), ("تاریخ فروش", 1.0), ("روز", 0.6)]

QTY_KW = [("تعداد", 1.0), ("مقدار", 0.85), ("کمیت", 0.8), ("qty", 1.0), ("quantity", 1.0)]

ORDER_KW = [("شماره فاکتور", 1.0), ("شماره سفارش", 0.97), ("کد سفارش", 0.95),
            ("کد فاکتور", 0.93), ("شماره سند", 0.7), ("فاکتور", 0.85),
            ("سفارش", 0.85), ("invoice", 0.95), ("order", 0.9)]

COST_KW = [("بهای تمام شده", 1.0), ("قیمت خرید", 0.9), ("هزینه", 0.85),
           ("cost", 0.9), ("cogs", 0.95)]
DISCOUNT_KW = [("مبلغ تخفیف", 1.0), ("درصد تخفیف", 0.95), ("تخفیف", 0.95), ("discount", 0.95)]
CATEGORY_KW = [("دسته‌بندی", 1.0), ("دسته بندی", 1.0), ("گروه کالا", 0.95), ("دسته", 0.9),
               ("گروه", 0.82), ("category", 0.9)]
CHANNEL_KW = [("کانال فروش", 1.0), ("کانال", 0.9), ("روش فروش", 0.85),
              ("channel", 0.9), ("source", 0.7)]
REGION_KW = [("منطقه", 0.95), ("استان", 0.95), ("شهر", 0.9), ("ناحیه", 0.85),
             ("region", 0.9), ("city", 0.85), ("province", 0.9)]
BRANCH_KW = [("شعبه", 1.0), ("فروشگاه", 0.95), ("نمایندگی", 0.9), ("مرکز فروش", 0.9),
             ("branch", 0.95), ("store", 0.9), ("outlet", 0.85)]
SALESPERSON_KW = [("فروشنده", 1.0), ("کارشناس فروش", 0.95), ("ویزیتور", 0.9),
                  ("بازاریاب", 0.85), ("salesperson", 0.95), ("sales rep", 0.9)]
EMAIL_KW = [("ایمیل", 1.0), ("پست الکترونیک", 0.95), ("رایانامه", 0.9),
            ("email", 1.0), ("mail", 0.8)]


@dataclass
class RoleGuess:
    """حدس یک نقش همراه با اطمینان و دلیل."""

    role: ColumnRole
    column: str | None
    confidence: float
    reason: str
    auto: bool  # آیا با اطمینان کافی به‌صورت خودکار انتخاب شد؟


@dataclass
class ColumnProfile:
    name: str
    norm: str
    n_rows: int
    n_nonnull: int
    numeric_ratio: float
    date_ratio: float
    text_ratio: float
    n_unique: int
    uniqueness: float
    samples: list[str]
    avg_text_len: float
    phone_like_ratio: float
    code_like_ratio: float


@dataclass
class MappingSuggestion:
    """نتیجه‌ی تشخیص خودکار نگاشت."""

    mapping: Mapping = field(default_factory=dict)
    scores: dict[ColumnRole, float] = field(default_factory=dict)
    guesses: dict[ColumnRole, RoleGuess] = field(default_factory=dict)
    unmapped_columns: list[str] = field(default_factory=list)

    @property
    def missing_required(self) -> list[ColumnRole]:
        return [r for r in REQUIRED_ROLES if r not in self.mapping]

    @property
    def is_valid(self) -> bool:
        return not self.missing_required

    @property
    def low_confidence_required(self) -> list[ColumnRole]:
        """نقش‌های ضروری که با اطمینان کافی حدس زده نشده‌اند."""
        return [r for r in REQUIRED_ROLES if r not in self.mapping]


# ---------------------------------------------------------------------------
# نرمال‌سازی و پروفایل‌سازی
# ---------------------------------------------------------------------------
def _norm(text: str) -> str:
    text = normalize_digits(str(text)).strip().lower()
    text = text.replace("ي", "ی").replace("ك", "ک").replace("‌", " ")  # نیم‌فاصله→فاصله
    text = re.sub(r"[_\-/.()،]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


_CURRENCY_WORDS = ("ریال", "تومان", "rial", "toman", "irr", "irt")


def _num_token(v: str) -> str:
    s = normalize_digits(str(v)).lower()
    for w in _CURRENCY_WORDS:
        s = s.replace(w, "")
    s = s.replace(",", "").replace("٬", "").strip()
    s = re.sub(r"[^\d.\-]", "", s)
    return s


def to_number(v: object) -> float:
    """تبدیل یک مقدار (فارسی/ارزی/متنی) به عدد یا NaN — قابل‌استفاده‌ی عمومی."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return float("nan")
    if isinstance(v, (int, float)):
        return float(v)
    tok = _num_token(v)
    if tok in ("", "-", ".", "-."):
        return float("nan")
    try:
        return float(tok)
    except ValueError:
        return float("nan")


_PHONE_RE = re.compile(r"^(?:0|0098|\+98|98)?9\d{9}$")
_STRICT_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?$")


def _is_numeric_token(s: str) -> bool:
    """آیا مقدار «واقعاً عددی» است؟ مقادیر دارای حرف (مثل C0001 یا INV-10) عددی نیستند."""
    t = normalize_digits(str(s)).lower()
    for w in _CURRENCY_WORDS:
        t = t.replace(w, "")
    t = t.replace(",", "").replace("٬", "").replace("%", "").replace(" ", "").strip()
    return bool(t) and bool(_STRICT_NUM_RE.fullmatch(t))


def _profile_column(name: str, series: pd.Series) -> ColumnProfile:
    # رشته‌ی خالی/فاصله/«nan/none» هم به‌عنوان مقدار غایب در نظر گرفته می‌شود
    as_str = series.map(lambda x: str(x).strip())
    present = (
        series.notna()
        & (as_str != "")
        & (~as_str.str.lower().isin(["nan", "none", "nat", "<na>"]))
    )
    nonnull = series[present]
    n_nonnull = int(len(nonnull))
    sample = nonnull.astype(str).head(300)
    denom = max(len(sample), 1)

    numeric_ok = date_ok = phone_ok = code_ok = 0
    text_lens: list[int] = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        parsed = pd.to_datetime(sample, errors="coerce", dayfirst=False, format="mixed")
    for i, v in enumerate(sample):
        s = str(v).strip()
        text_lens.append(len(s))
        if _is_numeric_token(s):
            numeric_ok += 1
        # تاریخ: میلادی یا الگوی جلالی
        if pd.notna(parsed.iloc[i]) if i < len(parsed) else False:
            date_ok += 1
        elif re.match(r"^\s*1[34]\d{2}[/\-.]\d{1,2}[/\-.]\d{1,2}", normalize_digits(s)):
            date_ok += 1
        # موبایل
        digits = re.sub(r"\D", "", normalize_digits(s))
        if _PHONE_RE.match(digits):
            phone_ok += 1
        # کد/فاکتور: شامل رقم و طول ≥۳، احتمالاً آلفاعددی
        if re.match(r"^[A-Za-z0-9\-_/]+$", s) and any(ch.isdigit() for ch in s) and len(s) >= 3:
            code_ok += 1

    numeric_ratio = numeric_ok / denom
    date_ratio = date_ok / denom
    phone_ratio = phone_ok / denom
    code_ratio = code_ok / denom
    text_ratio = 1.0 - numeric_ratio
    n_unique = int(nonnull.nunique())
    uniqueness = n_unique / n_nonnull if n_nonnull else 0.0
    avg_len = float(sum(text_lens) / len(text_lens)) if text_lens else 0.0

    return ColumnProfile(
        name=str(name), norm=_norm(name), n_rows=int(len(series)), n_nonnull=n_nonnull,
        numeric_ratio=numeric_ratio, date_ratio=date_ratio, text_ratio=text_ratio,
        n_unique=n_unique, uniqueness=uniqueness,
        samples=[str(x) for x in sample.head(10).tolist()],
        avg_text_len=avg_len, phone_like_ratio=phone_ratio, code_like_ratio=code_ratio,
    )


def _name_match(col_norm: str, keywords: list[tuple[str, float]]) -> tuple[float, str]:
    """بهترین وزن تطبیق نام + کلیدواژه‌ی منطبق."""
    best_w, best_kw = 0.0, ""
    tokens = col_norm.split()
    for kw, w in keywords:
        k = _norm(kw)
        score = 0.0
        if col_norm == k:
            score = w
        elif col_norm.startswith(k + " ") or col_norm.endswith(" " + k) or f" {k} " in f" {col_norm} ":
            score = 0.96 * w
        elif k in tokens:
            score = 0.9 * w
        elif k in col_norm:
            score = 0.8 * w
        if score > best_w:
            best_w, best_kw = score, kw
    return best_w, best_kw


def _has_block(col_norm: str, blocks: list[str]) -> bool:
    return any(_norm(b) in col_norm for b in blocks)


def _pct(x: float) -> int:
    return int(round(x * 100))


class SchemaMapper:
    """تشخیص و اعمال نگاشت ستون‌ها (نام + نوع داده + نمونه مقادیر)."""

    def auto_detect(self, df: pd.DataFrame) -> MappingSuggestion:
        profiles = {str(c): _profile_column(c, df[c]) for c in df.columns}

        # (col, role) -> (confidence, reason)
        cand: dict[tuple[str, ColumnRole], tuple[float, str]] = {}
        for col, p in profiles.items():
            for role in ColumnRole:
                conf, reason = self._score(role, p)
                if conf > 0:
                    cand[(col, role)] = (conf, reason)

        # بهترین حدس هر نقش (فارغ از آستانه) برای نمایش در UI
        best_per_role: dict[ColumnRole, tuple[str, float, str]] = {}
        for (col, role), (conf, reason) in cand.items():
            cur = best_per_role.get(role)
            if cur is None or conf > cur[1]:
                best_per_role[role] = (col, conf, reason)

        # تخصیص حریصانه فقط برای حدس‌های مطمئن (>= آستانه)
        confident = sorted(
            [(conf, col, role, reason) for (col, role), (conf, reason) in cand.items()
             if conf >= AUTO_SELECT_THRESHOLD],
            key=lambda x: (-x[0], x[2].value),
        )
        mapping: Mapping = {}
        scores: dict[ColumnRole, float] = {}
        used_cols: set[str] = set()
        assigned_reason: dict[ColumnRole, str] = {}
        for conf, col, role, reason in confident:
            if role in mapping or col in used_cols:
                continue
            mapping[role] = col
            scores[role] = round(conf, 3)
            assigned_reason[role] = reason
            used_cols.add(col)

        # fallback محصول: اگر محصول متنی نبود، از «کد کالا» استفاده کن
        if ColumnRole.PRODUCT not in mapping:
            self._product_code_fallback(profiles, used_cols, mapping, scores, assigned_reason)

        # fallback مشتری: اگر مشتری نبود ولی موبایل هست، موبایل را به‌عنوان شناسه‌ی مشتری بپذیر
        if ColumnRole.CUSTOMER_ID not in mapping and ColumnRole.PHONE in mapping:
            phone_col = mapping[ColumnRole.PHONE]
            mapping[ColumnRole.CUSTOMER_ID] = phone_col
            scores[ColumnRole.CUSTOMER_ID] = 0.66
            assigned_reason[ColumnRole.CUSTOMER_ID] = "ستون مشتری یافت نشد؛ شماره موبایل به‌عنوان شناسه‌ی مشتری استفاده شد."

        # ساخت guessها برای همه‌ی نقش‌ها
        guesses: dict[ColumnRole, RoleGuess] = {}
        for role in ColumnRole:
            if role in mapping:
                guesses[role] = RoleGuess(role, mapping[role], scores[role],
                                          assigned_reason.get(role, ""), auto=True)
            elif role in best_per_role:
                col, conf, reason = best_per_role[role]
                guesses[role] = RoleGuess(
                    role, None, round(conf, 3),
                    f"حدس کم‌اطمینان: «{col}» — {reason}", auto=False,
                )
            else:
                guesses[role] = RoleGuess(role, None, 0.0,
                                          "هیچ ستونی با اطمینان کافی برای این نقش یافت نشد.", auto=False)

        unmapped = [c for c in profiles if c not in used_cols]
        return MappingSuggestion(mapping=mapping, scores=scores, guesses=guesses,
                                 unmapped_columns=unmapped)

    # ------------------------------------------------------------------
    def _score(self, role: ColumnRole, p: ColumnProfile) -> tuple[float, str]:
        """confidence و دلیل برای یک (نقش، ستون). 0 یعنی نامزد نیست."""
        cn = p.norm
        npct = _pct(p.numeric_ratio)

        if role == ColumnRole.REVENUE:
            if _has_block(cn, REVENUE_BLOCK):
                return 0.0, ""
            w, kw = _name_match(cn, REVENUE_KW)
            if w == 0 or p.numeric_ratio < 0.70:
                return 0.0, ""
            conf = w * (0.55 + 0.45 * p.numeric_ratio)
            return conf, f"نام ستون شامل «{kw}» است و {npct}٪ مقادیر عددی هستند"

        if role == ColumnRole.UNIT_PRICE:
            w, kw = _name_match(cn, UNIT_PRICE_KW)
            if w == 0 or p.numeric_ratio < 0.70:
                return 0.0, ""
            return w * (0.55 + 0.45 * p.numeric_ratio), f"نام ستون شامل «{kw}» و {npct}٪ عددی است"

        if role == ColumnRole.PRODUCT:
            if _has_block(cn, PRODUCT_BLOCK):
                return 0.0, ""
            w, kw = _name_match(cn, PRODUCT_TEXT_KW)
            if w == 0:
                return 0.0, ""
            # محصول باید عمدتاً متنی باشد (نه عددی)
            text_fit = 1.0 - max(p.numeric_ratio - 0.2, 0.0)
            return w * (0.5 + 0.5 * text_fit), f"نام ستون شامل «{kw}» و عمدتاً متنی است"

        if role == ColumnRole.CUSTOMER_ID:
            if _has_block(cn, CUSTOMER_BLOCK):
                return 0.0, ""
            w, kw = _name_match(cn, CUSTOMER_KW)
            if w == 0:
                return 0.0, ""
            return w * (0.6 + 0.4 * min(p.text_ratio + 0.3, 1.0)), f"نام ستون شامل «{kw}» است"

        if role == ColumnRole.PHONE:
            w, kw = _name_match(cn, PHONE_KW)
            if w == 0 or p.phone_like_ratio < 0.5:
                return 0.0, ""
            return w * (0.5 + 0.5 * p.phone_like_ratio), \
                f"نام ستون شامل «{kw}» و {_pct(p.phone_like_ratio)}٪ مقادیر شبیه شماره موبایل هستند"

        if role == ColumnRole.DATE:
            w, kw = _name_match(cn, DATE_KW)
            if w == 0 or p.date_ratio < 0.60:
                return 0.0, ""
            return w * (0.5 + 0.5 * p.date_ratio), \
                f"نام ستون شامل «{kw}» و {_pct(p.date_ratio)}٪ مقادیر قابل‌تبدیل به تاریخ هستند"

        if role == ColumnRole.QUANTITY:
            w, kw = _name_match(cn, QTY_KW)
            if w == 0 or p.numeric_ratio < 0.6:
                return 0.0, ""
            return w * (0.55 + 0.45 * p.numeric_ratio), f"نام ستون شامل «{kw}» و {npct}٪ عددی است"

        if role == ColumnRole.ORDER_ID:
            w, kw = _name_match(cn, ORDER_KW)
            if w == 0:
                return 0.0, ""
            return w * (0.6 + 0.4 * min(p.uniqueness + 0.3, 1.0)), f"نام ستون شامل «{kw}» است"

        if role == ColumnRole.COST:
            w, kw = _name_match(cn, COST_KW)
            if w == 0 or p.numeric_ratio < 0.6:
                return 0.0, ""
            return w * (0.55 + 0.45 * p.numeric_ratio), f"نام ستون شامل «{kw}» و {npct}٪ عددی است"

        if role == ColumnRole.DISCOUNT:
            w, kw = _name_match(cn, DISCOUNT_KW)
            if w == 0 or p.numeric_ratio < 0.5:
                return 0.0, ""
            return w * (0.55 + 0.45 * p.numeric_ratio), f"نام ستون شامل «{kw}» و {npct}٪ عددی است"

        # ابعاد دسته‌ای متنی
        kw_table = {
            ColumnRole.CATEGORY: CATEGORY_KW, ColumnRole.CHANNEL: CHANNEL_KW,
            ColumnRole.REGION: REGION_KW, ColumnRole.BRANCH: BRANCH_KW,
            ColumnRole.SALESPERSON: SALESPERSON_KW,
        }.get(role)
        if kw_table is not None:
            w, kw = _name_match(cn, kw_table)
            if w == 0:
                return 0.0, ""
            return w * (0.6 + 0.4 * min(p.text_ratio + 0.4, 1.0)), f"نام ستون شامل «{kw}» است"

        if role == ColumnRole.EMAIL:
            w, kw = _name_match(cn, EMAIL_KW)
            if w == 0:
                return 0.0, ""
            return w * 0.9, f"نام ستون شامل «{kw}» است"

        return 0.0, ""

    def _product_code_fallback(self, profiles, used_cols, mapping, scores, reasons) -> None:
        best = None
        for col, p in profiles.items():
            if col in used_cols or _has_block(p.norm, PRODUCT_BLOCK):
                continue
            w, kw = _name_match(p.norm, PRODUCT_CODE_KW)
            if w > 0 and (best is None or w > best[1]):
                best = (col, w, kw)
        if best:
            col, _, kw = best
            mapping[ColumnRole.PRODUCT] = col
            scores[ColumnRole.PRODUCT] = 0.66
            reasons[ColumnRole.PRODUCT] = f"ستون متنی محصول یافت نشد؛ «{kw}» («{col}») به‌عنوان محصول استفاده شد."
            used_cols.add(col)

    # ------------------------------------------------------------------
    def apply(self, df: pd.DataFrame, mapping: Mapping) -> pd.DataFrame:
        """اعمال نگاشت: ساخت دیتافریم استاندارد (یک ستون منبع می‌تواند به دو نقش برود)."""
        missing = [r.value for r in REQUIRED_ROLES if r not in mapping]
        if missing:
            raise ValueError(f"نگاشت ناقص است؛ نقش‌های ضروری یافت نشدند: {', '.join(missing)}")

        out = pd.DataFrame(index=df.index)
        for role, col in mapping.items():
            if col not in df.columns:
                raise ValueError(f"ستون «{col}» برای نقش {role.value} در داده وجود ندارد.")
            out[standard_column(role)] = df[col].to_numpy()
        return out.reset_index(drop=True)


__all__ = [
    "SchemaMapper", "MappingSuggestion", "RoleGuess", "ColumnProfile", "Mapping",
    "NUMERIC_ROLES", "CATEGORICAL_ROLES", "to_number", "AUTO_SELECT_THRESHOLD",
]
