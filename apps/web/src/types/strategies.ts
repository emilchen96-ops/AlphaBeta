export type StrategyParameterType =
  "integer" | "decimal" | "boolean" | "string" | "enum";

export interface StrategyParameterDefinition {
  name: string;
  type: StrategyParameterType;
  required: boolean;
  default: string | number | boolean | null;
  description: string;
  min_value: string | number | null;
  max_value: string | number | null;
  choices: string[];
}

export interface StrategyCatalogItem {
  strategy_key: string;
  display_name: string;
  description: string;
  version: string;
  supported_timeframes: string[];
  parameter_schema_version: number;
  parameters: StrategyParameterDefinition[];
}

export interface StrategyRun {
  run_id: string;
  strategy_key: string;
  strategy_version: string;
  status: "CREATED" | "RUNNING" | "COMPLETED" | "FAILED";
  timeframe: string;
  instrument_ids: string[];
  instruments?: {
    id: string;
    symbol: string;
    exchange: string;
    name: string;
  }[];
  parameters?: Record<string, string | number | boolean>;
  start_at: string;
  end_at: string;
  bars_processed: number;
  signals_generated: number;
  warnings: string[];
  replayed?: boolean;
  started_at?: string | null;
  completed_at?: string | null;
  failed_at?: string | null;
  created_at?: string;
  error?: { code: string; message: string } | null;
  capabilities?: Record<string, boolean>;
}

export interface StrategyRunPage {
  items: StrategyRun[];
  page: number;
  page_size: number;
  total: number;
}

export interface StrategySignal {
  signal_id: string;
  strategy_run_id: string;
  sequence_number: number;
  strategy_key: string;
  strategy_version: string;
  instrument_id: string;
  instrument: {
    symbol: string | null;
    exchange: string | null;
    name: string | null;
  };
  signal_type: string;
  side: string;
  generated_at: string;
  bar_timestamp: string;
  quantity: string | null;
  target_weight: string | null;
  reference_price: string | null;
  confidence: string | null;
  reason: string | null;
  schema_version: number;
}

export interface StrategySignalPage {
  items: StrategySignal[];
  page: number;
  page_size: number;
  total: number;
}

export type ParameterGridValue = string | number | boolean;

export type StrategyExperimentStatus =
  "CREATED" | "RUNNING" | "COMPLETED" | "PARTIAL_FAILED" | "FAILED";

export interface StrategyExperimentSummary {
  experiment_id: string;
  idempotency_key: string;
  strategy_key: string;
  strategy_version: string;
  environment: string;
  timeframe: string;
  instrument_ids: string[];
  start_at: string;
  end_at: string;
  parameter_grid: Record<string, ParameterGridValue[]>;
  combination_count: number;
  runs_completed: number;
  runs_failed: number;
  total_signals: number;
  status: StrategyExperimentStatus;
  started_at: string | null;
  completed_at: string | null;
  failed_at: string | null;
  error: { code: string; message: string } | null;
  correlation_id: string;
  created_at: string;
  updated_at: string;
  replayed?: boolean;
  capabilities?: Record<string, boolean>;
}

export type StrategyExperiment = StrategyExperimentSummary;

export interface StrategyExperimentPage {
  items: StrategyExperimentSummary[];
  page: number;
  page_size: number;
  total: number;
}

export interface StrategyExperimentRun {
  combination_index: number;
  normalized_parameters: Record<string, ParameterGridValue>;
  strategy_run_id: string | null;
  run_status: StrategyRun["status"];
  bars_processed: number;
  signals_generated: number;
  warning: string | null;
}

export interface StrategyExperimentComparisonRow {
  combination_index: number;
  normalized_parameters: Record<string, ParameterGridValue>;
  strategy_run_id: string | null;
  run_status: StrategyRun["status"];
  bars_processed: number;
  total_signals: number;
  buy_signals: number;
  sell_signals: number;
  first_signal_at: string | null;
  last_signal_at: string | null;
  signaled_instrument_count: number;
  warning: string | null;
}

export interface StrategySignalOverlap {
  left_combination_index: number;
  right_combination_index: number;
  intersection_count: number;
  union_count: number;
  similarity: string;
}

export interface CreateStrategyExperimentRequest {
  strategy_key: string;
  instrument_ids: string[];
  timeframe: string;
  start_at: string;
  end_at: string;
  parameter_grid: Record<string, ParameterGridValue[]>;
  idempotency_key: string;
}
