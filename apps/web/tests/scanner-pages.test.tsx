import { fireEvent, screen } from "@testing-library/react";

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
    parameters: [
      {
        name: "volume_window",
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
  universe_type: "INSTRUMENTS",
  instrument_ids: ["11111111-1111-4111-8111-111111111111"],
  timeframe: "DAY_1",
  as_of: "2026-07-18T07:00:00Z",
  status: "COMPLETED",
  instruments_scanned: 1,
  matches_found: 1,
  started_at: "2026-07-18T08:00:00Z",
  completed_at: "2026-07-18T08:00:01Z",
  failed_at: null,
  error: null,
  correlation_id: "55555555-5555-4555-8555-555555555555",
  created_at: "2026-07-18T08:00:00Z",
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
  matched_at: "2026-07-18T07:00:00Z",
  reference_price: "12.34",
  reason_code: "VOLUME_ANOMALY",
  reason: "当前成交量达到此前历史均量的可配置倍数。",
  metrics: { volume_ratio: "3.5", window: 20 },
  schema_version: 1,
  created_at: "2026-07-18T08:00:01Z",
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
      if (url.includes("/scanners/catalog")) body = catalog;
      else if (url.endsWith(`/scan-runs/${runId}/results`))
        body = { items: [result], total: 1 };
      else if (url.endsWith(`/scan-runs/${runId}`)) body = run;
      else if (url.includes("/scan-runs?"))
        body = { items: [run], page: 1, page_size: 20, total: 1 };
      else if (url.includes("/instruments?"))
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

test("扫描器目录展示安全边界和动态参数", async () => {
  renderRoute("/scanners");
  expect(await screen.findByText("成交量异常放大")).toBeInTheDocument();
  expect(screen.getByText(/扫描结果仅为规则筛选结果/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /创建扫描运行/ }));
  expect(screen.getByText(/volume_window · 历史均量窗口/)).toBeInTheDocument();
  expect(
    screen.getByText(/minimum_volume_ratio · 最小成交量倍数/),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "运行历史日线扫描" }),
  ).toBeEnabled();
});

test("扫描运行列表提供筛选和详情入口", async () => {
  renderRoute("/scan-runs");
  expect(await screen.findByText("volume_anomaly")).toBeInTheDocument();
  expect(screen.getByText("扫描器筛选")).toBeInTheDocument();
  expect(screen.getByText("状态筛选")).toBeInTheDocument();
  expect(screen.getByText(/当前不是实时扫描/)).toBeInTheDocument();
});

test("扫描详情展示结果、指标和跨页面只读链接", async () => {
  renderRoute(`/scan-runs/${runId}`);
  expect(await screen.findByText("600000.SSE · 浦发银行")).toBeInTheDocument();
  expect(screen.getByText("3.5")).toBeInTheDocument();
  expect(screen.getByText(/"volume_ratio": "3.5"/)).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Instrument 与行情" }),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "策略目录" })).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "研究 Signal" }),
  ).toBeInTheDocument();
});

test.each(["/scanners", "/scan-runs", `/scan-runs/${runId}`])(
  "%s 不提供交易动作",
  async (route) => {
    renderRoute(route);
    expect(
      (await screen.findAllByText(/扫描|历史规则/)).length,
    ).toBeGreaterThan(0);
    expect(
      screen.queryByRole("button", {
        name: /买入|卖出|自动交易|下单|创建订单|Broker/,
      }),
    ).not.toBeInTheDocument();
  },
);
