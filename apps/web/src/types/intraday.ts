import type { MarketSyncRun, MarketTimeframe } from "./market";

export interface IntradayProvider {
  provider_key: string;
  health: string;
  supported_timeframes: MarketTimeframe[];
  input_types: string[];
  message: string;
}

export interface IntradayCoverage {
  timeframe: MarketTimeframe;
  instrument_count: number;
  bar_count: number;
  earliest_at: string | null;
  latest_at: string | null;
  expected_bar_count: number;
  missing_bar_count: number;
  complete_session_count: number;
  missing_session_count: number;
  raw_coverage: number;
  qfq_coverage: number;
  quality_error_count: number;
  latest_import_at: string | null;
  source_code: string;
}

export interface IntradayReadiness extends IntradayCoverage {
  capability_key: string;
  status: "READY" | "PARTIAL" | "NOT_READY" | "UNKNOWN";
  data_status: string;
  implementation_status: "IMPLEMENTED" | "NOT_IMPLEMENTED";
  ready_instrument_count: number;
  total_instrument_count: number;
  quality_error_count: number;
  warning_count: number;
  required_action: string | null;
}

export interface IntradayBar {
  id: number | null;
  instrument_id: string;
  source_id: string;
  timeframe: MarketTimeframe;
  adjustment_type: "NONE";
  bar_time: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string;
  amount: string | null;
  received_at: string;
  quality_status: string;
  quality_flags: Record<string, unknown>;
}

export interface IntradayImportResult {
  run: MarketSyncRun | null;
  rows_read: number;
  rows_valid: number;
  rows_invalid: number;
  bars_inserted: number;
  bars_updated: number;
  bars_skipped: number;
  conflicts: number;
  aggregated_bars_created: number;
  incomplete_windows: number;
  duration_seconds: number;
  errors: string[];
}
