"""façade سازگاری: ذخیره‌ی ماندگار نشست‌ها (پیاده‌سازی در persistence.py)."""

from .persistence import JobRecord, PersistentStore, SessionRecord, store

__all__ = ["store", "PersistentStore", "SessionRecord", "JobRecord"]
