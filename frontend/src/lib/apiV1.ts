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
  /** `null` یعنی انصرافی ثبت نشده — که «رضایت» نیست، فقط «نه‌گفتنی ثبت نشده». */
  contact_opt_out: {
    reason_fa: string | null;
    scope: string;
    source: string;
    opted_out_at: number | null;
  } | null;
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
  /** `null` یعنی پوششِ بها کامل نبود — نه اینکه بها صفر بوده. */
  cost_rial: number | null;
  gross_profit_rial: number | null;
  profit_per_customer_rial: number | null;
  cost: Money | null;
  gross_profit: Money | null;
  profit_per_customer: Money | null;
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
  /**
   * کوچک‌ترین اثری که با **این** اندازه‌ی گروه‌ها دیدنی بود. بدون این عدد،
   * «شواهد کافی نیست» مبهم است.
   */
  detectable_effect: number | null;
  power_note_fa: string | null;
  /** هزینه‌ی واقعیِ تماس. `null` یعنی ارسالی از داخل سیستم انجام نشده. */
  contact_cost_rial: number | null;
  contact_cost: Money | null;
  cost_per_incremental_order_rial: number | null;
  cost_per_incremental_order: Money | null;
  /**
   * سود ناخالص افزوده — شمالِ‌ستاره‌ی سند. `null` تا وقتی پوششِ بها در هر دو
   * بازو کامل نباشد؛ دلیلش همیشه در `gross_profit_note_fa` است.
   */
  incremental_gross_profit_rial: number | null;
  incremental_gross_profit: Money | null;
  gross_profit_note_fa: string | null;
};

/** نتیجه‌ی یک ارسال کمپین. */
export type CampaignSendResult = {
  "ارسال‌شده": number;
  "ناموفق": number;
  "بدون_شماره": number;
  "حالت_آزمایشی": boolean;
  "ارائه‌دهنده": string;
  "قطعه": number;
  "هزینه": Money;
  "مسدودشده": number;
  "دلایل_مسدودی": { "دلیل": string; "تعداد": number }[];
  "نمونه_پیام": {
    "مشتری": number;
    "گیرنده": string;
    "متن": string;
    "قطعه": number;
  }[];
  "بدون_متن": number;
  "یادداشت_هزینه": string;
  "توضیح"?: string;
  "یادداشت_مجوز_تماس"?: string;
};

export async function sendCampaignSms(
  id: number,
  body: { template?: string; dry_run?: boolean; confirm?: boolean } = {},
): Promise<CampaignDetail & { send: CampaignSendResult }> {
  return handle(
    await fetch(`${BASE}/api/v1/campaigns/${id}/send`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dry_run: true, ...body }),
    }),
  );
}

/** یک سطر از برنامه‌ی آزمایش: یک گروه، و اینکه چه می‌دانیم و چه لازم داریم. */
export type ExperimentCell = {
  kind: string;
  lifecycle_state: string;
  status: "proven" | "useless" | "inconclusive" | "thin" | "no_data";
  status_label_fa: string;
  settled: boolean;
  available: number;
  n_treatment: number;
  n_control: number;
  measured_uplift: number | null;
  ci: [number, number] | null;
  baseline_rate: number;
  baseline_source: "cell_control" | "global_control" | "assumed";
  baseline_source_fa: string;
  target_effect: number;
  holdout_pct: number;
  required_total: number | null;
  detectable_now: number | null;
  feasible_now: boolean;
  unmeasured_contacts: number;
  note_fa: string;
};

export type ExperimentPlan = {
  available: boolean;
  target_effect?: number;
  holdout_pct?: number;
  /** واحد «فرصتِ تماس» است نه «نفر» — یک مشتری می‌تواند در دو گروه باشد. */
  total_unmeasured_contacts?: number;
  next_experiment?: ExperimentCell | null;
  cells?: ExperimentCell[];
  method_note_fa?: string;
  holdout_note_fa?: string;
  note_fa?: string;
};

export async function getExperimentPlan(params: {
  targetEffect?: number;
  holdoutPct?: number;
} = {}): Promise<ExperimentPlan> {
  const query = new URLSearchParams();
  if (params.targetEffect != null) query.set("target_effect", String(params.targetEffect));
  if (params.holdoutPct != null) query.set("holdout_pct", String(params.holdoutPct));
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return handle(
    await fetch(`${BASE}/api/v1/experiment-plan${suffix}`, { cache: "no-store" }),
  );
}

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

// ------------------------------------------------------- اثر آموخته‌شده
export type UpliftCell = {
  kind: string;
  lifecycle_state: string;
  n_treatment: number;
  n_control: number;
  rate_treatment: number;
  rate_control: number;
  raw_uplift: number;
  uplift: number;
  basis: string;
  basis_label: string;
  ci: [number, number] | null;
  has_enough_data: boolean;
  useless: boolean;
};

export type UpliftTable = {
  available: boolean;
  note_fa?: string;
  n_observations?: number;
  global_uplift?: number | null;
  by_kind?: Record<string, number>;
  cells?: UpliftCell[];
  reference_note_fa?: string;
  method_note_fa?: string;
};

export async function getLearnedUplift(): Promise<UpliftTable> {
  return handle(await fetch(`${BASE}/api/v1/uplift`, { cache: "no-store" }));
}

export type DismissReason = { code: string; label: string };

export async function listDismissReasons(): Promise<{
  items: DismissReason[];
  note_fa: string;
}> {
  return handle(await fetch(`${BASE}/api/v1/dismiss-reasons`, { cache: "no-store" }));
}

/** یک ردیف از دفترِ «تماس نگیر». */
export type ContactSuppression = {
  id: number;
  customer_id: number | null;
  customer_name: string | null;
  phone: string | null;
  scope: string;
  source: string;
  reason_fa: string | null;
  opted_out_at: number | null;
  revoked_at: number | null;
  active: boolean;
};

export async function listContactSuppressions(activeOnly = true): Promise<{
  items: ContactSuppression[];
  total: number;
  note_fa: string;
}> {
  return handle(
    await fetch(`${BASE}/api/v1/contact-suppressions?active_only=${activeOnly}`, {
      cache: "no-store",
    }),
  );
}

/** ثبت انصراف. دلیل اجباری است — سرور رشته‌ی خالی را رد می‌کند. */
export async function optOutCustomer(
  customerId: number,
  reasonFa: string,
  actor?: string,
): Promise<{ created: boolean; reactivated: boolean; note_fa: string }> {
  return handle(
    await fetch(`${BASE}/api/v1/customers/${customerId}/opt-out`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason_fa: reasonFa, actor }),
    }),
  );
}

export async function revokeCustomerOptOut(
  customerId: number,
): Promise<{ revoked: boolean; note_fa: string }> {
  return handle(
    await fetch(`${BASE}/api/v1/customers/${customerId}/opt-out`, { method: "DELETE" }),
  );
}

/** پوششِ بهای تمام‌شده — پاسخِ «چرا سود محاسبه نشد؟». */
export type CostCoverage = {
  available: boolean;
  lines_total?: number;
  lines_with_cost?: number;
  coverage: number;
  note_fa: string;
};

export async function getCostCoverage(): Promise<CostCoverage> {
  return handle(await fetch(`${BASE}/api/v1/cost-coverage`, { cache: "no-store" }));
}

/** کف حاشیه — تصمیمِ کاربر، نه حدسِ سیستم. `null` یعنی تعیین‌نشده. */
export type MarginFloor = {
  available: boolean;
  margin_floor_bp: number | null;
  products_with_margin?: number;
  products_below_floor?: string[];
  note_fa: string;
};

export async function getMarginFloor(): Promise<MarginFloor> {
  return handle(await fetch(`${BASE}/api/v1/margin-floor`, { cache: "no-store" }));
}

export async function setMarginFloor(bp: number | null): Promise<MarginFloor> {
  return handle(
    await fetch(`${BASE}/api/v1/margin-floor`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ margin_floor_bp: bp }),
    }),
  );
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
