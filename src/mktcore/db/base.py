"""کلاس پایه‌ی ORM جداول canonical.

`Base.metadata` **فقط** جداول این لایه را می‌شناسد. جداول legacy
(`sessions`, `jobs`, `outbox`, `mapping_profiles`) عمداً بیرون می‌مانند تا هیچ
عملیات metadata — از جمله `create_all` — نتواند به آن‌ها دست بزند. `drop_all`
در هیچ مسیری صدا زده نمی‌شود.

قرارداد واحدها در همه‌ی مدل‌ها:

* مبلغ: عدد صحیح **ریال** با پسوند `_rial` (هرگز float؛ جمع‌پذیریِ بی‌خطا).
* تعداد: عدد صحیح ×۱۰۰۰ با پسوند `_milli` (تعداد کسری وزنی/حجمی را نگه می‌دارد).
* نسبت: basis point صحیح با پسوند `_bp` (۱۰۰٪ = ۱۰۰۰۰).
* زمان: مهر یونیکس اعشاری — همان قراردادی که جداول legacy دارند.
"""

from __future__ import annotations

import time

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# نام‌گذاری صریح قیدها → مهاجرت‌های آینده می‌توانند با نام به آن‌ها ارجاع دهند
# (SQLite قید بی‌نام را نمی‌تواند drop کند و بدون این، مهاجرت بعدی گیر می‌کند).
_NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """پایه‌ی همه‌ی مدل‌های canonical (و فقط آن‌ها)."""

    metadata = MetaData(naming_convention=_NAMING)


def now_ts() -> float:
    """مهر زمانی یونیکس (ثانیه، اعشاری)."""
    return time.time()


__all__ = ["Base", "now_ts"]
