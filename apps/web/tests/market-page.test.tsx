import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { healthyStatus, renderRoute } from "./test-utils";

const instrument = {
  id: "11111111-1111-4111-8111-111111111111",
  symbol: "600000",
  exchange: "SSE",
  market: "CN_A",
  name: "浦发银行(演示)",
  asset_type: "EQUITY",
  currency: "CNY",
  lot_size: "100",
  price_tick: "0.01",
  timezone: "Asia/Shanghai",
  is_active: true,
  updated_at: "2026-07-15T00:00:00Z",
};

function installMarketFetch() {
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
      if (url.includes("/instruments"))
        body = { items: [instrument], page: 1, page_size: 50, total: 1 };
      if (url.endsWith("/watchlists"))
        body = [
          {
            id: "w1",
            name: "核心观察",
            description: null,
            created_at: "2026-07-15T00:00:00Z",
            updated_at: "2026-07-15T00:00:00Z",
          },
        ];
      if (url.includes("/watchlists/w1"))
        body = {
          id: "w1",
          name: "核心观察",
          description: null,
          created_at: "2026-07-15T00:00:00Z",
          updated_at: "2026-07-15T00:00:00Z",
          items: [],
        };
      if (url.includes("/market-data/sources"))
        body = [
          {
            id: "s1",
            source_code: "DEMO",
            name: "Demo",
            status: "ACTIVE",
            priority: 0,
            supports_realtime: false,
            supported_timeframes: ["DAY_1", "MINUTE_1"],
            updated_at: "2026-07-15T00:00:00Z",
          },
        ];
      if (url.includes("/market-data/bars"))
        body = {
          source_code: "DEMO",
          items: [],
          freshness: {
            source_code: "DEMO",
            freshness_status: "UNKNOWN",
            latest_bar_time: null,
            latest_received_at: null,
            calculated_at: "2026-07-15T00:00:00Z",
          },
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
  installMarketFetch();
});

afterEach(() => vi.unstubAllGlobals());

test("行情路由显示完整工作台", async () => {
  renderRoute("/market");
  expect(
    await screen.findByRole("heading", { name: "行情" }),
  ).toBeInTheDocument();
  expect(screen.getByText("自选列表")).toBeInTheDocument();
  expect(screen.getByText("标的目录")).toBeInTheDocument();
});

test("展示 DEMO 行情源状态", async () => {
  renderRoute("/market");
  expect(await screen.findByText("DEMO · ACTIVE")).toBeInTheDocument();
});

test("标的目录展示代码和名称", async () => {
  renderRoute("/market");
  expect(await screen.findByText("600000 浦发银行(演示)")).toBeInTheDocument();
});

test("可以打开新建自选列表对话框", async () => {
  renderRoute("/market");
  await userEvent.click(
    await screen.findByRole("button", { name: "新建自选列表" }),
  );
  expect(screen.getByRole("dialog")).toHaveTextContent("新建自选列表");
});

test("未选择标的时显示引导空状态", async () => {
  renderRoute("/market");
  expect(await screen.findByText("选择一个标的查看行情")).toBeInTheDocument();
});
