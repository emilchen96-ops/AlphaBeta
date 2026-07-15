import { screen } from "@testing-library/react";

import { mockStatusSuccess, renderRoute } from "./test-utils";

beforeEach(() => {
  mockStatusSuccess();
  vi.stubGlobal("WebSocket", undefined);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("未知路由显示404页面", async () => {
  renderRoute("/missing-route");
  expect(await screen.findByText("页面不存在")).toBeInTheDocument();
});
