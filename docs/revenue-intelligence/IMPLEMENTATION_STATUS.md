# وضعیت پیاده‌سازی

> هر تسک یکی از این‌ها است: `not_started` · `in_progress` · `implemented` · `validated` · `blocked`.
> «implemented» فقط یعنی کد نوشته شده؛ «validated» یعنی تست + مهاجرت + API + UI + سند کامل است.

## تسک‌های فاز ۰+۱+۲

| کد | تسک | وضعیت |
|---|---|---|
| C0 | اسناد فاز صفر (حسابرسی، معماری هدف، قواعد مالی، بازگشت) | `in_progress` |
| C1 | تست‌های مبنا (تله‌ی رگرسیون رفتار فعلی) | `not_started` |
| C2 | rial_per_unit + رفع باگ تبدیل تخفیف مبلغی | `not_started` |
| C3 | sqlalchemy به deps اصلی + لایه‌ی db (engine/base/migrations) | `not_started` |
| C4 | mktcore/money.py — تبدیل ریال صحیح | `not_started` |
| C5 | identity/phone.py — نرمال‌سازی موبایل ایرانی + ماسک | `not_started` |
| C6 | catalog/normalize.py — نام محصول + اندازه‌ی بسته (عمومی) | `not_started` |
| C7 | مدل‌های canonical + repo_import (idempotent) | `not_started` |
| C8 | سیم‌کشی به analyze job + kill-switch + جداسازی خطا | `not_started` |
| C9 | حل هویت مشتری + حل محصول | `not_started` |
| C10 | آشتی + /api/v1/imports + /api/v1/data-quality | `not_started` |
| C11 | snapshot ویژگی مشتری + /api/v1/customers | `not_started` |
| C12 | موتور فرصت‌ها (contract/adapters/filters/ranking/lifecycle) | `not_started` |
| C13 | /api/v1/opportunities + accept/dismiss/snooze | `not_started` |
| C14 | مولدهای باقی‌مانده + lifecycle_state | `not_started` |
| C15 | فرانت: صندوق فرصت‌ها | `not_started` |
| C16 | فرانت: پرونده مشتری + پنل کیفیت داده | `not_started` |
| C17 | fixtureهای طلایی + نهایی‌سازی وضعیت | `not_started` |

## موارد مسدود / واگذارشده

| قابلیت | وضعیت |
|---|---|
| سود ناخالص / COGS / سود افزوده | `blocked: داده‌ی بهای خرید در دست نیست` |
| فیلتر واقعی قابلیت تأمین | `blocked: داده‌ی موجودی انبار در دست نیست` |
| کشش قیمت | `blocked: تنوع قیمت و کنترل‌های لازم ناکافی است` |
| مدل uplift / اثر علّی | `blocked: داده‌ی گروه کنترل وجود ندارد (فاز بعد)` |
| احراز هویت / RBAC / audit log | `deferred: خارج از دامنه‌ی این فازها` |
| Postgres / Celery / Alembic | `deferred: تصمیم مستند در TARGET_ARCHITECTURE` |

## سنجه‌های پذیرش

- [ ] تحلیل دوباره‌ی همان فایل ردیف تکراری نمی‌سازد (idempotent)
- [ ] جمع ریالی دفتر کل با KPI داشبورد در تلرانس مستند آشتی می‌کند
- [ ] هر فرصت شواهد کامل دارد (مولد+نسخه، سفارش‌های منبع، کدهای دلیل، فاکتورهای فیلتر)
- [ ] هیچ عدد درآمدی «سود» نامیده نمی‌شود
- [ ] هیچ فیلد علّی بدون شواهد آزمایشی پر نمی‌شود
- [ ] ۱۵۰ تست موجود + تست‌های جدید سبز
