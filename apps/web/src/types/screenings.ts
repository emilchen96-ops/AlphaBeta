export type ScreeningStatus =
  | "CREATED"
  | "QUEUED"
  | "PLANNING"
  | "CHECKING_COVERAGE"
  | "BACKFILLING_MARKET_DATA"
  | "BACKFILLING_REFERENCE_DATA"
  | "VERIFYING_DATA"
  | "PREPARING_FEATURES"
  | "SCREENING"
  | "RESOLVING"
  | "CHECKING_DATA"
  | "BACKFILLING"
  | "RUNNING"
  | "COMPLETED"
  | "PARTIAL_FAILED"
  | "FAILED"
  | "CANCELED";

export interface ScreeningUniverseSpec {
  universe_key: "ALL_A_SHARES";
  excluded_instrument_ids: string[];
  exclude_st: boolean;
  exclude_bse: boolean;
  exclude_star_market: boolean;
  exclude_chinext: boolean;
}

export interface ScreeningConditionSpec {
  condition_key: string;
  condition_version?: string;
  parameters: Record<string, string | number | boolean | null>;
}

export interface ScreeningRankingRule {
  field:
    | "score"
    | "volume_multiple"
    | "range_position"
    | "distance_to_anchor"
    | "current_close";
  direction: "ASC" | "DESC";
}

export interface ScreeningSpecSnapshot {
  schema_version: 1;
  name: string;
  origin:
    | "USER_STRUCTURED"
    | "USER_CORRECTED"
    | "NATURAL_LANGUAGE"
    | "AI_ASSISTED"
    | "BUILTIN_TEMPLATE"
    | "API";
  universe_spec: ScreeningUniverseSpec;
  as_of_date: string;
  timeframe: "DAY_1";
  conditions: ScreeningConditionSpec[];
  exclusions: Record<string, unknown>;
  ranking_rules: ScreeningRankingRule[];
  top_n: number | null;
  price_adjustment_mode: "RAW";
}

export interface ScreeningTemplate {
  template_key: string;
  display_name: string;
  description: string;
  timeframe: string;
  required_data: string;
  enabled: boolean;
  spec: ScreeningSpecSnapshot;
}

export interface UserScreening {
  id: string;
  name: string;
  description: string | null;
  source_text: string | null;
  origin: string;
  current_version: number;
  status: "DRAFT" | "ACTIVE" | "ARCHIVED";
  screening_spec: ScreeningSpecSnapshot;
  summary: string;
  created_at: string;
  updated_at: string;
  last_used_at: string | null;
}

export interface UserScreeningPage {
  items: UserScreening[];
  page: number;
  page_size: number;
  total: number;
}

export interface ScreeningWatchlistResult {
  watchlist_id: string;
  succeeded: number;
  already_exists: number;
  failed: number;
}

export interface ScreeningRun {
  screening_id: string;
  name: string;
  status: ScreeningStatus;
  current_phase: string;
  spec: ScreeningSpecSnapshot;
  total_instruments: number;
  processed_instruments: number;
  ready_instruments: number;
  insufficient_data_count: number;
  indeterminate_count: number;
  failed_count: number;
  matched_count: number;
  progress_percent: number;
  elapsed_ms: number;
  query_count: number;
  bars_read: number;
  batch_count: number;
  execution_stats: Record<string, unknown>;
  error: { code: string; message: string } | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  replayed: boolean;
  data_requirement_plan: Record<string, unknown> | null;
  data_preparation: Record<string, unknown> | null;
}

export interface ScreeningRunPage {
  items: ScreeningRun[];
  page: number;
  page_size: number;
  total: number;
}

export interface ScreeningProgress {
  screening_id: string;
  status: ScreeningStatus;
  total_instruments: number;
  processed_instruments: number;
  ready_instruments: number;
  insufficient_data_count: number;
  indeterminate_count: number;
  failed_count: number;
  matched_count: number;
  progress_percent: number;
  elapsed_ms: number;
  current_stage: string;
  stage_label: string;
  current_action: string;
  downloading_count: number;
  provider_failed_count: number;
  quality_failed_count: number;
  not_applicable_count: number;
}

export interface ScreeningResult {
  result_id: string;
  screening_id: string;
  rank: number;
  instrument_id: string;
  symbol: string;
  exchange: string;
  instrument_name: string;
  score: string;
  reference_price: string;
  matched_at: string;
  reason_code: string;
  reason: string;
  metrics: Record<string, unknown>;
}

export interface ScreeningResultPage {
  items: ScreeningResult[];
  page: number;
  page_size: number;
  total: number;
}

export type ScreeningParseStatus =
  "COMPLETE" | "PARTIAL" | "AMBIGUOUS" | "UNSUPPORTED";

export interface ScreeningParameterDefinition {
  name: string;
  display_name: string;
  type: "integer" | "decimal" | "boolean" | "enum";
  description: string;
  default: string | number | boolean | null;
  required: boolean;
  nullable: boolean;
  min_value: string | null;
  max_value: string | null;
  enum_values: string[];
  unit: string | null;
}

export interface ScreeningConditionDefinition {
  condition_key: string;
  display_name: string;
  description: string;
  category: string;
  parameter_schema: ScreeningParameterDefinition[];
  required_fields: string[];
  required_history_bars: number;
  supported_timeframes: string[];
  price_adjustment_mode: string;
  version: string;
  enabled: boolean;
}

export interface ScreeningPreview {
  summary: string;
  universe: string;
  conditions: string[];
  screening_time: string;
  ranking: string[];
  defaults: string[];
  data_requirements: string[];
  parser_source: string;
  no_future_data_rule: string;
  data_ready: boolean;
  data_readiness_message: string;
  can_execute: boolean;
  notices: string[];
}

export interface ScreeningParseResult {
  parse_status: ScreeningParseStatus;
  parser_source: "LOCAL_RULES" | "AI_ASSISTED";
  screening_spec: ScreeningSpecSnapshot | null;
  recognized_conditions: {
    condition_key: string;
    display_name: string;
    matched_expression: string;
  }[];
  ambiguities: string[];
  unsupported_fragments: string[];
  defaults_applied: {
    condition_key: string;
    parameter_name: string;
    display_name: string;
    value: string | number | boolean | null;
    explanation: string;
  }[];
  preview: ScreeningPreview | null;
  can_execute: boolean;
}

export interface ScreeningValidationResult {
  valid: boolean;
  parse_status: "COMPLETE";
  screening_spec: ScreeningSpecSnapshot;
  recognized_conditions: ScreeningParseResult["recognized_conditions"];
  preview: ScreeningPreview;
  can_execute: boolean;
}

export interface ScreeningPreviewResult {
  screening_spec: ScreeningSpecSnapshot;
  preview: ScreeningPreview;
  can_execute: boolean;
}
