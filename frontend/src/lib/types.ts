/** Shared API response types (mirrors backend schemas). */

export interface ValidationOut {
  dataset_id: string;
  filename: string;
  size_bytes: number;
  row_count: number;
  column_count: number;
  delimiter: string;
  encoding: string;
  status: string;
  messages: string[];
  warnings: string[];
  headers: string[];
  sample_rows: string[][];
}

export interface PreviewOut {
  columns: string[];
  rows: unknown[][];
  total_rows: number;
  truncated: boolean;
  column_types: Record<string, string>;
}

export interface DatasetOut {
  id: string;
  filename: string;
  size_bytes: number;
  row_count: number;
  column_count: number;
  validation_status: string;
  is_demo: boolean;
  created_at: string | null;
  runs: { id: string; status: string; created_at: string | null; progress: number }[];
}

export interface ColumnProfile {
  name: string;
  normalized: string;
  physical_type: string;
  semantic_type: string;
  likely_meaning: string;
  null_pct: number;
  unique_count: number;
  uniqueness_ratio: number;
  sample_values: (string | number)[];
  numeric_min: number | null;
  numeric_max: number | null;
  numeric_mean: number | null;
  typical_value: string;
  distribution: string;
  date_min: string | null;
  date_max: string | null;
  is_identifier: boolean;
  is_target: boolean;
  is_sensitive: boolean;
  semantic_confidence: number;
  reason: string;
  categories: { value: string; count: number }[];
  user_override: string | null;
}

export interface CapabilityState {
  state: string;
  reason: string;
  [k: string]: unknown;
}

export interface SchemaOut {
  columns: ColumnProfile[];
  semantic_map: Record<string, string>;
  capabilities: Record<string, CapabilityState>;
  detected: Record<string, number>;
  warnings: string[];
  row_count: number;
}

export interface JobStatus {
  name: string;
  label: string;
  status: string;
  required: boolean;
  detail: string;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface RunStatus {
  run_id: string;
  status: string;
  progress: number;
  current_stage: string;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  jobs: JobStatus[];
}

export interface ChartSpec {
  id: string;
  type: string;
  title: string;
  subtitle: string;
  columns: string[];
  data: Record<string, string | number>[];
  x: string;
  y: string;
  series: string[];
  unit: string;
  relevance: number;
  note: string;
}

export interface KeyFinding {
  id: string;
  category: string;
  title: string;
  detail: string;
  kind: string;
  evidence: string;
  severity?: string;
}

export interface ManifestModule {
  key: string;
  label: string;
  state: string;
  reason: string;
}

export interface Manifest {
  run_id: string;
  dataset_id: string;
  filename: string;
  brand: Record<string, string>;
  created_at: string;
  analysis_version: string;
  dataset_version: string;
  columns: ColumnProfile[];
  semantic_map: Record<string, string>;
  roles: Record<string, string | null>;
  capabilities: Record<string, CapabilityState>;
  modules: ManifestModule[];
  overview: Record<string, unknown>;
  quality: QualityReport | null;
  stats: {
    numeric: Record<string, string | number | null>[];
    categorical: Record<string, unknown>[];
    temporal: Record<string, unknown>[];
  };
  relationships: RelationshipResult;
  forecast: Record<string, unknown>;
  ml: MLBlock;
  financial: FinancialBlock;
  charts: ChartSpec[];
  findings: { key_findings: KeyFinding[]; provenance: Record<string, unknown> };
  cleaning: Record<string, unknown>;
  plan: Record<string, unknown>;
  warnings: string[];
  limitations: string[];
}

export interface QualityReport {
  score: number;
  grade: string;
  formula: string;
  missing: {
    columns_with_missing: { column: string; missing_count: number; missing_pct: number }[];
    total_missing_pct: number;
    empty_rows: number;
    empty_columns: string[];
    critical_missing: { column: string; missing_pct: number }[];
  };
  duplicates: Record<string, unknown>;
  invalid: Record<string, unknown>;
  outliers: Record<string, unknown>;
  summary: string[];
  recommendations: { action: string; targets: string[]; reason: string }[];
}

export interface RelationshipResult {
  labels: string[];
  pearson: (number | null)[][];
  spearman: (number | null)[][];
  strong_pairs: {
    a: string;
    b: string;
    pearson: number;
    spearman: number | null;
    strength: string;
    note: string;
  }[];
  categorical_associations: { a: string; b: string; cramers_v: number }[];
  mutual_information: { feature: string; target: string; mutual_information: number }[];
  note: string;
}

export interface MLBlock {
  supervised?: {
    task: string;
    status: string;
    reason?: string;
    target: string | null;
    features_used: string[];
    excluded_features: string[];
    split_strategy: string;
    metrics: Record<string, number>;
    baselines: Record<string, string | number>;
    per_class: { class: string; precision: number; recall: number; f1: number; support: number }[];
    confusion: number[][];
    feature_importance: { feature: string; importance: number; signed_coef?: number }[];
    models_tried: Record<string, string | number>[];
    best_model: string;
    limitations: string[];
    train_size: number;
    test_size: number;
    duration_s: number;
  } | null;
  clustering?: Record<string, unknown> | null;
  anomaly?: {
    method: string;
    status: string;
    reason?: string;
    features_used: string[];
    metrics: Record<string, number | Record<string, unknown>>;
    clusters: Record<string, unknown>[];
    anomalies: {
      row_index: number;
      score: number;
      reasons: { feature: string; value: number | null; deviation_sigma: number }[];
      detected_by: string;
      synthetic_label?: string;
    }[];
    sample_size: number;
    limitations: string[];
    duration_s: number;
  } | null;
}

export interface FinancialBlock {
  activated: boolean;
  modules: {
    summary?: Record<string, unknown>;
    network?: NetworkResult;
    patterns?: PatternResult;
    currency?: Record<string, unknown>;
    reconciliation?: Record<string, unknown>;
    performance?: Record<string, unknown>;
  };
}

export interface NetworkResult {
  status: string;
  reason?: string;
  node_count: number;
  edge_count: number;
  total_value: number | null;
  nodes: {
    id: string;
    label: string;
    x: number;
    y: number;
    out_value: number;
    in_value: number;
    out_count: number;
    in_count: number;
    net_flow: number;
    degree: number;
    pagerank: number;
    community: number;
  }[];
  edges: { source: string; target: string; count: number; value: number; width: number }[];
  metrics: Record<string, unknown>;
  communities: { community: number; size: number }[];
  warnings: string[];
}

export interface Finding {
  kind: string;
  title: string;
  severity: string;
  evidence: string;
  method: string;
  thresholds: Record<string, unknown>;
  entity: string;
  row_count: number;
  examples: Record<string, unknown>[];
  time_range: Record<string, string>;
  confidence: string;
  false_positive_note: string;
  next_steps: string;
}

export interface PatternResult {
  findings: Finding[];
  total: number;
  disclaimer: string;
  methodology: Record<string, string>;
}

export interface AssistantResponse {
  question: string;
  topic: string;
  confidence: number;
  answer: string;
  data: unknown;
  unable?: boolean;
  scope: string;
  limitations: string[];
  llm_note?: string;
  follow_ups: string[];
  chart_hint?: { type: string; x: string; y: string; rows: Record<string, unknown>[] };
  action?: string;
}

export interface AuthUser {
  id: string;
  email: string;
  display_name: string;
  provider: string;
}

export interface ProviderInfo {
  provider: string;
  label: string;
  mode: string;
  note: string;
  otp_enabled?: boolean;
  otp_length?: number;
  otp_ttl_seconds?: number;
  otp_delivery?: 'email' | 'dev_console';
  /** Which component delivers the passcode: supabase | smtp | dev_console. */
  otp_provider?: 'supabase' | 'smtp' | 'dev_console';
  /** True when the email carries a sign-in link that our callback page redeems. */
  link_enabled?: boolean;
  /** The URL Supabase sends the link back to (this app's /auth/callback). */
  link_callback?: string;
}

export interface Overview {
  datasets: number;
  runs_total: number;
  runs_by_status: Record<string, number>;
  upcoming_bookings: number;
  latest_runs: { id: string; dataset_id: string; status: string; progress: number; created_at: string | null }[];
  upcoming: { id: string; topic: string; scheduled_at: string | null; status: string }[];
  recent_orders: Order[];
}

export interface Booking {
  id: string;
  topic: string;
  detail: string;
  scheduled_at: string | null;
  status: string;
  created_at: string | null;
}

export interface Plan {
  key: string;
  name: string;
  amount_cents: number;
  amount: string;
}

export interface Order {
  id: string;
  plan: string;
  amount_cents: number;
  status: string;
  created_at: string | null;
  amount?: string;
  note?: string;
}

export interface DatasetComment {
  id: string;
  author: string;
  text: string;
  created_at: string | null;
  mine: boolean;
}

export interface HealthInfo {
  status: string;
  brand: Record<string, string>;
  limits: Record<string, number>;
  providers: { llm_configured: boolean; fx_provider_configured: boolean };
  stack: Record<string, string | number>;
}
