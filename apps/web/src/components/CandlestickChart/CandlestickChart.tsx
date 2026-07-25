import { Empty, Skeleton, Typography } from "antd";

import type { MarketBar } from "../../types/market";

const WIDTH = 980;
const HEIGHT = 420;
const LEFT = 18;
const RIGHT = 76;
const TOP = 18;
const BOTTOM = 38;

function labelTime(value: string, minute: boolean) {
  const date = new Date(value);
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    ...(minute ? { hour: "2-digit", minute: "2-digit", hour12: false } : {}),
  }).format(date);
}

export function CandlestickChart({
  bars,
  loading,
  variant = "candlestick",
  markers = [],
}: {
  bars: MarketBar[];
  loading: boolean;
  variant?: "candlestick" | "line";
  markers?: Array<{
    time: string;
    side: "BUY" | "SELL";
    label?: string;
  }>;
}) {
  if (loading) return <Skeleton active paragraph={{ rows: 8 }} />;
  if (!bars.length)
    return <Empty description="暂无 MiniQMT 历史行情，可在数据中心发起补数" />;

  const unique = new Map<string, MarketBar>();
  for (const bar of bars) unique.set(bar.bar_time, bar);
  const ordered = [...unique.values()].sort(
    (left, right) =>
      new Date(left.bar_time).getTime() - new Date(right.bar_time).getTime(),
  );
  const visible = ordered.slice(-120);
  const numeric = visible.filter((bar) =>
    [bar.open, bar.high, bar.low, bar.close].every((value) =>
      Number.isFinite(Number(value)),
    ),
  );
  if (!numeric.length) return <Empty description="K 线数据格式无效" />;

  const highest = Math.max(...numeric.map((bar) => Number(bar.high)));
  const lowest = Math.min(...numeric.map((bar) => Number(bar.low)));
  const span = Math.max(highest - lowest, Math.abs(highest) * 0.002, 0.01);
  const plotWidth = WIDTH - LEFT - RIGHT;
  const plotHeight = HEIGHT - TOP - BOTTOM;
  const step = plotWidth / numeric.length;
  const candleWidth = Math.max(Math.min(step * 0.58, 8), 1.5);
  const y = (value: number) => TOP + ((highest - value) / span) * plotHeight;
  const minute = numeric[0]?.timeframe !== "DAY_1";
  const timeTicks = [
    ...new Set([0, Math.floor((numeric.length - 1) / 2), numeric.length - 1]),
  ];
  const closeLine = numeric
    .map((bar, index) => {
      const x = LEFT + index * step + step / 2;
      return `${x},${y(Number(bar.close))}`;
    })
    .join(" ");
  const markerByDay = new Map(
    markers.map((marker) => [
      new Date(marker.time).toISOString().slice(0, 10),
      marker,
    ]),
  );

  return (
    <div className="candle-chart">
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label={`MiniQMT ${variant === "line" ? "分时图" : "K线图"}，共${numeric.length}根`}
      >
        {[0, 1, 2, 3, 4].map((line) => {
          const value = highest - (span * line) / 4;
          const lineY = TOP + (plotHeight * line) / 4;
          return (
            <g key={line}>
              <line
                x1={LEFT}
                x2={WIDTH - RIGHT}
                y1={lineY}
                y2={lineY}
                stroke="#e8edf3"
              />
              <text
                x={WIDTH - RIGHT + 8}
                y={lineY + 4}
                fill="#667085"
                fontSize="12"
              >
                {value.toFixed(value >= 100 ? 2 : 3)}
              </text>
            </g>
          );
        })}
        {variant === "line" ? (
          <polyline
            points={closeLine}
            fill="none"
            stroke="#1677ff"
            strokeWidth="2"
            vectorEffect="non-scaling-stroke"
          />
        ) : (
          numeric.map((bar, index) => {
            const x = LEFT + index * step + step / 2;
            const open = Number(bar.open);
            const close = Number(bar.close);
            const rising = close >= open;
            const color = rising ? "#d4380d" : "#08979c";
            const marker = markerByDay.get(
              new Date(bar.bar_time).toISOString().slice(0, 10),
            );
            return (
              <g key={bar.bar_time}>
                <line
                  x1={x}
                  x2={x}
                  y1={y(Number(bar.high))}
                  y2={y(Number(bar.low))}
                  stroke={color}
                />
                <rect
                  x={x - candleWidth / 2}
                  y={Math.min(y(open), y(close))}
                  width={candleWidth}
                  height={Math.max(Math.abs(y(open) - y(close)), 1)}
                  fill={rising ? "#fff" : color}
                  stroke={color}
                />
                {marker ? (
                  <g>
                    <circle
                      cx={x}
                      cy={
                        marker.side === "BUY"
                          ? Math.min(y(Number(bar.low)) + 18, HEIGHT - BOTTOM)
                          : Math.max(y(Number(bar.high)) - 18, TOP)
                      }
                      r="8"
                      fill={marker.side === "BUY" ? "#1677ff" : "#722ed1"}
                    >
                      <title>
                        {marker.label ??
                          (marker.side === "BUY" ? "买入信号" : "卖出信号")}
                      </title>
                    </circle>
                    <text
                      x={x}
                      y={
                        marker.side === "BUY"
                          ? Math.min(
                              y(Number(bar.low)) + 22,
                              HEIGHT - BOTTOM + 4,
                            )
                          : Math.max(y(Number(bar.high)) - 14, TOP + 4)
                      }
                      textAnchor="middle"
                      fill="#fff"
                      fontSize="10"
                    >
                      {marker.side === "BUY" ? "买" : "卖"}
                    </text>
                  </g>
                ) : null}
              </g>
            );
          })
        )}
        {timeTicks.map((index) => {
          const x = LEFT + index * step + step / 2;
          return (
            <text
              key={numeric[index].bar_time}
              x={x}
              y={HEIGHT - 10}
              textAnchor={
                index === 0
                  ? "start"
                  : index === numeric.length - 1
                    ? "end"
                    : "middle"
              }
              fill="#667085"
              fontSize="12"
            >
              {labelTime(numeric[index].bar_time, minute)}
            </text>
          );
        })}
      </svg>
      <Typography.Text type="secondary" className="candle-chart-caption">
        横轴为北京时间，纵轴为价格；
        {variant === "line" ? "蓝线为分钟收盘价。" : "红色上涨，青色下跌。"}
        {markers.length ? " 蓝色为买入信号，紫色为卖出信号。" : null}
        仅展示最近 {numeric.length} 根。
      </Typography.Text>
    </div>
  );
}
