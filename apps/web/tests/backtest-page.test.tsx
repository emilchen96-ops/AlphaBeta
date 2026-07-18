import { screen, waitFor } from "@testing-library/react";

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
  total_turnover: "20000",
  total_fees: "12",
  realized_pnl: "1000",
  win_rate: "1",
  profit_factor: null,
  average_exposure: "0.2",
  maximum_exposure: "0.4",
};

function response(body: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string | URL | Request) => {
      const url =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.toString()
            : input.url;
      if (url.endsWith("/api/v1/status")) return response(healthyStatus);
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
        return response({ items: [], page: 1, page_size: 50, total: 0 });
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
              daily_return: null,
              cumulative_return: "0",
              drawdown: "0",
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
      if (url.includes(`/backtests/${runId}/`)) return response({ items: [] });
      if (url.endsWith(`/backtests/${runId}`)) return response(run);
      if (url.includes("/backtests?"))
        return response({ items: [run], page: 1, page_size: 20, total: 1 });
      return response({});
    }),
  );
});

test("回测列表展示配置入口、时间规则和本地运行记录", async () => {
  renderRoute("/backtest");
  expect(await screen.findByText("A 股日线回测")).toBeInTheDocument();
  expect(screen.getByText("历史回测边界")).toBeInTheDocument();
  expect(screen.getByText("同步运行回测")).toBeInTheDocument();
  expect(await screen.findByText("sma_crossover")).toBeInTheDocument();
});

test("回测详情展示指标、曲线、事实与完整性状态", async () => {
  renderRoute(`/backtest/${runId}`);
  expect(
    await screen.findByText("回测详情 · sma_crossover"),
  ).toBeInTheDocument();
  expect(screen.getByText("Integrity 通过")).toBeInTheDocument();
  expect(screen.getByText("权益曲线")).toBeInTheDocument();
  expect(screen.getByText("回撤曲线")).toBeInTheDocument();
  await waitFor(() => expect(screen.getByText("1.00%")).toBeInTheDocument());
  expect(screen.queryByText(/实盘执行/)).not.toBeInTheDocument();
});
