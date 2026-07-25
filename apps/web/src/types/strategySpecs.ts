export type OperandKind = "FIELD" | "INDICATOR" | "CONSTANT";
export type LogicalOperator = "AND" | "OR";
export type ComparisonOperator = "GT" | "GTE" | "LT" | "LTE";

export interface StrategyOperand {
  kind: OperandKind;
  field: "open" | "high" | "low" | "close" | "volume" | null;
  indicator:
    | "SMA"
    | "ROLLING_HIGHEST"
    | "ROLLING_LOWEST"
    | "AVERAGE_VOLUME"
    | null;
  window: number | null;
  exclude_current: boolean;
  multiplier: string;
  value: string | null;
}

export interface StrategyComparison {
  type: "comparison";
  left: StrategyOperand;
  operator: ComparisonOperator;
  right: StrategyOperand;
}

export interface StrategyConditionGroup {
  type: "group";
  operator: LogicalOperator;
  conditions: Array<StrategyComparison | StrategyConditionGroup>;
}

export interface StrategySpec {
  schema_version: 1;
  name: string;
  description: string;
  entry: StrategyConditionGroup;
  exit: StrategyConditionGroup;
  timeframe: "DAY_1";
  quantity: string;
  single_instrument: boolean;
  data_range_years: number;
  origin: string;
}

export interface StrategyParseResult {
  status: "COMPLETE" | "PARTIAL";
  parser_source: "LOCAL_RULES" | "AI";
  spec: StrategySpec | null;
  preview: string[];
  warnings: string[];
  missing_fields: string[];
  ai_assistance: "DISABLED" | "ENABLED";
}

export interface StrategyTemplate {
  key: string;
  name: string;
  description: string;
  category: string;
  spec: StrategySpec | null;
  preview: string[];
  recommended: boolean;
}

export interface UserStrategy {
  id: string;
  name: string;
  description: string;
  current_version: number;
  archived: boolean;
  spec: StrategySpec;
  preview: string[];
  created_at: string;
  updated_at: string;
}

export interface UserStrategyPage {
  items: UserStrategy[];
  page: number;
  page_size: number;
  total: number;
}
