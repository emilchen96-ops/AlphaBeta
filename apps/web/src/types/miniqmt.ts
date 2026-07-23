export interface MiniQMTStatus {
  configured: boolean;
  state: string;
  agent: {
    state?: string;
    checked_at?: string;
    last_market_time?: string | null;
    last_received_at?: string | null;
    last_minute_bar_time?: string | null;
    error_code?: string | null;
    error_message?: string | null;
  } | null;
  desired_count: number;
  active_count: number;
  failed_count: number;
  latest_minute_bar_time: string | null;
  source: "MINIQMT";
  market_data_capability: "ENABLED";
  trading_capability: "DISABLED";
  trading_message: string;
}

export interface SubscriptionItem {
  instrument_id: string;
  symbol: string;
  exchange: string;
  name: string;
  provider_symbol: string;
  origins?: string[];
  desired_status?: string;
  status?: string;
  last_market_time?: string | null;
  last_received_at?: string | null;
  last_error_code?: string | null;
  last_error_message?: string | null;
  is_test_data?: boolean;
}

export interface SubscriptionPlan {
  version: string;
  desired_count: number;
  source_summary: Record<string, number>;
  created_at: string;
  items: SubscriptionItem[];
}

export interface RealtimeQuote {
  instrument_id: string;
  symbol: string;
  exchange: string;
  name: string;
  display_name: string;
  market_time: string;
  received_at: string;
  ingested_at: string;
  last_price: string;
  change: string | null;
  change_percent: string | null;
  open_price: string | null;
  high_price: string | null;
  low_price: string | null;
  previous_close: string | null;
  volume: string | null;
  amount: string | null;
  bid_price_1: string | null;
  ask_price_1: string | null;
  bid_volume_1: string | null;
  ask_volume_1: string | null;
  trading_status: string;
  source: "MINIQMT";
  is_test_data: false;
}
