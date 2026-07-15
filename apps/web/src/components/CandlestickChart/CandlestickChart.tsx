import { Empty, Skeleton } from "antd";

import type { MarketBar } from "../../types/market";

export function CandlestickChart({
  bars,
  loading,
}: {
  bars: MarketBar[];
  loading: boolean;
}) {
  if (loading) return <Skeleton active paragraph={{ rows: 8 }} />;
  if (!bars.length)
    return <Empty description="暂无行情数据，请先运行演示数据导入" />;
  const visible = bars.slice(-90);
  const highs = visible.map((bar) => Number(bar.high));
  const lows = visible.map((bar) => Number(bar.low));
  const highest = Math.max(...highs);
  const lowest = Math.min(...lows);
  const span = Math.max(highest - lowest, 0.01);
  const width = 900;
  const height = 360;
  const top = 20;
  const bottom = 30;
  const plotHeight = height - top - bottom;
  const step = width / visible.length;
  const y = (value: number) => top + ((highest - value) / span) * plotHeight;
  return (
    <div className="candle-chart" role="img" aria-label="K线图">
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
        {[0, 1, 2, 3, 4].map((line) => (
          <line
            key={line}
            x1="0"
            x2={width}
            y1={top + (plotHeight * line) / 4}
            y2={top + (plotHeight * line) / 4}
            stroke="#e8edf3"
          />
        ))}
        {visible.map((bar, index) => {
          const x = index * step + step / 2;
          const open = Number(bar.open);
          const close = Number(bar.close);
          const rising = close >= open;
          const color = rising ? "#d4380d" : "#08979c";
          return (
            <g key={`${bar.bar_time}-${index}`}>
              <line
                x1={x}
                x2={x}
                y1={y(Number(bar.high))}
                y2={y(Number(bar.low))}
                stroke={color}
              />
              <rect
                x={x - Math.max(step * 0.28, 1)}
                y={Math.min(y(open), y(close))}
                width={Math.max(step * 0.56, 2)}
                height={Math.max(Math.abs(y(open) - y(close)), 1)}
                fill={rising ? "#fff" : color}
                stroke={color}
              />
            </g>
          );
        })}
      </svg>
    </div>
  );
}
