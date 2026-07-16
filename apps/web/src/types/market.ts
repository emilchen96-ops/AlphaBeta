export type MarketTimeframe =
  "DAY_1" | "MINUTE_1" | "MINUTE_5" | "MINUTE_15" | "MINUTE_30" | "MINUTE_60";
export type AdjustmentType = "NONE" | "FORWARD" | "BACKWARD";
export type FreshnessStatus =
  "NORMAL" | "DELAYED" | "INCOMPLETE" | "INVALID" | "UNKNOWN";

export interface Instrument {
  id: string;
  symbol: string;
  exchange: string;
  market: string;
  name: string;
  asset_type: string;
  currency: string;
  lot_size: string;
  price_tick: string;
  timezone: string;
  is_active: boolean;
  updated_at: string;
}

export interface InstrumentPage {
  items: Instrument[];
  page: number;
  page_size: number;
  total: number;
}

export interface Watchlist {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
  updated_at: string;
}

export interface WatchlistItem {
  id: string;
  watchlist_id: string;
  instrument: Instrument;
  sort_order: number;
  note: string | null;
  created_at: string;
}

export interface WatchlistDetail extends Watchlist {
  items: WatchlistItem[];
}

export interface MarketDataSource {
  id: string;
  source_code: string;
  name: string;
  status: "ACTIVE" | "DISABLED" | "DEGRADED";
  priority: number;
  supports_realtime: boolean;
  provider_tier: "DEMO" | "FREE_BEST_EFFORT";
  supports_quotes: boolean;
  supports_recent_minute_bars: boolean;
  last_health_check_at: string | null;
  supported_timeframes: string[];
  updated_at: string;
}

export interface MarketQuote {
  instrument_id: string;
  source_code: string;
  symbol: string;
  quote_time: string | null;
  received_at: string;
  last_price: string;
  previous_close?: string | null;
  open?: string | null;
  high?: string | null;
  low?: string | null;
  volume?: string | null;
  amount?: string | null;
  quality_status: FreshnessStatus;
  provider_tier?: "FREE_BEST_EFFORT";
  usage?: ("RESEARCH_ONLY" | "NON_TRADING_GRADE")[];
  quality_flags?: Record<string, unknown>;
  revision: number;
  freshness?: "FRESH" | "STALE" | "MISSING";
  age_seconds?: number;
}

export interface LatestQuotesResponse {
  schema_version: 1;
  items: MarketQuote[];
  missing_instrument_ids: string[];
  calculated_at: string;
}

export interface RealtimeMarketStatus {
  enabled: boolean;
  state: string;
  source_code: string | null;
  circuit_state: string | null;
  consecutive_failures: number;
  requested_count: number;
  received_count: number;
  changed_count: number;
  rejected_count: number;
  checked_at: string | null;
  error_summary: string | null;
  worker_heartbeat: Record<string, unknown> | null;
}

export interface MarketBar {
  instrument_id: string;
  source_code: string;
  timeframe: MarketTimeframe;
  adjustment_type: AdjustmentType;
  bar_time: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string;
  amount: string | null;
  vwap: string | null;
  received_at: string;
  quality_status: FreshnessStatus;
}

export interface MarketBarsResponse {
  source_code: string;
  items: MarketBar[];
  freshness: {
    source_code: string;
    freshness_status: FreshnessStatus;
    latest_bar_time: string | null;
    latest_received_at: string | null;
    calculated_at: string;
  };
}
