"use client";

/**
 * سلامت مدل — §۲۷.۷ سند.
 *
 * هشت قلمی که سند می‌خواهد: نسخه‌ی فعال، پنجره‌ی آموزش، پنجره‌ی اعتبارسنجی،
 * سنجه‌های کسب‌وکاری، کالیبراسیون، انحراف، آخرین امتیازدهی، و دکمه‌ی بازگشت.
 *
 * قاعده‌ی نمایش (جمله‌ی آخر §۲۷.۷): «پیچیدگی خام ML را بدون تفسیر کسب‌وکاری
 * نشان نده.» پس هر عدد یک جمله‌ی فارسی همراه دارد، و وقتی مدلی فعال نیست
 * به‌جای نمودارِ خالی، **جدولِ «لازم در برابر موجود»** نشان داده می‌شود تا
 * کاربر بداند دقیقاً چقدر داده کم دارد.
 */

import { useCallback, useEffect, useState } from "react";
import { RefreshCw, Undo2 } from "lucide-react";

import {
  getModelDrift,
  listModelRuns,
  promoteModelRun,
  rollbackModelRun,
  trainModel,
  type ModelDrift,
  type ModelRun,
  type ModelRunList,
} from "@/lib/apiV1";
import { toFa } from "@/lib/format";

import { Alert, Badge, Button, Card, SectionTitle, Spinner, StatCard } from "./ui";

const STATUS_TONE: Record<string, "green" | "rose" | "gray" | "brand" | "accent"> = {
  promoted: "green",
  validated: "brand",
  validated_rejected: "accent",
  insufficient_data: "gray",
  trained: "gray",
  rolled_back: "accent",
  superseded: "gray",
};

const DRIFT_TONE: Record<string, "green" | "accent" | "rose"> = {
  پایدار: "green",
  هشدار: "accent",
  "تغییر معنادار": "rose",
};

export default function ModelHealth() {
  const [data, setData] = useState<ModelRunList | null>(null);
  const [drift, setDrift] = useState<Record<number, ModelDrift>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setData(await listModelRuns());
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا در خواندن وضعیت مدل‌ها");
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => {
      if (!cancelled) void load();
    });
    return () => {
      cancelled = true;
    };
  }, [load]);

  async function run(action: () => Promise<unknown>, message: string) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await action();
      setNotice(message);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "عملیات انجام نشد");
    } finally {
      setBusy(false);
    }
  }

  async function showDrift(id: number) {
    try {
      const report = await getModelDrift(id);
      setDrift((current) => ({ ...current, [id]: report }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا در سنجش انحراف");
    }
  }

  if (!data && !error) {
    return (
      <Card>
        <Spinner label="در حال خواندن وضعیت مدل‌ها…" />
      </Card>
    );
  }

  if (data && !data.available) {
    return (
      <Card>
        <SectionTitle title="سلامت مدل" />
        <Alert tone="info">{data.note_fa}</Alert>
      </Card>
    );
  }

  const active = data?.active ?? {};

  return (
    <div className="space-y-4">
      <Card>
        <SectionTitle
          title="سلامت مدل"
          subtitle="مدلی که فعال نباشد هیچ اثری بر رفتار سیستم ندارد."
        />

        {error && (
          <div className="mb-3">
            <Alert tone="warn">{error}</Alert>
          </div>
        )}
        {notice && (
          <div className="mb-3">
            <Alert tone="info">{notice}</Alert>
          </div>
        )}

        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {Object.entries(active).map(([key, run_]) => (
            <div
              key={key}
              className="rounded-xl border border-ink-200 p-3 text-sm dark:border-ink-700"
            >
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <b>{run_?.model_label_fa ?? key}</b>
                <Badge tone={run_ ? "green" : "gray"}>
                  {run_ ? `نسخه ${toFa(String(run_.model_version))}` : "مدلی فعال نیست"}
                </Badge>
              </div>
              {run_ ? (
                <ActiveModel run={run_} onDrift={() => void showDrift(run_.id)} drift={drift[run_.id]} />
              ) : (
                <p className="text-xs" style={{ color: "var(--muted)" }}>
                  تا وقتی مدلی فعال نشود، این بخش از سیستم دقیقاً مثل قبل کار
                  می‌کند و هیچ عددی از مدل روی مشتریان نوشته نمی‌شود.
                </p>
              )}
              {data?.trainable?.includes(key) && (
                <Button
                  variant="ghost"
                  disabled={busy}
                  onClick={() =>
                    void run(() => trainModel(key), `آموزش «${key}» انجام شد.`)
                  }
                >
                  <RefreshCw size={14} /> آموزش دوباره
                </Button>
              )}
            </div>
          ))}
        </div>
      </Card>

      <Card>
        <SectionTitle
          title="تاریخچه‌ی اجراها"
          subtitle="هر آموزش ثبت می‌شود — حتی وقتی نتیجه‌اش «داده کافی نبود» باشد."
        />
        <div className="max-h-[28rem] overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-white dark:bg-ink-900">
              <tr className="text-start">
                <th className="p-2 text-start">مدل</th>
                <th className="p-2 text-start">نسخه</th>
                <th className="p-2 text-start">وضعیت</th>
                <th className="p-2 text-start">پنجره‌ی آموزش</th>
                <th className="p-2 text-start">پنجره‌ی اعتبارسنجی</th>
                <th className="p-2 text-start">اقدام</th>
              </tr>
            </thead>
            <tbody>
              {(data?.items ?? []).map((item) => (
                <tr key={item.id} className="border-t border-ink-100 dark:border-ink-800">
                  <td className="p-2">{item.model_label_fa}</td>
                  <td className="p-2 tnum">{toFa(String(item.model_version))}</td>
                  <td className="p-2">
                    <Badge tone={STATUS_TONE[item.status] ?? "gray"}>
                      {item.status_label_fa}
                    </Badge>
                  </td>
                  <td className="p-2 tnum">{windowText(item.train_window)}</td>
                  <td className="p-2 tnum">{windowText(item.validate_window)}</td>
                  <td className="p-2">
                    <div className="flex flex-wrap gap-1.5">
                      {item.status === "validated" && (
                        <Button
                          variant="primary"
                          disabled={busy}
                          onClick={() =>
                            void run(
                              () => promoteModelRun(item.id),
                              "مدل فعال شد.",
                            )
                          }
                        >
                          فعال‌سازی
                        </Button>
                      )}
                      {item.promoted && (
                        <Button
                          variant="ghost"
                          disabled={busy}
                          onClick={() =>
                            void run(
                              () => rollbackModelRun(item.id),
                              "به نسخه‌ی قبلی برگشت.",
                            )
                          }
                        >
                          <Undo2 size={14} /> بازگشت
                        </Button>
                      )}
                    </div>
                    {item.blocked_reason_fa && (
                      <p className="mt-1 text-xs" style={{ color: "var(--muted)" }}>
                        {item.blocked_reason_fa}
                      </p>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

function ActiveModel({
  run,
  drift,
  onDrift,
}: {
  run: ModelRun;
  drift?: ModelDrift;
  onDrift: () => void;
}) {
  const metrics = (run.metrics ?? {}) as Record<string, number | undefined>;
  const lift = metrics.topk_lift_bp;
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-2">
        <StatCard label="پنجره‌ی آموزش" value={windowText(run.train_window)} />
        <StatCard label="پنجره‌ی اعتبارسنجی" value={windowText(run.validate_window)} />
      </div>
      <p className="text-xs" style={{ color: "var(--muted)" }}>
        {lift != null
          ? `این مدل در «K تای اول» ${toFa(String(Math.round(lift / 100)))}٪ بیشتر از
             روشِ سرانگشتیِ قبلی ارزش گرفت — همان معیاری که برای فعال‌سازی لازم بود.`
          : "سنجه‌ی اقتصادی برای این مدل ثبت نشده است."}
      </p>
      {metrics.max_calibration_bin_error != null && (
        <p className="text-xs" style={{ color: "var(--muted)" }}>
          کالیبراسیون: بیشترین اختلافِ «پیش‌بینی» با «واقعیت» در بین‌ها{" "}
          {toFa(String(Math.round(metrics.max_calibration_bin_error * 100)))} واحد درصد
          است؛ یعنی وقتی مدل ۸۰٪ می‌گوید، تقریباً ۸۰٪ اتفاق می‌افتد.
        </p>
      )}
      {run.last_scored_at && (
        <p className="text-xs" style={{ color: "var(--muted)" }}>
          آخرین امتیازدهی: {toFa(String(run.n_scored ?? 0))} مشتری
        </p>
      )}
      {explanationOf(run).slice(0, 3).map((line) => (
        <p key={line} className="text-xs" style={{ color: "var(--muted)" }}>
          • {line}
        </p>
      ))}
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="ghost" onClick={onDrift}>
          سنجش انحراف
        </Button>
        {drift && (
          <Badge tone={drift.level ? DRIFT_TONE[drift.level] ?? "gray" : "gray"}>
            {drift.measured ? drift.level : "نسنجیده"}
          </Badge>
        )}
      </div>
      {drift && (
        <p className="text-xs" style={{ color: "var(--muted)" }}>
          {drift.note_fa}
        </p>
      )}
    </div>
  );
}

function explanationOf(run: ModelRun): string[] {
  const raw = (run.metrics ?? {})["explanation_fa"];
  return Array.isArray(raw) ? (raw as string[]) : [];
}

function windowText(window: [string | null, string | null] | undefined): string {
  if (!window || !window[0] || !window[1]) return "—";
  return `${toFa(window[0])} تا ${toFa(window[1])}`;
}
