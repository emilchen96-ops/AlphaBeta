import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { healthyStatus, renderRoute } from "./test-utils";

const instrumentId = "22222222-2222-4222-8222-222222222222";

function response(body: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
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

function installFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url = requestUrl(input);
      if (url.endsWith("/system/status")) return response(healthyStatus);
      if (url.endsWith("/miniqmt/market-data/status"))
        return response({
          schema_version: 1,
          data: {
            configured: true,
            state: "CONNECTED",
            agent: {
              state: "CONNECTED",
              catalog_instrument_count: 5300,
              last_catalog_sync_at: "2026-07-23T01:00:00Z",
            },
            desired_count: 1,
            active_count: 1,
            failed_count: 0,
            latest_minute_bar_time: "2026-07-23T06:29:00Z",
            source: "MINIQMT",
            market_data_capability: "ENABLED",
            trading_capability: "DISABLED",
            trading_message: "交易能力关闭",
          },
        });
      if (url.includes("/instruments?"))
        return response({
          items: [
            {
              id: instrumentId,
              symbol: "600000",
              exchange: "SSE",
              market: "CN_A",
              name: "浦发银行",
              asset_type: "STOCK",
              currency: "CNY",
              lot_size: "100",
              price_tick: "0.01",
              timezone: "Asia/Shanghai",
              is_active: true,
              listed_at: "1999-11-10",
              delisted_at: null,
              lifecycle_status: "ACTIVE",
              updated_at: "2026-07-23T00:00:00Z",
            },
          ],
          page: 1,
          page_size: 50,
          total: 1,
        });
      if (url.endsWith("/market-data/overview"))
        return response({
          instrument_count: 5300,
          active_a_share_count: 5100,
          research_universe_count: 1,
          market_bar_count: 1000,
          earliest_bar: "2020-01-01T00:00:00Z",
          latest_bar: "2026-07-22T00:00:00Z",
          latest_sync_at: "2026-07-23T00:00:00Z",
          provider: "MINIQMT",
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
          name: "研究股票池",
          instrument_count: 1,
          instruments_with_data: 1,
          sufficient_instruments: 1,
          insufficient_instruments: 0,
          earliest_bar: "2020-01-01T00:00:00Z",
          latest_bar: "2026-07-22T00:00:00Z",
          latest_sync_at: "2026-07-23T00:00:00Z",
          items: [
            {
              instrument_id: instrumentId,
              symbol: "600000",
              name: "浦发银行",
              exchange: "SSE",
              bar_count: 1000,
              earliest_bar: "2020-01-01T00:00:00Z",
              latest_bar: "2026-07-22T00:00:00Z",
              mapping_status: "MAPPED",
              missing_requirements: [],
            },
          ],
        });
      if (url.endsWith("/market-data/readiness"))
        return response([
          {
            capability_key: "backtest_daily",
            display_name: "日线回测",
            status: "READY",
            ready_instrument_count: 1,
            total_instrument_count: 1,
            minimum_bars_required: 250,
            latest_data_date: "2026-07-22",
            blocking_issue_count: 0,
            warning_count: 0,
            reason: "数据可用",
            required_action: "无需操作",
            code_status: "WORKING",
          },
        ]);
      if (url.endsWith("/intraday/coverage"))
        return response({
          items: [
            {
              timeframe: "MINUTE_1",
              instrument_count: 1,
              bar_count: 240,
              earliest_at: "2026-07-22T01:30:00Z",
              latest_at: "2026-07-22T07:00:00Z",
              expected_bar_count: 240,
              missing_bar_count: 0,
              complete_session_count: 1,
              missing_session_count: 0,
              raw_coverage: 240,
              qfq_coverage: 0,
              quality_error_count: 0,
              latest_import_at: "2026-07-22T07:00:00Z",
              source_code: "MINIQMT",
            },
          ],
        });
      if (url.endsWith("/intraday/readiness"))
        return response({
          items: [
            {
              capability_key: "intraday_5m_ready",
              timeframe: "MINUTE_5",
              status: "READY",
              required_action: "无需操作",
            },
          ],
        });
      if (url.endsWith("/intraday/imports")) return response({ items: [] });
      if (url.endsWith("/intraday/quality-runs"))
        return response({ items: [], total: 0 });
      if (url.includes("/market-data/quality-runs?page="))
        return response({ items: [], page: 1, page_size: 20, total: 0 });
      if (url.endsWith("/market-reference/status"))
        return response({
          open_sessions: 500,
          adjustment_factors: 1000,
          trading_statuses: 1000,
          lifecycle_events: 5300,
        });
      if (url.includes("/market-data/sync-runs")) return response([]);
      if (url.includes("/market-data/bars?"))
        return response({
          source_code: "MINIQMT",
          items: [],
          freshness: {
            source_code: "MINIQMT",
            freshness_status: "UNKNOWN",
            latest_bar_time: null,
            latest_received_at: null,
            calculated_at: "2026-07-23T00:00:00Z",
          },
        });
      if (url.endsWith("/miniqmt/history/backfill") && init?.method === "POST")
        return response({
          schema_version: 1,
          data: {
            request_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            status: "QUEUED",
            provider: "MINIQMT",
          },
        });
      if (url.endsWith("/market-data/quality-runs") && init?.method === "POST")
        return response({
          run: {},
          issues: [],
          issue_page: 1,
          issue_page_size: 100,
          issue_total: 0,
          integrity_mismatches: [],
        });
      throw new Error(`unhandled ${url}`);
    }),
  );
}

beforeEach(installFetch);
afterEach(() => vi.unstubAllGlobals());

test("数据中心只展示 MiniQMT 正式数据并合并日线和分钟线", async () => {
  renderRoute("/market-data-center");
  expect(
    await screen.findByRole("heading", { name: "数据中心" }),
  ).toBeInTheDocument();
  expect(screen.getByText("正式行情数据源：MiniQMT")).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "日线行情" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "分钟行情" })).toBeInTheDocument();
  expect(
    screen.queryByText(/BaoStock 历史行情：已启用/),
  ).not.toBeInTheDocument();
});

test("数据中心从 MiniQMT 发起历史补数", async () => {
  const user = userEvent.setup();
  renderRoute("/market-data-center");
  const button = await screen.findByRole("button", {
    name: /从 MiniQMT 补充历史行情/,
  });
  await waitFor(() => expect(button).toBeEnabled());
  await user.click(button);
  await waitFor(() =>
    expect(
      vi
        .mocked(fetch)
        .mock.calls.some(
          ([request, init]) =>
            requestUrl(request).endsWith("/miniqmt/history/backfill") &&
            init?.method === "POST" &&
            typeof init.body === "string" &&
            init.body.includes('"timeframe":"DAY_1"'),
        ),
    ).toBe(true),
  );
});

test("旧分钟入口跳转到统一数据中心分钟页签", async () => {
  renderRoute("/intraday-market-data");
  expect(
    await screen.findByRole("heading", { name: "数据中心" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("tab", { name: "分钟行情", selected: true }),
  ).toBeInTheDocument();
  expect(await screen.findByText("5分钟行情研究")).toBeInTheDocument();
  expect(screen.getAllByText("5分钟").length).toBeGreaterThan(0);
  expect(screen.getByText("就绪")).toBeInTheDocument();
  expect(screen.queryByText("intraday_5m_ready")).not.toBeInTheDocument();
});
