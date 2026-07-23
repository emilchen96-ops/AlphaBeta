import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { healthyCapabilities, healthyStatus, renderRoute } from "./test-utils";

function response(body: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

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
      if (url.endsWith("/system/status")) return response(healthyStatus);
      if (url.endsWith("/system/capabilities"))
        return response(healthyCapabilities);
      if (url.endsWith("/miniqmt/market-data/status"))
        return response({
          schema_version: 1,
          data: {
            configured: true,
            state: "CONNECTED",
            agent: {
              state: "CONNECTED",
              last_market_time: "2026-07-23T02:30:00Z",
              last_received_at: "2026-07-23T02:30:01Z",
              last_minute_bar_time: "2026-07-23T02:29:00Z",
            },
            desired_count: 1,
            active_count: 1,
            failed_count: 0,
            latest_minute_bar_time: "2026-07-23T02:29:00Z",
            source: "MINIQMT",
            market_data_capability: "ENABLED",
            trading_capability: "DISABLED",
            trading_message: "交易功能: 未启用",
          },
        });
      if (url.endsWith("/market-subscriptions/desired"))
        return response({
          schema_version: 1,
          data: {
            version: "internal-version",
            desired_count: 1,
            source_summary: { WATCHLIST: 1 },
            created_at: "2026-07-23T02:00:00Z",
            items: [
              {
                instrument_id: "11111111-1111-4111-8111-111111111111",
                symbol: "600000",
                exchange: "SSE",
                name: "浦发银行",
                provider_symbol: "600000.SH",
                origins: ["WATCHLIST"],
                desired_status: "WAITING",
              },
            ],
          },
        });
      if (url.endsWith("/market-subscriptions/active"))
        return response({
          schema_version: 1,
          data: {
            items: [
              {
                instrument_id: "11111111-1111-4111-8111-111111111111",
                symbol: "600000",
                exchange: "SSE",
                name: "浦发银行",
                provider_symbol: "600000.SH",
                status: "SUBSCRIBED",
                last_market_time: "2026-07-23T02:30:00Z",
                is_test_data: false,
              },
            ],
          },
        });
      if (url.includes("/quotes?"))
        return response({
          schema_version: 1,
          data: {
            items: [
              {
                instrument_id: "11111111-1111-4111-8111-111111111111",
                symbol: "600000",
                exchange: "SSE",
                name: "浦发银行",
                display_name: "浦发银行（600000.SH）",
                market_time: "2026-07-23T02:30:00Z",
                received_at: new Date().toISOString(),
                ingested_at: new Date().toISOString(),
                last_price: "9.01",
                change: "0.01",
                change_percent: "0.1111",
                open_price: "8.92",
                high_price: "9.06",
                low_price: "8.91",
                previous_close: "9.00",
                volume: "213000",
                amount: "191483107",
                bid_price_1: "9.00",
                ask_price_1: "9.01",
                trading_status: "TRADING",
                source: "MINIQMT",
                is_test_data: false,
              },
            ],
          },
        });
      if (
        url.endsWith("/market-subscriptions/rebuild") ||
        url.endsWith("/market-subscriptions/sync")
      )
        return response({ schema_version: 1, data: {} });
      throw new Error(`unhandled ${url}`);
    }),
  );
}

beforeEach(installFetch);
afterEach(() => vi.unstubAllGlobals());

test("shows Chinese read-only status and real MiniQMT quote", async () => {
  renderRoute("/miniqmt-market-data");
  expect(await screen.findByText("MiniQMT 实时行情")).toBeInTheDocument();
  expect(screen.getByText(/交易功能：未启用/)).toBeInTheDocument();
  expect(
    (await screen.findAllByText("浦发银行（600000.SH）")).length,
  ).toBeGreaterThan(0);
  expect(screen.getByText("MiniQMT真实行情")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /下单|撤单|一键交易/ }),
  ).not.toBeInTheDocument();
}, 30_000);

test("subscription tab uses business names and hides internal UUID", async () => {
  const user = userEvent.setup();
  renderRoute("/miniqmt-market-data");
  await user.click(await screen.findByRole("tab", { name: "订阅状态" }));
  expect(
    (await screen.findAllByText("浦发银行（600000.SH）")).length,
  ).toBeGreaterThan(0);
  expect(screen.getByText("盘中监控自选股")).toBeInTheDocument();
  expect(screen.getByText("已订阅")).toBeInTheDocument();
  expect(screen.queryByText(/11111111-1111/)).not.toBeInTheDocument();
  expect(screen.queryByText("internal-version")).not.toBeInTheDocument();
}, 30_000);

test("rebuild and sync controls work without asking for idempotency key", async () => {
  const user = userEvent.setup();
  renderRoute("/miniqmt-market-data");
  await user.click(await screen.findByRole("button", { name: /重新计算订阅/ }));
  await user.click(screen.getByRole("button", { name: /同步订阅/ }));
  expect(screen.queryByLabelText(/幂等键/)).not.toBeInTheDocument();
}, 30_000);
