import type {
  AnalyzeResponse,
  AudienceKind,
  CampaignResponse,
  HealthResponse,
  JobStatus,
  SessionInfo,
  SMSResult,
  StrategyResponse,
  UploadResponse,
} from "./types";

const BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || "http://localhost:8000";

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `خطای سرور (${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* noop */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export async function getHealth(): Promise<HealthResponse> {
  return handle<HealthResponse>(await fetch(`${BASE}/api/health`, { cache: "no-store" }));
}

/** health با چند بار retry — تا بنر «سرور در دسترس نیست» ناخواسته ظاهر نشود. */
export async function getHealthWithRetry(retries = 3): Promise<HealthResponse> {
  let lastErr: unknown;
  for (let i = 0; i < retries; i++) {
    try {
      return await getHealth();
    } catch (e) {
      lastErr = e;
      await new Promise((r) => setTimeout(r, 800 * (i + 1)));
    }
  }
  throw lastErr;
}

// ---------------------------------------------------------------- jobها
export async function getJob(jobId: string): Promise<JobStatus> {
  return handle<JobStatus>(
    await fetch(`${BASE}/api/jobs/${encodeURIComponent(jobId)}`, { cache: "no-store" }),
  );
}

/**
 * poll کردن یک job تا اتمام. onProgress با (درصد، متن مرحله) صدا زده می‌شود.
 * روی خطای job با پیام فارسی سرور reject می‌کند. خطاهای گذرای شبکه (مثلاً
 * ری‌استارت لحظه‌ای سرور) تا ۵ بار با backoff تحمل می‌شوند.
 */
export async function pollJob<T>(
  jobId: string,
  onProgress?: (pct: number, stage: string) => void,
  intervalMs = 1200,
): Promise<T> {
  let netFailures = 0;
  for (;;) {
    let job: JobStatus;
    try {
      job = await getJob(jobId);
      netFailures = 0;
    } catch (e) {
      // پاسخ HTTP سرور (مثل 404) خطای واقعی است؛ فقط خطای شبکه retry می‌شود
      if (!(e instanceof TypeError)) throw e;
      netFailures += 1;
      if (netFailures >= 5) {
        throw new Error(
          "اتصال به سرور قطع شد؛ اگر سرور کرش کرده آن را دوباره اجرا کنید و صفحه را رفرش کنید.",
        );
      }
      await new Promise((r) => setTimeout(r, intervalMs * Math.min(1 + netFailures, 4)));
      continue;
    }
    onProgress?.(job.progress, job.stage);
    if (job.status === "done") return job.result as T;
    if (job.status === "error") throw new Error(job.error || "خطای نامشخص در پردازش");
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}

// --------------------------------------------------------- آپلود و تحلیل
export async function uploadFile(
  file: File,
  onProgress?: (pct: number, stage: string) => void,
  onSession?: (sessionId: string) => void,
): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);
  const { job_id, session_id } = await handle<{ job_id: string; session_id: string }>(
    await fetch(`${BASE}/api/upload`, { method: "POST", body: form }),
  );
  // شناسه‌ی نشست از همین لحظه در دسترس است تا بعد از کرش/رفرش گم نشود
  onSession?.(session_id);
  return pollJob<UploadResponse>(job_id, onProgress);
}

export async function loadSample(): Promise<UploadResponse> {
  return handle<UploadResponse>(await fetch(`${BASE}/api/sample`, { method: "POST" }));
}

export async function analyze(
  params: {
    session_id: string;
    mapping: Record<string, string>;
    horizon: number;
    balanced_uplift: number;
    file_currency: string;
    display_currency: string;
  },
  onProgress?: (pct: number, stage: string) => void,
): Promise<AnalyzeResponse> {
  const { job_id } = await handle<{ job_id: string }>(
    await fetch(`${BASE}/api/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    }),
  );
  return pollJob<AnalyzeResponse>(job_id, onProgress);
}

// ------------------------------------------------------------ بازیابی نشست
export async function getSessionInfo(sessionId: string): Promise<SessionInfo> {
  return handle<SessionInfo>(
    await fetch(`${BASE}/api/session/${encodeURIComponent(sessionId)}`, {
      cache: "no-store",
    }),
  );
}

// ------------------------------------------------------------- هوش مصنوعی
export async function getStrategy(
  session_id: string,
  onProgress?: (pct: number, stage: string) => void,
): Promise<StrategyResponse> {
  const { job_id } = await handle<{ job_id: string }>(
    await fetch(`${BASE}/api/strategy`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id }),
    }),
  );
  return pollJob<StrategyResponse>(job_id, onProgress, 2000);
}

export async function getCampaign(
  session_id: string,
  onProgress?: (pct: number, stage: string) => void,
): Promise<CampaignResponse> {
  const { job_id } = await handle<{ job_id: string }>(
    await fetch(`${BASE}/api/campaign`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id }),
    }),
  );
  return pollJob<CampaignResponse>(job_id, onProgress, 2000);
}

export async function getAudienceKinds(): Promise<{ kinds: AudienceKind[] }> {
  return handle<{ kinds: AudienceKind[] }>(
    await fetch(`${BASE}/api/audience-kinds`, { cache: "no-store" }),
  );
}

export function reportUrl(session_id: string, fmt: "pdf" | "html" = "pdf"): string {
  return `${BASE}/api/report?session_id=${encodeURIComponent(session_id)}&fmt=${fmt}`;
}

export type ExportSection = "segments" | "next_purchase" | "products" | "diagnostics" | "audit";

export function exportUrl(session_id: string, section: ExportSection): string {
  return `${BASE}/api/export?session_id=${encodeURIComponent(session_id)}&section=${section}`;
}

export async function sendSMS(params: {
  session_id: string;
  kind: string;
  template: string;
  limit?: number;
  dry_run?: boolean;
  confirm?: boolean;
}): Promise<SMSResult> {
  return handle<SMSResult>(
    await fetch(`${BASE}/api/sms/send`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dry_run: true, ...params }),
    }),
  );
}

export async function getOutbox(limit = 20): Promise<{ items: OutboxItem[] }> {
  return handle<{ items: OutboxItem[] }>(
    await fetch(`${BASE}/api/outbox?limit=${limit}`, { cache: "no-store" }),
  );
}

export interface OutboxItem {
  id: number;
  created_at: number;
  session_id: string | null;
  kind: string;
  audience: string | null;
  customer_id: string | null;
  phone: string | null;
  message: string | null;
  status: string;
  provider: string | null;
  dry_run: number;
}
