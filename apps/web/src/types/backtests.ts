export type BacktestStatus = "CREATED" | "RUNNING" | "COMPLETED" | "FAILED";

export interface BacktestRun {
  id: string;
  idempotency_key: string;
  strategy_key: string;
  strategy_version: string;
  status: BacktestStatus;
  strategy_run_id: string | null;
  account_id: string | null;
  bars_processed: number;
  sessions_processed: number;
  signals_generated: number;
  risk_passed: number;
  risk_rejected: number;
  risk_reviewed: number;
  orders_created: number;
  fills_generated: number;
  started_at: string | null;
  completed_at: string | null;
  failed_at: string | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  replayed?: boolean;
  metrics?: BacktestMetrics | null;
  configuration?: Record<string, unknown> | null;
}

export interface BacktestPage {
  items: BacktestRun[];
  page: number;
  page_size: number;
  total: number;
}

export interface BacktestMetrics {
  initial_equity: string;
  final_equity: string;
  total_return: string;
  annualized_return: string | null;
  maximum_drawdown: string;
  annualized_volatility: string | null;
  sharpe_ratio: string | null;
  trading_sessions: number;
  fill_count: number;
  total_turnover: string;
  total_fees: string;
  realized_pnl: string;
  win_rate: string | null;
  profit_factor: string | null;
  average_exposure: string;
  maximum_exposure: string;
  [key: string]: unknown;
}

export interface BacktestEquityPoint {
  id: string;
  timestamp: string;
  cash: string;
  market_value: string;
  total_equity: string;
  daily_return: string | null;
  cumulative_return: string;
  drawdown: string;
  warnings: string[];
}

export interface BacktestTrade {
  id: string;
  instrument_id: string;
  opened_at: string;
  closed_at: string;
  quantity: string;
  entry_price: string;
  exit_price: string;
  gross_pnl: string;
  fees: string;
  net_pnl: string;
}

export interface BacktestFact {
  id?: string;
  event_type?: string;
  sequence_number?: number;
  occurred_at?: string;
  summary?: string;
  [key: string]: unknown;
}

export interface BacktestIntegrity {
  run_id: string;
  passed: boolean;
  checked_at: string;
  issues: { code: string; message: string; entity_type: string }[];
}

export interface CreateBacktestRequest {
  strategy_key: string;
  parameters: Record<string, string | number | boolean>;
  instrument_ids: string[];
  timeframe: "DAY_1";
  start_at: string;
  end_at: string;
  initial_cash: string;
  order_type: "MARKET" | "LIMIT";
  time_in_force: "DAY" | "GTC";
  fee_configuration: {
    commission_rate: string;
    minimum_commission: string;
    stamp_duty_rate: string;
    transfer_fee_rate: string;
  };
  slippage_configuration: {
    basis_points: string;
    maximum_slippage: string | null;
  };
  maximum_volume_participation: string | null;
  benchmark_symbol: string | null;
  idempotency_key: string;
}
