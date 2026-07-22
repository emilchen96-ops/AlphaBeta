import { fireEvent, screen, waitFor } from "@testing-library/react";

import { healthyStatus, renderRoute } from "./test-utils";
import { estimateCombinationCount } from "../src/pages/strategyExperimentUtils";

const experimentId = "55555555-5555-4555-8555-555555555555";
const runId = "66666666-6666-4666-8666-666666666666";
const instrumentId = "11111111-1111-4111-8111-111111111111";
const catalog = [
  {
    strategy_key: "grid_strategy",
    display_name: "Grid Research Strategy",
    description: "test strategy",
    version: "2.1.0",
    supported_timeframes: ["MINUTE_1"],
    parameter_schema_version: 1,
    parameters: [
      {
        name: "window",
        type: "integer",
        required: false,
        default: 5,
        description: "窗口",
        min_value: 1,
        max_value: 100,
        choices: [],
      },
      {
        name: "threshold",
        type: "decimal",
        required: false,
        default: "0.10000000",
        description: "阈值",
        min_value: "0.00000001",
        max_value: "1",
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
      {
        name: "label",
        type: "string",
        required: false,
        default: "base",
        description: "标签",
        min_value: null,
        max_value: null,
        choices: [],
      },
    ],
  },
];
const experiment = {
  experiment_id: experimentId,
  idempotency_key: "experiment:test",
  strategy_key: "grid_strategy",
  strategy_version: "2.1.0",
  environment: "test",
  timeframe: "MINUTE_1",
  instrument_ids: [instrumentId],
  start_at: "2026-01-01T00:00:00Z",
  end_at: "2026-01-02T00:00:00Z",
  parameter_grid: { threshold: ["0.10000000", "0.20000000"] },
  combination_count: 2,
  runs_completed: 1,
  runs_failed: 1,
  total_signals: 3,
  status: "PARTIAL_FAILED",
  started_at: "2026-01-01T00:00:00Z",
  completed_at: "2026-01-01T00:01:00Z",
  failed_at: null,
  error: null,
  correlation_id: "experiment-correlation-id",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:01:00Z",
  capabilities: { creates_orders: false },
};
const runs = [
  {
    combination_index: 0,
    normalized_parameters: { threshold: "0.10000000" },
    strategy_run_id: runId,
    run_status: "COMPLETED",
    bars_processed: 10,
    signals_generated: 3,
    warning: null,
  },
  {
    combination_index: 1,
    normalized_parameters: { threshold: "0.20000000" },
    strategy_run_id: null,
    run_status: "FAILED",
    bars_processed: 0,
    signals_generated: 0,
    warning: "组合运行失败",
  },
];
const comparison = [
  {
    combination_index: 0,
    normalized_parameters: { threshold: "0.10000000" },
    strategy_run_id: runId,
    run_status: "COMPLETED",
    bars_processed: 10,
    total_signals: 3,
    buy_signals: 2,
    sell_signals: 1,
    first_signal_at: "2026-01-01T00:01:00Z",
    last_signal_at: "2026-01-01T00:03:00Z",
    signaled_instrument_count: 1,
    warning: null,
  },
  {
    combination_index: 1,
    normalized_parameters: { threshold: "0.20000000" },
    strategy_run_id: null,
    run_status: "FAILED",
    bars_processed: 0,
    total_signals: 0,
    buy_signals: 0,
    sell_signals: 0,
    first_signal_at: null,
    last_signal_at: null,
    signaled_instrument_count: 0,
    warning: "组合运行失败",
  },
];
const overlap = [
  {
    left_combination_index: 0,
    right_combination_index: 1,
    intersection_count: 1,
    union_count: 3,
    similarity: "0.333333333333333333",
  },
];

let experimentItems: (typeof experiment)[] = [experiment];
let experimentStatus = experiment.status;
let postResponse: Promise<Response> | undefined;

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
      "X-Correlation-ID": "header-correlation",
    },
  });
}

function installFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : input.url;
      if (url.endsWith("/api/v1/status"))
        return Promise.resolve(response(healthyStatus));
      if (url.includes("/strategies/catalog"))
        return Promise.resolve(response(catalog));
      if (url.includes("/instruments?"))
        return Promise.resolve(
          response({
            items: [
              {
                id: instrumentId,
                symbol: "600000",
                exchange: "SSE",
                name: "浦发银行",
              },
            ],
            page: 1,
            page_size: 50,
            total: 1,
          }),
        );
      if (url.endsWith(`/strategy-experiments/${experimentId}/runs`))
        return Promise.resolve(response(runs));
      if (url.endsWith(`/strategy-experiments/${experimentId}/comparison`))
        return Promise.resolve(response(comparison));
      if (url.endsWith(`/strategy-experiments/${experimentId}/signal-overlap`))
        return Promise.resolve(response(overlap));
      if (url.endsWith(`/strategy-experiments/${experimentId}`))
        return Promise.resolve(
          response({ ...experiment, status: experimentStatus }),
        );
      if (url.endsWith("/strategy-experiments") && init?.method === "POST")
        return postResponse ?? Promise.resolve(response(experiment, 201));
      if (url.includes("/strategy-experiments?"))
        return Promise.resolve(
          response({
            items: experimentItems.map((item) => ({
              ...item,
              status: experimentStatus,
            })),
            page: 1,
            page_size: 20,
            total: experimentItems.length,
          }),
        );
      return Promise.resolve(response(healthyStatus));
    }),
  );
}

beforeEach(() => {
  experimentItems = [experiment];
  experimentStatus = experiment.status;
  postResponse = undefined;
  vi.stubGlobal("WebSocket", undefined);
  installFetch();
});
afterEach(() => vi.unstubAllGlobals());

test("加载实验列表并明确区分部分失败状态", async () => {
  renderRoute("/strategy-experiments");
  expect(await screen.findByText("部分组合失败")).toBeInTheDocument();
  expect(screen.getByText("grid_strategy")).toBeInTheDocument();
  expect(
    screen.getByText(/研究信号（Signal）数量只表示触发频率/),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /买入|交易|执行/ }),
  ).not.toBeInTheDocument();
});

test("实验列表提供空状态、策略状态和创建时间筛选", async () => {
  experimentItems = [];
  renderRoute("/strategy-experiments");
  expect(await screen.findByText("暂无批量研究实验")).toBeInTheDocument();
  expect(screen.getAllByRole("combobox").length).toBeGreaterThanOrEqual(2);
  expect(screen.getByLabelText("创建时间起点")).toBeInTheDocument();
  expect(screen.getByLabelText("创建时间终点")).toBeInTheDocument();
});

test("目录预选驱动五类参数网格并显示默认值和组合预览", async () => {
  renderRoute("/strategy-experiments?strategy_key=grid_strategy");
  expect(
    await screen.findByText("观察周期（window） · 整数"),
  ).toBeInTheDocument();
  expect(screen.getByText("阈值（threshold） · 小数")).toBeInTheDocument();
  expect(screen.getByText("是否启用（enabled） · 是/否")).toBeInTheDocument();
  expect(screen.getByText("运行模式（mode） · 选项")).toBeInTheDocument();
  expect(screen.getByText("标签（label） · 文本")).toBeInTheDocument();
  expect(screen.getByText(/默认值：0.10000000/)).toBeInTheDocument();
  expect(screen.getByText("组合数量预览：1")).toBeInTheDocument();
});

test("候选值添加删除后按各参数候选数乘积预览组合", () => {
  const grid = {
    window: [2, 3],
    threshold: ["0.10000000", "0.20000000"],
    enabled: [true, false],
  };
  expect(estimateCombinationCount(grid)).toBe(8);
  grid.window.pop();
  expect(estimateCombinationCount(grid)).toBe(4);
  expect(estimateCombinationCount({})).toBe(1);
});

test.each([
  ["COMPLETED", "全部完成"],
  ["PARTIAL_FAILED", "部分组合失败"],
  ["FAILED", "全部失败"],
])("详情正确显示 %s 实验状态", async (status, label) => {
  experimentStatus = status;
  renderRoute(`/strategy-experiments/${experimentId}`);
  expect(await screen.findByText(label)).toBeInTheDocument();
});

test("详情展示组合、Signal对比、跳转与保留精度的重合矩阵", async () => {
  renderRoute(`/strategy-experiments/${experimentId}`);
  expect(
    await screen.findByText(/threshold=\[0\.10000000/),
  ).toBeInTheDocument();
  expect(screen.getAllByText("组合运行失败").length).toBeGreaterThan(0);
  expect(screen.getByText("买入信号")).toBeInTheDocument();
  expect(screen.getByText("卖出信号")).toBeInTheDocument();
  expect(screen.getAllByText("0.333333333333333333").length).toBe(2);
  expect(screen.getByRole("link", { name: "运行详情" })).toHaveAttribute(
    "href",
    `/strategy-runs/${runId}`,
  );
  expect(screen.getByRole("link", { name: "研究信号" })).toHaveAttribute(
    "href",
    `/signals?strategy_run_id=${runId}`,
  );
});

test("同步创建期间按钮禁用以防重复提交", async () => {
  let resolvePost!: (value: Response) => void;
  postResponse = new Promise((resolve) => {
    resolvePost = resolve;
  });
  renderRoute("/strategy-experiments?strategy_key=grid_strategy");
  await screen.findByText("观察周期（window） · 整数");
  const instrumentSelect = screen.getByLabelText("标的");
  fireEvent.mouseDown(instrumentSelect);
  fireEvent.click(await screen.findByText(/600000\.SSE/));
  fireEvent.change(screen.getByLabelText("开始时间"), {
    target: { value: "2026-01-01T00:00" },
  });
  fireEvent.change(screen.getByLabelText("结束时间"), {
    target: { value: "2026-01-02T00:00" },
  });
  const submit = screen.getByRole("button", { name: /开始批量研究/ });
  fireEvent.click(submit);
  fireEvent.click(submit);
  await waitFor(() => expect(submit).toBeDisabled());
  expect(
    (fetch as ReturnType<typeof vi.fn>).mock.calls.filter(
      ([, init]) => init?.method === "POST",
    ),
  ).toHaveLength(1);
  resolvePost(response(experiment, 201));
});
