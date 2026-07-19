export type ScannerParameterValue = string | number | boolean | null;

export interface ScannerParameterDefinition {
  name: string;
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
}

export interface ScanRun {
  scan_run_id: string;
  scanner_key: string;
  scanner_version: string;
  parameters: Record<string, ScannerParameterValue>;
  universe_type: string;
  instrument_ids: string[];
  timeframe: string;
  as_of: string;
  status: "CREATED" | "RUNNING" | "COMPLETED" | "FAILED";
  instruments_scanned: number;
  matches_found: number;
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
}
