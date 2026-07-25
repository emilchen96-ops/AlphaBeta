import { render } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";

import { AppProviders } from "../src/app/providers";
import { routes } from "../src/app/router";

export const healthyStatus = {
  api: "online",
  postgresql: "online",
  redis: "online",
  environment: "development",
  product_mode: "RESEARCH_ONLY",
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
      module_key: "historical_market_data",
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
      module_key: "daily_backtest",
      implementation_status: "WORKING",
      data_status: "READY",
      configuration_status: "NOT_REQUIRED",
      available: true,
      reason: "BT01 日线回测已完成。",
      required_actions: [],
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
      else if (url.includes("/api/v1/miniqmt/market-data/status")) {
        body = {
          schema_version: 1,
          data: {
            configured: false,
            state: "NOT_CONFIGURED",
            agent: null,
            desired_count: 0,
            active_count: 0,
            failed_count: 0,
            latest_minute_bar_time: null,
            source: "MINIQMT",
            market_data_capability: "ENABLED",
            trading_capability: "DISABLED",
            trading_message: "交易能力关闭",
          },
        };
      } else if (url.includes("/api/v1/market-subscriptions/active")) {
        body = { schema_version: 1, data: { items: [] } };
      } else if (url.includes("/api/v1/strategies/catalog")) body = [];
      else if (url.includes("/api/v1/strategy-templates")) body = [];
      else if (url.includes("/api/v1/user-strategies")) {
        body = { items: [], page: 1, page_size: 100, total: 0 };
      }
      else if (url.includes("/api/v1/backtests?")) {
        body = { items: [], page: 1, page_size: 20, total: 0 };
      } else if (url.includes("/api/v1/instruments?")) {
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
