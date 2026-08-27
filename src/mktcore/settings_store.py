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


__all__ = [
    "MAX_MARGIN_FLOOR_BP",
    "get_setting",
    "margin_floor_bp",
    "set_margin_floor_bp",
    "set_setting",
]
