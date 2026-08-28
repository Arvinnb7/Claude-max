# راهنمای عملیات

سند §۳۶. مخاطبش کسی است که این سیستم را روی **سرور شخصی یا VPS** بالا می‌آورد و
نگه می‌دارد. فرضِ این سند: یک ماشین، یک کسب‌وکار، SQLite، و Docker Compose.

> هر دستوری که اینجا آمده روی همان ماشین اجرا می‌شود. اگر چیزی را نمی‌فهمید،
> **اجرایش نکنید** — به‌خصوص در بخش «بازیابی».

---

## ۱. بالا آوردن

```bash
cp .env.example .env          # و بعد ویرایشش کنید
docker compose up -d --build
docker compose logs -f api    # تا «Application startup complete»
```

سه چیز را همان اول تنظیم کنید:

| کلید | چرا مهم است |
|---|---|
| `MKT_API_TOKEN` | بدونش هر کسی که به آدرس برسد می‌تواند پیامک واقعی بفرستد و فهرست شماره‌ها را بگیرد. **فقط حروف و ارقام انگلیسی** — مقدارِ هدر HTTP نمی‌تواند فارسی باشد. |
| `MKT_DATA_DIR` | باید روی یک volume ماندگار باشد، نه داخل کانتینر. با ری‌ساختنِ کانتینر، هرچه بیرونِ این مسیر باشد از بین می‌رود. |
| `MKT_CORS_ORIGINS` | آدرسِ واقعیِ رابط کاربری. `*` نگذارید. |

بعد از تنظیم توکن، همان مقدار را در رابط کاربری هم وارد کنید (نشانِ «توکن لازم
است» در نوار بالای صفحه)؛ وگرنه خودِ برنامه هم ۴۰۱ می‌گیرد.

### بررسیِ سلامت

```bash
curl -s localhost:8000/api/health | jq '{status, database, api_token_required}'
```

* `status: "ok"` و `database.ok: true` یعنی سالم.
* پاسخِ **۵۰۳** یعنی دیتابیس جواب نمی‌دهد — به بخش ۵ بروید.
* `api_token_required: false` یعنی سرور بی‌گارد است.

---

## ۲. پشتیبان‌گیری

**تنها چیزی که باید پشتیبان بگیرید، پوشه‌ی `MKT_DATA_DIR` است.** همه‌چیزِ
ماندگار آنجاست: `app.db` (دفتر کل + نشست‌ها + jobها + outbox) و فایل‌های نشست.

SQLite را **در حال اجرا کپی نکنید**؛ فایلِ نیمه‌نوشته پشتیبانِ خراب است. به‌جایش
از دستورِ خودِ SQLite استفاده کنید که با نوشتنِ هم‌زمان سازگار است:

```bash
# پشتیبانِ سازگار، بدون توقف سرویس
docker compose exec api \
  sqlite3 /data/app.db ".backup '/data/backup-$(date +%F).db'"

# بیرون کشیدن و فشرده‌کردن
docker compose cp api:/data/backup-$(date +%F).db ./backups/
gzip ./backups/backup-$(date +%F).db
```

فایل‌های نشست (پوشه‌های کنارِ `app.db`) با `tar` گرفته می‌شوند:

```bash
tar czf ./backups/sessions-$(date +%F).tgz -C ./data sessions
```

### هر چند وقت

| داده | فاصله‌ی پیشنهادی | چرا |
|---|---|---|
| `app.db` | روزانه | همه‌ی داده‌ی تصمیم‌گیری اینجاست |
| فایل‌های نشست | هفتگی | بازساختنی‌اند (با تحلیلِ دوباره‌ی فایل) |

**پیش از هر ارتقا یا مهاجرت، یک پشتیبانِ تازه بگیرید.**

---

## ۳. بازیابی

```bash
docker compose stop api                 # نوشتنِ هم‌زمان ممنوع
gunzip -c backups/backup-1405-06-06.db.gz > data/app.db
docker compose start api
curl -s localhost:8000/api/health | jq .status
```

بعد از بازیابی، این‌ها را چک کنید:

```bash
curl -s localhost:8000/api/v1/data-quality | jq '.counts, .quality_summary'
curl -s localhost:8000/api/v1/ops/jobs/dead-letter | jq '.count'
```

⚠️ **پیش از حذفِ هر جدولی، `ROLLBACK.md` را بخوانید.** بعضی جدول‌ها از هیچ
تحلیلی بازساخته نمی‌شوند — مهم‌ترینشان `contact_suppressions` است (فهرست کسانی
که گفته‌اند «پیام نفرست»). حذفش یعنی همه‌شان بی‌صدا به فهرست تماس برگردند.

---

## ۴. مهاجرت طرح‌واره

مهاجرت‌ها **خودکار** و در زمان راه‌اندازی اجرا می‌شوند (`ensure_schema`)، با یک
دفترِ نسخه در جدول `schema_migrations`. نه Alembic لازم است نه دستور دستی.

```bash
docker compose exec api \
  sqlite3 /data/app.db "SELECT version, name, applied_at FROM schema_migrations ORDER BY version;"
```

* هر مهاجرت **یک‌بار** اجرا می‌شود و idempotent است.
* `PRAGMA user_version` عمداً روی ۲ می‌ماند؛ آن مالِ لایه‌ی قدیمیِ نشست‌هاست و
  ربطی به دفتر کل ندارد.
* بازگشت به نسخه‌ی قبلیِ کد بدون بازگرداندنِ پشتیبان **پشتیبانی نمی‌شود**:
  جدول‌های تازه می‌مانند و کدِ قدیمی نمی‌شناسدشان.

---

## ۵. عیب‌یابی

### `health` می‌گوید ناسالم

```bash
docker compose logs --tail=100 api | grep -i "health\|database"
ls -la data/            # دسترسی و فضای دیسک
df -h                   # «no space left» شایع‌ترین علت است
```

### کارِ زمان‌بندی‌شده انجام نمی‌شود

```bash
curl -s localhost:8000/api/v1/ops/jobs | jq '.jobs[] | {name, last_run: .last_run.status}'
curl -s localhost:8000/api/v1/ops/jobs/dead-letter | jq '.runs[] | {job_name, attempt, error_first_line, note_fa}'
```

کارِ «مرده» خودبه‌خود دوباره اجرا **نمی‌شود**. علت را رفع کنید و بعد:

```bash
curl -X POST -H "X-API-Token: $MKT_API_TOKEN" \
  localhost:8000/api/v1/ops/jobs/runs/<run_id>/retry
```

### یک درخواست کند یا خطادار بود

هر پاسخ هدرِ `X-Request-Id` دارد و همان شناسه در لاگ می‌آید:

```bash
docker compose logs api | grep "rid=<شناسه>"
curl -s localhost:8000/api/v1/ops/metrics | jq '.routes[:5], .error_rate'
```

شمارنده‌ها در حافظه‌اند و با ری‌استارت صفر می‌شوند؛ `uptime_seconds` می‌گوید از
کِی می‌شمارند.

### `database is locked`

SQLite تک-نویسنده است. اگر تکرار شد:

```bash
docker compose exec api sqlite3 /data/app.db "PRAGMA journal_mode;"   # باید wal باشد
```

اجرای هم‌زمانِ موتور فرصت‌ها با «اجاره‌ی اجرا» بسته شده (`job_leases`)؛ اجرای
دوم صریحاً رد می‌شود، نه اینکه منتظر بماند.

### ردیف‌هایی از فایل در گزارش نیستند

```bash
curl -s localhost:8000/api/v1/quarantine | jq '.total, .by_reason'
```

هر ردیف دلیل و **راهِ اصلاح** دارد. تا اصلاح نشوند، در هیچ عددی شمرده نمی‌شوند.

---

## ۶. ارتقا

```bash
tar czf backups/pre-upgrade-$(date +%F).tgz data/   # اول پشتیبان
git pull && docker compose up -d --build
curl -s localhost:8000/api/health | jq '.status, .database.ok'
docker compose exec api sqlite3 /data/app.db "SELECT MAX(version) FROM schema_migrations;"
```

اگر بالا نیامد: کانتینر را پایین بیاورید، پشتیبان را برگردانید (بخش ۳)، و به
کامیتِ قبلی برگردید.

---

## ۷. تمدید TLS

TLS جلوی این برنامه است (Caddy یا nginx)، نه داخلش. با Caddy تمدید خودکار است؛
با certbot:

```bash
sudo certbot renew --dry-run     # آزمایش
sudo certbot renew && docker compose restart proxy
```

گواهیِ منقضی یعنی رابط کاربری کار نمی‌کند و توکن هم روی HTTP رمزنشده می‌رود.
یادآورِ تقویمی بگذارید.
