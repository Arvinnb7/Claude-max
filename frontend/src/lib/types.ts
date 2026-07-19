// انواع داده‌ی API — هم‌راستا با api/serialize.py

export interface RoleInfo {
  role: string;
  label: string;
  required: boolean;
  suggested: string | null;
  confidence: number;
  reason: string;
  low_confidence: boolean;
}

export interface UploadResponse {
  session_id: string;
  sheets: string[];
  columns: string[];
  roles: RoleInfo[];
  preview: Record<string, string>[];
  n_rows: number;
  warnings?: string[];
}

export interface KPIs {
  total_revenue: number;
  gross_sales: number;
  returns_total: number;
  returns_count: number;
  return_rate: number | null;
  net_sales: number;
  discount_total: number | null;
  n_orders: number;
  n_customers: number;
  aov: number;
  avg_daily_revenue: number;
  mom_growth: number | null;
  yoy_growth: number | null;
  repeat_rate: number | null;
  gross_margin: number | null;
  revenue_per_customer: number | null;
  flags: string[];
}

export interface Point {
  date: string;
  value: number | null;
}

export interface Segment {
  name: string;
  size: number;
  revenue: number;
}

export interface BreakdownRow {
  label: string;
  revenue: number;
  share: number;
  cumulative_share: number;
}

export interface Anomaly {
  date: string;
  value: number;
  expected: number;
  z_score: number;
  direction: string;
}

export interface Scenario {
  key: string;
  name_fa: string;
  total: number;
  uplift_vs_forecast: number;
  rationale: string;
  per_period: Point[];
}

export interface AnalyzeResponse {
  currency: string;
  kpis: KPIs;
  trends: {
    daily: Point[];
    monthly: Point[];
    moving_avg_30: Point[];
    overall_trend_pct: number | null;
  };
  segmentation: {
    segments: Segment[];
    breakdowns: Record<string, BreakdownRow[]>;
  };
  anomalies: Anomaly[];
  seasonality: {
    weekday_index: Record<string, number>;
    strength: number | null;
    peak_day: string | null;
  };
  quality: {
    n_rows: number;
    date_min: string | null;
    date_max: string | null;
    span_days: number | null;
    warnings: string[];
  };
  forecast?: {
    model_name: string;
    horizon: number;
    total: number;
    history: Point[];
    yhat: Point[];
    lower: Point[];
    upper: Point[];
    backtest: Record<string, number>;
  };
  targets?: {
    horizon: number;
    forecast_total: number;
    recommended: string;
    scenarios: Scenario[];
  };
  products?: {
    product: string;
    revenue: number;
    quantity: number;
    orders: number;
    share: number;
    abc_class: string;
    growth: number | null;
  }[];
  basket?: {
    avg_basket_size: number;
    rules: {
      antecedent: string;
      consequent: string;
      confidence: number;
      lift: number;
      support: number;
      pair_count: number;
    }[];
  };
  sequences?: {
    antecedent: string;
    consequent: string;
    completion_rate: number;
    median_lag_days: number;
    n_antecedent_buyers: number;
    incomplete_count: number;
  }[];
  next_purchase?: {
    customer_id: string;
    predicted_next_date: string | null;
    status: string;
    overdue_days: number;
    likely_products: string[];
    expected_value: number;
    buy_probability_30d: number | null;
    recommendations: { product: string; reason: string }[];
  }[];
  basket_eval?: {
    n_eval: number;
    hitrate_at_5: number;
    recall_at_5: number;
    popularity_hitrate_at_5: number;
    heuristic_hitrate_at_5: number;
    best_config: string;
    coverage: number;
  };
  performance?: {
    branches: EntityPerf[];
    salespeople: EntityPerf[];
  };
  inventory?: {
    product: string;
    recommendation: string;
    growth: number | null;
    revenue_share: number;
    margin: number | null;
    reason: string;
  }[];
  diagnostics?: {
    overall_pct: number | null;
    period_label: string;
    is_declining: boolean;
    drivers: { dimension: string; label: string; pct_change: number | null; contribution: number }[];
  };
  purchase_cycle?: {
    products: {
      product: string;
      product_type: string;
      repurchase_rate: number;
      median_cycle_days: number | null;
      n_buyers: number;
    }[];
    notifications: {
      customer_id: string;
      product: string;
      cycle_days: number;
      days_offset: number;
      status: string;
      message: string;
    }[];
    onetime_targets: {
      product: string;
      gateway_products: string[];
      potential_count: number;
      existing_buyers: number;
    }[];
  };
  branch_targets?: TargetAlloc;
  salesperson_targets?: TargetAlloc;
  pacing?: {
    monthly_target: number;
    achieved: number;
    gap: number;
    days_remaining: number;
    required_daily: number;
    on_track: boolean;
    pace_ratio: number;
    week_plan: { date: string; weekday: string; target_revenue: number; emphasis: string }[];
  };
}

export interface EntityPerf {
  name: string;
  revenue: number;
  orders: number;
  customers: number;
  aov: number;
  share: number;
  growth: number | null;
  rank: number;
}

export interface TargetAlloc {
  dimension: string;
  total_target: number;
  entities: {
    name: string;
    target: number;
    growth_required: number;
    reward_tiers: { آستانه: string; پاداش: string }[];
  }[];
}

export interface ChannelMessage {
  channel: string;
  subject: string | null;
  body: string;
  call_script: string | null;
  timing: string;
  personalization_vars: string[];
}

export interface CampaignResponse {
  summary: string;
  audiences: {
    segment_name: string;
    audience_definition: string;
    objective: string;
    offer: string;
    estimated_size: number | null;
    success_kpi: string;
    channels: ChannelMessage[];
  }[];
  weekly_actions: { day: string; focus: string; actions: string[] }[];
}

export interface SMSResult {
  audience_size: number;
  تعداد_کل: number;
  ارسال‌شده: number;
  ناموفق: number;
  حالت_آزمایشی: boolean;
  ارائه‌دهنده: string;
  نمونه: { مشتری: string; گیرنده: string; متن: string; وضعیت: string }[];
  توضیح?: string;
}

export interface AudienceKind {
  key: string;
  label: string;
}

export interface StrategyResponse {
  executive_summary: string;
  factor_analysis: { factor: string; finding: string; impact: string }[];
  target_rationale: string;
  recommendations: {
    title: string;
    priority: string;
    rationale: string;
    expected_impact: string;
    effort: string;
  }[];
  risks: string[];
}

export interface HealthResponse {
  status: string;
  ai_available: boolean;
  model: string;
  currency: string;
  sms_enabled: boolean;
  scheduler: boolean;
}

export interface JobStatus {
  id: string;
  kind: string;
  status: "queued" | "running" | "done" | "error";
  progress: number;
  stage: string;
  error?: string;
  result?: unknown;
}

export interface SessionInfo {
  exists: boolean;
  filename?: string | null;
  columns_payload?: UploadResponse | null;
  analysis?: AnalyzeResponse | null;
  strategy?: StrategyResponse | null;
  campaign?: CampaignResponse | null;
}
