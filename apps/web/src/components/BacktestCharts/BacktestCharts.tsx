import { Empty, Typography } from "antd";

import type { BacktestEquityPoint } from "../../types/backtests";

interface ChartProps {
  points: BacktestEquityPoint[];
  field: "total_equity" | "drawdown";
  title: string;
  color: string;
  percent?: boolean;
}

function number(value: string) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function BacktestLineChart({
  points,
  field,
  title,
  color,
  percent = false,
}: ChartProps) {
  if (!points.length) return <Empty description={`${title}暂无数据`} />;
  const width = 900;
  const height = 260;
  const padding = 34;
  const values = points.map((point) => number(point[field]));
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const spread = maximum - minimum || Math.max(Math.abs(maximum), 1);
  const coordinates = values.map((value, index) => {
    const x =
      padding +
      (index / Math.max(values.length - 1, 1)) * (width - padding * 2);
    const y = padding + ((maximum - value) / spread) * (height - padding * 2);
    return `${x},${y}`;
  });
  const format = (value: number) =>
    percent ? `${(value * 100).toFixed(2)}%` : value.toLocaleString("zh-CN");
  return (
    <div className="backtest-chart" role="img" aria-label={title}>
      <Typography.Text strong>{title}</Typography.Text>
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
        <line
          x1={padding}
          y1={height - padding}
          x2={width - padding}
          y2={height - padding}
          stroke="#d0d5dd"
        />
        <line
          x1={padding}
          y1={padding}
          x2={padding}
          y2={height - padding}
          stroke="#d0d5dd"
        />
        <polyline
          points={coordinates.join(" ")}
          fill="none"
          stroke={color}
          strokeWidth="3"
          vectorEffect="non-scaling-stroke"
        />
        <text x={padding + 4} y={padding - 8} fill="#667085" fontSize="12">
          {format(maximum)}
        </text>
        <text
          x={padding + 4}
          y={height - padding - 8}
          fill="#667085"
          fontSize="12"
        >
          {format(minimum)}
        </text>
      </svg>
    </div>
  );
}
