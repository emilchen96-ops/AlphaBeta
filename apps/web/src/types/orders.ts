export interface OrderFactSummary {
  id: string;
  account_id: string;
  account_name: string | null;
  instrument_id: string;
  symbol: string | null;
  exchange: string | null;
  instrument_name: string | null;
  side: "BUY" | "SELL";
  order_type: "LIMIT" | "MARKET";
  time_in_force: string;
  requested_quantity: string;
  limit_price: string | null;
  estimated_notional: string | null;
  status: string;
  intent_source: string;
  row_version: number;
  confirmation_required: boolean;
  correlation_id: string;
  expires_at: string | null;
  confirmed_at: string | null;
  cancelled_at: string | null;
  expired_at: string | null;
  created_at: string;
  updated_at: string;
  capabilities: { can_confirm: boolean; can_cancel: boolean };
  warnings: string[];
  actions: Array<Record<string, unknown>>;
  commands: Array<Record<string, unknown>>;
  outbox: Array<Record<string, unknown>>;
  risk_decision_id: string | null;
  risk_decision: string | null;
  risk_evaluated_at: string | null;
  risk_rule_summary: Array<Record<string, unknown>>;
}

export interface OrderPage {
  items: OrderFactSummary[];
  page: number;
  page_size: number;
  total: number;
}

export interface OrderTimelineItem {
  kind: string;
  label: string;
  actor_type: string | null;
  actor_id: string | null;
  reason: string | null;
  order_version: number | null;
  occurred_at: string;
  correlation_id: string;
}

export type SimulatedExecutionStatus =
  "FILLED" | "PARTIALLY_FILLED" | "NO_FILL" | "REJECTED" | "EXPIRED";

export interface CreateSimulatedExecutionRequest {
  idempotency_key: string;
  timestamp: string;
  trading_status: "TRADING" | "SUSPENDED" | "CLOSED" | "UNKNOWN";
  open: string | null;
  high: string | null;
  low: string | null;
  close: string | null;
  last_price: string | null;
  bid_price: string | null;
  ask_price: string | null;
  available_volume: string | null;
  price_limit_up: string | null;
  price_limit_down: string | null;
  source: string;
  is_stale: boolean;
}

export interface SimulatedExecutionResult {
  execution_attempt_id: string;
  order_id: string;
  order_status: string;
  result_status: SimulatedExecutionStatus;
  requested_quantity: string;
  previously_filled_quantity: string;
  attempted_quantity: string;
  filled_quantity: string;
  remaining_quantity: string;
  average_fill_price: string | null;
  fill_ids: string[];
  total_fee: string;
  rejection_code: string | null;
  message: string;
  warnings: string[];
  correlation_id: string;
  idempotent: boolean;
}

export interface BrokerExecutionAttempt {
  id: string;
  attempt_number: number;
  result_status: SimulatedExecutionStatus;
  input_order_status: string;
  requested_quantity: string;
  previously_filled_quantity: string;
  attempted_quantity: string;
  filled_quantity: string;
  remaining_quantity: string;
  average_fill_price: string | null;
  rejection_code: string | null;
  message: string;
  market_snapshot: Record<string, unknown>;
  account_snapshot?: Record<string, unknown> | null;
  fee_model_version: string;
  slippage_model_version: string;
  correlation_id: string;
  started_at: string;
  completed_at: string;
}

export interface ExecutionAttemptPage {
  items: BrokerExecutionAttempt[];
  page: number;
  page_size: number;
  total: number;
}

export interface FillSummary {
  fill_id: string;
  execution_attempt_id: string | null;
  order_id: string;
  account: { id: string; code: string; name: string };
  instrument: { id: string; symbol: string; exchange: string; name: string };
  side: "BUY" | "SELL";
  quantity: string;
  price: string;
  gross_amount: string;
  commission: string;
  stamp_duty: string;
  transfer_fee: string;
  other_fee: string;
  total_fee: string;
  net_cash_effect: string;
  executed_at: string;
  execution_reference: string | null;
  correlation_id: string;
}

export type FillDetail = FillSummary;

export interface FillPage {
  items: FillSummary[];
  page: number;
  page_size: number;
  total: number;
}

export interface ExecutionIntegrityReport {
  order_id: string;
  valid: boolean;
  issues: Array<{
    code: string;
    message: string;
    execution_attempt_id: string | null;
    fill_id: string | null;
  }>;
}
