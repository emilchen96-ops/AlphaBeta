import { screen } from "@testing-library/react";

import { healthyStatus, mockStatusSuccess, renderRoute } from "./test-utils";

beforeEach(() => {
  vi.stubGlobal("WebSocket", undefined);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("Dashboard显示加载状态", () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => new Promise(() => undefined)),
  );
  const { container } = renderRoute("/");
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
  const fetchMock = vi
    .fn()
    .mockRejectedValueOnce(new TypeError("offline"))
    .mockRejectedValueOnce(new TypeError("offline"))
    .mockImplementation(() =>
      Promise.resolve(
        new Response(JSON.stringify(healthyStatus), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
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
