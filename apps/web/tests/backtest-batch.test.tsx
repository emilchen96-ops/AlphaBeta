import { screen } from "@testing-library/react";

import { healthyStatus, renderRoute } from "./test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

test("失败的共享资金组合任务显示原因而不是读取缺失的逐股统计", async () => {
  const batchId = "fff2d30c-ac42-4d05-99c3-0825dc096c5d";
  const batch = {
    id: batchId,
    name: "科技板块共享资金组合回测",
    scope: "WATCHLIST",
    execution_mode: "SHARED_PORTFOLIO",
    instrument_count: 24,
    watchlist_id: null,
    status: "FAILED",
    total_count: 1,
    pending_count: 0,
    running_count: 0,
    completed_count: 0,
    failed_count: 1,
    cancelled_count: 0,
    progress_percent: 100,
    started_at: "2026-08-04T08:00:00Z",
    completed_at: "2026-08-04T08:01:00Z",
    error_code: null,
    error_message: null,
    created_at: "2026-08-04T08:00:00Z",
    updated_at: "2026-08-04T08:01:00Z",
  };

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
      if (url.endsWith(`/research/backtest-batches/${batchId}`)) {
        body = batch;
      } else if (
        url.includes(`/research/backtest-batches/${batchId}/results`)
      ) {
        body = {
          items: [
            {
              item_id: "item-1",
              instrument_id: "00000000-0000-4000-8000-000000000001",
              symbol: "PORTFOLIO",
              exchange: "CN_A",
              name: "共享组合",
              status: "FAILED",
              backtest_run_id: null,
              error_code: "BACKTEST_TOO_MANY_INSTRUMENTS",
              error_message: "instrument count exceeds the configured limit",
            },
          ],
          page: 1,
          page_size: 50,
          total: 1,
        };
      } else if (
        url.endsWith(`/research/backtest-batches/${batchId}/summary`)
      ) {
        body = {
          batch,
          notice: "共享资金组合任务尚未生成组合回测运行。",
          portfolio: null,
          data_preparation: {
            required_sessions: 0,
            ready_sessions: 0,
            missing_sessions: 0,
            progress_percent: 0,
            preparing_stocks: 0,
            queued_segments: 0,
          },
          intraday_execution: {
            daily_bars_checked: 0,
            daily_prefilter_candidates: 0,
            daily_prefilter_excluded: 0,
            minute_sessions_loaded: 0,
            minute_bars_processed: 0,
            signals_generated: 0,
            stocks_with_signals: 0,
            stocks_with_fills: 0,
            data_preparation_seconds: 0,
            strategy_replay_seconds: 0,
          },
        };
      } else if (url.endsWith("/system/capabilities")) {
        body = {
          generated_at: "",
          database_reachable: true,
          counts: {},
          items: [],
        };
      }
      return Promise.resolve(
        new Response(JSON.stringify(body), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }),
  );

  renderRoute(`/research/backtest-batches/${batchId}`);

  expect(await screen.findByText("共享资金组合回测失败")).toBeInTheDocument();
  expect(
    screen.getByText("失败原因：组合股票数量超过系统允许范围"),
  ).toBeInTheDocument();
  expect(
    screen.queryByText("Unexpected Application Error!"),
  ).not.toBeInTheDocument();
});
