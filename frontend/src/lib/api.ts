import type {
  AnalyzeResponse,
  AudienceKind,
  CampaignResponse,
  HealthResponse,
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

export async function uploadFile(file: File): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);
  return handle<UploadResponse>(
    await fetch(`${BASE}/api/upload`, { method: "POST", body: form }),
  );
}

export async function loadSample(): Promise<UploadResponse> {
  return handle<UploadResponse>(await fetch(`${BASE}/api/sample`, { method: "POST" }));
}

export async function analyze(params: {
  session_id: string;
  mapping: Record<string, string>;
  horizon: number;
  balanced_uplift: number;
}): Promise<AnalyzeResponse> {
  return handle<AnalyzeResponse>(
    await fetch(`${BASE}/api/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    }),
  );
}

export async function getStrategy(session_id: string): Promise<StrategyResponse> {
  return handle<StrategyResponse>(
    await fetch(`${BASE}/api/strategy`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id }),
    }),
  );
}

export async function getCampaign(session_id: string): Promise<CampaignResponse> {
  return handle<CampaignResponse>(
    await fetch(`${BASE}/api/campaign`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id }),
    }),
  );
}

export async function getAudienceKinds(): Promise<{ kinds: AudienceKind[] }> {
  return handle<{ kinds: AudienceKind[] }>(
    await fetch(`${BASE}/api/audience-kinds`, { cache: "no-store" }),
  );
}

export async function sendSMS(params: {
  session_id: string;
  kind: string;
  template: string;
  limit?: number;
}): Promise<SMSResult> {
  return handle<SMSResult>(
    await fetch(`${BASE}/api/sms/send`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...params, dry_run: true }),
    }),
  );
}
