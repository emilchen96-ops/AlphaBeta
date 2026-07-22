import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { healthyStatus, renderRoute } from "./test-utils";

const account = {
  id: "11111111-1111-4111-8111-111111111111",
  account_code: "DEMO-001",
  name: "Demo",
};
const instrument = {
  id: "22222222-2222-4222-8222-222222222222",
  symbol: "600000",
  exchange: "SSE",
  name: "浦发银行",
};
const order = {
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
  requested_quantity: "200",
  limit_price: "10.00",
  estimated_notional: "2000.00",
  status: "QUEUED",
  intent_source: "MANUAL",
  row_version: 3,
  confirmation_required: false,
  correlation_id: "44444444-4444-4444-8444-444444444444",
  expires_at: null,
  confirmed_at: "2026-07-18T00:00:00Z",
  cancelled_at: null,
  expired_at: null,
  created_at: "2026-07-18T00:00:00Z",
  updated_at: "2026-07-18T00:00:00Z",
  capabilities: { can_confirm: false, can_cancel: false },
  warnings: [],
  actions: [],
  commands: [{ status: "PENDING" }],
  outbox: [{ status: "PENDING" }],
  risk_decision_id: null,
  risk_decision: "PASS",
  risk_evaluated_at: "2026-07-18T00:00:00Z",
  risk_rule_summary: [],
};
const fill = {
  fill_id: "55555555-5555-4555-8555-555555555555",
  execution_attempt_id: "66666666-6666-4666-8666-666666666666",
  order_id: order.id,
  account: { id: account.id, code: "DEMO-001", name: "Demo" },
  instrument,
  side: "BUY",
  quantity: "100",
  price: "9.99",
  gross_amount: "999.00",
  commission: "5.00",
  stamp_duty: "0.00",
  transfer_fee: "0.02",
  other_fee: "0.00",
  total_fee: "5.02",
  net_cash_effect: "-1004.02",
  executed_at: "2026-07-18T01:00:00Z",
  execution_reference: "SIMULATED:attempt:1",
  correlation_id: order.correlation_id,
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
      if (url.includes("/api/v1/accounts?"))
        body = { items: [account], total: 1, page: 1, page_size: 100 };
      else if (url.includes("/api/v1/instruments?"))
        body = { items: [instrument], total: 1, page: 1, page_size: 50 };
      else if (url.includes("/execution-attempts"))
        body = { items: [], total: 0, page: 1, page_size: 100 };
      else if (url.includes(`/orders/${order.id}/fills`))
        body = { items: [fill], total: 1, page: 1, page_size: 100 };
      else if (url.includes(`/orders/${order.id}/timeline`)) body = [];
      else if (url.endsWith(`/orders/${order.id}`)) body = order;
      else if (url.includes("/api/v1/orders?"))
        body = { items: [order], total: 1, page: 1, page_size: 20 };
      else if (
        url.includes("/simulated-executions") &&
        init?.method === "POST"
      ) {
        body = {
          execution_attempt_id: fill.execution_attempt_id,
          order_id: order.id,
          order_status: "PARTIALLY_FILLED",
          result_status: "PARTIALLY_FILLED",
          requested_quantity: "200",
          previously_filled_quantity: "0",
          attempted_quantity: "200",
          filled_quantity: "100",
          remaining_quantity: "100",
          average_fill_price: "9.99",
          fill_ids: [fill.fill_id],
          total_fee: "5.02",
          rejection_code: null,
          message: "partially filled",
          warnings: [],
          correlation_id: order.correlation_id,
          idempotent: false,
        };
      } else if (url.includes("/api/v1/fills?"))
        body = { items: [fill], total: 1, page: 1, page_size: 20 };
      else if (url.endsWith(`/fills/${fill.fill_id}`)) body = fill;
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

test("QUEUED 订单显示模拟执行入口、边界警告和二次确认", async () => {
  installFetch();
  renderRoute("/orders");
  await userEvent.click(
    await screen.findByRole("button", { name: "模拟执行" }),
  );
  expect(screen.getByRole("dialog")).toHaveTextContent("仅限本地模拟成交");
  expect(
    screen.getByText(/不连接真实行情、券商或 MiniQMT/),
  ).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "检查并继续" }));
  expect(
    (await screen.findAllByText("确认执行本地模拟成交？")).length,
  ).toBeGreaterThan(0);
  expect(
    screen.queryByRole("button", { name: /实盘|真实下单|MiniQMT/ }),
  ).not.toBeInTheDocument();
});

test("成交记录页面只读展示费用拆分", async () => {
  renderRoute("/fills");
  expect(
    await screen.findByRole(
      "heading",
      { name: "成交记录" },
      { timeout: 10_000 },
    ),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/不能创建、编辑、删除或强制记账/),
  ).toBeInTheDocument();
  fireEvent.click(await screen.findByText(fill.fill_id));
  expect(await screen.findByText("成交详情（Fill，只读）")).toBeInTheDocument();
  expect(
    await screen.findByText("印花税", {}, { timeout: 10_000 }),
  ).toBeInTheDocument();
  expect(
    await screen.findByText("过户费", {}, { timeout: 10_000 }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /创建 Fill|删除 Fill|强制记账/ }),
  ).not.toBeInTheDocument();
});
