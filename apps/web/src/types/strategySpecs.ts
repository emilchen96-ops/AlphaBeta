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
    | "NEXT_OPEN"
    | "SIGNAL_CLOSE_LIMIT"
    | "SAME_DAY_NEXT_MINUTE"
    | "INTRADAY_NEXT_MINUTE"
    | "INTRADAY_SIGNAL_CLOSE";
  signal_timeframe?: "MINUTE_1" | "MINUTE_5" | "MINUTE_15";
  auto_prepare_minute_data?: boolean;
  optimistic_fill_assumption?: boolean;
  position_size_ratio: string | null;
  maximum_entry_gap_ratio: string | null;
  time_in_force: "DAY" | "GTC";
  idempotency_key: string;
}

export type BacktestScope = "SINGLE" | "MANUAL" | "WATCHLIST" | "ALL_A_SHARES";

export type BacktestBatchExecutionMode = "INDEPENDENT" | "SHARED_PORTFOLIO";

export interface BacktestBatchRequest extends Omit<
  QuickBacktestRequest,
  "instrument_id" | "price_adjustment_mode"
> {
  scope: Exclude<BacktestScope, "SINGLE">;
  execution_mode: BacktestBatchExecutionMode;
  instrument_ids: string[];
  watchlist_id: string | null;
  exclude_st: boolean;
  exclude_bse: boolean;
  exclude_star_market: boolean;
  exclude_chinext: boolean;
  minimum_listing_trading_days: number | null;
  maximum_holdings: number;
  maximum_total_exposure: string;
  maximum_instrument_weight: string;
  allow_position_addition: boolean;
  entry_ranking: string;
  benchmark_symbol: string | null;
}

export interface BacktestBatch {
  id: string;
  name: string;
  scope: Exclude<BacktestScope, "SINGLE">;
  execution_mode: BacktestBatchExecutionMode;
  instrument_count: number;
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
  bars_processed: number | null;
  signals_generated: number | null;
  candidate_session_count: number | null;
  minute_replay_session_count: number | null;
  processed_minute_bar_count: number | null;
  data_preparation_summary: Record<string, unknown> | null;
  performance_summary: Record<string, unknown> | null;
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
    fill_count: number;
    backtest_run_id: string | null;
  }>;
  top: Array<BacktestBatchResult & { instrument_display: string }>;
  bottom: Array<BacktestBatchResult & { instrument_display: string }>;
  failure_reasons: Array<{ code: string; count: number }>;
  portfolio?: null | {
    run: Record<string, unknown>;
    configuration: Record<string, unknown>;
    metrics: Record<string, string | number | null> | null;
    equity_curve: Array<{
      timestamp: string;
      cash: string;
      market_value: string;
      total_equity: string;
      gross_exposure: string;
      net_exposure: string;
      cumulative_return: string;
      drawdown: string;
      positions_count: number;
    }>;
    drawdown_landmarks: null | {
      peak_at: string;
      peak_equity: string;
      trough_at: string;
      trough_equity: string;
      maximum_drawdown: string;
      recovered_at: string | null;
      recovered: boolean;
      current_drawdown: string;
      longest_drawdown_sessions: number;
    };
    benchmark: {
      symbol: string | null;
      name?: string;
      curve: Array<{ timestamp: string; cumulative_return: string }>;
      warning: string | null;
    };
    summary: {
      benchmark_total_return: string | null;
      excess_return: string | null;
      maximum_positions: number;
      average_positions: string;
      average_exposure: string;
      average_idle_cash_ratio: string;
      average_holding_days: string | null;
      current_drawdown: string;
      longest_drawdown_sessions: number;
    };
    signals: Array<Record<string, unknown>>;
    orders: Array<Record<string, unknown>>;
    fills: Array<Record<string, unknown>>;
    trades: Array<Record<string, unknown>>;
    rejections: Array<Record<string, unknown>>;
    positions: Array<Record<string, unknown>>;
    contributions: Array<{
      instrument_id: string;
      instrument_display: string;
      symbol: string | null;
      exchange: string | null;
      realized_pnl: string;
      unrealized_pnl: string;
      total_contribution: string;
      current_market_value: string;
      fees: string;
      trade_count: number;
      buy_fill_count: number;
      sell_fill_count: number;
    }>;
    timeline: Array<Record<string, unknown>>;
  };
  data_preparation: {
    required_sessions: number;
    ready_sessions: number;
    missing_sessions: number;
    progress_percent: number;
    preparing_stocks: number;
    queued_segments: number;
  };
  intraday_execution: {
    daily_bars_checked: number;
    daily_prefilter_candidates: number;
    daily_prefilter_excluded: number;
    minute_sessions_loaded: number;
    minute_bars_processed: number;
    signals_generated: number;
    stocks_with_signals: number;
    stocks_with_fills: number;
    data_preparation_seconds: number;
    strategy_replay_seconds: number;
  };
}
