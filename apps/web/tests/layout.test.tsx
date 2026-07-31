import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { mockStatusSuccess, renderRoute } from "./test-utils";

beforeEach(() => {
  mockStatusSuccess("RESEARCH_ONLY");
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

test("主导航按用户任务收敛并隐藏内部事实页面", () => {
  renderRoute("/");
  for (const label of [
    "首页",
    "行情",
    "自选股",
    "智能选股",
    "策略回测",
    "AI调研",
    "研究档案",
    "数据中心",
    "设置",
  ]) {
    expect(
      screen.getByRole("menuitem", { name: new RegExp(`${label}$`) }),
    ).toBeInTheDocument();
  }
  for (const label of ["订单", "成交记录", "研究运行", "研究信号", "持仓"]) {
    expect(
      screen.queryByRole("menuitem", { name: new RegExp(`${label}$`) }),
    ).not.toBeInTheDocument();
  }
});

test("策略回测以快速回测为主入口并保留统一工作区标签", async () => {
  renderRoute("/strategy-research");
  expect(
    await screen.findByRole("heading", { name: "策略回测" }),
  ).toBeInTheDocument();
  for (const label of ["快速回测", "策略模板", "参数对比", "我的策略"]) {
    expect(screen.getByRole("tab", { name: label })).toBeInTheDocument();
  }
  expect(screen.getByRole("button", { name: /开始回测$/ })).toBeInTheDocument();
});

test("研究模式阻止直接打开交易页面", async () => {
  renderRoute("/orders");
  expect(
    await screen.findByText("当前为研究模式，交易类页面未启用"),
  ).toBeInTheDocument();
  expect(screen.getByText("MiniQMT（只读）")).toBeInTheDocument();
});
