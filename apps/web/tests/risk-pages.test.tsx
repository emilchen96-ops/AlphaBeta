import { fireEvent, screen, waitFor } from "@testing-library/react";

import { healthyStatus, renderRoute } from "./test-utils";

const account = {
  id: "11111111-1111-4111-8111-111111111111",
  account_code: "SIM-1",
  name: "模拟账户",
};
const instrument = {
  id: "22222222-2222-4222-8222-222222222222",
  symbol: "600000",
  exchange: "SSE",
  name: "浦发银行",
};
const base = {
  id: "33333333-3333-4333-8333-333333333333",
  request_id: "44444444-4444-4444-8444-444444444444",
  source_type: "MANUAL_ORDER",
  source_id: null,
  account_id: account.id,
  instrument_id: instrument.id,
  account: { id: account.id, code: account.account_code, name: account.name },
  instrument: {
    id: instrument.id,
    symbol: instrument.symbol,
    exchange: instrument.exchange,
    name: instrument.name,
  },
  overall_decision: "ALLOW",
  side: "BUY",
  order_type: "LIMIT",
  quantity: "100.00000000",
  estimated_notional: "1000.00",
  projected_instrument_weight: "0.01000000",
  projected_total_exposure: "0.01000000",
  limits_snapshot: { max_order_notional: "1000000" },
  account_snapshot: { cash_available: "100000.00", position_count: 0 },
  instrument_snapshot: { lot_size: "100", price_tick: "0.01" },
  warnings: [],
  risk_rule_summary: [],
  order_id: "55555555-5555-4555-8555-555555555555",
  correlation_id: "66666666-6666-4666-8666-666666666666",
  evaluated_at: "2026-07-17T00:00:00Z",
  rule_results: [
    {
      id: "77777777-7777-4777-8777-777777777777",
      seq: 1,
      rule_key: "account_eligibility",
      decision: "ALLOW",
      reason_code: "RISK_RULE_PASSED",
      message: "rule passed",
      severity: "INFO",
      observed_value: "ACTIVE",
      limit_value: "ACTIVE",
      evaluated_at: "2026-07-17T00:00:00Z",
    },
  ],
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
      if (url.includes("/api/v1/accounts?"))
        body = { items: [account], page: 1, page_size: 100, total: 1 };
      else if (url.includes("/api/v1/instruments?"))
        body = { items: [instrument], page: 1, page_size: 50, total: 1 };
      else if (url.includes(`/api/v1/risk-decisions/${base.id}`)) body = base;
      else if (url.includes("/api/v1/risk-decisions?"))
        body = {
          items: [
            base,
            {
              ...base,
              id: "88888888-8888-4888-8888-888888888888",
              overall_decision: "REJECT",
              order_id: null,
            },
            {
              ...base,
              id: "99999999-9999-4999-8999-999999999999",
              overall_decision: "REQUIRE_CONFIRMATION",
              order_id: null,
            },
          ],
          page: 1,
          page_size: 20,
          total: 3,
        };
      else if (url.includes("/api/v1/risk-limits/active"))
        body = {
          max_order_notional: "1000000",
          max_instrument_weight: null,
          max_total_exposure: "1",
          max_orders_per_window: 20,
          order_frequency_window_seconds: 60,
          allow_market_orders: false,
          require_reference_price_for_market_order: true,
          kill_switch_enabled: true,
          configuration_source: "服务端权威配置",
          effective_at: "2026-07-17T00:00:00Z",
          warnings: [],
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

test("风控列表展示三态文案并支持筛选与详情入口", async () => {
  renderRoute("/risk/decisions");
  expect(
    await screen.findByRole("heading", { name: "风控决策" }),
  ).toBeInTheDocument();
  expect(await screen.findAllByText("风控通过")).not.toHaveLength(0);
  expect(await screen.findByText("风控拒绝")).toBeInTheDocument();
  expect(await screen.findByText("需要人工复核")).toBeInTheDocument();
  fireEvent.mouseDown(screen.getByLabelText("决策结果"));
  fireEvent.click(
    await screen.findByText("风控拒绝", {
      selector: ".ant-select-item-option-content",
    }),
  );
  await waitFor(() => expect(fetch).toHaveBeenCalled());
  expect(
    screen.queryByRole("button", { name: /跳过风控/ }),
  ).not.toBeInTheDocument();
});

test("风控详情展示规则、快照、限制与订单跳转", async () => {
  renderRoute(`/risk/decisions/${base.id}`);
  expect(
    await screen.findByRole("heading", { name: "风控决策详情" }),
  ).toBeInTheDocument();
  expect(await screen.findByText("account_eligibility")).toBeInTheDocument();
  expect(screen.getByText(/实际使用的风险限制/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /查看关联订单/ })).toHaveAttribute(
    "href",
    `/orders?order_id=${base.order_id}`,
  );
});

test("限制页只读并在紧急停止开关开启时告警", async () => {
  renderRoute("/risk/limits");
  expect(
    await screen.findByRole("heading", { name: "当前风控限制" }),
  ).toBeInTheDocument();
  expect(
    await screen.findByText("紧急停止开关（Kill Switch）已开启"),
  ).toBeInTheDocument();
  expect(screen.getByText(/不允许通过浏览器修改风控限制/)).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /开启|关闭|保存/ }),
  ).not.toBeInTheDocument();
  expect(screen.getByText("未配置限制")).toBeInTheDocument();
});
