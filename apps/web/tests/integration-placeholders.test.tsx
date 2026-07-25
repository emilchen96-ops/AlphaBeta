import { screen } from "@testing-library/react";

import { mockStatusSuccess, renderRoute } from "./test-utils";

beforeEach(() => {
  mockStatusSuccess();
  vi.stubGlobal("WebSocket", undefined);
});

afterEach(() => vi.unstubAllGlobals());

test("回测入口展示已完成的本地日线运行能力且没有实盘按钮", async () => {
  renderRoute("/backtest");
  expect(await screen.findByText("快速回测")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /开始回测/ })).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /实盘|跟单|MiniQMT/ }),
  ).not.toBeInTheDocument();
});

test("审计与设置页面不会暴露无响应的编辑操作", async () => {
  const audit = renderRoute("/audit");
  expect(await screen.findByText("计划开发")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /查询|导出/ }),
  ).not.toBeInTheDocument();
  audit.unmount();

  renderRoute("/settings");
  expect(
    await screen.findByRole("heading", { name: "设置" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /保存|应用/ }),
  ).not.toBeInTheDocument();
});
