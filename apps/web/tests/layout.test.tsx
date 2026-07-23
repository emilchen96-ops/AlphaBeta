import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { mockStatusSuccess, renderRoute } from "./test-utils";

beforeEach(() => {
  mockStatusSuccess();
  vi.stubGlobal("WebSocket", undefined);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("应用主布局可以渲染", async () => {
  renderRoute("/market");
  expect(screen.getByLabelText("AlphaDesk")).toBeInTheDocument();
  expect(
    await screen.findByRole("heading", { name: "行情" }),
  ).toBeInTheDocument();
  expect(screen.getByText("Web · 正常")).toBeInTheDocument();
});

test("导航菜单可以切换页面并高亮当前项", async () => {
  renderRoute("/");
  const marketMenuItem = screen.getByText("行情").closest("[role=menuitem]");
  expect(marketMenuItem).not.toBeNull();
  if (marketMenuItem === null) {
    throw new Error("行情菜单项不存在");
  }
  await userEvent.click(marketMenuItem);
  expect(
    await screen.findByRole("heading", { name: "行情" }),
  ).toBeInTheDocument();
  expect(marketMenuItem).toHaveClass("ant-menu-item-selected");
});
