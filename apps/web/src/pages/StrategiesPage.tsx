import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Collapse,
  Empty,
  Space,
  Tag,
  Typography,
} from "antd";
import { useNavigate } from "react-router-dom";

import { getStrategyCatalog } from "../api/strategies";
import { systemCapabilitiesQueryOptions } from "../api/system";
import {
  displayEnum,
  displayParameter,
  displayStrategy,
} from "../utils/display";

const descriptions: Record<string, string> = {
  price_volume_breakout_sma_exit:
    "价格突破近期高点并出现成交量放大时买入，跌破短期均线时退出。",
  volume_breakout: "价格突破近期高点并由成交量确认，跌破近期低点时退出。",
  sma_crossover: "短期均线上穿长期均线时进入，下穿时退出。",
  trend_pullback: "在趋势保持向上时等待价格回踩并重新转强。",
  atr_channel: "使用均线和平均真实波幅构造动态趋势通道。",
};

const category: Record<string, string> = {
  price_volume_breakout_sma_exit: "突破",
  volume_breakout: "突破",
  sma_crossover: "趋势",
  trend_pullback: "趋势",
  atr_channel: "波动率",
};

export function StrategiesPage() {
  const navigate = useNavigate();
  const capabilities = useQuery(systemCapabilitiesQueryOptions);
  const catalog = useQuery({
    queryKey: ["strategy-catalog"],
    queryFn: getStrategyCatalog,
  });
  const unavailable =
    capabilities.data?.items?.find(
      (item) => item.module_key === "strategy_research",
    )?.available === false;

  if (catalog.isError) {
    return (
      <Alert
        showIcon
        type="error"
        title="无法读取策略模板"
        description="请确认 AlphaDesk API 已启动后重试。"
      />
    );
  }

  return (
    <section>
      <Typography.Title level={2}>策略模板</Typography.Title>
      <Typography.Paragraph type="secondary">
        从一个容易理解的模板开始。模板只用于历史研究，不会发送真实交易。
      </Typography.Paragraph>
      <Space orientation="vertical" size="middle" style={{ display: "flex" }}>
        {(catalog.data ?? []).map((item) => (
          <Card
            key={item.strategy_key}
            title={displayStrategy(item.strategy_key)}
            extra={
              <Button
                type="primary"
                disabled={unavailable}
                onClick={() =>
                  void navigate(
                    `/research/backtest?template=${encodeURIComponent(item.strategy_key)}`,
                  )
                }
              >
                使用此策略
              </Button>
            }
          >
            <Typography.Paragraph>
              {descriptions[item.strategy_key] || item.description}
            </Typography.Paragraph>
            <Space wrap>
              <Tag color="blue">
                {category[item.strategy_key] ?? "研究策略"}
              </Tag>
              {item.supported_timeframes.map((timeframe) => (
                <Tag key={timeframe}>{displayEnum(timeframe)}</Tag>
              ))}
            </Space>
            <Collapse
              ghost
              style={{ marginTop: 12 }}
              items={[
                {
                  key: "technical",
                  label: "查看技术详情",
                  children: (
                    <Space orientation="vertical" size={4}>
                      <Typography.Text type="secondary">
                        英文策略键：{item.strategy_key}
                      </Typography.Text>
                      <Typography.Text type="secondary">
                        版本：v{item.version}
                      </Typography.Text>
                      {item.parameters.map((parameter) => (
                        <Typography.Text type="secondary" key={parameter.name}>
                          {displayParameter(parameter.name)}：默认值{" "}
                          {String(parameter.default ?? "必填")}
                        </Typography.Text>
                      ))}
                    </Space>
                  ),
                },
              ]}
            />
          </Card>
        ))}
        {!catalog.isLoading && !catalog.data?.length ? (
          <Empty description="暂无可用策略模板" />
        ) : null}
      </Space>
    </section>
  );
}
