import { screen } from "@testing-library/react";

import { renderRoute } from "./test-utils";
import { beforeEach, afterEach, vi } from "vitest";

const response = (body: unknown) =>
  Promise.resolve(
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string | URL | Request) => {
      const url =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : input.url;
      if (url.endsWith("/system/status"))
        return response({
          api: "online",
          postgresql: "online",
          redis: "online",
          environment: "development",
        });
      if (url.endsWith("/miniqmt/market-data/status"))
        return response({
          schema_version: 1,
          data: {
            configured: true,
            state: "CONNECTED",
            agent: null,
            desired_count: 0,
            active_count: 0,
            failed_count: 0,
            latest_minute_bar_time: null,
          },
        });
      if (url.includes("/instruments?"))
        return response({ items: [], page: 1, page_size: 50, total: 0 });
      if (url.endsWith("/market-data/overview")) return response({});
      if (url.endsWith("/market-data/coverage")) return response({ items: [] });
      if (url.endsWith("/market-data/readiness")) return response([]);
      if (url.endsWith("/intraday/coverage")) return response({ items: [] });
      if (url.endsWith("/intraday/readiness")) return response({ items: [] });
      if (url.endsWith("/intraday/imports")) return response({ items: [] });
      if (url.endsWith("/intraday/quality-runs"))
        return response({ items: [], total: 0 });
      if (url.includes("/market-data/quality-runs?page="))
        return response({ items: [], page: 1, page_size: 20, total: 0 });
      if (url.endsWith("/market-reference/status")) return response({});
      if (url.includes("/market-data/sync-runs")) return response([]);
      throw new Error(`unhandled ${url}`);
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());

test("分钟数据旧路由跳转到统一数据中心", async () => {
  renderRoute("/intraday-market-data");
  expect(
    await screen.findByRole("heading", { name: "数据中心" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("tab", { name: "分钟行情", selected: true }),
  ).toBeInTheDocument();
  expect(screen.queryByText("D03_FIXTURE")).not.toBeInTheDocument();
});
