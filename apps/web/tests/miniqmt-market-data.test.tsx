import { screen } from "@testing-library/react";

import { mockStatusSuccess, renderRoute } from "./test-utils";

beforeEach(mockStatusSuccess);
afterEach(() => vi.unstubAllGlobals());

test("旧实时行情入口跳转到统一行情页", async () => {
  renderRoute("/miniqmt-market-data");
  expect(
    await screen.findByRole("heading", { name: "行情" }),
  ).toBeInTheDocument();
  expect(screen.getByText("MiniQMT 行情状态")).toBeInTheDocument();
  expect(screen.queryByText("MiniQMT 实时行情")).not.toBeInTheDocument();
});

test("统一行情页不暴露任何交易操作", async () => {
  renderRoute("/miniqmt-market-data");
  await screen.findByRole("heading", { name: "行情" });
  expect(
    screen.queryByRole("button", { name: /下单|撤单|交易/ }),
  ).not.toBeInTheDocument();
});
