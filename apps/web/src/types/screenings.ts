export type ScreeningStatus =
  | "CREATED"
  | "QUEUED"
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
  origin: "USER_STRUCTURED" | "BUILTIN_TEMPLATE" | "API";
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
  template_key: "LIMIT_UP_PULLBACK" | "BOTTOM_VOLUME_EXPANSION";
  display_name: string;
  description: string;
  spec: ScreeningSpecSnapshot;
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
