type InstrumentLike = {
  symbol?: string | null;
  exchange?: string | null;
  name?: string | null;
};

const enumLabels: Record<string, string> = {
  ACTIVE: "已启用",
  DISABLED: "未启用",
  DEGRADED: "服务降级",
  BUY: "买入",
  SELL: "卖出",
  ENTRY: "建仓",
  EXIT: "退出持仓",
  REBALANCE: "调整持仓",
  ADVICE: "研究建议",
  ALLOW: "风控通过",
  PASS: "风控通过",
  REJECT: "风控拒绝",
  REQUIRE_CONFIRMATION: "需要人工复核",
  REVIEW: "需要人工复核",
  MANUAL_ORDER: "人工订单",
  STRATEGY_SIGNAL: "策略信号",
  REPLAY: "历史回放",
  BACKTEST: "日线回测",
  BROKER_ORDER: "券商订单",
  SYSTEM: "系统任务",
  HISTORICAL_SYNC: "历史行情同步",
  COMPLETE: "估值完整",
  PARTIAL: "部分估值",
  STALE: "行情陈旧",
  UNAVAILABLE: "不可估值（UNAVAILABLE）",
  NORMAL: "正常",
  DELAYED: "延迟",
  INCOMPLETE: "数据不完整",
  INVALID: "数据无效",
  UNKNOWN: "未知",
  CONNECTED: "已连接",
  DISCONNECTED: "未连接",
  CREATED: "已创建",
  RUNNING: "运行中",
  COMPLETED: "已完成",
  FAILED: "失败",
  SUCCEEDED: "成功",
  PARTIALLY_SUCCEEDED: "部分成功",
  CANCELLED: "已取消",
  LIMIT: "限价单（LIMIT）",
  MARKET: "市价单（MARKET）",
  DAY: "当日有效（DAY）",
  GTC: "撤销前有效（GTC）",
  RAW: "不复权（RAW）",
  QFQ: "前复权（QFQ）",
  DAY_1: "日线",
  MINUTE_1: "1分钟",
  MINUTE_5: "5分钟",
  MINUTE_15: "15分钟",
  MINUTE_30: "30分钟",
  MINUTE_60: "60分钟",
  READY: "就绪",
  NOT_READY: "未就绪",
  IMPLEMENTED: "已实现",
  NOT_IMPLEMENTED: "尚未实现",
  integer: "整数",
  decimal: "小数",
  boolean: "是/否",
  string: "文本",
  date: "日期",
  enum: "选项",
  MATCHED: "核对一致",
  MISMATCHED: "存在差异",
  READ_ONLY: "只读",
  SUSPENDED: "已暂停",
  CLOSED: "已关闭",
  IMMEDIATE: "即时可用",
  T_PLUS_ONE: "次日可用（T+1）",
  FILLED: "全部成交",
  PARTIALLY_FILLED: "部分成交",
  WAITING_CONFIRMATION: "等待确认",
  PENDING: "等待处理",
  WAITING: "等待订阅",
  SUBSCRIBED: "已订阅",
  STOPPED: "已停止",
  NOT_CONFIGURED: "未配置",
  CONNECTING: "连接中",
  SUPPRESSED: "已抑制外发",
  QUANTITY: "指定数量",
  SESSION_OPEN: "交易日开盘",
  SESSION_CLOSE: "交易日收盘",
  SESSION_END: "交易日结束",
};

const strategyLabels: Record<string, string> = {
  sma_crossover: "均线交叉策略（SMA Crossover）",
  volume_breakout: "成交量突破策略（Volume Breakout）",
  rsi_reversion: "RSI 均值回归策略（RSI Reversion）",
};

const scannerLabels: Record<string, string> = {
  limit_up_pullback: "涨停后回落筛选（limit_up_pullback）",
  volume_anomaly: "成交量异常筛选（volume_anomaly）",
};

const marketSourceLabels: Record<string, string> = {
  BAOSTOCK: "BaoStock 历史行情",
  AKSHARE_EASTMONEY: "AKShare 东方财富行情",
  FREE_BEST_EFFORT: "免费尽力而为行情",
  MINIQMT: "MiniQMT 行情",
};

const parameterLabels: Record<string, string> = {
  lookback_days: "回溯交易日数",
  limit_up_threshold: "涨停判定阈值",
  baseline_tolerance: "基准价容差",
  minimum_days_after_limit_up: "涨停后最短间隔",
  maximum_days_after_limit_up: "涨停后最长间隔",
  require_current_above_baseline: "不低于起涨基准价",
  minimum_current_volume_ratio: "当前成交量最低比例",
  short_window: "短期均线周期",
  long_window: "长期均线周期",
  volume_window: "平均成交量计算周期",
  minimum_volume_ratio: "最低成交量倍数",
  breakout_window: "价格突破观察周期",
  volume_multiplier: "放量倍数",
  exit_window: "退出观察周期",
  quantity: "每次交易数量",
  enabled: "是否启用",
  mode: "运行模式",
  threshold: "阈值",
  window: "观察周期",
  label: "标签",
};

export function displayEnum(value: string | null | undefined): string {
  if (!value) return "—";
  return enumLabels[value] ?? value;
}

export function displayStrategy(value: string | null | undefined): string {
  if (!value) return "—";
  return strategyLabels[value] ?? value;
}

export function displayScanner(value: string | null | undefined): string {
  if (!value) return "—";
  return scannerLabels[value] ?? value;
}

export function displayMarketSource(value: string | null | undefined): string {
  if (!value) return "—";
  return marketSourceLabels[value] ?? value;
}

export function displayParameter(name: string): string {
  const label = parameterLabels[name];
  return label ? `${label}（${name}）` : name;
}

export function normalizeExchange(exchange: string | null | undefined): string {
  const normalized = exchange?.toUpperCase();
  if (normalized === "SSE" || normalized === "SHSE") return "SH";
  if (normalized === "SZSE") return "SZ";
  if (normalized === "BSE") return "BJ";
  return normalized ?? "";
}

export function formatInstrument(
  instrument: Partial<InstrumentLike> | null | undefined,
  fallback = "未知标的",
): string {
  if (!instrument) return fallback;
  const symbol = instrument.symbol?.trim();
  const exchange = normalizeExchange(instrument.exchange);
  const code = [symbol, exchange].filter(Boolean).join(".");
  const name = instrument.name?.trim();
  if (name && code) return `${name}（${code}）`;
  return name || code || fallback;
}

function finiteNumber(
  value: string | number | null | undefined,
): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function formatNumber(
  value: string | number | null | undefined,
  options: Intl.NumberFormatOptions = {},
): string {
  const parsed = finiteNumber(value);
  if (parsed === null) return "—";
  const normalized = Object.is(parsed, -0) ? 0 : parsed;
  return new Intl.NumberFormat("zh-CN", {
    maximumFractionDigits: 8,
    ...options,
  }).format(normalized);
}

export function formatMoney(value: string | number | null | undefined): string {
  const formatted = formatNumber(value, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return formatted === "—" ? formatted : `¥${formatted}`;
}

export function formatPrice(value: string | number | null | undefined): string {
  return formatNumber(value, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  });
}

export function formatQuantity(
  value: string | number | null | undefined,
): string {
  return formatNumber(value, { maximumFractionDigits: 4 });
}

export function formatPercentRatio(
  value: string | number | null | undefined,
  digits = 2,
): string {
  const parsed = finiteNumber(value);
  if (parsed === null) return "—";
  return `${formatNumber(parsed * 100, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}%`;
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN");
}

export function shortId(value: string | null | undefined): string {
  if (!value) return "—";
  return `${value.slice(0, 8)}…`;
}

export function isTestData(value: unknown): boolean {
  if (value === null || value === undefined) return false;
  const text = typeof value === "string" ? value : JSON.stringify(value);
  return /(^|[^A-Z0-9])(DEMO|FIXTURE|U01|D03|BT01)([^A-Z0-9]|$)|DETERMINISTIC|演示/i.test(
    text,
  );
}

export function localizeReason(value: string | null | undefined): string {
  if (!value) return "—";
  if (value === "PROFIT_FACTOR_UNDEFINED_NO_LOSS_TRADES") {
    return "没有亏损交易，利润因子无法计算";
  }
  const downward = value.match(
    /SMA downward crossover:\s*short=([^,]+),\s*long=(.+)/i,
  );
  if (downward) {
    return `短期均线向下跌破长期均线：短期均线 ${formatPrice(downward[1])}，长期均线 ${formatPrice(downward[2])}`;
  }
  const upward = value.match(
    /SMA upward crossover:\s*short=([^,]+),\s*long=(.+)/i,
  );
  if (upward) {
    return `短期均线向上突破长期均线：短期均线 ${formatPrice(upward[1])}，长期均线 ${formatPrice(upward[2])}`;
  }
  return value;
}
