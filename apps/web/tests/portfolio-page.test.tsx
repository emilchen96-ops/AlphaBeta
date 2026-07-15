import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { healthyStatus, renderRoute } from "./test-utils";

const account = {
  id: "11111111-1111-4111-8111-111111111111",
  account_code: "DEMO-001",
  name: "M04 Demo Account",
  status: "ACTIVE",
  broker_type: "SIMULATED",
  base_currency: "CNY",
  settlement_policy: "IMMEDIATE",
  created_at: "2026-07-15T00:00:00Z",
  updated_at: "2026-07-15T00:00:00Z",
};

const balance = {
  id: "22222222-2222-4222-8222-222222222222",
  account_id: account.id,
  currency: "CNY",
  total_cash: "92939.84",
  available_cash: "92939.84",
  frozen_cash: "0",
  row_version: 4,
  as_of: "2026-07-15T00:00:00Z",
};

const snapshot = {
  id: "33333333-3333-4333-8333-333333333333",
  account_id: account.id,
  as_of: "2026-07-15T00:00:00Z",
  cash_total: "92939.84",
  cash_available: "92939.84",
  cash_frozen: "0",
  positions_cost_basis: "7326",
  positions_market_value: "7380",
  total_equity: "100319.84",
  realized_pnl: "265.84",
  unrealized_pnl: "54",
  valuation_status: "COMPLETE",
  priced_position_count: 1,
  unpriced_position_count: 0,
  latest_price_time: "2026-01-01T00:00:00Z",
  metadata: {},
};

function installPortfolioFetch(options?: {
  empty?: boolean;
  partial?: boolean;
}) {
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
      if (url.includes("/api/v1/accounts?") && !url.includes(account.id)) {
        body = {
          items: options?.empty ? [] : [account],
          page: 1,
          page_size: 100,
          total: options?.empty ? 0 : 1,
        };
      } else if (url.endsWith(`/accounts/${account.id}/summary`)) {
        body = {
          account,
          cash_balances: [balance],
          positions: [],
          latest_snapshot: {
            ...snapshot,
            valuation_status: options?.partial ? "PARTIAL" : "COMPLETE",
            total_equity: options?.partial ? null : snapshot.total_equity,
            unrealized_pnl: options?.partial ? null : snapshot.unrealized_pnl,
          },
          latest_reconciliation: null,
        };
      } else if (url.includes(`/accounts/${account.id}/`)) {
        body = { items: [], page: 1, page_size: 100, total: 0 };
      }
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
  installPortfolioFetch();
});

afterEach(() => vi.unstubAllGlobals());

test("模拟账户页展示账本摘要和主要操作", async () => {
  renderRoute("/portfolio");
  expect(
    await screen.findByRole("heading", { name: "模拟账户与持仓" }),
  ).toBeInTheDocument();
  expect(await screen.findByText("100,319.84")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /重新估值/ })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /执行核对/ })).toBeInTheDocument();
});

test("持仓页提供五类账本与核对标签页", async () => {
  renderRoute("/portfolio");
  expect(
    await screen.findByRole("tab", { name: "当前持仓" }),
  ).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "资金流水" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "持仓流水" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "估值快照" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "核对记录" })).toBeInTheDocument();
});

test("估值不完整时显示明确警告且不伪造总权益", async () => {
  installPortfolioFetch({ partial: true });
  renderRoute("/portfolio");
  expect(await screen.findByText("估值状态：PARTIAL")).toBeInTheDocument();
  expect(
    screen.getByText("存在缺失或陈旧行情时，总权益不会被伪装成完整数值。"),
  ).toBeInTheDocument();
});

test("可以打开新建模拟账户对话框", async () => {
  renderRoute("/portfolio");
  await userEvent.click(
    await screen.findByRole("button", { name: /新建模拟账户/ }),
  );
  expect(screen.getByRole("dialog")).toHaveTextContent("新建模拟账户");
});

test("无账户时显示安全空状态", async () => {
  installPortfolioFetch({ empty: true });
  renderRoute("/portfolio");
  expect(
    await screen.findByText("尚无模拟账户，请先创建账户"),
  ).toBeInTheDocument();
});
