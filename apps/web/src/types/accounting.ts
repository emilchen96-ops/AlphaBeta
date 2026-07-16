export type AccountStatus = "ACTIVE" | "READ_ONLY" | "SUSPENDED" | "CLOSED";
export type ValuationStatus = "COMPLETE" | "PARTIAL" | "STALE" | "UNAVAILABLE";

export interface Page<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
}

export interface Account {
  id: string;
  account_code: string;
  name: string;
  status: AccountStatus;
  broker_type: string;
  base_currency: string;
  settlement_policy: "IMMEDIATE" | "T_PLUS_ONE";
  created_at: string;
  updated_at: string;
}

export interface CashBalance {
  id: string;
  account_id: string;
  currency: string;
  total_cash: string;
  available_cash: string;
  frozen_cash: string;
  row_version: number;
  as_of: string;
}

export interface Position {
  id: string;
  instrument_id: string;
  total_quantity: string;
  available_quantity: string;
  frozen_quantity: string;
  unsettled_quantity: string;
  cost_basis: string;
  average_cost: string;
  market_value: string | null;
  realized_pnl: string;
  unrealized_pnl: string | null;
  last_price: string | null;
  last_price_at: string | null;
  valuation_status: ValuationStatus;
  as_of: string;
}

export interface AccountSnapshot {
  id: string;
  account_id: string;
  as_of: string;
  cash_total: string;
  cash_available: string;
  cash_frozen: string;
  positions_cost_basis: string;
  positions_market_value: string | null;
  total_equity: string | null;
  realized_pnl: string;
  unrealized_pnl: string | null;
  valuation_status: ValuationStatus;
  priced_position_count: number;
  unpriced_position_count: number;
  latest_price_time: string | null;
  metadata: Record<string, unknown>;
}

export interface Reconciliation {
  id: string;
  account_id: string;
  status: "MATCHED" | "MISMATCHED" | "FAILED";
  started_at: string;
  completed_at: string | null;
  discrepancy_count: number;
  discrepancies: Record<string, unknown>[];
}

export interface AccountSummary {
  account: Account;
  cash_balances: CashBalance[];
  positions: Position[];
  latest_snapshot: AccountSnapshot | null;
  latest_reconciliation: Reconciliation | null;
}

export interface LivePositionValuation {
  instrument_id: string;
  symbol: string;
  quantity: string;
  price: string | null;
  market_value: string | null;
  unrealized_pnl: string | null;
  price_source: string | null;
  quote_time: string | null;
  freshness: "FRESH" | "STALE" | "MISSING";
}

export interface AccountLiveValuation {
  account_id: string;
  cash_balance: string;
  positions_market_value: string;
  total_equity: string;
  status: "COMPLETE" | "STALE" | "UNAVAILABLE";
  calculated_at: string;
  positions: LivePositionValuation[];
}

export interface LedgerTransaction {
  id: string;
  transaction_type: string;
  status: string;
  business_key: string;
  related_fill_id: string | null;
  occurred_at: string;
  description: string | null;
}

export interface CashLedgerEntry {
  id: number;
  entry_type: string;
  total_delta: string;
  total_cash_after: string;
  gross_amount: string | null;
  fee_amount: string | null;
  occurred_at: string;
}

export interface PositionLedgerEntry {
  id: number;
  instrument_id: string;
  entry_type: string;
  quantity_delta: string;
  cost_basis_delta: string;
  realized_pnl_delta: string;
  total_quantity_after: string;
  occurred_at: string;
}
