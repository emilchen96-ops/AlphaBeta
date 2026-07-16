import { fireEvent, screen, waitFor } from "@testing-library/react";

import { healthyStatus, renderRoute } from "./test-utils";

const account = {
  id: "11111111-1111-4111-8111-111111111111",
  account_code: "DEMO-001",
  name: "M04 Demo Account",
  status: "ACTIVE",
  broker_type: "SIMULATED",
  base_currency: "CNY",
  settlement_policy: "IMMEDIATE",
  created_at: "2026-07-16T00:00:00Z",
  updated_at: "2026-07-16T00:00:00Z",
};

const instrument = {
  id: "22222222-2222-4222-8222-222222222222",
  symbol: "600000",
  exchange: "SSE",
  market: "CN",
  name: "浦发银行",
  asset_type: "EQUITY",
  currency: "CNY",
  lot_size: "100",
  price_tick: "0.01",
  timezone: "Asia/Shanghai",
  is_active: true,
  updated_at: "2026-07-16T00:00:00Z",
};

const waitingOrder = {
  id: "33333333-3333-4333-8333-333333333333",
  account_id: account.id,
  account_name: account.name,
  instrument_id: instrument.id,
  symbol: instrument.symbol,
  exchange: instrument.exchange,
  instrument_name: instrument.name,
  side: "BUY",
  order_type: "LIMIT",
  time_in_force: "DAY",
  requested_quantity: "1000.00000000",
  limit_price: "12.34000000",
  estimated_notional: "12340.00",
  status: "WAITING_CONFIRMATION",
  intent_source: "MANUAL",
  row_version: 2,
  confirmation_required: true,
  correlation_id: "44444444-4444-4444-8444-444444444444",
  expires_at: null,
  confirmed_at: null,
  cancelled_at: null,
  expired_at: null,
  created_at: "2026-07-16T00:00:00Z",
  updated_at: "2026-07-16T00:00:00Z",
  capabilities: { can_confirm: true, can_cancel: true },
  warnings: [],
  actions: [],
  commands: [],
  outbox: [],
};

function installFetch() {
  const fetchMock = vi.fn(
    (input: string | URL | Request, init?: RequestInit) => {
      const url =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : input.url;
      let body: unknown = healthyStatus;
      if (url.includes("/api/v1/accounts?")) {
        body = { items: [account], page: 1, page_size: 100, total: 1 };
      } else if (url.includes("/api/v1/instruments?")) {
        body = { items: [instrument], page: 1, page_size: 50, total: 1 };
      } else if (url.includes(`/orders/${waitingOrder.id}/timeline`)) {
        body = [
          {
            kind: "TRANSITION",
            label: "CREATED -> WAITING_CONFIRMATION",
            actor_type: "LOCAL_USER",
            actor_id: null,
            reason: null,
            order_version: 2,
            occurred_at: waitingOrder.created_at,
            correlation_id: waitingOrder.correlation_id,
          },
        ];
      } else if (url.includes(`/orders/${waitingOrder.id}/confirm`)) {
        body = {
          ...waitingOrder,
          status: "QUEUED",
          row_version: 3,
          capabilities: { can_confirm: false, can_cancel: false },
          actions: [{ action_type: "CONFIRM" }],
          commands: [{ status: "PENDING" }],
          outbox: [{ status: "PENDING" }],
        };
      } else if (url.includes(`/orders/${waitingOrder.id}/cancel`)) {
        body = { ...waitingOrder, status: "CANCELLED", row_version: 3 };
      } else if (url.endsWith(`/orders/${waitingOrder.id}`)) {
        body = waitingOrder;
      } else if (url.includes("/api/v1/orders?")) {
        body = { items: [waitingOrder], page: 1, page_size: 20, total: 1 };
      } else if (url.endsWith("/api/v1/orders") && init?.method === "POST") {
        body = waitingOrder;
      }
      return Promise.resolve(
        new Response(JSON.stringify(body), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    },
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

beforeEach(() => {
  vi.stubGlobal("WebSocket", undefined);
  installFetch();
});

afterEach(() => vi.unstubAllGlobals());

test("订单中心展示事实状态和安全边界", async () => {
  renderRoute("/orders");
  expect(
    await screen.findByRole("heading", { name: "订单中心" }),
  ).toBeInTheDocument();
  expect(await screen.findByText(/等待.*人工.*确认/)).toBeInTheDocument();
  expect(
    screen.getByText(/不会连接执行器、券商或产生成交/),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /实盘|强制成交|自动交易/ }),
  ).not.toBeInTheDocument();
});

test("可以打开创建表单且明确提示 MARKET 无法估算", async () => {
  renderRoute("/orders");
  fireEvent.click(await screen.findByRole("button", { name: /创建订单/ }));
  expect(await screen.findByText("创建人工订单意图")).toBeInTheDocument();
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  expect(screen.getByText(/MARKET 无法估算成交金额/)).toBeInTheDocument();
});

test("人工确认必须经过说明弹窗并携带当前版本", async () => {
  const fetchMock = installFetch();
  renderRoute("/orders");
  fireEvent.click(await screen.findByRole("button", { name: "人工确认" }));
  expect(
    screen.getByText(/OrderCommand PENDING 与 Outbox PENDING/),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /确认（不发送）/ }));
  await waitFor(() => {
    const call = fetchMock.mock.calls.find(([url]) => {
      const address =
        typeof url === "string" ? url : url instanceof URL ? url.href : url.url;
      return address.includes("/confirm");
    });
    expect(call).toBeDefined();
    const body = call?.[1]?.body;
    expect(typeof body === "string" ? body : "").toContain(
      '"expected_order_version":2',
    );
  });
});

test("取消动作使用当前 row_version", async () => {
  const fetchMock = installFetch();
  renderRoute("/orders");
  fireEvent.click(await screen.findByRole("button", { name: /取\s*消/ }));
  await waitFor(() => {
    const call = fetchMock.mock.calls.find(([url]) => {
      const address =
        typeof url === "string" ? url : url instanceof URL ? url.href : url.url;
      return address.includes("/cancel");
    });
    const body = call?.[1]?.body;
    expect(typeof body === "string" ? body : "").toContain(
      '"expected_order_version":2',
    );
  });
});
