import { render } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";

import { AppProviders } from "../src/app/providers";
import { routes } from "../src/app/router";

export const healthyStatus = {
  api: "online",
  postgresql: "online",
  redis: "online",
  environment: "development",
  version: "0.1.0",
  server_time: "2026-07-15T08:00:00+00:00",
  correlation_id: "test-correlation-id",
};

export const healthyCapabilities = {
  generated_at: "2026-07-19T08:00:00+00:00",
  database_reachable: true,
  counts: {},
  items: [
    {
      module_key: "market_data",
      implementation_status: "WORKING",
      data_status: "READY",
      configuration_status: "NOT_REQUIRED",
      available: true,
      reason: "历史行情可读取当前 PostgreSQL 历史日线。",
      required_actions: [],
    },
    {
      module_key: "scanner",
      implementation_status: "WORKING",
      data_status: "READY",
      configuration_status: "NOT_REQUIRED",
      available: true,
      reason: "条件扫描可读取当前 PostgreSQL 历史日线。",
      required_actions: [],
    },
    {
      module_key: "backtest",
      implementation_status: "PARTIAL",
      data_status: "UNKNOWN",
      configuration_status: "NOT_REQUIRED",
      available: false,
      reason: "BT01 尚未安全整合。",
      required_actions: ["完成 BT01-R"],
    },
  ],
};

export function mockStatusSuccess() {
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
      if (url.endsWith("/system/capabilities")) body = healthyCapabilities;
      else if (url.includes("/api/v1/watchlists")) body = [];
      else if (url.includes("/api/v1/market-data/sources")) body = [];
      else if (url.includes("/api/v1/instruments?")) {
        body = { items: [], page: 1, page_size: 50, total: 0 };
      } else if (url.includes("/api/v1/market-data/realtime/status")) {
        body = {
          enabled: false,
          state: "disabled",
          source_code: null,
          circuit_state: null,
          consecutive_failures: 0,
          requested_count: 0,
          received_count: 0,
          changed_count: 0,
          rejected_count: 0,
          checked_at: null,
          error_summary: null,
          worker_heartbeat: null,
        };
      }
      return Promise.resolve(
        new Response(JSON.stringify(body), {
          status: 200,
          headers: {
            "Content-Type": "application/json",
            "X-Correlation-ID": "test-id",
          },
        }),
      );
    }),
  );
}

export function renderRoute(initialEntry = "/") {
  const router = createMemoryRouter(routes, { initialEntries: [initialEntry] });
  return render(
    <AppProviders>
      <RouterProvider router={router} />
    </AppProviders>,
  );
}
