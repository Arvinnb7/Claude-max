"use client";

import { useRef, useState } from "react";
import { FileSpreadsheet, Sparkles, Upload, Wand2 } from "lucide-react";

import { loadSample, uploadFile } from "@/lib/api";
import { toFa } from "@/lib/format";
import type { UploadResponse } from "@/lib/types";
import { Alert, Button, Card, SectionTitle, Spinner } from "./ui";

const STEPS = ["بارگذاری داده", "نگاشت ستون‌ها", "تحلیل و استراتژی"];

export function Stepper({ active }: { active: number }) {
  return (
    <div className="mb-8 flex items-center justify-center gap-2">
      {STEPS.map((label, i) => (
        <div key={label} className="flex items-center gap-2">
          <div className="flex items-center gap-2">
            <span
              className={`grid h-8 w-8 place-items-center rounded-full text-sm font-bold ${
                i <= active
                  ? "bg-brand-600 text-white"
                  : "bg-ink-100 text-ink-400 dark:bg-ink-800 dark:text-ink-500"
              }`}
            >
              {toFa(i + 1)}
            </span>
            <span
              className={`text-sm ${i <= active ? "font-semibold" : ""}`}
              style={{ color: i <= active ? "var(--text)" : "var(--muted)" }}
            >
              {label}
            </span>
          </div>
          {i < STEPS.length - 1 && (
            <span
              className={`mx-2 h-px w-8 ${i < active ? "bg-brand-400" : "bg-ink-200 dark:bg-ink-700"}`}
            />
          )}
        </div>
      ))}
    </div>
  );
}

export function UploadStep({ onLoaded }: { onLoaded: (r: UploadResponse) => void }) {
  const [loading, setLoading] = useState<"file" | "sample" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function handleFile(file: File) {
    setError(null);
    setLoading("file");
    try {
      onLoaded(await uploadFile(file));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(null);
    }
  }

  async function handleSample() {
    setError(null);
    setLoading("sample");
    try {
      onLoaded(await loadSample());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(null);
    }
  }

  if (loading) return <Spinner label="در حال بارگذاری و بررسی داده…" />;

  return (
    <div className="grid gap-5 md:grid-cols-2">
      <Card className="flex flex-col">
        <SectionTitle title="بارگذاری فایل فروش" subtitle="اکسل (xlsx/xls) یا CSV" />
        <div
          onClick={() => fileRef.current?.click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            const f = e.dataTransfer.files?.[0];
            if (f) handleFile(f);
          }}
          className="flex flex-1 cursor-pointer flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed border-ink-200 py-12 text-center transition hover:border-brand-400 hover:bg-brand-50/40 dark:border-ink-700 dark:hover:border-brand-500 dark:hover:bg-brand-500/10"
        >
          <span className="grid h-14 w-14 place-items-center rounded-2xl bg-brand-50 text-brand-600">
            <Upload size={26} />
          </span>
          <p className="font-semibold">فایل را اینجا رها کنید یا کلیک کنید</p>
          <p className="text-xs" style={{ color: "var(--muted)" }}>
            ستون‌های فارسی پشتیبانی می‌شوند؛ نگاشت خودکار انجام می‌شود
          </p>
          <input
            ref={fileRef}
            type="file"
            accept=".xlsx,.xls,.csv,.txt,.tsv"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) handleFile(f);
            }}
          />
        </div>
      </Card>

      <Card className="flex flex-col">
        <SectionTitle title="بدون داده؟ دموی فوری" subtitle="با داده‌ی نمونه‌ی واقع‌گرایانه" />
        <div className="flex flex-1 flex-col items-center justify-center gap-4 text-center">
          <span className="grid h-14 w-14 place-items-center rounded-2xl bg-orange-50 text-accent-600">
            <Sparkles size={26} />
          </span>
          <p className="text-sm" style={{ color: "var(--muted)" }}>
            یک دیتاست فروش دو ساله با روند، فصلی‌بودن و ناهنجاری تولید می‌شود تا همه‌ی
            قابلیت‌ها را ببینید.
          </p>
          <Button onClick={handleSample} variant="outline">
            <Wand2 size={16} /> بارگذاری داده‌ی نمونه
          </Button>
        </div>
      </Card>

      {error && (
        <div className="md:col-span-2">
          <Alert tone="error">{error}</Alert>
        </div>
      )}

      <div className="md:col-span-2">
        <Card>
          <div className="flex items-center gap-3 text-sm" style={{ color: "var(--muted)" }}>
            <FileSpreadsheet size={18} className="text-brand-500" />
            داده‌ی شما فقط برای تحلیل در همین نشست استفاده می‌شود و جایی ذخیره‌ی دائم نمی‌شود.
          </div>
        </Card>
      </div>
    </div>
  );
}

export function MappingStep({
  data,
  onConfirm,
  onBack,
  loading,
}: {
  data: UploadResponse;
  onConfirm: (mapping: Record<string, string>) => void;
  onBack: () => void;
  loading: boolean;
}) {
  const init: Record<string, string> = {};
  for (const r of data.roles) if (r.suggested) init[r.role] = r.suggested;
  const [mapping, setMapping] = useState<Record<string, string>>(init);
  const [ackLowConf, setAckLowConf] = useState(false);

  const requiredMissing = data.roles
    .filter((r) => r.required && !mapping[r.role])
    .map((r) => r.label);

  // ستون‌هایی که سیستم با اطمینان پایین حدس زده (و کاربر تغییرشان نداده)
  const lowConfFields = data.roles.filter(
    (r) => r.low_confidence && !mapping[r.role],
  );
  // فیلدهای الزامی که فقط با حدس کم‌اطمینان پر می‌شوند
  const requiredLowConf = data.roles.filter(
    (r) => r.required && !mapping[r.role] && r.confidence > 0 && r.confidence < 0.65,
  );

  function setRole(role: string, col: string) {
    setMapping((m) => {
      const next = { ...m };
      if (col === "") delete next[role];
      else next[role] = col;
      return next;
    });
  }

  return (
    <div className="space-y-5">
      <Card>
        <SectionTitle
          title="نگاشت ستون‌ها"
          subtitle={`سیستم نقش ${toFa(
            Object.keys(init).length,
          )} ستون را حدس زده است؛ در صورت نیاز اصلاح کنید. ستون‌های ستاره‌دار الزامی‌اند.`}
        />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {data.roles.map((r) => {
            const selected = !!mapping[r.role];
            const conf = Math.round(r.confidence * 100);
            const tone =
              selected && r.confidence >= 0.65
                ? "text-emerald-600"
                : r.confidence >= 0.65
                  ? "text-emerald-600"
                  : r.confidence > 0
                    ? "text-amber-600"
                    : "text-ink-400";
            return (
              <div key={r.role}>
                <label className="mb-1 flex items-center justify-between text-sm font-medium">
                  <span>
                    {r.label}
                    {r.required && <span className="text-rose-500"> *</span>}
                  </span>
                  {r.confidence > 0 && (
                    <span className={`text-xs tnum ${tone}`}>اطمینان {toFa(conf)}٪</span>
                  )}
                </label>
                <select
                  value={mapping[r.role] ?? ""}
                  onChange={(e) => setRole(r.role, e.target.value)}
                  className="w-full rounded-xl border border-ink-200 bg-white px-3 py-2 text-sm outline-none focus:border-brand-400 focus:ring-2 focus:ring-brand-100 dark:border-ink-700 dark:bg-ink-800 dark:text-ink-100 dark:focus:ring-brand-500/30"
                >
                  <option value="">— انتخاب نشده —</option>
                  {data.columns.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
                {!selected && r.low_confidence && (
                  <p className="mt-1 text-xs text-amber-600">
                    ⚠️ این ستون با اطمینان پایین حدس زده شده؛ لطفاً بررسی و دستی انتخاب کنید.
                    {r.reason ? ` (${r.reason})` : ""}
                  </p>
                )}
                {selected && r.reason && (
                  <p className="mt-1 text-xs" style={{ color: "var(--muted)" }}>
                    {r.reason}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      </Card>

      <Card>
        <SectionTitle title="پیش‌نمایش داده" />
        <div className="scrollbar-thin overflow-x-auto">
          <table className="w-full text-right text-sm">
            <thead>
              <tr className="border-b border-ink-200 text-ink-500 dark:border-ink-700 dark:text-ink-400">
                {data.columns.map((c) => (
                  <th key={c} className="whitespace-nowrap px-3 py-2 font-medium">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.preview.slice(0, 8).map((row, i) => (
                <tr key={i} className="border-b border-ink-100 dark:border-ink-800">
                  {data.columns.map((c) => (
                    <td key={c} className="whitespace-nowrap px-3 py-2 tnum">
                      {row[c]}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {requiredMissing.length > 0 && (
        <Alert tone="warn">
          نقش‌های الزامی انتخاب نشده‌اند: {requiredMissing.join("، ")}. لطفاً ستون درست را
          دستی انتخاب کنید تا تحلیل کورکورانه اجرا نشود.
        </Alert>
      )}

      {requiredMissing.length === 0 && lowConfFields.length > 0 && (
        <Alert tone="warn">
          <label className="flex cursor-pointer items-start gap-2">
            <input
              type="checkbox"
              checked={ackLowConf}
              onChange={(e) => setAckLowConf(e.target.checked)}
              className="mt-1"
            />
            <span>
              برخی ستون‌ها با اطمینان پایین حدس زده شده‌اند (
              {lowConfFields.map((r) => r.label).join("، ")}). نگاشت را بررسی کردم و تأیید
              می‌کنم.
            </span>
          </label>
        </Alert>
      )}

      <div className="flex items-center justify-between">
        <Button variant="outline" onClick={onBack}>
          بازگشت
        </Button>
        <Button
          onClick={() => onConfirm(mapping)}
          disabled={
            requiredMissing.length > 0 ||
            loading ||
            (lowConfFields.length > 0 && !ackLowConf) ||
            requiredLowConf.length > 0
          }
        >
          {loading ? "در حال تحلیل…" : "تأیید و تحلیل"}
        </Button>
      </div>
    </div>
  );
}
