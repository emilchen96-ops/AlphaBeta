import { ReloadOutlined, SyncOutlined } from "@ant-design/icons";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Descriptions,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";

import {
  getActiveSubscriptions,
  getDesiredSubscriptions,
  getMiniQMTStatus,
  getRealtimeQuotes,
  rebuildSubscriptions,
  syncSubscriptions,
} from "../api/miniqmt";
import { PageHeader } from "../components/PageHeader/PageHeader";
import type { RealtimeQuote, SubscriptionItem } from "../types/miniqmt";
import {
  displayEnum,
  formatDateTime,
  formatInstrument,
  formatMoney,
  formatNumber,
  formatPrice,
  formatQuantity,
} from "../utils/display";

const originLabels: Record<string, string> = {
  WATCHLIST: "盘中监控自选股",
  SCANNER: "条件扫描股票池",
  BENCHMARK: "系统基准标的",
  TEMPORARY: "行情详情临时订阅",
};

export function MiniQMTMarketDataPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [originFilter, setOriginFilter] = useState<string>();
  const [statusFilter, setStatusFilter] = useState<string>();
  const status = useQuery({
    queryKey: ["miniqmt-status"],
    queryFn: getMiniQMTStatus,
    refetchInterval: 10_000,
  });
  const desired = useQuery({
    queryKey: ["miniqmt-desired"],
    queryFn: getDesiredSubscriptions,
  });
  const active = useQuery({
    queryKey: ["miniqmt-active"],
    queryFn: getActiveSubscriptions,
    refetchInterval: 10_000,
  });
  const quotes = useQuery({
    queryKey: ["miniqmt-quotes"],
    queryFn: getRealtimeQuotes,
    refetchInterval: 5_000,
  });
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["miniqmt-status"] }),
      queryClient.invalidateQueries({ queryKey: ["miniqmt-desired"] }),
      queryClient.invalidateQueries({ queryKey: ["miniqmt-active"] }),
      queryClient.invalidateQueries({ queryKey: ["miniqmt-quotes"] }),
    ]);
  };
  const rebuild = useMutation({
    mutationFn: rebuildSubscriptions,
    onSuccess: async () => {
      await refresh();
      void message.success("期望订阅已重新计算");
    },
    onError: (error: Error) => void message.error(error.message),
  });
  const sync = useMutation({
    mutationFn: syncSubscriptions,
    onSuccess: async () => {
      await refresh();
      void message.success("订阅同步请求已创建，等待Windows行情代理执行");
    },
    onError: (error: Error) => void message.error(error.message),
  });

  const statusData = status.data;
  const activeById = new Map(
    (active.data?.items ?? []).map((item) => [item.instrument_id, item]),
  );
  const subscriptionRows = (desired.data?.items ?? [])
    .map((item) => ({
      ...item,
      ...activeById.get(item.instrument_id),
      origins: item.origins,
      desired_status: item.desired_status,
    }))
    .filter(
      (item) =>
        (!originFilter || item.origins?.includes(originFilter)) &&
        (!statusFilter || (item.status ?? "WAITING") === statusFilter),
    );

  return (
    <div>
      <PageHeader
        title="MiniQMT 实时行情"
        description="只读连接 MiniQMT 行情，服务于自选股、条件扫描、策略回测和历史数据积累。"
        action={
          <Space>
            <Button
              icon={<SyncOutlined />}
              loading={rebuild.isPending}
              onClick={() => rebuild.mutate()}
            >
              重新计算订阅
            </Button>
            <Button
              type="primary"
              loading={sync.isPending}
              onClick={() => sync.mutate()}
            >
              同步订阅
            </Button>
            <Button icon={<ReloadOutlined />} onClick={() => void refresh()}>
              刷新
            </Button>
          </Space>
        }
      />
      <Alert
        type="info"
        showIcon
        title="当前为只读行情模式"
        description="交易功能：未启用。系统不会读取券商账户、资金、持仓、委托或成交，也不能下单和撤单。"
      />
      {!statusData?.configured ? (
        <Alert
          type="warning"
          showIcon
          title="MiniQMT行情服务尚未配置"
          description="请在本机环境变量中配置MiniQMT数据目录并启动Windows行情代理。"
        />
      ) : null}
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={12} lg={6}>
          <Card>
            <Statistic
              title="MiniQMT行情连接"
              value={displayEnum(statusData?.state)}
            />
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card>
            <Statistic
              title="期望订阅"
              value={desired.data?.desired_count ?? 0}
              suffix="只"
            />
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card>
            <Statistic
              title="实际订阅"
              value={statusData?.active_count ?? 0}
              suffix="只"
            />
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card>
            <Statistic
              title="订阅失败"
              value={statusData?.failed_count ?? 0}
              suffix="只"
            />
          </Card>
        </Col>
      </Row>
      <Tabs
        style={{ marginTop: 16 }}
        items={[
          {
            key: "quotes",
            label: "实时行情",
            children: (
              <Card>
                <Table<RealtimeQuote>
                  rowKey="instrument_id"
                  loading={quotes.isLoading}
                  dataSource={quotes.data?.items ?? []}
                  scroll={{ x: 1500 }}
                  pagination={{ pageSize: 20 }}
                  columns={[
                    {
                      title: "股票",
                      fixed: "left",
                      render: (_, item) => formatInstrument(item),
                    },
                    {
                      title: "最新价",
                      dataIndex: "last_price",
                      render: formatPrice,
                    },
                    {
                      title: "涨跌幅",
                      dataIndex: "change_percent",
                      render: (value: RealtimeQuote["change_percent"]) =>
                        value === null
                          ? "—"
                          : `${formatNumber(value, {
                              minimumFractionDigits: 2,
                              maximumFractionDigits: 2,
                            })}%`,
                    },
                    {
                      title: "涨跌额",
                      dataIndex: "change",
                      render: formatPrice,
                    },
                    {
                      title: "今开",
                      dataIndex: "open_price",
                      render: formatPrice,
                    },
                    {
                      title: "最高",
                      dataIndex: "high_price",
                      render: formatPrice,
                    },
                    {
                      title: "最低",
                      dataIndex: "low_price",
                      render: formatPrice,
                    },
                    {
                      title: "昨收",
                      dataIndex: "previous_close",
                      render: formatPrice,
                    },
                    {
                      title: "成交量",
                      dataIndex: "volume",
                      render: formatQuantity,
                    },
                    {
                      title: "成交额",
                      dataIndex: "amount",
                      render: formatMoney,
                    },
                    {
                      title: "买一",
                      dataIndex: "bid_price_1",
                      render: formatPrice,
                    },
                    {
                      title: "卖一",
                      dataIndex: "ask_price_1",
                      render: formatPrice,
                    },
                    {
                      title: "行情时间",
                      dataIndex: "market_time",
                      render: formatDateTime,
                    },
                    {
                      title: "数据状态",
                      render: (_, item) => (
                        <Space>
                          <Tag color="green">MiniQMT真实行情</Tag>
                          {Date.now() - new Date(item.market_time).getTime() >
                          60_000 ? (
                            <Tag color="orange">行情可能已延迟</Tag>
                          ) : (
                            <Tag color="green">正常</Tag>
                          )}
                        </Space>
                      ),
                    },
                  ]}
                />
              </Card>
            ),
          },
          {
            key: "subscriptions",
            label: "订阅状态",
            children: (
              <Card>
                <Space wrap style={{ marginBottom: 16 }}>
                  <Select
                    aria-label="按订阅来源筛选"
                    placeholder="订阅来源"
                    allowClear
                    value={originFilter}
                    onChange={setOriginFilter}
                    style={{ width: 200 }}
                    options={Object.entries(originLabels).map(
                      ([value, label]) => ({
                        value,
                        label,
                      }),
                    )}
                  />
                  <Select
                    aria-label="按实际状态筛选"
                    placeholder="实际状态"
                    allowClear
                    value={statusFilter}
                    onChange={setStatusFilter}
                    style={{ width: 160 }}
                    options={["SUBSCRIBED", "WAITING", "FAILED", "STOPPED"].map(
                      (value) => ({ value, label: displayEnum(value) }),
                    )}
                  />
                </Space>
                <Table<SubscriptionItem>
                  rowKey="instrument_id"
                  dataSource={subscriptionRows}
                  loading={desired.isLoading || active.isLoading}
                  pagination={{ pageSize: 20 }}
                  columns={[
                    {
                      title: "股票",
                      render: (_, item) => formatInstrument(item),
                    },
                    {
                      title: "订阅来源",
                      dataIndex: "origins",
                      render: (values: string[]) =>
                        values
                          ?.map((value) => originLabels[value] ?? value)
                          .join("、"),
                    },
                    {
                      title: "期望状态",
                      dataIndex: "desired_status",
                      render: displayEnum,
                    },
                    {
                      title: "实际状态",
                      dataIndex: "status",
                      render: (value: SubscriptionItem["status"]) => (
                        <Tag
                          color={value === "SUBSCRIBED" ? "green" : "orange"}
                        >
                          {displayEnum(value ?? "WAITING")}
                        </Tag>
                      ),
                    },
                    {
                      title: "最近行情时间",
                      dataIndex: "last_market_time",
                      render: formatDateTime,
                    },
                    {
                      title: "最近错误",
                      dataIndex: "last_error_message",
                      render: (value: SubscriptionItem["last_error_message"]) =>
                        value || "—",
                    },
                    {
                      title: "数据类型",
                      render: (_, item) =>
                        item.is_test_data ? (
                          <Tag>测试数据</Tag>
                        ) : (
                          <Tag color="green">真实行情</Tag>
                        ),
                    },
                  ]}
                />
              </Card>
            ),
          },
          {
            key: "status",
            label: "连接状态",
            children: (
              <Card>
                <Descriptions column={2} bordered>
                  <Descriptions.Item label="Windows行情代理">
                    {displayEnum(statusData?.agent?.state)}
                  </Descriptions.Item>
                  <Descriptions.Item label="行情数据来源">
                    MiniQMT
                  </Descriptions.Item>
                  <Descriptions.Item label="最近一条行情时间">
                    {formatDateTime(statusData?.agent?.last_market_time)}
                  </Descriptions.Item>
                  <Descriptions.Item label="最近接收时间">
                    {formatDateTime(statusData?.agent?.last_received_at)}
                  </Descriptions.Item>
                  <Descriptions.Item label="最新分钟Bar时间">
                    {formatDateTime(
                      statusData?.agent?.last_minute_bar_time ??
                        statusData?.latest_minute_bar_time,
                    )}
                  </Descriptions.Item>
                  <Descriptions.Item label="交易功能">
                    <Tag>未启用</Tag>
                  </Descriptions.Item>
                </Descriptions>
                {statusData?.agent?.error_message ? (
                  <Typography.Paragraph type="danger" style={{ marginTop: 16 }}>
                    {statusData.agent.error_message}
                  </Typography.Paragraph>
                ) : null}
              </Card>
            ),
          },
        ]}
      />
    </div>
  );
}
