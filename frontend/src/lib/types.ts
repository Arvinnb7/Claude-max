// انواع داده‌ی API — هم‌راستا با api/serialize.py

export interface RoleInfo {
  role: string;
  label: string;
  required: boolean;
  suggested: string | null;
}

export interface UploadResponse {
  session_id: string;
  sheets: string[];
  columns: string[];
  roles: RoleInfo[];
  preview: Record<string, string>[];
  n_rows: number;
}

export interface KPIs {
  total_revenue: number;
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
}
