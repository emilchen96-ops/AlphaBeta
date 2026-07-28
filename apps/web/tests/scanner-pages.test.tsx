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
const screeningTemplates = [
  {
    template_key: "LIMIT_UP_PULLBACK",
    display_name: "涨停回踩",
    description: "最近涨停后回踩起涨锚点，且成交量缩至涨停日的一半以内",
    spec: {
      schema_version: 1,
      name: "涨停回踩",
      origin: "BUILTIN_TEMPLATE",
      universe_spec: {
        universe_key: "ALL_A_SHARES",
        excluded_instrument_ids: [],
        exclude_st: false,
        exclude_bse: false,
        exclude_star_market: false,
        exclude_chinext: false,
      },
      as_of_date: "2026-07-22",
      timeframe: "DAY_1",
      conditions: [
        {
          condition_key: "LIMIT_UP_PULLBACK",
          condition_version: "1.0.0",
          parameters: {
            lookback_days: 20,
            anchor_tolerance: "0.03",
            minimum_limit_up_completion: "0.98",
            maximum_volume_ratio: "0.50",
          },
        },
      ],
      exclusions: {},
      ranking_rules: [{ field: "score", direction: "DESC" }],
      top_n: null,
      price_adjustment_mode: "RAW",
    },
  },
  {
    template_key: "BOTTOM_VOLUME_EXPANSION",
    display_name: "底部放倍量",
    description: "价格处于60日区间底部，成交量超过20日均量2倍且收阳",
    spec: {
      schema_version: 1,
      name: "底部放倍量",
      origin: "BUILTIN_TEMPLATE",
      universe_spec: {
        universe_key: "ALL_A_SHARES",
        excluded_instrument_ids: [],
        exclude_st: false,
        exclude_bse: false,
        exclude_star_market: false,
        exclude_chinext: false,
      },
      as_of_date: "2026-07-22",
      timeframe: "DAY_1",
      conditions: [
        {
          condition_key: "BOTTOM_VOLUME_EXPANSION",
          condition_version: "1.0.0",
          parameters: {
            range_window: 60,
            bottom_ratio: "0.20",
            volume_window: 20,
            minimum_volume_multiple: "2",
            require_bullish_candle: true,
            exclude_current_from_range: true,
            exclude_current_from_average_volume: true,
          },
        },
      ],
      exclusions: {},
      ranking_rules: [{ field: "volume_multiple", direction: "DESC" }],
      top_n: null,
      price_adjustment_mode: "RAW",
    },
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
const screeningRun = {
  screening_id: runId,
  name: "底部放倍量",
  status: "COMPLETED",
  current_phase: "COMPLETED",
  spec: screeningTemplates[1].spec,
  total_instruments: 5200,
  processed_instruments: 5080,
  ready_instruments: 5080,
  insufficient_data_count: 3,
  indeterminate_count: 2,
  failed_count: 0,
  matched_count: 1,
  progress_percent: 100,
  elapsed_ms: 1234,
  query_count: 3,
  bars_read: 300000,
  batch_count: 11,
  execution_stats: { future_bars_read: 0, no_n_plus_one: true },
  error: null,
  created_at: "2026-07-22T08:00:00Z",
  started_at: "2026-07-22T08:00:00Z",
  completed_at: "2026-07-22T08:00:01Z",
  replayed: false,
};
const screeningResult = {
  result_id: "77777777-7777-4777-8777-777777777777",
  screening_id: runId,
  rank: 1,
  instrument_id: "11111111-1111-4111-8111-111111111111",
  symbol: "600000",
  exchange: "SSE",
  instrument_name: "浦发银行",
  score: "3.5",
  reference_price: "12.34",
  matched_at: "2026-07-22T07:00:00Z",
  reason_code: "BOTTOM_VOLUME_EXPANSION",
  reason: "当前位于此前60日区间底部，成交量为此前20日均量的3.5倍且当日收阳。",
  metrics: { volume_multiple: "3.5", future_bars_read: 0 },
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
      if (url.includes("/screening-templates")) body = screeningTemplates;
      else if (
        url.endsWith("/research/screenings") &&
        init?.method === "POST"
      ) {
        if (typeof init.body !== "string") {
          throw new Error("expected JSON request body");
        }
        createPayload = JSON.parse(init.body) as Record<string, unknown>;
        body = { ...screeningRun, status: "QUEUED", current_phase: "QUEUED" };
        status = 202;
      } else if (url.includes(`/research/screenings/${runId}/progress`))
        body = {
          screening_id: runId,
          status: "COMPLETED",
          total_instruments: 5200,
          processed_instruments: 5080,
          ready_instruments: 5080,
          insufficient_data_count: 3,
          indeterminate_count: 2,
          failed_count: 0,
          matched_count: 1,
          progress_percent: 100,
          elapsed_ms: 1234,
        };
      else if (url.includes(`/research/screenings/${runId}/results`))
        body = {
          items: [screeningResult],
          total: 1,
          page: 1,
          page_size: 100,
        };
      else if (url.endsWith(`/research/screenings/${runId}`))
        body = screeningRun;
      else if (url.includes("/research/screenings?"))
        body = { items: [screeningRun], page: 1, page_size: 20, total: 1 };
      else if (url.includes("/scanners/catalog")) body = catalog;
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

test("SC02-A页面用两个标准模板创建点时全A股筛选并解释结果", async () => {
  renderRoute("/scanners");
  expect(await screen.findByText("涨停回踩")).toBeInTheDocument();
  expect(screen.getAllByText("底部放倍量").length).toBeGreaterThan(0);
  expect(screen.queryByText(/自然语言|AI解析|我的选股方案/)).not.toBeInTheDocument();
  expect(await screen.findByText(/浦发银行（600000.SH）/)).toBeInTheDocument();
  expect(screen.getByText(/成交量为此前20日均量的3.5倍/)).toBeInTheDocument();

  const bottomCard = screen
    .getAllByText("底部放倍量")[0]
    .closest(".ant-card");
  expect(bottomCard).not.toBeNull();
  fireEvent.click(
    within(bottomCard as HTMLElement).getByRole("button", {
      name: /开始筛选/,
    }),
  );
  const dialog = screen.getByRole("dialog");
  expect(within(dialog).getByText("股票范围：当日全部A股")).toBeInTheDocument();
  expect(within(dialog).queryByText(/研究股票池/)).not.toBeInTheDocument();
  expect(within(dialog).queryByText("DAY_1")).not.toBeInTheDocument();

  fireEvent.click(within(dialog).getByRole("button", { name: "开始筛选" }));
  await waitFor(() => expect(createPayload).toBeDefined());
  expect(createPayload).toMatchObject({
    name: "底部放倍量",
    as_of_date: "2026-07-22",
    timeframe: "DAY_1",
    universe_spec: {
      universe_key: "ALL_A_SHARES",
      exclude_st: true,
    },
    conditions: [
      {
        condition_key: "BOTTOM_VOLUME_EXPANSION",
        parameters: { minimum_volume_multiple: "2" },
      },
    ],
  });
  expect(
    (
      createPayload?.conditions as {
        condition_version?: string;
      }[]
    )[0],
  ).not.toHaveProperty("condition_version");
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
    expect((await screen.findAllByText(/扫描|筛选/)).length).toBeGreaterThan(0);
    expect(
      screen.queryByRole("button", {
        name: /买入|卖出|自动交易|下单|创建订单|Broker/,
      }),
    ).not.toBeInTheDocument();
  },
);
