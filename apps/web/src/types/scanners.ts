export type ScannerParameterValue = string | number | boolean | null;

export interface ScannerParameterDefinition {
  name: string;
  display_name: string;
  unit: string | null;
  type: "integer" | "decimal" | "boolean";
  description: string;
  required: boolean;
  nullable: boolean;
  default: ScannerParameterValue;
  min_value: string | number | null;
  max_value: string | number | null;
}

export interface ScannerCatalogItem {
  scanner_key: string;
  display_name: string;
  description: string;
  version: string;
  supported_timeframes: string[];
  schema_version: number;
  parameters: ScannerParameterDefinition[];
  data_source: "MINIQMT";
  default_universe: "ALL_ACTIVE_A_SHARES";
  execution_mode: "BACKGROUND_BATCH";
}

export interface ScanRun {
  scan_run_id: string;
  scanner_key: string;
  scanner_version: string;
  parameters: Record<string, ScannerParameterValue>;
  universe_type: string;
  universe_filters: Record<string, unknown>;
  instrument_ids: string[];
  source_code: string;
  timeframe: string;
  as_of: string;
  status:
    | "CREATED"
    | "QUEUED"
    | "RESOLVING"
    | "CHECKING_DATA"
    | "BACKFILLING"
    | "RUNNING"
    | "COMPLETED"
    | "PARTIAL"
    | "FAILED"
    | "CANCELED";
  current_phase: string;
  progress_percent: number;
  total_instruments: number;
  excluded_instruments: number;
  data_ready_instruments: number;
  backfill_requested: number;
  backfill_failed: number;
  insufficient_history: number;
  instruments_scanned: number;
  matches_found: number;
  failed_instruments: number;
  cancel_requested: boolean;
  started_at: string | null;
  completed_at: string | null;
  failed_at: string | null;
  error: { code: string; message: string } | null;
  correlation_id: string;
  created_at: string;
  replayed: boolean;
  capabilities: Record<string, boolean>;
}

export interface ScanRunPage {
  items: ScanRun[];
  page: number;
  page_size: number;
  total: number;
}

export interface ScanResult {
  scan_result_id: string;
  scan_run_id: string;
  instrument_id: string;
  instrument: { symbol: string; exchange: string; name: string };
  rank: number;
  score: string;
  matched_at: string;
  reference_price: string;
  reason_code: string;
  reason: string;
  metrics: Record<string, unknown>;
  schema_version: number;
  created_at: string;
}

export interface ScanResultList {
  items: ScanResult[];
  total: number;
  page: number;
  page_size: number;
}

export interface ScannerSessionDefault {
  scan_date: string;
  data_source: "MINIQMT";
  timeframe: "DAY_1";
}

export interface ScanRunMember {
  instrument_id: string;
  symbol: string;
  exchange: string;
  instrument_name: string;
  status: string;
  reason_code: string | null;
  reason: string | null;
  bars_available: number;
  required_bars: number;
}

export interface ScanRunMemberList {
  items: ScanRunMember[];
  summary: Record<string, number>;
  total: number;
}
