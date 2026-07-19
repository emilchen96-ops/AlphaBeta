import { screen } from "@testing-library/react";

import { mockStatusSuccess, renderRoute } from "./test-utils";

beforeEach(() => {
  mockStatusSuccess();
  vi.stubGlobal("WebSocket", undefined);
});

afterEach(() => vi.unstubAllGlobals());

test("回测入口明确标记部分完成且没有虚假运行按钮", async () => {
  renderRoute("/backtest");
  expect(
    await screen.findByText("部分完成，当前分支不可用"),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /启动|运行回测/ }),
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
    await screen.findByRole("heading", { name: "设置（只读）" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /保存|应用/ }),
  ).not.toBeInTheDocument();
});
