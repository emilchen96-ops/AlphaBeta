export type RiskDisplayDecision = "PASS" | "REJECT" | "REVIEW";

export interface RiskRuleResult {
  id: string;
  seq: number;
  rule_key: string;
  decision: "ALLOW" | "REJECT" | "REQUIRE_CONFIRMATION";
  reason_code: string;
  message: string;
  severity: string;
  observed_value: string | number | boolean | null;
  limit_value: string | number | boolean | null;
  evaluated_at: string;
}

export interface RiskDecision {
  id: string;
  request_id: string;
  source_type: string;
  source_id: string | null;
  account_id: string;
  instrument_id: string;
  account: { id: string; code: string | null; name: string | null };
  instrument: {
    id: string;
    symbol: string | null;
    exchange: string | null;
    name: string | null;
  };
  overall_decision: "ALLOW" | "REJECT" | "REQUIRE_CONFIRMATION";
  side: string | null;
  order_type: string | null;
  quantity: string | number | null;
  estimated_notional: string | null;
  projected_instrument_weight: string | null;
  projected_total_exposure: string | null;
  limits_snapshot: Record<string, unknown>;
  account_snapshot: Record<string, unknown>;
  instrument_snapshot: Record<string, unknown>;
  warnings: string[];
  rule_results: RiskRuleResult[];
  risk_rule_summary: Array<Record<string, unknown>>;
  order_id: string | null;
  correlation_id: string;
  evaluated_at: string;
}

export interface RiskDecisionPage {
  items: RiskDecision[];
  page: number;
  page_size: number;
  total: number;
}

export interface ActiveRiskLimits {
  max_order_notional: string | null;
  max_instrument_weight: string | null;
  max_total_exposure: string | null;
  max_orders_per_window: number | null;
  order_frequency_window_seconds: number;
  allow_market_orders: boolean;
  require_reference_price_for_market_order: boolean;
  kill_switch_enabled: boolean;
  configuration_source: string;
  effective_at: string;
  warnings: string[];
}
