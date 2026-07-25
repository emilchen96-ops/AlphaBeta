import { screen, waitFor } from "@testing-library/react";

import { healthyStatus, renderRoute } from "./test-utils";

const replayId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const replay = {
  id: replayId,
  idempotency_key: "replay-test",
  status: "PAUSED",
  row_version: 7,
  strategy_key: "sma_crossover",
  strategy_version: "1.0.0",
  account_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
  strategy_run_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
  current_session_date: "2026-01-05",
  current_session_index: 2,
  total_sessions: 10,
  speed_mode: "MANUAL",
  bars_processed: 2,
  signals_generated: 1,
  orders_created: 1,
  fills_generated: 0,
  started_at: "2026-01-01T01:30:00Z",
  paused_at: "2026-01-05T07:01:00Z",
  completed_at: null,
  stopped_at: null,
  failed_at: null,
  error_code: null,
  error_message: null,
  last_heartbeat_at: null,
  worker_online: false,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-05T07:01:00Z",
  final_summary: {},
  integrity_summary: {},
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
    "WebSocket",
    class {
      onmessage: (() => void) | null = null;
      close() {}
    },
  );
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
      if (url.includes(`/replays/${replayId}/state`))
        return response({
          state: {
            ...replay,
            cash: { available_cash: "100000" },
            positions: [],
            current_bar: { open: "10", close: "11" },
            latest_equity: null,
          },
        });
      if (url.includes(`/replays/${replayId}/events`))
        return response({
          items: [
            {
              id: "event-1",
              replay_run_id: replayId,
              sequence_number: 1,
              event_type: "RUN_CREATED",
              business_time: "2026-01-01T00:00:00Z",
              occurred_at: "2026-01-01T00:00:00Z",
              instrument_id: null,
              related_entity_type: null,
              related_entity_id: null,
              summary: "Historical replay created",
              payload: {},
            },
          ],
          total: 1,
        });
      if (url.includes(`/replays/${replayId}/integrity`))
        return response({
          replay_run_id: replayId,
          ok: true,
          checked_at: "2026-01-05T07:01:00Z",
          issues: [],
          facts: {},
        });
      if (url.includes(`/replays/${replayId}/equity`))
        return response({ items: [] });
      if (url.includes(`/replays/${replayId}/`)) return response({ items: [] });
      if (url.endsWith(`/replays/${replayId}`)) return response(replay);
      if (url.includes("/replays?"))
        return response({ items: [replay], page: 1, page_size: 50, total: 1 });
      return response({});
    }),
  );
});

test("历史回放列表明确安全边界并展示回放入口", async () => {
  renderRoute("/replays");
  expect(await screen.findByText("逐日查看")).toBeInTheDocument();
  expect(
    screen.getByText("逐日查看是回测的解释工具，不是另一套回测"),
  ).toBeInTheDocument();
  expect(await screen.findByText("sma_crossover")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /真实下单|实盘|MiniQMT/ }),
  ).not.toBeInTheDocument();
});

test("暂停状态只启用恢复、单步、速度和停止控制", async () => {
  renderRoute(`/replays/${replayId}`);
  expect(await screen.findByText("历史回放控制台")).toBeInTheDocument();
  await waitFor(() =>
    expect(screen.getByText("Historical replay created")).toBeInTheDocument(),
  );
  expect(screen.getByRole("button", { name: /启动$/ })).toBeDisabled();
  expect(screen.getByRole("button", { name: /暂停$/ })).toBeDisabled();
  expect(screen.getByRole("button", { name: /恢复$/ })).toBeEnabled();
  expect(
    screen.getByRole("button", { name: /单步一个 Session/ }),
  ).toBeEnabled();
  expect(screen.getByText("Integrity 通过")).toBeInTheDocument();
  expect(screen.getByText("open")).toBeInTheDocument();
  expect(screen.getByText("10")).toBeInTheDocument();
});
