import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { healthyCapabilities, healthyStatus, renderRoute } from "./test-utils";

const runId = "11111111-1111-4111-8111-111111111111";
const instrumentId = "22222222-2222-4222-8222-222222222222";
const timestamps = {
  started_at: "2026-07-19T08:00:00Z",
  completed_at: "2026-07-19T08:01:00Z",
};
const syncRun = {
  id: runId,
  source_id: "33333333-3333-4333-8333-333333333333",
  status: "PARTIALLY_SUCCEEDED",
  timeframe: "DAY_1",
  adjustment_type: "NONE",
  requested_symbols: ["600000", "000001"],
  requested_start: "2026-07-18T00:00:00Z",
  requested_end: "2026-07-18T00:00:00Z",
  ...timestamps,
  total_received: 1,
  total_inserted: 1,
  total_updated: 0,
  total_rejected: 0,
  error_summary: "MARKET_DATA_UPDATE_FAILED",
  correlation_id: "44444444-4444-4444-8444-444444444444",
  metadata: {
    operation: "DAILY_UPDATE",
    up_to_date_instrument_count: 0,
    completed_instrument_count: 1,
    failed_instrument_count: 1,
  },
};
const qualityRun = {
  id: runId,
  universe_key: "research",
  provider: "BAOSTOCK",
  timeframe: "DAY_1",
  status: "COMPLETED",
  instruments_checked: 2,
  bars_checked: 300,
  issues_found: 1,
  error_count: 0,
  warning_count: 1,
  info_count: 0,
  ...timestamps,
  correlation_id: "55555555-5555-4555-8555-555555555555",
  metadata: { issue_types: { INSUFFICIENT_BARS: 1 } },
  created_at: "2026-07-19T08:00:00Z",
  updated_at: "2026-07-19T08:01:00Z",
};
const issue = {
  id: "66666666-6666-4666-8666-666666666666",
  quality_run_id: runId,
  instrument_id: instrumentId,
  issue_type: "INSUFFICIENT_BARS",
  severity: "WARNING",
  timeframe: "DAY_1",
  first_affected_at: "2026-01-01T00:00:00Z",
  last_affected_at: "2026-07-18T00:00:00Z",
  observed_value: "150",
  expected_value: "250",
  message: "日线数量低于受控研究/回测基线。",
  required_action: "扩大历史补数起始范围。",
  metadata: { symbol: "600000" },
  created_at: "2026-07-19T08:01:00Z",
};

function response(body: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status: 200,
      headers: {
        "Content-Type": "application/json",
        "X-Correlation-ID": "market-data-test",
      },
    }),
  );
}

function requestUrl(input: string | URL | Request) {
  return typeof input === "string"
    ? input
    : input instanceof URL
      ? input.href
      : input.url;
}

function requestBody(init?: RequestInit) {
  return typeof init?.body === "string" ? init.body : "";
}

function installFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url = requestUrl(input);
      if (url.endsWith("/system/status")) return response(healthyStatus);
      if (url.endsWith("/system/capabilities"))
        return response(healthyCapabilities);
      if (url.endsWith("/market-data/overview"))
        return response({
          instrument_count: 5000,
          active_a_share_count: 4998,
          research_universe_count: 300,
          market_bar_count: 256408,
          earliest_bar: "2023-01-03T00:00:00Z",
          latest_bar: "2026-07-18T00:00:00Z",
          latest_sync_at: "2026-07-19T08:01:00Z",
          provider: "BAOSTOCK",
          timeframe: "DAY_1",
          adjustment_type: "NONE",
          scanner_ready: true,
          strategy_ready: true,
          backtest_data_ready: true,
          backtest_code_status: "WORKING",
        });
      if (url.endsWith("/market-data/coverage"))
        return response({
          universe_key: "research",
          name: "D01 Research Universe",
          instrument_count: 300,
          instruments_with_data: 300,
          sufficient_instruments: 299,
          insufficient_instruments: 1,
          earliest_bar: "2023-01-03T00:00:00Z",
          latest_bar: "2026-07-18T00:00:00Z",
          latest_sync_at: "2026-07-19T08:01:00Z",
          items: [
            {
              instrument_id: instrumentId,
              symbol: "600000",
              name: "浦发银行",
              exchange: "SSE",
              bar_count: 150,
              earliest_bar: "2026-01-01T00:00:00Z",
              latest_bar: "2026-07-18T00:00:00Z",
              mapping_status: "MAPPED",
              missing_requirements: ["backtest_daily"],
            },
          ],
        });
      if (url.endsWith("/market-data/readiness"))
        return response([
          {
            capability_key: "scanner_volume_anomaly",
            display_name: "放量异常 Scanner",
            status: "READY",
            ready_instrument_count: 300,
            total_instrument_count: 300,
            minimum_bars_required: 21,
            latest_data_date: "2026-07-18",
            blocking_issue_count: 0,
            warning_count: 0,
            reason: "全部研究标的满足最低日线数量。",
            required_action: "无需数据操作。",
            code_status: "WORKING",
          },
          {
            capability_key: "backtest_daily",
            display_name: "日线回测",
            status: "PARTIAL",
            ready_instrument_count: 299,
            total_instrument_count: 300,
            minimum_bars_required: 250,
            latest_data_date: "2026-07-18",
            blocking_issue_count: 0,
            warning_count: 1,
            reason: "299/300 个标的满足最低日线数量。",
            required_action: "先执行日线增量更新, 再运行数据质量检查。",
            code_status: "WORKING",
          },
        ]);
      if (url.endsWith("/market-reference/status"))
        return response({
          calendar_provider: "FIXTURE",
          adjustment_provider: "FIXTURE",
          suspension_provider: "FIXTURE",
          provider_configured: true,
          calendar_sessions: 730,
          open_sessions: 480,
          calendar_start: "2025-01-01",
          calendar_end: "2026-12-31",
          latest_completed_session: "2026-07-21",
          adjustment_factors: 30000,
          adjustment_instruments: 300,
          latest_factor_date: "2026-07-21",
          qfq_ready_instruments: 300,
          trading_statuses: 30000,
          suspended_sessions: 12,
          latest_status_date: "2026-07-21",
          lifecycle_events: 300,
          lifecycle_instruments: 300,
          raw_price_ready: true,
          adjusted_price_ready: true,
          calendar_ready: true,
          suspension_ready: true,
          scanner_ready: true,
          strategy_ready: true,
          backtest_ready: true,
          replay_ready: true,
          warnings: [],
        });
      if (url.includes("/market-data/sync-runs")) return response([syncRun]);
      if (url.includes(`/market-data/quality-runs/${runId}`))
        return response({
          run: qualityRun,
          issues: [issue],
          issue_page: 1,
          issue_page_size: 100,
          issue_total: 1,
          integrity_mismatches: [],
        });
      if (url.includes("/market-data/quality-runs?page="))
        return response({
          items: [qualityRun],
          page: 1,
          page_size: 20,
          total: 1,
        });
      if (url.endsWith("/market-data/quality-runs") && init?.method === "POST")
        return response({
          run: qualityRun,
          issues: [issue],
          issue_page: 1,
          issue_page_size: 1,
          issue_total: 1,
          integrity_mismatches: [],
        });
      if (
        url.endsWith("/market-data/daily-updates") &&
        init?.method === "POST"
      ) {
        const payload = JSON.parse(requestBody(init)) as { dry_run: boolean };
        return response({
          run: payload.dry_run ? null : syncRun,
          target_date: "2026-07-18",
          requested: 30,
          up_to_date: 28,
          completed: payload.dry_run ? 0 : 1,
          failed: payload.dry_run ? 0 : 1,
          unprocessed: payload.dry_run ? 2 : 0,
          bars_fetched: payload.dry_run ? 0 : 1,
          bars_inserted: payload.dry_run ? 0 : 1,
          bars_updated: 0,
          bars_skipped: 0,
          invalid_bars: 0,
          retry_count: 2,
          failures: payload.dry_run
            ? []
            : [{ code: "MARKET_DATA_UPDATE_FAILED" }],
          plans: [],
          dry_run: payload.dry_run,
          idempotent_replay: false,
        });
      }
      return response({});
    }),
  );
}

beforeEach(() => {
  vi.stubGlobal("WebSocket", undefined);
  installFetch();
});
afterEach(() => vi.unstubAllGlobals());

test("数据中心展示真实后端五区、覆盖不足和安全边界", async () => {
  renderRoute("/market-data-center");
  expect(await screen.findByText("历史行情数据中心")).toBeInTheDocument();
  expect(screen.getByText("1. 数据总览")).toBeInTheDocument();
  expect(screen.getByText("2. 市场参考数据与价格语义")).toBeInTheDocument();
  expect(screen.getByText("3. Universe 覆盖情况")).toBeInTheDocument();
  expect(screen.getByText("4. 同步运行与每日更新")).toBeInTheDocument();
  expect(screen.getByText("5. 数据质量")).toBeInTheDocument();
  expect(screen.getByText("6. 功能可用性")).toBeInTheDocument();
  expect(await screen.findByText("浦发银行")).toBeInTheDocument();
  expect(screen.getByText("backtest_daily")).toBeInTheDocument();
  expect(screen.getByText("BT01 日线回测代码已完成")).toBeInTheDocument();
  expect(
    screen.getByText(/不提供实时行情，也不连接 MiniQMT/),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /编辑K线|删除K线|补0/ }),
  ).not.toBeInTheDocument();
}, 30_000);

test("dry-run 与实际更新提交受保护并准确显示部分失败", async () => {
  renderRoute("/market-data-center");
  const dryRun = await screen.findByRole("button", { name: "Dry-run 预览" });
  fireEvent.click(dryRun);
  expect(await screen.findByText("更新预览")).toBeInTheDocument();
  const calls = vi.mocked(fetch).mock.calls;
  const dryCall = calls.find(
    ([input, init]) =>
      requestUrl(input).includes("daily-updates") &&
      requestBody(init).includes('"dry_run":true'),
  );
  expect(dryCall).toBeDefined();

  fireEvent.click(screen.getByRole("button", { name: /更新到最新日线/ }));
  expect(await screen.findByText("部分失败")).toBeInTheDocument();
  expect(screen.getByText(/失败 1，新增 1/)).toBeInTheDocument();
}, 35_000);

test("质量检查与 Issue type 筛选请求均由后端驱动", async () => {
  const user = userEvent.setup();
  renderRoute("/market-data-center");
  await user.click(
    await screen.findByRole("button", { name: /执行数据质量检查/ }),
  );
  await waitFor(() =>
    expect(
      vi
        .mocked(fetch)
        .mock.calls.some(
          ([input, init]) =>
            requestUrl(input).endsWith("/market-data/quality-runs") &&
            init?.method === "POST",
        ),
    ).toBe(true),
  );
  fireEvent.change(screen.getByPlaceholderText("Issue type"), {
    target: { value: "STALE_DATA" },
  });
  await waitFor(() =>
    expect(
      vi
        .mocked(fetch)
        .mock.calls.some(([input]) =>
          requestUrl(input).includes("issue_type=STALE_DATA"),
        ),
    ).toBe(true),
  );
}, 30_000);
