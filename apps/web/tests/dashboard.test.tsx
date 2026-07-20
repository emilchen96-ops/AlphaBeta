import { act, screen } from "@testing-library/react";

import {
  healthyCapabilities,
  healthyStatus,
  mockStatusSuccess,
  renderRoute,
} from "./test-utils";

beforeEach(() => {
  vi.stubGlobal("WebSocket", undefined);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("Dashboard显示加载状态", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => new Promise(() => undefined)),
  );
  let container!: HTMLElement;
  await act(async () => {
    ({ container } = renderRoute("/"));
    await Promise.resolve();
  });
  expect(container.querySelector(".ant-skeleton")).toBeInTheDocument();
});

test("Dashboard显示基础设施真实响应", async () => {
  mockStatusSuccess();
  renderRoute("/");
  expect(
    (await screen.findAllByText("PostgreSQL · 在线")).length,
  ).toBeGreaterThan(0);
  expect(screen.getAllByText("Redis · 在线").length).toBeGreaterThan(0);
  expect(screen.getByText("0.1.0")).toBeInTheDocument();
  expect(
    await screen.findByText("功能可用性（后端权威检查）"),
  ).toBeInTheDocument();
  expect(screen.getByText("历史行情")).toBeInTheDocument();
  expect(screen.getAllByText("已实现").length).toBeGreaterThan(0);
});

test("Dashboard在API失败时保持可用", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
  renderRoute("/");
  expect(
    await screen.findByText("无法获取系统状态", undefined, { timeout: 4_000 }),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "重新连接" })).toBeInTheDocument();
});

test("Dashboard可在API恢复后手动重新连接", async () => {
  let statusAttempts = 0;
  const fetchMock = vi.fn((input: string | URL | Request) => {
    const url =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    if (url.endsWith("/system/capabilities")) {
      return Promise.resolve(
        new Response(JSON.stringify(healthyCapabilities), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }
    statusAttempts += 1;
    if (statusAttempts <= 2) return Promise.reject(new TypeError("offline"));
    return Promise.resolve(
      new Response(JSON.stringify(healthyStatus), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute("/");
  const retryButton = await screen.findByRole(
    "button",
    { name: "重新连接" },
    { timeout: 4_000 },
  );
  retryButton.click();
  expect((await screen.findAllByText("FastAPI · 在线")).length).toBeGreaterThan(
    0,
  );
});
