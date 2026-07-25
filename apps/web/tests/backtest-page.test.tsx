import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { healthyStatus, renderRoute } from "./test-utils";

const runId = "77777777-7777-4777-8777-777777777777";
const run = {
  id: runId,
  idempotency_key: "backtest:test",
  strategy_key: "sma_crossover",
  strategy_version: "1.0.0",
  status: "COMPLETED",
  strategy_run_id: "88888888-8888-4888-8888-888888888888",
  account_id: "99999999-9999-4999-8999-999999999999",
  bars_processed: 20,
  sessions_processed: 10,
  signals_generated: 2,
  risk_passed: 2,
  risk_rejected: 0,
  risk_reviewed: 0,
  orders_created: 2,
  fills_generated: 2,
  started_at: "2026-01-01T01:30:00Z",
  completed_at: "2026-01-15T07:01:00Z",
  failed_at: null,
  error_code: null,
  error_message: null,
  created_at: "2026-01-01T00:00:00Z",
};
const metrics = {
  initial_equity: "100000",
  final_equity: "101000",
  total_return: "0.01",
  annualized_return: "0.28",
  maximum_drawdown: "-0.02",
  annualized_volatility: "0.1",
  sharpe_ratio: "1.2",
  trading_sessions: 10,
  fill_count: 2,
  buy_fill_count: 1,
  sell_fill_count: 1,
  total_turnover: "20000",
  total_commission: "8",
  total_stamp_duty: "3",
  total_transfer_fee: "1",
  total_other_fee: "0",
  total_fees: "12",
  realized_pnl: "1000",
  win_rate: "1",
  loss_rate: "0",
  profit_factor: null,
  average_win: "1000",
  average_loss: null,
  average_exposure: "0.2",
  maximum_exposure: "0.4",
  warnings: ["PROFIT_FACTOR_UNDEFINED_NO_LOSS_TRADES"],
};

const signal = {
  id: "signal-1",
  instrument_id: "instrument-1",
  signal_type: "QUANTITY",
  side: "BUY",
  status: "ACTIVE",
  generated_at: "2026-01-05T07:00:00Z",
  bar_timestamp: "2026-01-05T07:00:00Z",
  valid_until: "2026-01-06T07:00:00Z",
  target_quantity: "100",
  target_weight: null,
  reference_price: "10.00",
  reason: "SMA crossed above",
};

const risk = {
  id: "risk-1",
  signal_id: signal.id,
  instrument_id: signal.instrument_id,
  overall_decision: "PASS",
  evaluated_at: "2026-01-05T07:00:01Z",
  estimated_notional: "1000",
  projected_instrument_weight: "0.01",
  projected_total_exposure: "0.01",
  warnings: [],
};

const order = {
  id: "order-1",
  signal_id: signal.id,
  instrument_id: signal.instrument_id,
  side: "BUY",
  order_type: "LIMIT",
  time_in_force: "DAY",
  status: "FILLED",
  requested_quantity: "100",
  filled_quantity: "100",
  limit_price: "10.10",
  average_fill_price: "10.02",
  created_at: "2026-01-05T07:00:02Z",
  confirmed_at: "2026-01-05T07:00:03Z",
  submitted_at: "2026-01-06T01:30:00Z",
  completed_at: "2026-01-06T01:30:01Z",
  expired_at: null,
};

const fill = {
  id: "fill-1",
  order_id: order.id,
  instrument_id: signal.instrument_id,
  quantity: "100",
  price: "10.02",
  gross_amount: "1002",
  commission: "5",
  tax: "0",
  other_fee: "0.01",
  net_amount: "1007.01",
  executed_at: "2026-01-06T01:30:01Z",
  received_at: "2026-01-06T01:30:02Z",
};

const timelineEvent = {
  id: "event-1",
  event_type: "SESSION_OPEN",
  sequence_number: 1,
  occurred_at: "2026-01-06T01:30:00Z",
  summary: "Execute pending orders",
  details: { session_date: "2026-01-06" },
};

let submittedBody: Record<string, unknown> | null;
let requestedUrls: string[];
let activeRun: Record<string, unknown>;

function response(body: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

beforeEach(() => {
  submittedBody = null;
  requestedUrls = [];
  activeRun = run;
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.toString()
            : input.url;
      requestedUrls.push(url);
      if (url.endsWith("/api/v1/system/status")) return response(healthyStatus);
      if (url.includes("/strategies/catalog"))
        return response([
          {
            strategy_key: "sma_crossover",
            display_name: "SMA Crossover",
            description: "test",
            version: "1.0.0",
            supported_timeframes: ["DAY_1"],
            parameter_schema_version: 1,
            parameters: [],
          },
        ]);
      if (url.includes("/instruments?"))
        return response({
          items: [
            {
              id: "instrument-1",
              symbol: "600000",
              name: "浦发银行",
              exchange: "SSE",
            },
          ],
          page: 1,
          page_size: 50,
          total: 1,
        });
      if (url.endsWith("/api/v1/backtests") && init?.method === "POST") {
        if (typeof init.body !== "string")
          throw new Error("expected JSON request body");
        submittedBody = JSON.parse(init.body) as Record<string, unknown>;
        return response(activeRun);
      }
      if (url.includes(`/backtests/${runId}/metrics`))
        return response({ metrics });
      if (url.includes(`/backtests/${runId}/equity-curve`))
        return response({
          items: [
            {
              id: "point-1",
              timestamp: "2026-01-01T07:01:00Z",
              cash: "100000",
              market_value: "0",
              total_equity: "100000",
              gross_exposure: "1200",
              net_exposure: "1000",
              daily_return: null,
              cumulative_return: "0",
              drawdown: "0",
              positions_count: 0,
              warnings: [],
            },
          ],
        });
      if (url.includes(`/backtests/${runId}/integrity`))
        return response({
          run_id: runId,
          passed: true,
          checked_at: run.completed_at,
          issues: [],
        });
      if (url.includes(`/backtests/${runId}/signals`))
        return response({ items: [signal] });
      if (url.includes(`/backtests/${runId}/risk-decisions`))
        return response({ items: [risk] });
      if (url.includes(`/backtests/${runId}/orders`))
        return response({ items: [order] });
      if (url.includes(`/backtests/${runId}/fills`))
        return response({ items: [fill] });
      if (url.includes(`/backtests/${runId}/timeline`))
        return response({ items: [timelineEvent] });
      if (url.includes(`/backtests/${runId}/`)) return response({ items: [] });
      if (url.endsWith(`/backtests/${runId}`)) return response(activeRun);
      if (url.includes("/backtests?"))
        return response({ items: [run], page: 1, page_size: 20, total: 1 });
      return response({});
    }),
  );
});

test("回测列表展示配置入口、时间规则和本地运行记录", async () => {
  renderRoute("/backtest");
  expect(await screen.findByText("快速回测")).toBeInTheDocument();
  expect(screen.getByText("历史回测边界")).toBeInTheDocument();
  expect(screen.getByText("开始回测")).toBeInTheDocument();
  expect(screen.getByText("MiniQMT（只读行情）")).toBeInTheDocument();
  expect(screen.queryByLabelText("本地历史数据源")).not.toBeInTheDocument();
  expect(await screen.findByText(/均线交叉策略/)).toBeInTheDocument();
});

test("回测详情展示指标、曲线、事实与完整性状态", async () => {
  renderRoute(`/backtest/${runId}`);
  expect(
    await screen.findByText(/回测详情 · 均线交叉策略/),
  ).toBeInTheDocument();
  expect(screen.getByText("完整性检查：通过")).toBeInTheDocument();
  expect(screen.getByText("权益曲线")).toBeInTheDocument();
  expect(screen.getByText("回撤曲线")).toBeInTheDocument();
  expect(
    screen.getByText("没有亏损交易，利润因子无法计算"),
  ).toBeInTheDocument();
  await waitFor(() => expect(screen.getByText("1.00%")).toBeInTheDocument());
  expect(screen.getByText("¥1,200.00")).toBeInTheDocument();
  expect(screen.queryByText("120000.00%")).not.toBeInTheDocument();
  expect(screen.getByText("SMA crossed above")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /实盘|MiniQMT|真实交易/ }),
  ).not.toBeInTheDocument();
}, 60_000);

test("创建表单固定使用MiniQMT并允许成交量参与率留空", async () => {
  const user = userEvent.setup();
  renderRoute("/backtest");

  await user.click(await screen.findByLabelText("策略"));
  await user.click(
    await screen.findByText(/SMA Crossover/, {
      selector: ".ant-select-item-option-content",
    }),
  );
  await user.click(screen.getByLabelText(/回测股票/));
  await user.click(await screen.findByText(/600000/));
  fireEvent.change(screen.getByLabelText("开始日期"), {
    target: { value: "2026-01-01" },
  });
  fireEvent.change(screen.getByLabelText(/结束日期/), {
    target: { value: "2026-01-15" },
  });
  fireEvent.change(screen.getByLabelText(/最大成交量参与率/), {
    target: { value: "" },
  });
  await user.click(screen.getByRole("button", { name: /开始回测/ }));

  await waitFor(() => expect(submittedBody).not.toBeNull());
  expect(submittedBody).toMatchObject({
    maximum_volume_participation: null,
    strategy_key: "sma_crossover",
    data_source_code: "MINIQMT",
    instrument_ids: ["instrument-1"],
  });
  expect(String(submittedBody?.idempotency_key)).toMatch(/^backtest:/);
}, 60_000);

test.each(["CREATED", "RUNNING", "FAILED"] as const)(
  "%s 运行没有 metrics 时详情仍可查看",
  async (status) => {
    activeRun = {
      ...run,
      status,
      completed_at: null,
      failed_at: status === "FAILED" ? "2026-01-05T07:00:00Z" : null,
      error_code: status === "FAILED" ? "BACKTEST_STRATEGY_FAILED" : null,
      error_message: status === "FAILED" ? "strategy failed safely" : null,
    };
    renderRoute(`/backtest/${runId}`);

    expect(await screen.findByText(/回测详情/)).toBeInTheDocument();
    expect(screen.getByText("绩效指标尚未生成")).toBeInTheDocument();
    if (status === "FAILED") {
      expect(screen.getByText("BACKTEST_STRATEGY_FAILED")).toBeInTheDocument();
      expect(screen.getByText("strategy failed safely")).toBeInTheDocument();
    }
    expect(
      requestedUrls.some((url) => url.endsWith(`/backtests/${runId}/metrics`)),
    ).toBe(false);
  },
);

test("事实标签分别展示研究信号、风控、订单、成交与时间线的关键字段", async () => {
  const user = userEvent.setup();
  renderRoute(`/backtest/${runId}`);
  expect(await screen.findByText("SMA crossed above")).toBeInTheDocument();

  await user.click(screen.getByRole("tab", { name: /风控决策/ }));
  expect(screen.getByText("风控通过")).toBeInTheDocument();
  await user.click(screen.getByRole("tab", { name: /订单/ }));
  expect(screen.getByText("全部成交")).toBeInTheDocument();
  await user.click(screen.getByRole("tab", { name: /成交与费用/ }));
  expect(screen.getByText("¥1,007.01")).toBeInTheDocument();
  await user.click(screen.getByRole("tab", { name: /事件时间线/ }));
  expect(screen.getByText("Execute pending orders")).toBeInTheDocument();
}, 60_000);
