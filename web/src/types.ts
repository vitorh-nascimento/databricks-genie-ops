export interface SpaceCounts {
  tables: number;
  metric_views: number;
  volumes: number;
  join_specs: number;
  examples: number;
  benchmarks: number;
}

export interface HealthSummary {
  score: number;
  passed: boolean;
  errors: number;
  warnings: number;
  infos: number;
}

export interface BenchmarkItemResult {
  case_id: string;
  question: string;
  domain: string;
  difficulty: string;
  mode: string;
  status: 'GOOD' | 'BAD' | 'NEEDS_REVIEW' | 'EXCLUDED';
  semantic_score: number;
  result_match: boolean | null;
  expected_sql: string | null;
  generated_sql: string | null;
  latency_ms: number;
  error_message: string | null;
  details: string[];
}

export interface BenchmarkRunRecord {
  run_id: string;
  space_name: string;
  env: string;
  mode: string;
  created_at: string;
  total: number;
  passed: number;
  failed: number;
  needs_review: number;
  excluded: number;
  accuracy_pct: number;
  avg_latency_ms: number;
  p50_latency_ms: number;
  p95_latency_ms: number;
  config_hash: string;
  items: BenchmarkItemResult[];
}

export interface RegressionDiff {
  previous_run_id: string;
  current_run_id: string;
  previous_accuracy: number;
  current_accuracy: number;
  delta_accuracy: number;
  fixed: string[];
  regressed: string[];
  unchanged: string[];
  new_cases: string[];
  removed_cases: string[];
}

export interface SpaceOverview {
  name: string;
  title: string;
  description: string;
  owner: string;
  domains: string[];
  default_env: string;
  environments: string[];
  counts: SpaceCounts;
  health: HealthSummary;
  latest_run: BenchmarkRunRecord | null;
  total_runs: number;
}

export interface SpacesListResponse {
  summary: {
    total_spaces: number;
    avg_health_score: number;
    avg_accuracy_pct: number | null;
    total_benchmarks: number;
  };
  spaces: SpaceOverview[];
}

export interface LintIssue {
  code: string;
  severity: 'ERROR' | 'WARNING' | 'INFO';
  surface: string;
  message: string;
  recommendation: string;
}

export interface LintReportResponse {
  space_name: string;
  health_score: number;
  passed: boolean;
  error_count: number;
  warning_count: number;
  info_count: number;
  issues: LintIssue[];
}

export interface FailureDiagnosis {
  case_id: string;
  question: string;
  root_cause_class: string;
  confidence: string;
  evidence: string[];
  recommended_lever: string;
  proposed_action: string;
  avoid_antipattern: string;
}

export interface DiagnoseResponse {
  space_name: string;
  run_id: string | null;
  total_failures: number;
  diagnoses: FailureDiagnosis[];
  hierarchy: string[];
}

export interface SpaceDetailResponse {
  space: {
    name: string;
    title: string;
    description: string;
    target_audience: string;
    owner: string;
    domains: string[];
    default_env: string;
  };
  sources: {
    tables: { identifier: string; description: string[]; column_configs: { column_name: string; exclude?: boolean }[] }[];
    metric_views: { identifier: string; description: string[]; column_configs: { column_name: string }[] }[];
    volumes: { path: string; description: string[] }[];
  };
  instructions: {
    join_specs: { left: { identifier: string }; right: { identifier: string }; condition: string; relationship_type: string }[];
    text_instructions: string[];
    sample_questions: { question: string }[];
  };
  config_hash: string;
}

export interface DeltaExportPreviewResponse {
  space_name: string;
  catalog: string;
  schema: string;
  schema_mode: 'four_tables' | 'events';
  runs_exported: number;
  ddl_count: number;
  dml_count: number;
  sql: string;
}

export interface JudgeVerdict {
  passed: boolean;
  score: number;
  reasoning: string;
  provider: string;
  model: string;
  criteria_checks: { criterion: string; passed: boolean }[];
}

export interface StreamedAgentEvent {
  event: string;
  timestamp_ms?: number;
  payload: Record<string, unknown>;
}
