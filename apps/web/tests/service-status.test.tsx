import { render, screen } from "@testing-library/react";

import { ServiceStatus } from "../src/components/ServiceStatus/ServiceStatus";

test("服务状态组件正确显示在线和离线", () => {
  const { rerender } = render(<ServiceStatus name="API" status="online" />);
  expect(screen.getByText("API · 在线")).toBeInTheDocument();
  rerender(<ServiceStatus name="API" status="offline" />);
  expect(screen.getByText("API · 离线")).toBeInTheDocument();
});
