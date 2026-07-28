import { fireEvent, screen, waitFor } from "@testing-library/react";

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
    timeframe: "日线",
    required_data: "MiniQMT历史日线",
    enabled: true,
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
    timeframe: "日线",
    required_data: "MiniQMT历史日线",
    enabled: true,
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
const screeningConditions = [
  {
    condition_key: "LIMIT_UP_PULLBACK",
    display_name: "涨停回踩",
    description: "最近涨停后回踩起涨锚点且成交量显著收缩",
    category: "PATTERN",
    parameter_schema: [
      {
        name: "lookback_days",
        display_name: "回看交易日数",
        type: "integer",
        description: "向前寻找涨停事件的交易日数量",
        default: 20,
        required: true,
        nullable: false,
        min_value: "2",
        max_value: "250",
        enum_values: [],
        unit: "交易日",
      },
      {
        name: "event_selection",
        display_name: "涨停事件选择",
        type: "enum",
        description: "多次涨停时选择最近且数据完整的事件",
        default: "LATEST_VALID",
        required: true,
        nullable: false,
        min_value: null,
        max_value: null,
        enum_values: ["LATEST_VALID"],
        unit: null,
      },
      {
        name: "anchor_price",
        display_name: "起涨价格定义",
        type: "enum",
        description: "涨停前一交易日收盘价",
        default: "PRE_LIMIT_PREVIOUS_CLOSE",
        required: true,
        nullable: false,
        min_value: null,
        max_value: null,
        enum_values: ["PRE_LIMIT_PREVIOUS_CLOSE"],
        unit: null,
      },
      {
        name: "maximum_distance_pct",
        display_name: "回踩距离",
        type: "decimal",
        description: "当前收盘价距离起涨价格的最大比例",
        default: "0.03",
        required: true,
        nullable: false,
        min_value: "0",
        max_value: "1",
        enum_values: [],
        unit: null,
      },
      {
        name: "minimum_price_ratio_to_anchor",
        display_name: "最低保护比例",
        type: "decimal",
        description: "当前价格不得低于起涨价格的比例",
        default: "0.98",
        required: true,
        nullable: false,
        min_value: "0",
        max_value: "2",
        enum_values: [],
        unit: null,
      },
      {
        name: "volume_reference",
        display_name: "成交量参考",
        type: "enum",
        description: "使用涨停日成交量作为参照",
        default: "LIMIT_UP_DAY_VOLUME",
        required: true,
        nullable: false,
        min_value: null,
        max_value: null,
        enum_values: ["LIMIT_UP_DAY_VOLUME"],
        unit: null,
      },
      {
        name: "maximum_volume_ratio",
        display_name: "最大成交量比例",
        type: "decimal",
        description: "当前成交量不得超过涨停日成交量的比例",
        default: "0.50",
        required: true,
        nullable: false,
        min_value: "0",
        max_value: "10",
        enum_values: [],
        unit: null,
      },
    ],
    required_fields: ["open", "high", "low", "close", "volume", "price_limit"],
    required_history_bars: 22,
    supported_timeframes: ["DAY_1"],
    price_adjustment_mode: "RAW",
    version: "1.0.0",
    enabled: true,
  },
];
const naturalSpec = {
  ...screeningTemplates[0].spec,
  name: "自然语言选股：涨停回踩",
  origin: "NATURAL_LANGUAGE",
  conditions: [
    {
      condition_key: "LIMIT_UP_PULLBACK",
      condition_version: "1.0.0",
      parameters: {
        lookback_days: 20,
        event_selection: "LATEST_VALID",
        anchor_price: "PRE_LIMIT_PREVIOUS_CLOSE",
        maximum_distance_pct: "0.03",
        minimum_price_ratio_to_anchor: "0.98",
        volume_reference: "LIMIT_UP_DAY_VOLUME",
        maximum_volume_ratio: "0.50",
      },
    },
  ],
};
const userScreeningId = "88888888-8888-4888-8888-888888888888";
const savedScreening = {
  id: userScreeningId,
  name: "我的涨停回踩",
  description: "浏览器回归方案",
  source_text: "找过去20日涨停后缩量回踩的股票",
  origin: "NATURAL_LANGUAGE",
  current_version: 2,
  status: "ACTIVE",
  screening_spec: naturalSpec,
  summary: "自然语言选股：涨停回踩，共1项标准条件。",
  created_at: "2026-07-20T08:00:00Z",
  updated_at: "2026-07-21T08:00:00Z",
  last_used_at: null,
};
function previewFor(spec = naturalSpec) {
  const lookback = spec.conditions[0].parameters.lookback_days;
  return {
    summary: "自然语言选股：涨停回踩，共1项标准条件。",
    universe: "筛选日期当时存在的全部A股（沪、深、北）。",
    conditions: [
      `过去${lookback}个交易日内出现过涨停。`,
      "当前收盘价距离起涨价格不超过3%。",
      "当前收盘价不低于起涨价格的98%。",
      "当前成交量不超过涨停日成交量的50%。",
    ],
    screening_time: "2026-07-22收盘后（已完成交易日）。",
    ranking: ["按标准条件得分从高到低排序。"],
    defaults: [
      "系统暂按不低于起涨价的98%理解。",
      "系统暂按当前成交量不超过涨停日成交量的50%理解。",
    ],
    data_requirements: [
      "涨停回踩：至少22根日K线；需要开盘价、最高价、最低价、收盘价、成交量。",
    ],
    parser_source: "本地确定性规则",
    no_future_data_rule:
      "只读取筛选日期及以前的本地历史日线，不会读取未来数据。",
    data_ready: true,
    data_readiness_message: "本地历史日线已就绪。",
    can_execute: true,
    notices: [],
  };
}
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
let createRequests = 0;
let lastPreviewLookback: unknown;
let userScreeningItems: unknown[] = [];
let savedScreeningRunRequests = 0;
let savedScreeningRunDate: string | undefined;

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
      if (url.includes("/screening-conditions")) body = screeningConditions;
      else if (
        url.endsWith(`/user-screenings/${userScreeningId}/run`) &&
        init?.method === "POST"
      ) {
        if (typeof init.body !== "string") {
          throw new Error("expected JSON request body");
        }
        savedScreeningRunRequests += 1;
        savedScreeningRunDate = (
          JSON.parse(init.body) as { as_of_date: string }
        ).as_of_date;
        body = { ...screeningRun, status: "QUEUED", current_phase: "QUEUED" };
        status = 202;
      } else if (url.includes("/user-screenings"))
        body = {
          items: userScreeningItems,
          page: 1,
          page_size: 100,
          total: userScreeningItems.length,
        };
      else if (url.includes("/watchlists")) body = [];
      else if (
        url.endsWith("/screening-specs/parse") &&
        init?.method === "POST"
      ) {
        if (typeof init.body !== "string") {
          throw new Error("expected JSON request body");
        }
        const request = JSON.parse(init.body) as { text: string };
        const ambiguous = request.text.includes("低位放量");
        body = {
          parse_status: ambiguous ? "AMBIGUOUS" : "COMPLETE",
          parser_source: "LOCAL_RULES",
          screening_spec: naturalSpec,
          recognized_conditions: [
            {
              condition_key: "LIMIT_UP_PULLBACK",
              display_name: "涨停回踩",
              matched_expression: "涨停回踩与缩量",
            },
          ],
          ambiguities: ambiguous
            ? [
                "系统无法确定“低位”的观察周期和范围，也无法确定“放量”的倍数。请确认以下参数。",
              ]
            : [],
          unsupported_fragments: [],
          defaults_applied: [
            {
              condition_key: "LIMIT_UP_PULLBACK",
              parameter_name: "minimum_price_ratio_to_anchor",
              display_name: "最低保护比例",
              value: "0.98",
              explanation: "系统暂按不低于起涨价的98%理解。",
            },
          ],
          preview: previewFor(),
          can_execute: !ambiguous,
        };
      } else if (
        url.endsWith("/screening-specs/preview") &&
        init?.method === "POST"
      ) {
        if (typeof init.body !== "string") {
          throw new Error("expected JSON request body");
        }
        const request = JSON.parse(init.body) as {
          screening_spec: typeof naturalSpec;
        };
        lastPreviewLookback =
          request.screening_spec.conditions[0].parameters.lookback_days;
        body = {
          screening_spec: request.screening_spec,
          preview: previewFor(request.screening_spec),
          can_execute: true,
        };
      } else if (
        url.endsWith("/screening-specs/validate") &&
        init?.method === "POST"
      ) {
        if (typeof init.body !== "string") {
          throw new Error("expected JSON request body");
        }
        const request = JSON.parse(init.body) as {
          screening_spec: typeof naturalSpec;
        };
        body = {
          valid: true,
          parse_status: "COMPLETE",
          screening_spec: request.screening_spec,
          recognized_conditions: [
            {
              condition_key: "LIMIT_UP_PULLBACK",
              display_name: "涨停回踩",
              matched_expression: "涨停回踩与缩量",
            },
          ],
          preview: previewFor(request.screening_spec),
          can_execute: true,
        };
      } else if (url.includes("/screening-templates"))
        body = screeningTemplates;
      else if (
        url.endsWith("/research/screenings") &&
        init?.method === "POST"
      ) {
        if (typeof init.body !== "string") {
          throw new Error("expected JSON request body");
        }
        createRequests += 1;
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
  createRequests = 0;
  lastPreviewLookback = undefined;
  userScreeningItems = [];
  savedScreeningRunRequests = 0;
  savedScreeningRunDate = undefined;
  vi.stubGlobal("WebSocket", undefined);
  installFetch();
});
afterEach(() => vi.unstubAllGlobals());

test("SC02-B自然语言解析、可视化修改和开始选股形成完整闭环", async () => {
  renderRoute("/scanners");
  expect((await screen.findAllByText("自然语言选股")).length).toBeGreaterThan(
    0,
  );
  fireEvent.change(screen.getByLabelText("选股描述"), {
    target: {
      value:
        "找过去20日涨停过，目前回踩到涨停前收盘价附近3%，并且明显缩量的股票。",
    },
  });
  fireEvent.click(screen.getByRole("button", { name: /解析选股条件/ }));

  expect(await screen.findByText("条件已识别，可以确认")).toBeInTheDocument();
  expect(screen.getByText("中文规则预览")).toBeInTheDocument();
  expect(
    screen.getAllByText(/系统暂按不低于起涨价的98%理解/).length,
  ).toBeGreaterThan(0);
  expect(screen.getByLabelText("回看交易日数")).toHaveValue("20");
  expect(screen.queryByText("lookback_days")).not.toBeInTheDocument();
  expect(screen.queryByText(runId)).not.toBeInTheDocument();

  const lookbackInput = screen.getByLabelText("回看交易日数");
  fireEvent.change(lookbackInput, {
    target: { value: "25" },
  });
  fireEvent.blur(lookbackInput);
  await waitFor(() => expect(lastPreviewLookback).toBe(25));
  await waitFor(() =>
    expect(document.body).toHaveTextContent("过去25个交易日内出现过涨停"),
  );
  fireEvent.change(screen.getByLabelText("回看交易日数"), {
    target: { value: "20" },
  });
  await waitFor(() => expect(lastPreviewLookback).toBe(20));
  await waitFor(() =>
    expect(document.body).toHaveTextContent("过去20个交易日内出现过涨停"),
  );

  const startButton = screen.getByRole("button", { name: /开始选股/ });
  fireEvent.click(startButton);
  fireEvent.click(startButton);
  await waitFor(() => expect(createPayload).toBeDefined());
  expect(createRequests).toBe(1);
  expect(createPayload).toMatchObject({
    name: "自然语言选股：涨停回踩",
    as_of_date: "2026-07-22",
    universe_spec: { universe_key: "ALL_A_SHARES" },
    conditions: [
      {
        condition_key: "LIMIT_UP_PULLBACK",
        parameters: { lookback_days: 20 },
      },
    ],
  });
  expect(createPayload?.idempotency_key).toEqual(
    expect.stringMatching(/^screening:/),
  );
  expect(await screen.findByText(/浦发银行（600000.SH）/)).toBeInTheDocument();
  expect(screen.getByText(/成交量为此前20日均量的3.5倍/)).toBeInTheDocument();
  expect(document.body).not.toHaveTextContent(runId);
  expect(document.body).not.toHaveTextContent("idempotency");
  expect(document.body).not.toHaveTextContent("ScreeningSpec");
});

test("SC02-B模糊描述给出中文修正提示并自动打开编辑器", async () => {
  renderRoute("/scanners");
  expect((await screen.findAllByText("自然语言选股")).length).toBeGreaterThan(
    0,
  );
  fireEvent.change(screen.getByLabelText("选股描述"), {
    target: { value: "找低位放量的股票" },
  });
  fireEvent.click(screen.getByRole("button", { name: /解析选股条件/ }));

  expect(await screen.findByText("需要确认几个参数")).toBeInTheDocument();
  expect(
    screen.getByText(
      "系统无法确定“低位”的观察周期和范围，也无法确定“放量”的倍数。请确认以下参数。",
    ),
  ).toBeInTheDocument();
  expect(screen.getByText("确认或修改条件")).toBeInTheDocument();
  expect(screen.getByLabelText("回看交易日数")).toBeInTheDocument();
});

test("SC02-C从已保存方案确认后按最新交易日关联版本重跑", async () => {
  userScreeningItems = [savedScreening];
  renderRoute("/scanners?tab=mine");

  expect(await screen.findByText("我的涨停回踩")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "再次运行" }));

  expect(await screen.findByText("确认或修改条件")).toBeInTheDocument();
  expect(screen.getByLabelText("筛选日期")).toHaveValue("2026-07-22");
  fireEvent.click(screen.getByRole("button", { name: /开始选股/ }));

  await waitFor(() => expect(savedScreeningRunRequests).toBe(1));
  expect(savedScreeningRunDate).toBe("2026-07-22");
  expect(createRequests).toBe(0);
});

test("旧扫描运行列表入口重定向到统一历史结果", async () => {
  renderRoute("/scan-runs");
  expect(await screen.findByText("历史结果")).toBeInTheDocument();
  expect(screen.getByPlaceholderText("按方案名称筛选")).toBeInTheDocument();
});

test("旧扫描详情入口重定向到统一历史结果", async () => {
  renderRoute(`/scan-runs/${runId}`);
  expect(await screen.findByText("历史结果")).toBeInTheDocument();
  expect(screen.getByPlaceholderText("按方案名称筛选")).toBeInTheDocument();
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
