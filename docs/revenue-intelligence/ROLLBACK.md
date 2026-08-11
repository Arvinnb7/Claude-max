# پشتیبان‌گیری و بازگشت

## پشتیبان‌گیری (قبل از ارتقا — الزامی)

دیتابیس در حالت WAL است؛ **کپی کردن تنها `app.db` کافی نیست** (فایل `app.db-wal`
هم داده دارد). از API پشتیبان SQLite استفاده کنید:

```bash
python -c "import sqlite3; s=sqlite3.connect('data/app.db'); d=sqlite3.connect('data/app.db.bak'); s.backup(d); d.close(); s.close()"
cp -r data/sessions data/sessions.bak      # ویندوز: xcopy /E /I data\sessions data\sessions.bak
```

## بازگشت

جداول قدیمی (`sessions`, `jobs`, `outbox`, `mapping_profiles`) در این ارتقا
**دست نمی‌خورند** و `PRAGMA user_version` در ۲ می‌ماند. بنابراین:

1. **کد قدیمی روی دیتابیس جدید درست کار می‌کند** — جداول canonical فقط بی‌استفاده
   می‌مانند. بازگشت = `git checkout <commit قبلی>` و ری‌استارت سرور.
2. بازگردانی پشتیبان **اختیاری** است، نه الزامی.
3. خاموش کردن فوری لایه‌ی جدید بدون تغییر کد:
   ```bash
   MKT_CANONICAL_ENABLE=0
   ```
   تحلیل، داشبورد، گزارش و اکسل کامل کار می‌کنند؛ فقط تب «صندوق فرصت‌ها» و
   endpointهای `/api/v1` داده‌ی تازه نمی‌گیرند.

## بازگردانی کامل

```bash
cp data/app.db.bak data/app.db
rm -f data/app.db-wal data/app.db-shm
rm -rf data/sessions && mv data/sessions.bak data/sessions
```
