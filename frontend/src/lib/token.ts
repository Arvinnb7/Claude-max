/**
 * توکنِ دسترسی سمتِ مرورگر.
 *
 * ## مسئله‌ای که این فایل حل می‌کند
 *
 * سمتِ سرور، مسیرهای نوشتنی و پرخرج با هدرِ `X-API-Token` بسته شده‌اند. تا پیش
 * از این، رابط کاربری **هیچ** جایی این هدر را نمی‌فرستاد؛ یعنی به‌محضِ تنظیمِ
 * `MKT_API_TOKEN` روی سرور، خودِ برنامه هم از کار می‌افتاد. عملاً کاربر بین
 * «امن» و «کارکردن» یکی را باید انتخاب می‌کرد — که یعنی هیچ‌کس آن را روشن
 * نمی‌کرد.
 *
 * ## چرا `localStorage` و نه کوکی
 *
 * سرور توکن را از هدر می‌خواند نه از کوکی، و این نصب تک‌کاربره‌ی محلی/VPS است.
 * `localStorage` ساده‌ترین چیزی است که کار می‌کند و در برابر CSRF هم بهتر است:
 * توکن **خودکار** به هیچ درخواستی چسبانده نمی‌شود، فقط کدِ خودمان می‌فرستدش.
 * در عوض در برابر XSS آسیب‌پذیر است — که برای این سطح از سیستم پذیرفته شده و
 * در `SECURITY_AND_PRIVACY` مکتوب می‌شود.
 *
 * ## چرا نه در متغیر محیطیِ Next
 *
 * `NEXT_PUBLIC_*` در خروجیِ build جاسازی می‌شود و در سورسِ صفحه دیده می‌شود؛
 * توکنی که در هر تبِ مرورگرِ هر کسی قابل خواندن باشد، توکن نیست.
 */

const STORAGE_KEY = "mkt_api_token";

export const TOKEN_HEADER = "X-API-Token";

type Listener = (token: string) => void;

const listeners = new Set<Listener>();

/** خطای «توکن لازم است یا غلط است» — تا UI بتواند جدایش کند از خطای معمول. */
export class UnauthorizedError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "UnauthorizedError";
  }
}

export function getToken(): string {
  if (typeof window === "undefined") return "";
  try {
    return window.localStorage.getItem(STORAGE_KEY) ?? "";
  } catch {
    // حالت خصوصیِ مرورگر یا مسدودبودنِ ذخیره‌سازی: بی‌توکن ادامه می‌دهیم
    return "";
  }
}

export function setToken(token: string): void {
  if (typeof window === "undefined") return;
  const value = token.trim();
  try {
    if (value) window.localStorage.setItem(STORAGE_KEY, value);
    else window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* noop */
  }
  listeners.forEach((fn) => fn(value));
}

export function clearToken(): void {
  setToken("");
}

export function hasToken(): boolean {
  return getToken().length > 0;
}

/** اشتراک در تغییرِ توکن — برای بنر و فرمِ تنظیمات. */
export function subscribeToken(fn: Listener): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

/** هدرهای درخواست، با توکن اگر تنظیم شده باشد. */
export function authHeaders(extra?: HeadersInit): Headers {
  const headers = new Headers(extra);
  const token = getToken();
  if (token) headers.set(TOKEN_HEADER, token);
  return headers;
}

/**
 * جایگزینِ `fetch` برای همه‌ی تماس‌های API.
 *
 * تنها کاری که می‌کند چسباندنِ هدرِ توکن است. عمداً هیچ منطقِ دیگری ندارد تا
 * جایگزینیِ `fetch` با آن در سراسر کلاینت بی‌خطر باشد.
 */
export function apiFetch(url: string, init: RequestInit = {}): Promise<Response> {
  return fetch(url, { ...init, headers: authHeaders(init.headers) });
}

/**
 * دانلودِ فایل با هدرِ توکن.
 *
 * لینکِ ساده‌ی `<a href>` نمی‌تواند هدر بفرستد؛ پس فایل را با `fetch`
 * می‌گیریم و از روی `blob` ذخیره می‌کنیم. نامِ فایل از هدرِ
 * `Content-Disposition` خوانده می‌شود تا نامِ فارسیِ سرور حفظ شود.
 */
export async function downloadWithToken(url: string, fallbackName: string): Promise<void> {
  const res = await apiFetch(url);
  if (!res.ok) {
    let detail = `خطای سرور (${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* noop */
    }
    if (res.status === 401) throw new UnauthorizedError(detail);
    throw new Error(detail);
  }

  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filenameFrom(res.headers.get("content-disposition")) || fallbackName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // آزادکردنِ حافظه بعد از اینکه مرورگر دانلود را برداشت
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 10_000);
}

/** `attachment; filename*=UTF-8''...` یا `attachment; filename="..."` */
export function filenameFrom(disposition: string | null): string {
  if (!disposition) return "";
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
  if (utf8) {
    try {
      return decodeURIComponent(utf8[1].trim());
    } catch {
      return utf8[1].trim();
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(disposition);
  return plain ? plain[1].trim() : "";
}
