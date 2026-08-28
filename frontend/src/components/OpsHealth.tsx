"use client";

import { AlertTriangle, PlayCircle, RotateCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import {
  listDeadLetter,
  listJobs,
  retryJobRun,
  runJobNow,
  type JobRun,
  type ScheduledJob,
} from "@/lib/apiV1";
import { toFa } from "@/lib/format";

import { Alert, Badge, Button, Card, SectionTitle, Spinner } from "./ui";

/**
 * وضعیت کارهای پس‌زمینه و **صف مرده** (§۲۸).
 *
 * سند می‌گوید «Dead-letter/failure visibility» و «Expose job status in the
 * UI/API». صف مرده‌ای که فقط در دیتابیس باشد دیده نمی‌شود — و شکستی که دیده
 * نشود، تکرار می‌شود.
 */
const STATUS_TONE: Record<string, "green" | "accent" | "rose" | "gray"> = {
  succeeded: "green",
  skipped: "gray",
  running: "accent",
  retry_scheduled: "accent",
  dead_letter: "rose",
};

const STATUS_LABEL: Record<string, string> = {
  succeeded: "موفق",
  skipped: "رد شد",
  running: "در حال اجرا",
  retry_scheduled: "تلاش دوباره",
  dead_letter: "شکست نهایی",
};

function when(stamp: number | null): string {
  if (!stamp) return "—";
  return toFa(new Date(stamp * 1000).toLocaleString("fa-IR"));
}

export default function OpsHealth() {
  const [jobs, setJobs] = useState<ScheduledJob[] | null>(null);
  const [dead, setDead] = useState<{ count: number; runs: JobRun[]; note_fa: string } | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [list, dlq] = await Promise.all([listJobs(), listDeadLetter()]);
      setJobs(list.jobs ?? []);
      setDead(dlq);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "خطا در خواندن وضعیت کارها");
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

  if (error) return <Alert tone="error">{error}</Alert>;
  if (!jobs || !dead) return <Spinner label="در حال خواندن وضعیت کارها…" />;

  return (
    <div className="space-y-4">
      {dead.count > 0 && (
        <Alert tone="error">
          <div className="flex items-start gap-2">
            <AlertTriangle size={18} className="mt-0.5 shrink-0" />
            <div>
              <b>{toFa(String(dead.count))} کار در صف مرده است.</b>
              <p className="mt-1 text-xs">{dead.note_fa}</p>
            </div>
          </div>
        </Alert>
      )}

      <Card>
        <SectionTitle
          title="کارهای زمان‌بندی‌شده"
          subtitle="آنچه بدون دخالت شما اجرا می‌شود — و آخرین نتیجه‌ی هرکدام."
        />
        <ul className="space-y-2">
          {jobs.map((job) => (
            <li
              key={job.name}
              className="rounded-xl border border-ink-200 p-3 text-sm dark:border-ink-700"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <b>{job.title_fa}</b>
                  <span className="ms-2 text-xs" style={{ color: "var(--muted)" }}>
                    {job.interval_hours !== null
                      ? `هر ${toFa(String(job.interval_hours))} ساعت`
                      : `ساعت ${toFa(String(job.hour ?? 0))}`}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  {job.last_run && (
                    <Badge tone={STATUS_TONE[job.last_run.status] ?? "gray"}>
                      {STATUS_LABEL[job.last_run.status] ?? job.last_run.status}
                    </Badge>
                  )}
                  <Button
                    variant="ghost"
                    disabled={busy === job.name}
                    onClick={() => {
                      setBusy(job.name);
                      void runJobNow(job.name)
                        .then(load)
                        .catch((e: unknown) =>
                          setError(e instanceof Error ? e.message : "اجرا نشد"),
                        )
                        .finally(() => setBusy(null));
                    }}
                  >
                    <PlayCircle size={16} /> اجرا
                  </Button>
                </div>
              </div>
              {job.last_run ? (
                <p className="mt-1 text-xs" style={{ color: "var(--muted)" }}>
                  آخرین اجرا: {when(job.last_run.started_at)}
                  {job.last_run.note_fa ? ` — ${job.last_run.note_fa}` : ""}
                </p>
              ) : (
                <p className="mt-1 text-xs" style={{ color: "var(--muted)" }}>
                  هنوز اجرا نشده است.
                </p>
              )}
            </li>
          ))}
        </ul>
      </Card>

      {dead.count > 0 && (
        <Card>
          <SectionTitle
            title="صف مرده"
            subtitle="این کارها خودبه‌خود دوباره اجرا نمی‌شوند. علت را رفع کنید و بعد «تلاش دوباره» را بزنید."
          />
          <ul className="space-y-2">
            {dead.runs.map((run) => (
              <li
                key={run.id}
                className="rounded-xl border border-rose-200 p-3 text-sm dark:border-rose-500/30"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <b>{run.job_name}</b>
                  <div className="flex items-center gap-2">
                    <span className="text-xs tnum" style={{ color: "var(--muted)" }}>
                      {toFa(String(run.attempt))} تلاش · {when(run.started_at)}
                    </span>
                    <Button
                      variant="outline"
                      disabled={busy === `run-${run.id}`}
                      onClick={() => {
                        setBusy(`run-${run.id}`);
                        void retryJobRun(run.id)
                          .then(load)
                          .catch((e: unknown) =>
                            setError(e instanceof Error ? e.message : "تلاش دوباره نشد"),
                          )
                          .finally(() => setBusy(null));
                      }}
                    >
                      <RotateCw size={14} /> تلاش دوباره
                    </Button>
                  </div>
                </div>
                {run.error_first_line && (
                  <p className="mt-1 text-xs" dir="ltr" style={{ color: "var(--muted)" }}>
                    {run.error_first_line}
                  </p>
                )}
                <p className="mt-1 text-xs" style={{ color: "var(--muted)" }}>
                  شناسه‌ی همبستگی: <code>{run.correlation_id}</code>
                </p>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
