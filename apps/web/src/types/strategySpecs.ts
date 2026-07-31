export type OperandKind = "FIELD" | "INDICATOR" | "CONSTANT";
export type LogicalOperator = "AND" | "OR";
export type ComparisonOperator = "GT" | "GTE" | "LT" | "LTE";

export interface StrategyOperand {
  kind: OperandKind;
  field: "open" | "high" | "low" | "close" | "volume" | null;
  indicator:
    "SMA" | "ROLLING_HIGHEST" | "ROLLING_LOWEST" | "AVERAGE_VOLUME" | null;
  window: number | null;
  exclude_current: boolean;
  multiplier: string;
  value: string | null;
}

export interface StrategyComparison {
  type: "comparison";
  left: StrategyOperand;
  operator: ComparisonOperator;
  right: StrategyOperand;
}

export interface StrategyConditionGroup {
  type: "group";
  operator: LogicalOperator;
  conditions: Array<StrategyComparison | StrategyConditionGroup>;
}

export interface StrategySpec {
  schema_version: 1;
  name: string;
  description: string;
  entry: StrategyConditionGroup;
  exit: StrategyConditionGroup;
  timeframe: "DAY_1";
  quantity: string;
  single_instrument: boolean;
  data_range_years: number;
  origin: string;
}

export interface StrategyParseResult {
  status: "COMPLETE" | "PARTIAL";
  parser_source: "LOCAL_RULES" | "AI";
  spec: StrategySpec | null;
  preview: string[];
  warnings: string[];
  missing_fields: string[];
  ai_assistance: "DISABLED" | "ENABLED";
}

export interface StrategyTemplate {
  key: string;
  name: string;
  description: string;
  category: string;
  spec: StrategySpec | null;
  preview: string[];
  recommended: boolean;
}

export interface UserStrategy {
  id: string;
  name: string;
  description: string;
  current_version: number;
  archived: boolean;
  spec: StrategySpec;
  preview: string[];
  created_at: string;
  updated_at: string;
}

export interface UserStrategyPage {
  items: UserStrategy[];
  page: number;
  page_size: number;
  total: number;
}

export interface QuickBacktestRequest {
  instrument_id: string;
  start_at: string;
  end_at: string;
  initial_cash: string;
  spec?: StrategySpec;
  user_strategy_id?: string;
  price_adjustment_mode: "RAW" | "QFQ";
  commission_rate: string;
  minimum_commission: string;
  stamp_duty_rate: string;
  transfer_fee_rate: string;
  slippage_basis_points: string;
  maximum_volume_participation: string | null;
  execution_price_mode:
    "NEXT_OPEN" | "SIGNAL_CLOSE_LIMIT" | "SAME_DAY_NEXT_MINUTE";
  position_size_ratio: string | null;
  maximum_entry_gap_ratio: string | null;
  time_in_force: "DAY" | "GTC";
  idempotency_key: string;
}

export type BacktestScope = "SINGLE" | "WATCHLIST" | "ALL_A_SHARES";

export interface BacktestBatchRequest extends Omit<
  QuickBacktestRequest,
  "instrument_id" | "price_adjustment_mode"
> {
  scope: Exclude<BacktestScope, "SINGLE">;
  watchlist_id: string | null;
  exclude_st: boolean;
  exclude_bse: boolean;
  exclude_star_market: boolean;
  exclude_chinext: boolean;
}

export interface BacktestBatch {
  id: string;
  name: string;
  scope: Exclude<BacktestScope, "SINGLE">;
  watchlist_id: string | null;
  status:
    | "CREATED"
    | "RUNNING"
    | "COMPLETED"
    | "PARTIAL_FAILED"
    | "FAILED"
    | "CANCELLED";
  total_count: number;
  pending_count: number;
  running_count: number;
  completed_count: number;
  failed_count: number;
  cancelled_count: number;
  progress_percent: number;
  started_at: string | null;
  completed_at: string | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  filters?: {
    exclude_st?: boolean;
    exclude_bse?: boolean;
    exclude_star_market?: boolean;
    exclude_chinext?: boolean;
  };
}

export interface BacktestBatchResult {
  item_id: string;
  instrument_id: string;
  symbol: string;
  exchange: string;
  name: string;
  status: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";
  backtest_run_id: string | null;
  total_return: string | null;
  annualized_return: string | null;
  maximum_drawdown: string | null;
  sharpe_ratio: string | null;
  fill_count: number | null;
  error_code: string | null;
  error_message: string | null;
}

export interface BacktestBatchDistribution {
  count: number;
  average: string | null;
  median: string | null;
  p25: string | null;
  p50: string | null;
  p75: string | null;
}

export interface BacktestBatchHistogramBucket {
  minimum: number;
  maximum: number;
  count: number;
}

export interface BacktestBatchSummary {
  batch: BacktestBatch;
  notice: string;
  counts: {
    total: number;
    completed: number;
    failed: number;
    traded: number;
    profitable: number;
  };
  ratios: {
    traded: string | null;
    profitable: string | null;
  };
  returns: BacktestBatchDistribution;
  drawdowns: BacktestBatchDistribution;
  sharpe_distribution: BacktestBatchHistogramBucket[];
  fill_distribution: BacktestBatchHistogramBucket[];
  return_histogram: BacktestBatchHistogramBucket[];
  return_drawdown_scatter: Array<{
    instrument_id: string;
    instrument_display: string;
    total_return: string;
    maximum_drawdown: string;
  }>;
  top: Array<BacktestBatchResult & { instrument_display: string }>;
  bottom: Array<BacktestBatchResult & { instrument_display: string }>;
  failure_reasons: Array<{ code: string; count: number }>;
}
