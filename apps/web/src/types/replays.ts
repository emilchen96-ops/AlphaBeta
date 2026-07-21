export type ReplayStatus =
  | "CREATED"
  | "READY"
  | "RUNNING"
  | "PAUSED"
  | "COMPLETED"
  | "STOPPED"
  | "FAILED";

export type ReplaySpeedMode = "MANUAL" | "X1" | "X10" | "X100";

export interface ReplayRun {
  id: string;
  idempotency_key: string;
  status: ReplayStatus;
  row_version: number;
  strategy_key: string;
  strategy_version: string;
  account_id: string | null;
  strategy_run_id: string | null;
  current_session_date: string | null;
  current_session_index: number;
  total_sessions: number;
  speed_mode: ReplaySpeedMode;
  bars_processed: number;
  signals_generated: number;
  orders_created: number;
  fills_generated: number;
  started_at: string | null;
  paused_at: string | null;
  completed_at: string | null;
  stopped_at: string | null;
  failed_at: string | null;
  error_code: string | null;
  error_message: string | null;
  last_heartbeat_at: string | null;
  worker_online: boolean;
  created_at: string;
  updated_at: string;
  replayed?: boolean;
  configuration?: ReplayConfiguration;
  final_summary?: Record<string, unknown>;
  integrity_summary?: Record<string, unknown>;
}

export interface ReplayConfiguration {
  speed_mode: ReplaySpeedMode;
  schema_version: number;
  execution: {
    parameters: Record<string, string | number | boolean>;
    instrument_ids: string[];
    start_at: string;
    end_at: string;
    initial_cash: string;
    order_type: string;
    time_in_force: string;
    fee_configuration: Record<string, string | number>;
    slippage_configuration: Record<string, string | number | null>;
    maximum_volume_participation: string | null;
  };
}

export interface ReplayPage {
  items: ReplayRun[];
  page: number;
  page_size: number;
  total: number;
}

export interface ReplayEvent {
  id: string;
  replay_run_id: string;
  sequence_number: number;
  event_type: string;
  business_time: string;
  occurred_at: string;
  instrument_id: string | null;
  related_entity_type: string | null;
  related_entity_id: string | null;
  summary: string;
  payload: Record<string, unknown>;
}

export interface ReplayEquityPoint {
  id: string;
  run_id: string;
  timestamp: string;
  cash: string;
  market_value: string;
  total_equity: string;
  gross_exposure: string;
  net_exposure: string;
  daily_return: string | null;
  cumulative_return: string;
  drawdown: string;
  positions_count: number;
  warnings: string[];
}

export interface ReplayState {
  status: ReplayStatus;
  row_version: number;
  cash: Record<string, unknown> | null;
  positions: Record<string, unknown>[];
  latest_equity: ReplayEquityPoint | null;
  [key: string]: unknown;
}

export interface ReplayIntegrity {
  replay_run_id: string;
  ok: boolean;
  checked_at: string;
  issues: string[];
  facts: Record<string, unknown>;
}

export interface CreateReplayRequest {
  strategy_key: string;
  parameters: Record<string, string | number | boolean>;
  instrument_ids: string[];
  start_at: string;
  end_at: string;
  initial_cash: string;
  order_type: string;
  time_in_force: string;
  fee_configuration: Record<string, string>;
  slippage_configuration: Record<string, string | null>;
  maximum_volume_participation: string | null;
  risk_configuration_reference: string;
  speed_mode: ReplaySpeedMode;
  data_source_code: string | null;
  idempotency_key: string;
}
