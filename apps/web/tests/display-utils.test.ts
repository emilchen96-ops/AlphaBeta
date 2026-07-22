import {
  displayEnum,
  displayParameter,
  displayScanner,
  displayStrategy,
  formatInstrument,
  formatMoney,
  formatPercentRatio,
  formatQuantity,
  isTestData,
  localizeReason,
} from "../src/utils/display";

test("统一映射内部枚举、策略、扫描器与参数名称", () => {
  expect(displayEnum("MANUAL_ORDER")).toBe("人工订单");
  expect(displayEnum("UNAVAILABLE")).toBe("不可估值（UNAVAILABLE）");
  expect(displayStrategy("sma_crossover")).toContain("均线交叉策略");
  expect(displayScanner("volume_anomaly")).toContain("成交量异常筛选");
  expect(displayParameter("lookback_days")).toBe(
    "回溯交易日数（lookback_days）",
  );
});

test("业务数值不会显示科学计数法或超长小数", () => {
  expect(formatMoney("0E-8")).toBe("¥0.00");
  expect(formatMoney("99689.5344444")).toBe("¥99,689.53");
  expect(formatQuantity("100.00000000")).toBe("100");
  expect(formatPercentRatio("0.0996811797148")).toBe("9.97%");
});

test("标的显示为名称和标准代码", () => {
  expect(
    formatInstrument({ symbol: "600000", exchange: "SSE", name: "浦发银行" }),
  ).toBe("浦发银行（600000.SH）");
});

test("识别验收数据并翻译均线原因", () => {
  expect(isTestData("D03_FIXTURE")).toBe(true);
  expect(isTestData("BAOSTOCK")).toBe(false);
  expect(
    localizeReason("SMA downward crossover: short=10.46666666, long=10.6"),
  ).toBe("短期均线向下跌破长期均线：短期均线 10.4667，长期均线 10.60");
});
