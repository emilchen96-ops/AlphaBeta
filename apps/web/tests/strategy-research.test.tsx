import { fireEvent, screen } from "@testing-library/react";

import { healthyStatus, renderRoute } from "./test-utils";

const runId = "33333333-3333-4333-8333-333333333333";
const catalog = [
  {
    strategy_key: "sma_crossover",
    display_name: "SMA Crossover",
    description: "均线交叉研究策略",
    version: "1.0.0",
    supported_timeframes: ["MINUTE_1"],
    parameter_schema_version: 1,
    parameters: [
      {
        name: "short_window",
        type: "integer",
        required: false,
        default: 5,
        description: "短窗口",
        min_value: 1,
        max_value: null,
        choices: [],
      },
      {
        name: "quantity",
        type: "decimal",
        required: false,
        default: "100",
        description: "参考数量",
        min_value: "0.1",
        max_value: null,
        choices: [],
      },
      {
        name: "enabled",
        type: "boolean",
        required: false,
        default: true,
        description: "启用",
        min_value: null,
        max_value: null,
        choices: [],
      },
      {
        name: "mode",
        type: "enum",
        required: false,
        default: "fast",
        description: "模式",
        min_value: null,
        max_value: null,
        choices: ["fast", "slow"],
      },
    ],
  },
];
const run = {
  run_id: runId,
  strategy_key: "sma_crossover",
  strategy_version: "1.0.0",
  status: "FAILED",
  timeframe: "MINUTE_1",
  instrument_ids: ["11111111-1111-4111-8111-111111111111"],
  instruments: [],
  parameters: { short_window: 5, quantity: "100" },
  start_at: "2026-01-01T00:00:00Z",
  end_at: "2026-01-02T00:00:00Z",
  bars_processed: 0,
  signals_generated: 0,
  warnings: [],
  started_at: "2026-01-01T00:00:00Z",
  completed_at: null,
  failed_at: "2026-01-01T00:00:01Z",
  created_at: "2026-01-01T00:00:00Z",
  error: { code: "STRATEGY_EXECUTION_ERROR", message: "strategy run failed" },
  capabilities: { creates_orders: false },
};
const signal = {
  signal_id: "44444444-4444-4444-8444-444444444444",
  strategy_run_id: runId,
  sequence_number: 1,
  strategy_key: "sma_crossover",
  strategy_version: "1.0.0",
  instrument_id: "11111111-1111-4111-8111-111111111111",
  instrument: { symbol: "600000", exchange: "SSE", name: "浦发银行" },
  signal_type: "ENTRY",
  side: "BUY",
  generated_at: "2026-01-01T01:00:00Z",
  bar_timestamp: "2026-01-01T01:00:00Z",
  quantity: "100.00000000",
  target_weight: null,
  reference_price: "12.34000000",
  confidence: "0.80000000",
  reason: "SMA crossover",
  schema_version: 1,
};

function installFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string | URL | Request) => {
      const url =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : input.url;
      let body: unknown = healthyStatus;
      if (url.includes("/strategies/catalog")) body = catalog;
      else if (url.includes(`/strategy-runs/${runId}/signals`))
        body = { items: [signal], page: 1, page_size: 20, total: 1 };
      else if (url.endsWith(`/strategy-runs/${runId}`)) body = run;
      else if (url.includes("/strategy-runs?"))
        body = { items: [run], page: 1, page_size: 20, total: 1 };
      else if (url.includes("/signals?"))
        body = { items: [signal], page: 1, page_size: 20, total: 1 };
      else if (url.includes("/instruments?"))
        body = { items: [], page: 1, page_size: 50, total: 0 };
      return Promise.resolve(
        new Response(JSON.stringify(body), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }),
  );
}

beforeEach(() => {
  vi.stubGlobal("WebSocket", undefined);
  installFetch();
});
afterEach(() => vi.unstubAllGlobals());

test("策略目录加载并展示安全边界", async () => {
  renderRoute("/strategies");
  expect(
    await screen.findAllByText("均线交叉策略（SMA Crossover）"),
  ).not.toHaveLength(0);
  expect(
    screen.getByText(/模板只用于历史研究，不会发送真实交易/),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /买入|卖出|自动交易|转为订单/ }),
  ).not.toBeInTheDocument();
});

test("普通模板页隐藏工程参数并提供统一使用入口", async () => {
  renderRoute("/strategies");
  expect(await screen.findByText("使用此策略")).toBeInTheDocument();
  expect(screen.queryByText("创建研究运行")).not.toBeInTheDocument();
  expect(screen.queryByText("批量研究")).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("查看技术详情"));
  expect(screen.getByText(/短期均线周期（short_window）/)).toBeInTheDocument();
  expect(screen.getByText(/每次交易数量（quantity）/)).toBeInTheDocument();
  expect(screen.getByText(/是否启用（enabled）/)).toBeInTheDocument();
  expect(screen.getByText(/运行模式（mode）/)).toBeInTheDocument();
});

test("研究运行列表支持状态展示和筛选", async () => {
  renderRoute("/strategy-runs");
  expect(
    await screen.findByText("运行失败", {}, { timeout: 10_000 }),
  ).toBeInTheDocument();
  expect(screen.getByText(/历史研究运行，不是绩效回测/)).toBeInTheDocument();
});

test("FAILED运行详情展示脱敏错误和Signal边界", async () => {
  renderRoute(`/strategy-runs/${runId}`);
  expect(await screen.findByText("strategy run failed")).toBeInTheDocument();
  expect(
    screen.getByText(/reference_price 仅为研究参考价/),
  ).toBeInTheDocument();
});

test("Signal页面展示Decimal字符串与研究原因", async () => {
  renderRoute(`/signals?strategy_run_id=${runId}`);
  expect(
    await screen.findByText("12.34", {}, { timeout: 10_000 }),
  ).toBeInTheDocument();
  expect(screen.getByText("SMA crossover")).toBeInTheDocument();
  expect(screen.getByText(/只创建风控决策，不创建订单/)).toBeInTheDocument();
});

test("策略目录展示版本和后端参数说明", async () => {
  renderRoute("/strategies");
  fireEvent.click(await screen.findByText("查看技术详情"));
  expect(await screen.findByText(/版本：v1\.0\.0/)).toBeInTheDocument();
  expect(screen.getAllByText(/quantity/).length).toBeGreaterThan(0);
});

test("研究运行列表提供策略和状态筛选", async () => {
  renderRoute("/strategy-runs");
  expect(await screen.findByText("策略筛选")).toBeInTheDocument();
  expect(screen.getByText("状态筛选")).toBeInTheDocument();
});

test("运行详情展示规范化参数", async () => {
  renderRoute(`/strategy-runs/${runId}`);
  expect(await screen.findByText(/"short_window": 5/)).toBeInTheDocument();
  expect(screen.getByText(/"quantity": "100"/)).toBeInTheDocument();
});

test("Signal页面提供研究筛选而没有交易动作", async () => {
  renderRoute("/signals");
  expect(
    await screen.findByPlaceholderText("策略运行编号"),
  ).toBeInTheDocument();
  expect(screen.getByText("信号类型")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /立即执行|创建Fill/ }),
  ).not.toBeInTheDocument();
});

test.each(["/strategies", "/strategy-runs", "/signals"])(
  "%s 页面不存在自动交易入口",
  async (route) => {
    renderRoute(route);
    expect(
      (
        await screen.findAllByText(
          route === "/strategies"
            ? /策略模板|SMA Crossover/
            : /Signal|研究运行|SMA Crossover/,
        )
      ).length,
    ).toBeGreaterThan(0);
    expect(
      screen.queryByRole("button", {
        name: /买入|卖出|自动交易|实盘|转为订单/,
      }),
    ).not.toBeInTheDocument();
  },
);
