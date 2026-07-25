export type ServiceState = "online" | "offline";
export type WebSocketState = "connected" | "connecting" | "disconnected";
export type ProductMode = "RESEARCH_ONLY" | "FULL_SIMULATION";

export interface SystemStatus {
  api: "online";
  postgresql: ServiceState;
  redis: ServiceState;
  environment: string;
  product_mode: ProductMode;
  version: string;
  server_time: string;
  correlation_id: string;
}

export type CapabilityImplementationStatus =
  "WORKING" | "PARTIAL" | "PLACEHOLDER" | "NOT_IMPLEMENTED" | "DISABLED";
export type CapabilityReadinessStatus =
  "READY" | "MISSING" | "DISABLED" | "NOT_REQUIRED" | "UNKNOWN";
export type CapabilityConfigurationStatus =
  | CapabilityReadinessStatus
  | "FAKE"
  | "REAL_CONFIGURED"
  | "REAL_AVAILABLE"
  | "REAL_UNAVAILABLE";

export interface SystemCapability {
  module_key: string;
  implementation_status: CapabilityImplementationStatus;
  data_status: CapabilityReadinessStatus;
  configuration_status: CapabilityConfigurationStatus;
  available: boolean;
  availability?:
    | "READY"
    | "NEEDS_DATA"
    | "NEEDS_CONFIG"
    | "DEMO_ONLY"
    | "DISABLED"
    | "PARTIAL"
    | "NOT_IMPLEMENTED"
    | "AVAILABLE"
    | "DEGRADED"
    | "NOT_AVAILABLE";
  reason: string;
  required_actions: string[];
  last_success_at?: string | null;
  provider?: string | null;
  provider_status?: "READY" | "MISSING" | "DISABLED" | "UNKNOWN";
  mode?: string;
  worker_status?: "ONLINE" | "OFFLINE" | "NOT_REQUIRED";
}

export interface CapabilityDataCounts {
  instrument_count: number | null;
  market_bar_count: number | null;
  daily_market_bar_count: number | null;
  market_bar_instrument_count: number | null;
  earliest_market_bar_at: string | null;
  latest_market_bar_at: string | null;
  simulated_account_count: number | null;
  scan_run_count: number | null;
  strategy_run_count: number | null;
  strategy_experiment_count: number | null;
  information_source_count: number | null;
  information_item_count: number | null;
  market_event_count: number | null;
  ai_analysis_run_count: number | null;
  order_count: number | null;
  executable_order_count: number | null;
  fill_count: number | null;
  risk_decision_count: number | null;
  backtest_run_count: number | null;
  replay_run_count: number | null;
  trading_calendar_session_count: number | null;
  adjustment_factor_count: number | null;
  trading_status_count: number | null;
  lifecycle_event_count: number | null;
}

export interface SystemCapabilities {
  generated_at: string;
  database_reachable: boolean;
  counts: CapabilityDataCounts;
  items: SystemCapability[];
}

export interface ApiErrorEnvelope {
  error: {
    code: string;
    message: string;
    details: unknown;
    correlation_id: string;
    timestamp: string;
  };
}
