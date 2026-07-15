export type MarketTimeframe = "DAY_1" | "MINUTE_1";
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
  supported_timeframes: string[];
  updated_at: string;
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
