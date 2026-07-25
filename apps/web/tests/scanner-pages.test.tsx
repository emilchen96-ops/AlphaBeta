import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import { healthyStatus, renderRoute } from "./test-utils";

const runId = "33333333-3333-4333-8333-333333333333";
const catalog = [
  {
    scanner_key: "volume_anomaly",
    display_name: "成交量异常放大",
    description: "使用历史均量识别成交量异常",
    version: "1.0.0",
    supported_timeframes: ["DAY_1"],
    schema_version: 1,
    data_source: "MINIQMT",
    default_universe: "ALL_ACTIVE_A_SHARES",
    execution_mode: "BACKGROUND_BATCH",
    parameters: [
      {
        name: "volume_window",
        display_name: "平均成交量计算周期",
        unit: "交易日",
        type: "integer",
        description: "历史均量窗口",
        required: false,
        nullable: false,
        default: 20,
        min_value: 1,
        max_value: 500,
      },
      {
        name: "minimum_volume_ratio",
        display_name: "最低成交量倍数",
        unit: "倍",
        type: "decimal",
        description: "最小成交量倍数",
        required: false,
        nullable: false,
        default: "2",
        min_value: "0",
        max_value: null,
      },
    ],
  },
];
const run = {
  scan_run_id: runId,
  scanner_key: "volume_anomaly",
  scanner_version: "1.0.0",
  parameters: { volume_window: 20, minimum_volume_ratio: "2" },
  universe_type: "ALL_ACTIVE_A_SHARES",
  universe_filters: {
    exclude_st: true,
    exclude_suspended: true,
    exclude_insufficient_history: true,
  },
  instrument_ids: [],
  source_code: "MINIQMT",
  timeframe: "DAY_1",
  price_adjustment_mode: "RAW",
  as_of: "2026-07-22T07:00:00Z",
  status: "COMPLETED",
  current_phase: "COMPLETED",
  progress_percent: 100,
  total_instruments: 5200,
  excluded_instruments: 120,
  data_ready_instruments: 5080,
  backfill_requested: 300,
  backfill_failed: 2,
  insufficient_history: 3,
  instruments_scanned: 5077,
  matches_found: 1,
  failed_instruments: 0,
  cancel_requested: false,
  started_at: "2026-07-22T08:00:00Z",
  completed_at: "2026-07-22T08:00:01Z",
  failed_at: null,
  error: null,
  correlation_id: "55555555-5555-4555-8555-555555555555",
  created_at: "2026-07-22T08:00:00Z",
  replayed: false,
  capabilities: {
    creates_signals: false,
    creates_orders: false,
    uses_risk: false,
    uses_broker: false,
    modifies_portfolio: false,
    is_realtime: false,
  },
};
const result = {
  scan_result_id: "44444444-4444-4444-8444-444444444444",
  scan_run_id: runId,
  instrument_id: "11111111-1111-4111-8111-111111111111",
  instrument: { symbol: "600000", exchange: "SSE", name: "浦发银行" },
  rank: 1,
  score: "3.5",
  matched_at: "2026-07-22T07:00:00Z",
  reference_price: "12.34",
  reason_code: "VOLUME_ANOMALY",
  reason: "当前成交量达到此前历史均量的可配置倍数。",
  metrics: {
    volume_ratio: "3.5",
    current_volume: "3000000",
    current_amount: "37000000",
    daily_return: "0.05",
    market_data_time: "2026-07-22T07:00:00Z",
    data_source: "MINIQMT",
  },
  schema_version: 1,
  created_at: "2026-07-22T08:00:01Z",
};

let createPayload: Record<string, unknown> | undefined;

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
      let body: unknown = healthyStatus;
      let status = 200;
      if (url.includes("/scanners/catalog")) body = catalog;
      else if (url.includes("/scanners/session-default"))
        body = {
          scan_date: "2026-07-22",
          data_source: "MINIQMT",
          timeframe: "DAY_1",
        };
      else if (url.includes(`/scan-runs/${runId}/results`))
        body = { items: [result], total: 1, page: 1, page_size: 50 };
      else if (url.endsWith(`/scan-runs/${runId}/members`))
        body = {
          items: [],
          summary: { MATCHED: 1, EXCLUDED: 120, DATA_MISSING: 3 },
          total: 124,
        };
      else if (url.endsWith(`/scan-runs/${runId}`)) body = run;
      else if (url.includes("/scan-runs?"))
        body = { items: [run], page: 1, page_size: 20, total: 1 };
      else if (url.endsWith("/scan-runs") && init?.method === "POST") {
        if (typeof init.body !== "string") {
          throw new Error("expected JSON request body");
        }
        createPayload = JSON.parse(init.body) as Record<string, unknown>;
        body = { ...run, status: "QUEUED", current_phase: "QUEUED" };
        status = 201;
      } else if (url.includes("/instruments?"))
        body = {
          items: [
            {
              id: result.instrument_id,
              symbol: "600000",
              exchange: "SSE",
              name: "浦发银行",
            },
          ],
          page: 1,
          page_size: 50,
          total: 1,
        };
      return new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
}

beforeEach(() => {
  createPayload = undefined;
  vi.stubGlobal("WebSocket", undefined);
  installFetch();
});
afterEach(() => vi.unstubAllGlobals());

test("全市场扫描窗口不再要求研究股票池并自动填入中文默认值", async () => {
  renderRoute("/scanners");
  expect(await screen.findByText(/成交量异常筛选/)).toBeInTheDocument();
  expect(
    screen.queryByText(/扫描结果仅为规则筛选结果/),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /开始全市场扫描/ }));
  const dialog = screen.getByRole("dialog");
  expect(within(dialog).getByText("全部正常上市A股")).toBeInTheDocument();
  expect(within(dialog).getByText("MiniQMT")).toBeInTheDocument();
  expect(within(dialog).queryByText(/研究股票池/)).not.toBeInTheDocument();
  expect(within(dialog).queryByText("DAY_1")).not.toBeInTheDocument();
  expect(
    within(dialog).queryByText(/幂等键|instrument_id/),
  ).not.toBeInTheDocument();

  fireEvent.click(within(dialog).getByText(/高级参数（已填入推荐默认值）/));
  expect(
    await within(dialog).findByText(/平均成交量计算周期（volume_window）/),
  ).toBeInTheDocument();
  expect(
    within(dialog).getByText(/最低成交量倍数（minimum_volume_ratio）/),
  ).toBeInTheDocument();
  const numericInputs = within(dialog).getAllByRole("spinbutton");
  expect(numericInputs).toHaveLength(3);
  expect(numericInputs[1]).toHaveValue("20");
  expect(numericInputs[2]).toHaveValue("2");

  fireEvent.click(within(dialog).getByRole("button", { name: "开始扫描" }));
  await waitFor(() => expect(createPayload).toBeDefined());
  expect(createPayload).toMatchObject({
    scanner_key: "volume_anomaly",
    universe_type: "ALL_ACTIVE_A_SHARES",
    scan_date: "2026-07-22",
  });
  expect(createPayload).not.toHaveProperty("instrument_ids");
  expect(createPayload).not.toHaveProperty("idempotency_key");
  expect(createPayload).toMatchObject({
    parameters: {
      volume_window: 20,
      minimum_volume_ratio: "2",
    },
  });
});

test("扫描运行列表用中文展示全市场范围和任务状态", async () => {
  renderRoute("/scan-runs");
  expect(await screen.findByText(/成交量异常筛选/)).toBeInTheDocument();
  expect(screen.getByText("已完成")).toBeInTheDocument();
  expect(screen.getByText(/总数 5200 · 排除 120/)).toBeInTheDocument();
  expect(screen.getByText("新建全市场扫描")).toBeInTheDocument();
});

test("扫描详情展示股票名称、数据准备统计和中文关键指标", async () => {
  renderRoute(`/scan-runs/${runId}`);
  expect(await screen.findByText("浦发银行（600000.SH）")).toBeInTheDocument();
  expect(screen.getByText(/目录 5200 · 排除 120/)).toBeInTheDocument();
  expect(document.body).toHaveTextContent("放量倍数");
  expect(document.body).toHaveTextContent("3.5");
  expect(document.body).toHaveTextContent("MiniQMT数据时间");
  expect(screen.queryByText(result.instrument_id)).not.toBeInTheDocument();
  expect(screen.queryByText(/幂等键/)).not.toBeInTheDocument();
});

test.each(["/scanners", "/scan-runs", `/scan-runs/${runId}`])(
  "%s 不提供交易动作",
  async (route) => {
    renderRoute(route);
    expect((await screen.findAllByText(/扫描/)).length).toBeGreaterThan(0);
    expect(
      screen.queryByRole("button", {
        name: /买入|卖出|自动交易|下单|创建订单|Broker/,
      }),
    ).not.toBeInTheDocument();
  },
);
