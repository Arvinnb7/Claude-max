"""تنظیم‌های سیاست که کاربر می‌گذارد — خواندن و نوشتنِ `app_settings`.

**چرا این ماژول جدا است.** موتور فرصت‌ها اجازه ندارد عددِ سیاستی را حدس بزند؛
یا کاربر گذاشته یا نگذاشته. اینجا فقط همان دو حالت وجود دارد و حالت سومی به‌نام
«پیش‌فرضِ منطقی» ساخته نمی‌شود: `None` یعنی تعیین‌نشده، و فیلترها آن را
«بررسی نشد» ثبت می‌کنند، نه «قبول».

کف حاشیه به **پایه‌ی هزارم** (basis point) نگه‌داری می‌شود، مثل هر نسبت دیگری
در این سیستم: ۲۰۰۰ یعنی ۲۰٪. اعشار شناور برای درصد یعنی ۲۰٪ گاهی ۱۹٫۹۹۹٪ شود.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from mktcore.db.base import now_ts
from mktcore.db.engine import session_scope, write_lock
from mktcore.db.lookup import resolve_business_id
from mktcore.db.migrations import ensure_schema
from mktcore.db.models import AppSetting

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.orm import Session

# بیشترین مقدار معنادار: ۱۰۰٪. حاشیه‌ی بیش از صد درصد یعنی بها منفی است.
MAX_MARGIN_FLOOR_BP = 10_000

# سقفِ عددِ ظرفیت. بزرگ‌تر از این یعنی کاربر عملاً ظرفیت نگذاشته و بهتر است
# همان «تنظیم‌نشده» بماند تا عددی که هیچ‌وقت نمی‌خورد.
MAX_DAILY_CAPACITY = 100_000


def get_setting(session: Session, business_id: int, key: str) -> str | None:
    return session.scalar(
        select(AppSetting.value_text).where(
            AppSetting.business_id == business_id, AppSetting.key == key,
        )
    )


def set_setting(
    session: Session, business_id: int, key: str, value: str, *,
    note_fa: str | None = None,
) -> None:
    row = session.scalar(
        select(AppSetting).where(
            AppSetting.business_id == business_id, AppSetting.key == key,
        )
    )
    if row is None:
        session.add(AppSetting(
            business_id=business_id, key=key, value_text=value, note_fa=note_fa,
        ))
    else:
        row.value_text = value
        row.note_fa = note_fa
        row.updated_at = now_ts()
    session.flush()


def margin_floor_bp(session: Session, business_id: int) -> int | None:
    """کف حاشیه‌ی تعیین‌شده، یا `None` اگر کاربر تعیینش نکرده باشد."""
    raw = get_setting(session, business_id, AppSetting.KEY_MARGIN_FLOOR_BP)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        # مقدارِ خراب یعنی «نمی‌دانیم»، نه «صفر». صفر یعنی «هر حاشیه‌ای قبول
        # است» و آن ادعایی است که کاربر نکرده.
        return None


def set_margin_floor_bp(
    value_bp: int | None, *, business_slug: str = "default",
    db_path: Path | None = None, note_fa: str | None = None,
) -> int | None:
    """ثبت کف حاشیه. `None` یعنی برداشتنِ کف (بازگشت به «بررسی نشد»)."""
    ensure_schema(db_path)
    with write_lock, session_scope(db_path) as session:
        business_id = resolve_business_id(session, business_slug)
        if business_id is None:
            raise ValueError("کسب‌وکاری ثبت نشده است؛ اول یک فایل فروش تحلیل کنید.")
        if value_bp is None:
            row = session.scalar(
                select(AppSetting).where(
                    AppSetting.business_id == business_id,
                    AppSetting.key == AppSetting.KEY_MARGIN_FLOOR_BP,
                )
            )
            if row is not None:
                session.delete(row)
            return None
        value = int(value_bp)
        if not 0 <= value <= MAX_MARGIN_FLOOR_BP:
            raise ValueError("کف حاشیه باید بین ۰ و ۱۰۰۰۰ پایه (۰ تا ۱۰۰٪) باشد.")
        set_setting(
            session, business_id, AppSetting.KEY_MARGIN_FLOOR_BP, str(value),
            note_fa=note_fa,
        )
        return value


def daily_capacity(session: Session, business_id: int) -> int | None:
    """ظرفیت روزانه‌ی تیم، یا `None` اگر تعیین نشده باشد."""
    raw = get_setting(session, business_id, AppSetting.KEY_DAILY_CAPACITY)
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    # صفر یعنی «هیچ‌کس نمی‌تواند پیگیری کند» و آن ادعای عجیبی است؛ اگر کسی
    # ظرفیت را صفر گذاشت، احتمالاً منظورش «تنظیم نکردن» بوده.
    return value if value > 0 else None


def set_daily_capacity(
    value: int | None, *, business_slug: str = "default",
    db_path: Path | None = None, note_fa: str | None = None,
) -> int | None:
    """ثبت ظرفیت روزانه. `None` یعنی برداشتنش (بازگشت به «بررسی نشد»)."""
    ensure_schema(db_path)
    with write_lock, session_scope(db_path) as session:
        business_id = resolve_business_id(session, business_slug)
        if business_id is None:
            raise ValueError("کسب‌وکاری ثبت نشده است؛ اول یک فایل فروش تحلیل کنید.")
        if value is None:
            row = session.scalar(
                select(AppSetting).where(
                    AppSetting.business_id == business_id,
                    AppSetting.key == AppSetting.KEY_DAILY_CAPACITY,
                )
            )
            if row is not None:
                session.delete(row)
            return None
        number = int(value)
        if not 1 <= number <= MAX_DAILY_CAPACITY:
            raise ValueError(
                f"ظرفیت روزانه باید بین ۱ و {MAX_DAILY_CAPACITY} باشد."
            )
        set_setting(
            session, business_id, AppSetting.KEY_DAILY_CAPACITY, str(number),
            note_fa=note_fa,
        )
        return number


# ------------------------------------------------------------ نردبان تخفیف
# بزرگ‌ترین پله‌ی معنادار: ۵۰٪. بالاتر از آن با «کف حاشیه» هم‌خوان نیست و
# احتمالاً اشتباهِ واحد است (۵۰۰۰ به‌جای ۵۰۰).
MAX_LADDER_RUNG_BP = 5_000
MAX_LADDER_RUNGS = 8


def offer_ladder_bp(session: Session, business_id: int) -> tuple[int, ...] | None:
    """پله‌های نردبان، صعودی و یکتا؛ یا `None` اگر کاربر تعیین نکرده باشد.

    مقدارِ خراب هم `None` است — «نمی‌دانیم»، نه «نردبانِ خالی».
    """
    raw = get_setting(session, business_id, AppSetting.KEY_OFFER_LADDER_BP)
    if raw is None:
        return None
    try:
        rungs = sorted({int(part) for part in raw.split(",") if part.strip()})
    except (TypeError, ValueError):
        return None
    rungs = [r for r in rungs if 0 < r <= MAX_LADDER_RUNG_BP]
    return tuple(rungs) or None


def set_offer_ladder_bp(
    rungs: list[int] | tuple[int, ...] | None, *, business_slug: str = "default",
    db_path: Path | None = None, note_fa: str | None = None,
) -> tuple[int, ...] | None:
    """ثبت نردبان. `None` یا فهرستِ خالی یعنی برداشتنش (بازگشت به «بررسی نشد»)."""
    ensure_schema(db_path)
    with write_lock, session_scope(db_path) as session:
        business_id = resolve_business_id(session, business_slug)
        if business_id is None:
            raise ValueError("کسب‌وکاری ثبت نشده است؛ اول یک فایل فروش تحلیل کنید.")
        if not rungs:
            row = session.scalar(
                select(AppSetting).where(
                    AppSetting.business_id == business_id,
                    AppSetting.key == AppSetting.KEY_OFFER_LADDER_BP,
                )
            )
            if row is not None:
                session.delete(row)
            return None
        cleaned = sorted({int(r) for r in rungs})
        if len(cleaned) > MAX_LADDER_RUNGS:
            raise ValueError(f"نردبان حداکثر {MAX_LADDER_RUNGS} پله می‌تواند داشته باشد.")
        for rung in cleaned:
            if not 0 < rung <= MAX_LADDER_RUNG_BP:
                raise ValueError(
                    f"پله‌ی {rung} معتبر نیست؛ هر پله باید بین ۱ و {MAX_LADDER_RUNG_BP} "
                    "پایه‌ی هزارم (تا ۵۰٪) باشد."
                )
        set_setting(
            session, business_id, AppSetting.KEY_OFFER_LADDER_BP,
            ",".join(str(r) for r in cleaned), note_fa=note_fa,
        )
        return tuple(cleaned)


def full_price_thresholds(session: Session, business_id: int) -> dict:
    """آستانه‌های طبقه‌ی «تمام‌قیمت‌خری» + اینکه از تنظیمِ کاربرند یا پیش‌فرض."""
    from mktcore.features.discount import (
        DEFAULT_HIGH_BP,
        DEFAULT_LOW_BP,
        DEFAULT_MIN_LINES,
    )

    def _int(key: str, default: int) -> tuple[int, bool]:
        raw = get_setting(session, business_id, key)
        if raw is None:
            return default, False
        try:
            return int(raw), True
        except (TypeError, ValueError):
            return default, False

    high, high_set = _int(AppSetting.KEY_FULL_PRICE_HIGH_BP, DEFAULT_HIGH_BP)
    low, low_set = _int(AppSetting.KEY_FULL_PRICE_LOW_BP, DEFAULT_LOW_BP)
    min_lines, min_set = _int(AppSetting.KEY_FULL_PRICE_MIN_LINES, DEFAULT_MIN_LINES)
    return {
        "high_bp": high, "low_bp": low, "min_lines": min_lines,
        "configured": high_set or low_set or min_set,
    }


def set_full_price_thresholds(
    *, high_bp: int | None = None, low_bp: int | None = None,
    min_lines: int | None = None, business_slug: str = "default",
    db_path: Path | None = None,
) -> dict:
    """ثبت آستانه‌ها؛ هر کدام `None` باشد دست نمی‌خورد. `low < high` الزامی است."""
    ensure_schema(db_path)
    with write_lock, session_scope(db_path) as session:
        business_id = resolve_business_id(session, business_slug)
        if business_id is None:
            raise ValueError("کسب‌وکاری ثبت نشده است؛ اول یک فایل فروش تحلیل کنید.")
        current = full_price_thresholds(session, business_id)
        new_high = current["high_bp"] if high_bp is None else int(high_bp)
        new_low = current["low_bp"] if low_bp is None else int(low_bp)
        new_min = current["min_lines"] if min_lines is None else int(min_lines)
        if not (0 <= new_low < new_high <= 10_000):
            raise ValueError("آستانه‌ها باید ۰ ≤ پایین < بالا ≤ ۱۰۰۰۰ باشند.")
        if new_min < 1:
            raise ValueError("کمینه‌ی خطوط باید دست‌کم ۱ باشد.")
        for key, value in (
            (AppSetting.KEY_FULL_PRICE_HIGH_BP, new_high),
            (AppSetting.KEY_FULL_PRICE_LOW_BP, new_low),
            (AppSetting.KEY_FULL_PRICE_MIN_LINES, new_min),
        ):
            set_setting(session, business_id, key, str(value))
        return full_price_thresholds(session, business_id)


__all__ = [
    "MAX_DAILY_CAPACITY",
    "MAX_LADDER_RUNGS",
    "MAX_LADDER_RUNG_BP",
    "full_price_thresholds",
    "offer_ladder_bp",
    "set_full_price_thresholds",
    "set_offer_ladder_bp",
    "MAX_MARGIN_FLOOR_BP",
    "daily_capacity",
    "set_daily_capacity",
    "get_setting",
    "margin_floor_bp",
    "set_margin_floor_bp",
    "set_setting",
]
