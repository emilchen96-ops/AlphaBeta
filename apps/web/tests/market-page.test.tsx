import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { healthyStatus, renderRoute } from "./test-utils";

const instrument = {
  id: "11111111-1111-4111-8111-111111111111",
  symbol: "300285",
  exchange: "SZSE",
  market: "CN_A",
  name: "国瓷材料",
  asset_type: "STOCK",
  currency: "CNY",
  lot_size: "100",
  price_tick: "0.01",
  timezone: "Asia/Shanghai",
  is_active: true,
  listed_at: "2012-01-13",
  delisted_at: null,
  lifecycle_status: "ACTIVE",
  updated_at: "2026-07-23T00:00:00Z",
};

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

function installMarketFetch(
  options: {
    bars?: Record<string, unknown>[];
    quoteItems?: Record<string, unknown>[];
  } = {},
) {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string | URL | Request) => {
      const url = requestUrl(input);
      if (url.endsWith("/system/status")) return response(healthyStatus);
      if (url.includes("/instruments?"))
        return response({
          items: [instrument],
          page: 1,
          page_size: 50,
          total: 1,
        });
      if (url.endsWith("/watchlists")) return response([]);
      if (url.endsWith("/miniqmt/market-data/status"))
        return response({
          schema_version: 1,
          data: {
            configured: true,
            state: "CONNECTED",
            agent: {
              state: "CONNECTED",
              catalog_instrument_count: 5300,
              last_market_time: "2026-07-23T06:30:00Z",
            },
            desired_count: 0,
            active_count: 0,
            failed_count: 0,
            latest_minute_bar_time: null,
            source: "MINIQMT",
            market_data_capability: "ENABLED",
            trading_capability: "DISABLED",
            trading_message: "交易能力关闭",
          },
        });
      if (url.endsWith("/market-subscriptions/active"))
        return response({ schema_version: 1, data: { items: [] } });
      if (
        url.endsWith("/market-subscriptions/temporary") ||
        url.endsWith("/market-subscriptions/rebuild") ||
        url.endsWith("/market-subscriptions/sync")
      )
        return response({ schema_version: 1, data: {} });
      if (url.includes("/market-data/bars?"))
        return response({
          source_code: "MINIQMT",
          items: options.bars ?? [],
          freshness: {
            source_code: "MINIQMT",
            freshness_status: "UNKNOWN",
            latest_bar_time: null,
            latest_received_at: null,
            calculated_at: "2026-07-23T00:00:00Z",
          },
        });
      if (url.includes("/market-data/quotes/latest?"))
        return response({
          schema_version: 1,
          items: options.quoteItems ?? [],
          missing_instrument_ids: options.quoteItems?.length
            ? []
            : [instrument.id],
          calculated_at: "2026-07-23T00:00:00Z",
        });
      throw new Error(`unhandled ${url}`);
    }),
  );
}

beforeEach(() => {
  vi.stubGlobal("WebSocket", undefined);
  installMarketFetch();
});
afterEach(() => vi.unstubAllGlobals());

test("行情页合并 MiniQMT 状态、A股目录和K线周期", async () => {
  renderRoute("/market");
  expect(
    await screen.findByRole("heading", { name: "行情" }),
  ).toBeInTheDocument();
  expect(screen.getByText("MiniQMT 行情状态")).toBeInTheDocument();
  expect(screen.getByText("A 股标的目录")).toBeInTheDocument();
  expect(screen.getByText("交易能力：关闭（只读行情）")).toBeInTheDocument();
  expect(screen.getByText("60分钟")).toBeInTheDocument();
  expect(screen.queryByText("免费实时行情")).not.toBeInTheDocument();
});

test("代码或名称搜索由回车和搜索按钮触发", async () => {
  const user = userEvent.setup();
  renderRoute("/market");
  const input = await screen.findByPlaceholderText(
    "输入代码或名称，如 300285、300285.SZ",
  );
  await user.clear(input);
  await user.type(input, "300285");
  fireEvent.keyDown(input, { key: "Enter", code: "Enter" });
  await waitFor(() =>
    expect(
      vi
        .mocked(fetch)
        .mock.calls.some(([request]) =>
          requestUrl(request).includes("keyword=300285"),
        ),
    ).toBe(true),
  );
  expect(await screen.findByText("国瓷材料（300285.SZ）")).toBeInTheDocument();
});

test("选择股票后缺数状态提供 MiniQMT 补数入口", async () => {
  const user = userEvent.setup();
  renderRoute("/market");
  await user.click(await screen.findByText("国瓷材料（300285.SZ）"));
  expect(
    await screen.findByText("该标的尚无 MiniQMT 历史日线"),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "从 MiniQMT 补充历史行情" }),
  ).toBeInTheDocument();
});

test("实时快照缺少昨收时使用上一根日线收盘价计算涨跌", async () => {
  installMarketFetch({
    bars: [
      {
        instrument_id: instrument.id,
        source_code: "MINIQMT",
        timeframe: "DAY_1",
        adjustment_type: "NONE",
        bar_time: "2026-07-22T00:00:00Z",
        open: "8.98",
        high: "9.03",
        low: "8.95",
        close: "9.01",
        volume: "1000",
        amount: "9000",
        quality_status: "NORMAL",
        received_at: "2026-07-22T08:00:00Z",
      },
      {
        instrument_id: instrument.id,
        source_code: "MINIQMT",
        timeframe: "DAY_1",
        adjustment_type: "NONE",
        bar_time: "2026-07-23T00:00:00Z",
        open: "8.92",
        high: "9.06",
        low: "8.91",
        close: "9.05",
        volume: "1200",
        amount: "10800",
        quality_status: "NORMAL",
        received_at: "2026-07-23T08:00:00Z",
      },
    ],
    quoteItems: [
      {
        instrument_id: instrument.id,
        source_code: "MINIQMT",
        symbol: instrument.symbol,
        quote_time: "2026-07-23T07:00:00Z",
        received_at: "2026-07-23T07:00:01Z",
        last_price: "9.05",
        volume: "1200",
        quality_status: "NORMAL",
        revision: 1,
      },
    ],
  });
  renderRoute("/market");
  await userEvent.click(await screen.findByText("国瓷材料（300285.SZ）"));
  expect(await screen.findByText("0.04 / 0.44%")).toBeInTheDocument();
});

test("可以打开新建自选列表对话框", async () => {
  renderRoute("/market");
  await userEvent.click(
    await screen.findByRole("button", { name: "新建自选列表" }),
  );
  expect(screen.getByRole("dialog")).toHaveTextContent("新建自选列表");
});
