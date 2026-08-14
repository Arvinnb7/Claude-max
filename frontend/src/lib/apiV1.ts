/**
 * کلاینت مسیرهای `/api/v1` — دفتر کل، فرصت‌ها و کیفیت داده.
 *
 * جدا از `api.ts` نگه داشته شده تا قرارداد فعلی داشبورد دست‌نخورده بماند.
 *
 * قاعده‌ی مهم رندر: مبالغ به شکل `Money` می‌آیند (`rial` صحیح + `display_text`
 * آماده). **هرگز** `compact()` یا هر قالب‌بندی دیگری روی `rial` زده نشود —
 * عدد ریالی است و ده برابر بزرگ‌تر از واحد نمایش؛ همیشه `display_text` رندر شود.
 */

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

export type Money = {
  rial: number | null;
  display_text: string;
  display_currency: string;
};

export type ImportBatch = {
  id: number;
  dataset_key: string;
  revision: number;
  session_id: string | null;
  filename: string | null;
  sheet: string | null;
  created_at: number;
  date_min: string | null;
  date_max: string | null;
  rows: {
    total: number | null;
    clean: number | null;
    invalid: number | null;
    duplicate: number | null;
    returns: number | null;
  };
  lines_inserted: number;
  lines_updated: number;
  net_sales: Money;
  file_currency: string | null;
  display_currency: string | null;
  validation_status: string | null;
  reconcile_status: string | null;
};

export type ReconcileCheck = {
  id: string;
  label: string;
  expected: string | null;
  actual: string | null;
  delta: string | null;
  tolerance: string | null;
  status: "OK" | "WARN" | "MISMATCH";
  detail: string | null;
};

export type DataQualityGap = {
  id: string;
  label_fa: string;
  impact_fa: string;
  coverage: number;
  severity: string;
};

export type DataQuality = {
  available: boolean;
  note_fa?: string;
  counts?: Record<string, number>;
  latest_batch?: ImportBatch | null;
  mismatches?: { id: string; label: string; expected: string | null; actual: string | null; detail: string | null }[];
  gaps?: DataQualityGap[];
  economics_note_fa?: string;
};

export type CustomerFeatures = {
  as_of: string;
  n_orders: number | null;
  n_lines: number | null;
  monetary: Money;
  aov: Money;
  clv_12m: Money;
  value_at_risk: Money;
  recency_days: number | null;
  tenure_days: number | null;
  avg_gap_days: number | null;
  overdue_days: number | null;
  p_alive: number | null;
  segment: string | null;
  lifecycle_state: string | null;
  lifecycle_label: string | null;
  cycle_status: string | null;
  top_product: string | null;
};

export type LifecycleTransition = {
  as_of: string;
  from: string | null;
  from_label: string | null;
  to: string;
  to_label: string;
  reason: string | null;
  basis: string | null;
  basis_label: string | null;
  overdue_ratio: number | null;
};

export type CustomerRow = {
  id: number;
  key: string;
  name: string | null;
  phone_masked: string | null;
  has_phone: boolean;
  first_order_date: string | null;
  last_order_date: string | null;
  resolution_method: string;
  features: CustomerFeatures | null;
};

export type CustomerProfile = {
  available: boolean;
  customer: CustomerRow;
  feature_history: {
    as_of: string;
    n_orders: number | null;
    monetary: Money;
    recency_days: number | null;
    segment: string | null;
    lifecycle_state: string | null;
    cycle_status: string | null;
  }[];
  lifecycle_timeline: LifecycleTransition[];
  lines: {
    date: string;
    product: string | null;
    quantity: number | null;
    revenue: Money;
    is_return: boolean;
    source_row: number | null;
    sheet: string | null;
  }[];
  economics_note_fa: string;
};

export type OpportunityFactor = {
  code: string;
  label: string;
  outcome: "evidence" | "filter_pass" | "filter_skip" | "filter_block";
  detail: string | null;
  value: string | null;
};

export type Opportunity = {
  id: number;
  kind: string;
  title: string;
  action: string;
  reason: string;
  message: string | null;
  customer_id: number | null;
  customer_name: string | null;
  product_id: number | null;
  expected_value: Money;
  value_kind: string;
  probability: number | null;
  confidence: string | null;
  status: string;
  status_reason: string | null;
  assigned_to: string | null;
  owner_hint: string | null;
  due_date: string | null;
  expires_at: string | null;
  snooze_until: string | null;
  seen_count: number;
  generator: string;
  generator_version: number;
  attributed_revenue: Money;
  incremental_revenue: Money;
  causal_note_fa: string;
  created_at: number;
  updated_at: number;
  factors?: OpportunityFactor[];
  events?: {
    type: string;
    from: string | null;
    to: string | null;
    actor: string | null;
    note: string | null;
    at: number;
  }[];
};

export type OpportunityList = {
  available: boolean;
  note_fa?: string;
  items: Opportunity[];
  total: number;
  status_counts?: Record<string, number>;
  open_pipeline?: Money;
  economics_note_fa?: string;
};

export type CustomerList = {
  available: boolean;
  note_fa?: string;
  items: CustomerRow[];
  total: number;
  as_of?: string | null;
  economics_note_fa?: string;
};

// ------------------------------------------------------------------ توابع
export async function listImports(limit = 50): Promise<{
  available: boolean;
  note_fa?: string;
  items: ImportBatch[];
  economics_note_fa?: string;
}> {
  return handle(
    await fetch(`${BASE}/api/v1/imports?limit=${limit}`, { cache: "no-store" }),
  );
}

export async function getImport(
  batchId: number,
): Promise<ImportBatch & { checks: ReconcileCheck[]; economics_note_fa: string }> {
  return handle(await fetch(`${BASE}/api/v1/imports/${batchId}`, { cache: "no-store" }));
}

export async function getDataQuality(): Promise<DataQuality> {
  return handle(await fetch(`${BASE}/api/v1/data-quality`, { cache: "no-store" }));
}

export async function listCustomers(params: {
  q?: string;
  limit?: number;
  offset?: number;
  orderBy?: "monetary" | "recency" | "orders" | "name";
} = {}): Promise<CustomerList> {
  const search = new URLSearchParams();
  if (params.q) search.set("q", params.q);
  search.set("limit", String(params.limit ?? 50));
  search.set("offset", String(params.offset ?? 0));
  search.set("order_by", params.orderBy ?? "monetary");
  return handle(
    await fetch(`${BASE}/api/v1/customers?${search.toString()}`, { cache: "no-store" }),
  );
}

export async function getCustomer(customerId: number): Promise<CustomerProfile> {
  return handle(
    await fetch(`${BASE}/api/v1/customers/${customerId}`, { cache: "no-store" }),
  );
}

export async function listOpportunities(params: {
  status?: string;
  kind?: string;
  assignedTo?: string;
  limit?: number;
  offset?: number;
} = {}): Promise<OpportunityList> {
  const search = new URLSearchParams();
  search.set("status", params.status ?? "open");
  if (params.kind) search.set("kind", params.kind);
  if (params.assignedTo) search.set("assigned_to", params.assignedTo);
  search.set("limit", String(params.limit ?? 50));
  search.set("offset", String(params.offset ?? 0));
  return handle(
    await fetch(`${BASE}/api/v1/opportunities?${search.toString()}`, { cache: "no-store" }),
  );
}

export async function getOpportunity(id: number): Promise<Opportunity> {
  return handle(await fetch(`${BASE}/api/v1/opportunities/${id}`, { cache: "no-store" }));
}

export type OpportunityActionName = "accept" | "dismiss" | "snooze" | "done" | "reopen";

// ------------------------------------------------------------------ کمپین
export type CampaignSummary = {
  id: number;
  name: string;
  kind: string | null;
  status: string;
  holdout_pct: number;
  analysis_window_days: number;
  created_at: number;
  exported_at: number | null;
  closed_at: number | null;
  treatment_size: number;
  control_size: number;
  exposed_count: number;
  treatment_pipeline: Money;
  strata: Record<string, number>;
  exposure_note_fa?: string;
};

export type ArmSummary = {
  size: number;
  converters: number;
  orders: number;
  revenue_rial: number;
  conversion_rate: number;
  revenue_per_customer_rial: number;
};

export type CampaignReport = {
  verdict: "proven" | "inconclusive" | "attribution_only" | "not_ready";
  verdict_label: string;
  verdict_reason_fa: string;
  is_causal: boolean;
  arms: { treatment: ArmSummary; control: ArmSummary };
  absolute_lift: number | null;
  relative_lift: number | null;
  lift_ci: [number, number] | null;
  incremental_orders: number | null;
  incremental_revenue: Money;
  incremental_revenue_ci: [number, number] | null;
  blocked_metrics: Record<string, string>;
};

export type CampaignMemberRow = {
  customer_id: number;
  customer_name: string | null;
  arm: string;
  stratum: string | null;
  exposure_date: string | null;
  expected_value: Money;
  outcome: {
    orders: number;
    revenue: Money;
    matched_product: boolean;
    window: [string, string];
  } | null;
};

export type CampaignDetail = CampaignSummary & {
  report: CampaignReport;
  members: CampaignMemberRow[];
};

export async function listCampaigns(): Promise<{
  available: boolean;
  note_fa?: string;
  items: CampaignSummary[];
  exposure_note_fa?: string;
}> {
  return handle(await fetch(`${BASE}/api/v1/campaigns`, { cache: "no-store" }));
}

export async function getCampaign(id: number): Promise<CampaignDetail> {
  return handle(await fetch(`${BASE}/api/v1/campaigns/${id}`, { cache: "no-store" }));
}

export async function createCampaign(body: {
  name: string;
  status?: string;
  kind?: string;
  holdout_pct?: number;
  analysis_window_days?: number;
  limit?: number;
}): Promise<CampaignSummary> {
  return handle(
    await fetch(`${BASE}/api/v1/campaigns`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}

export async function refreshCampaign(id: number): Promise<CampaignDetail> {
  return handle(
    await fetch(`${BASE}/api/v1/campaigns/${id}/refresh`, { method: "POST" }),
  );
}

export async function closeCampaign(id: number): Promise<CampaignDetail> {
  return handle(
    await fetch(`${BASE}/api/v1/campaigns/${id}/close`, { method: "POST" }),
  );
}

export function campaignExportUrl(id: number): string {
  return `${BASE}/api/v1/campaigns/${id}/export`;
}

export type DismissReason = { code: string; label: string };

export async function listDismissReasons(): Promise<{
  items: DismissReason[];
  note_fa: string;
}> {
  return handle(await fetch(`${BASE}/api/v1/dismiss-reasons`, { cache: "no-store" }));
}

export async function actOnOpportunity(
  id: number,
  action: OpportunityActionName,
  body: {
    actor?: string;
    note?: string;
    assigned_to?: string;
    snooze_until?: string;
    reason_code?: string;
  } = {},
): Promise<Opportunity> {
  return handle(
    await fetch(`${BASE}/api/v1/opportunities/${id}/${action}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}
