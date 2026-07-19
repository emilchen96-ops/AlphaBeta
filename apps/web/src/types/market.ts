export type MarketTimeframe =
  "DAY_1" | "MINUTE_1" | "MINUTE_5" | "MINUTE_15" | "MINUTE_30" | "MINUTE_60";
export type AdjustmentType = "NONE" | "FORWARD" | "BACKWARD";
export type FreshnessStatus =
  "NORMAL" | "DELAYED" | "INCOMPLETE" | "INVALID" | "UNKNOWN";

export interface Instrument {
  id: string;
  symbol: string;
  exchange: string;
  market: string;
  name: string;
  asset_type: string;
  currency: string;
  lot_size: string;
  price_tick: string;
  timezone: string;
  is_active: boolean;
  updated_at: string;
}

export interface InstrumentPage {
  items: Instrument[];
  page: number;
  page_size: number;
  total: number;
}

export interface Watchlist {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
  updated_at: string;
}

export interface WatchlistItem {
  id: string;
  watchlist_id: string;
  instrument: Instrument;
  sort_order: number;
  note: string | null;
  created_at: string;
}

export interface WatchlistDetail extends Watchlist {
  items: WatchlistItem[];
}

export interface MarketDataSource {
  id: string;
  source_code: string;
  name: string;
  status: "ACTIVE" | "DISABLED" | "DEGRADED";
  priority: number;
  supports_realtime: boolean;
  provider_tier: "DEMO" | "FREE_BEST_EFFORT";
  supports_quotes: boolean;
  supports_recent_minute_bars: boolean;
  last_health_check_at: string | null;
  supported_timeframes: string[];
  updated_at: string;
}

export interface MarketQuote {
  instrument_id: string;
  source_code: string;
  symbol: string;
  quote_time: string | null;
  received_at: string;
  last_price: string;
  previous_close?: string | null;
  open?: string | null;
  high?: string | null;
  low?: string | null;
  volume?: string | null;
  amount?: string | null;
  quality_status: FreshnessStatus;
  provider_tier?: "FREE_BEST_EFFORT";
  usage?: ("RESEARCH_ONLY" | "NON_TRADING_GRADE")[];
  quality_flags?: Record<string, unknown>;
  revision: number;
  freshness?: "FRESH" | "STALE" | "MISSING";
  age_seconds?: number;
}

export interface LatestQuotesResponse {
  schema_version: 1;
  items: MarketQuote[];
  missing_instrument_ids: string[];
  calculated_at: string;
}

export interface RealtimeMarketStatus {
  enabled: boolean;
  state: string;
  source_code: string | null;
  circuit_state: string | null;
  consecutive_failures: number;
  requested_count: number;
  received_count: number;
  changed_count: number;
  rejected_count: number;
  checked_at: string | null;
  error_summary: string | null;
  worker_heartbeat: Record<string, unknown> | null;
}

export interface MarketBar {
  instrument_id: string;
  source_code: string;
  timeframe: MarketTimeframe;
  adjustment_type: AdjustmentType;
  bar_time: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string;
  amount: string | null;
  vwap: string | null;
  received_at: string;
  quality_status: FreshnessStatus;
}

export interface MarketBarsResponse {
  source_code: string;
  items: MarketBar[];
  freshness: {
    source_code: string;
    freshness_status: FreshnessStatus;
    latest_bar_time: string | null;
    latest_received_at: string | null;
    calculated_at: string;
  };
}

export type MarketSyncStatus =
  "RUNNING" | "SUCCEEDED" | "PARTIALLY_SUCCEEDED" | "FAILED" | "CANCELLED";

export interface MarketSyncRun {
  id: string;
  source_id: string;
  status: MarketSyncStatus;
  timeframe: MarketTimeframe;
  adjustment_type: AdjustmentType;
  requested_symbols: string[];
  started_at: string;
  requested_start: string | null;
  requested_end: string | null;
  completed_at: string | null;
  total_received: number;
  total_inserted: number;
  total_updated: number;
  total_rejected: number;
  error_summary: string | null;
  correlation_id: string;
  metadata: Record<string, unknown>;
}

export interface MarketDataOverview {
  instrument_count: number;
  active_a_share_count: number;
  research_universe_count: number;
  market_bar_count: number;
  earliest_bar: string | null;
  latest_bar: string | null;
  latest_sync_at: string | null;
  provider: string;
  timeframe: MarketTimeframe;
  adjustment_type: AdjustmentType;
  scanner_ready: boolean;
  strategy_ready: boolean;
  backtest_data_ready: boolean;
  backtest_code_status: "PARTIAL";
}

export interface InstrumentCoverage {
  instrument_id: string;
  symbol: string;
  name: string;
  exchange: string;
  bar_count: number;
  earliest_bar: string | null;
  latest_bar: string | null;
  mapping_status: string;
  missing_requirements: string[];
}

export interface UniverseCoverage {
  universe_key: string;
  name: string;
  instrument_count: number;
  instruments_with_data: number;
  sufficient_instruments: number;
  insufficient_instruments: number;
  earliest_bar: string | null;
  latest_bar: string | null;
  latest_sync_at: string | null;
  items: InstrumentCoverage[];
}

export interface ReadinessCapability {
  capability_key: string;
  display_name: string;
  status: "READY" | "PARTIAL" | "NOT_READY" | "UNKNOWN";
  ready_instrument_count: number;
  total_instrument_count: number;
  minimum_bars_required: number;
  latest_data_date: string | null;
  blocking_issue_count: number;
  warning_count: number;
  reason: string;
  required_action: string;
  code_status: "WORKING" | "PARTIAL";
}

export interface DailyUpdateResult {
  run: MarketSyncRun | null;
  target_date: string;
  requested: number;
  up_to_date: number;
  completed: number;
  failed: number;
  unprocessed: number;
  bars_fetched: number;
  bars_inserted: number;
  bars_updated: number;
  bars_skipped: number;
  invalid_bars: number;
  retry_count: number;
  failures: Record<string, string>[];
  plans: {
    instrument_id: string;
    symbol: string;
    start_date: string;
    target_date: string;
    state: string;
  }[];
  dry_run: boolean;
  idempotent_replay: boolean;
}

export type QualitySeverity = "ERROR" | "WARNING" | "INFO";

export interface MarketDataQualityRun {
  id: string;
  universe_key: string | null;
  provider: string | null;
  timeframe: MarketTimeframe;
  status: "CREATED" | "RUNNING" | "COMPLETED" | "FAILED";
  instruments_checked: number;
  bars_checked: number;
  issues_found: number;
  error_count: number;
  warning_count: number;
  info_count: number;
  started_at: string;
  completed_at: string | null;
  correlation_id: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface MarketDataQualityIssue {
  id: string;
  quality_run_id: string;
  instrument_id: string | null;
  issue_type: string;
  severity: QualitySeverity;
  timeframe: MarketTimeframe;
  first_affected_at: string | null;
  last_affected_at: string | null;
  observed_value: string | null;
  expected_value: string | null;
  message: string;
  required_action: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface QualityRunPage {
  items: MarketDataQualityRun[];
  page: number;
  page_size: number;
  total: number;
}

export interface QualityRunDetail {
  run: MarketDataQualityRun;
  issues: MarketDataQualityIssue[];
  issue_page: number;
  issue_page_size: number;
  issue_total: number;
  integrity_mismatches: string[];
}
