import { render, screen } from "@testing-library/react";

import { CandlestickChart } from "../src/components/CandlestickChart/CandlestickChart";
import type { MarketBar } from "../src/types/market";

const base: MarketBar = {
  instrument_id: "i1",
  source_code: "DEMO",
  timeframe: "DAY_1",
  adjustment_type: "NONE",
  bar_time: "2025-01-01T00:00:00Z",
  open: "10",
  high: "11",
  low: "9",
  close: "10.5",
  volume: "100",
  amount: "1050",
  vwap: "10.25",
  received_at: "2025-01-01T00:01:00Z",
  quality_status: "NORMAL",
  adjustment_mode: "RAW",
  factor: "1",
  reference_factor: "1",
  raw_bar_id: null,
};

test("K线加载时显示骨架", () => {
  const { container } = render(<CandlestickChart bars={[]} loading />);
  expect(container.querySelector(".ant-skeleton")).toBeInTheDocument();
});

test("空行情显示明确提示", () => {
  render(<CandlestickChart bars={[]} loading={false} />);
  expect(
    screen.getByText("暂无行情数据，请先前往数据中心下载历史行情"),
  ).toBeInTheDocument();
});

test("有效行情渲染可访问 K 线图", () => {
  render(<CandlestickChart bars={[base]} loading={false} />);
  expect(screen.getByRole("img", { name: "K线图" })).toBeInTheDocument();
});

test("上涨和下跌行情都渲染蜡烛实体", () => {
  const falling = {
    ...base,
    bar_time: "2025-01-02T00:00:00Z",
    open: "10.5",
    close: "10",
  };
  const { container } = render(
    <CandlestickChart bars={[base, falling]} loading={false} />,
  );
  expect(container.querySelectorAll("rect")).toHaveLength(2);
});
