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
