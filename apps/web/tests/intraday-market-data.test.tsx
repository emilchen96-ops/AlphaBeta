import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { healthyCapabilities, healthyStatus, renderRoute } from "./test-utils";

const instrumentId = "22222222-2222-4222-8222-222222222222";

function response(body: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

function installFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : input.url;
      if (url.endsWith("/system/status")) return response(healthyStatus);
      if (url.endsWith("/system/capabilities"))
        return response(healthyCapabilities);
      if (url.endsWith("/intraday/providers"))
        return response({
          items: [
            {
              provider_key: "D03_FIXTURE",
              health: "AVAILABLE",
              supported_timeframes: ["MINUTE_1"],
              input_types: ["fixture"],
              message: "offline fixture",
            },
            {
              provider_key: "LOCAL_FILE",
              health: "AVAILABLE_CLI_ONLY",
              supported_timeframes: ["MINUTE_1"],
              input_types: ["csv"],
              message: "CSV CLI only",
            },
          ],
          limits: { http_upload: false },
        });
      if (url.endsWith("/intraday/coverage")) return response({ items: [] });
      if (url.endsWith("/intraday/imports") && init?.method !== "POST")
        return response({ items: [] });
      if (url.endsWith("/intraday/quality-runs") && init?.method !== "POST")
        return response({ items: [], total: 0 });
      if (url.endsWith("/intraday/readiness"))
        return response({
          items: [
            {
              capability_key: "bt02_5m_ready",
              timeframe: "MINUTE_5",
              data_status: "READY",
              implementation_status: "NOT_IMPLEMENTED",
              ready_instrument_count: 2,
              required_action: "代码尚未开发",
            },
          ],
        });
      if (url.includes("/instruments?"))
        return response({
          items: [
            {
              id: instrumentId,
              symbol: "600000",
              name: "D03 Fixture SSE",
              exchange: "SSE",
            },
          ],
          page: 1,
          page_size: 50,
          total: 1,
        });
      if (url.includes("/intraday/bars?"))
        return response({ items: [], historical: true, realtime: false });
      if (url.endsWith("/intraday/imports") && init?.method === "POST")
        return response({
          run: null,
          rows_read: 2400,
          rows_valid: 2400,
          rows_invalid: 0,
          bars_inserted: 2400,
          bars_updated: 0,
          bars_skipped: 0,
          conflicts: 0,
          aggregated_bars_created: 760,
          incomplete_windows: 0,
          duration_seconds: 1,
          errors: [],
        });
      throw new Error(`unhandled ${url}`);
    }),
  );
}

beforeEach(installFetch);
afterEach(() => vi.unstubAllGlobals());

test("shows offline provider boundary, CLI import guidance and BT02 code status", async () => {
  const user = userEvent.setup();
  renderRoute("/intraday-market-data");
  expect(await screen.findByText("分钟行情数据中心")).toBeInTheDocument();
  expect(await screen.findByText("D03_FIXTURE")).toBeInTheDocument();
  expect(screen.getByText(/不连接实时WebSocket/)).toBeInTheDocument();
  await user.click(screen.getByRole("tab", { name: "导入任务" }));
  expect(
    await screen.findByText(/本地文件通过CLI安全导入/),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /上传/ }),
  ).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /导入2只股票/ }));
  await waitFor(() =>
    expect(screen.getByText(/导入 2400 根/)).toBeInTheDocument(),
  );
  await user.click(screen.getByRole("tab", { name: "Readiness" }));
  expect((await screen.findAllByText("代码尚未开发")).length).toBeGreaterThan(
    0,
  );
});
