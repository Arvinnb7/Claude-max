// ابزارهای قالب‌بندی فارسی

const FA_DIGITS = ["۰", "۱", "۲", "۳", "۴", "۵", "۶", "۷", "۸", "۹"];

export function toFa(input: string | number): string {
  return String(input).replace(/[0-9]/g, (d) => FA_DIGITS[Number(d)]);
}

export function num(value: number | null | undefined, opts?: { fa?: boolean }): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const s = Math.round(value).toLocaleString("en-US");
  return opts?.fa ? toFa(s) : s;
}

export function compact(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const abs = Math.abs(value);
  if (abs >= 1e9) return `${toFa((value / 1e9).toFixed(1))} میلیارد`;
  if (abs >= 1e6) return `${toFa((value / 1e6).toFixed(1))} میلیون`;
  if (abs >= 1e3) return `${toFa((value / 1e3).toFixed(1))} هزار`;
  return toFa(Math.round(value).toString());
}

export function pct(value: number | null | undefined, fromRatio = true): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const v = fromRatio ? value * 100 : value;
  return `${toFa(v.toFixed(1))}٪`;
}

export function jalali(iso: string | null): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return toFa(
      new Intl.DateTimeFormat("fa-IR", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
      }).format(d),
    );
  } catch {
    return iso;
  }
}

export function jalaliShort(iso: string): string {
  try {
    const d = new Date(iso);
    return new Intl.DateTimeFormat("fa-IR", { year: "2-digit", month: "short" }).format(d);
  } catch {
    return iso;
  }
}
