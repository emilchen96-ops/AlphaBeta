import { screen } from "@testing-library/react";

import { mockStatusSuccess, renderRoute } from "./test-utils";

test("开始使用页面解释演示边界和完整研究路径", async () => {
  mockStatusSuccess();
  renderRoute("/getting-started");

  expect(await screen.findByText("开始使用 AlphaDesk")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: /一键创建演示研究环境/ }),
  ).toBeInTheDocument();
  expect(screen.getByText(/不会下载外部数据/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "运行 Backtest" })).toHaveAttribute(
    "href",
    "/backtest",
  );
});
