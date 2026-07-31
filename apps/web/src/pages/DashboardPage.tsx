import {
  ApiOutlined,
  CloudServerOutlined,
  DatabaseOutlined,
  GlobalOutlined,
  SyncOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Row,
  Skeleton,
  Space,
  Tag,
  Typography,
} from "antd";
import { useQuery } from "@tanstack/react-query";
import { Link, useOutletContext } from "react-router-dom";

import type { AppOutletContext } from "../components/AppLayout/AppLayout";
import { PageHeader } from "../components/PageHeader/PageHeader";
import { ServiceStatus } from "../components/ServiceStatus/ServiceStatus";
import { systemCapabilitiesQueryOptions } from "../api/system";
import type { SystemCapability } from "../types/system";

const moduleLabels: Record<string, string> = {
  infrastructure: "基础设施",
  historical_market_data: "历史行情",
  scanner: "条件扫描",
  strategy_research: "策略回测",
  strategy_experiments: "批量研究",
  information_center: "资讯中心",
  ai_research: "AI 研究",
  orders: "订单",
  risk: "风控",
  simulated_broker: "模拟 Broker",
  daily_backtest: "日线回测",
  realtime_market_data: "实时行情",
  miniqmt: "MiniQMT",
  audit: "审计中心",
  settings: "设置",
};

const capabilityStatusLabels: Record<string, string> = {
  WORKING: "已实现",
  PARTIAL: "部分完成",
  PLACEHOLDER: "占位",
  NOT_IMPLEMENTED: "未实现",
  READY: "就绪",
  MISSING: "缺数据",
  DISABLED: "未启用",
  NOT_REQUIRED: "不需要",
  UNKNOWN: "未知",
  NEEDS_DATA: "需要数据",
  NEEDS_CONFIG: "需要配置",
  DEMO_ONLY: "仅演示",
};

const moduleLinks: Record<string, string> = {
  infrastructure: "/",
  historical_market_data: "/market-data-center",
  scanner: "/scanners",
  strategy_research: "/strategies",
  strategy_experiments: "/strategy-experiments",
  information_center: "/information",
  ai_research: "/ai-research",
  orders: "/orders",
  risk: "/risk/decisions",
  simulated_broker: "/fills",
  daily_backtest: "/backtest",
  realtime_market_data: "/market",
  miniqmt: "/settings",
  audit: "/audit",
  settings: "/settings",
};

function formatUtc(value: string | number | undefined): string {
  if (!value) return "—";
  return `${new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "medium",
    timeZone: "UTC",
  }).format(new Date(value))} UTC`;
}

export function DashboardPage() {
  const context = useOutletContext<AppOutletContext>();
  const {
    status,
    websocketStatus,
    isLoading,
    isError,
    lastUpdatedAt,
    refresh,
  } = context;
  const capabilities = useQuery(systemCapabilitiesQueryOptions);

  return (
    <section>
      <PageHeader
        title="系统总览"
        description="查看基础设施和研究功能的真实可用状态。"
        action={
          <Space wrap>
            <Link to="/getting-started">
              <Button type="primary">开始使用</Button>
            </Link>
            <Button
              icon={<SyncOutlined />}
              onClick={() => void refresh()}
              loading={isLoading}
            >
              刷新状态
            </Button>
          </Space>
        }
      />

      {isLoading ? (
        <Card>
          <Skeleton active paragraph={{ rows: 5 }} />
        </Card>
      ) : null}

      {isError ? (
        <Alert
          type="error"
          showIcon
          title="无法获取系统状态"
          description="FastAPI 可能尚未启动或请求已超时。页面仍可继续使用，恢复服务后请重试。"
          action={<Button onClick={() => void refresh()}>重新连接</Button>}
        />
      ) : null}

      {!isLoading && !isError && status ? (
        <>
          <Row gutter={[16, 16]} className="status-grid">
            <Col xs={24} sm={12} xl={8}>
              <Card className="status-card">
                <GlobalOutlined className="status-icon" />
                <ServiceStatus name="Web 前端" status="normal" />
                <Typography.Text type="secondary">
                  当前管理后台已加载
                </Typography.Text>
              </Card>
            </Col>
            <Col xs={24} sm={12} xl={8}>
              <Card className="status-card">
                <ApiOutlined className="status-icon" />
                <ServiceStatus name="FastAPI" status={status.api} />
                <Typography.Text type="secondary">基础状态接口</Typography.Text>
              </Card>
            </Col>
            <Col xs={24} sm={12} xl={8}>
              <Card className="status-card">
                <DatabaseOutlined className="status-icon" />
                <ServiceStatus name="PostgreSQL" status={status.postgresql} />
                <Typography.Text type="secondary">M01 连接探测</Typography.Text>
              </Card>
            </Col>
            <Col xs={24} sm={12} xl={8}>
              <Card className="status-card">
                <DatabaseOutlined className="status-icon" />
                <ServiceStatus name="Redis" status={status.redis} />
                <Typography.Text type="secondary">
                  未启用 Streams
                </Typography.Text>
              </Card>
            </Col>
            <Col xs={24} sm={12} xl={8}>
              <Card className="status-card">
                <CloudServerOutlined className="status-icon" />
                <ServiceStatus name="WebSocket" status={websocketStatus} />
                <Typography.Text type="secondary">
                  仅用于实时展示连接
                </Typography.Text>
              </Card>
            </Col>
          </Row>

          <Card title="运行信息" className="details-card">
            <Descriptions column={{ xs: 1, sm: 2, lg: 3 }}>
              <Descriptions.Item label="应用版本">
                {status.version}
              </Descriptions.Item>
              <Descriptions.Item label="运行环境">
                {status.environment}
              </Descriptions.Item>
              <Descriptions.Item label="服务端时间">
                {formatUtc(status.server_time)}
              </Descriptions.Item>
              <Descriptions.Item label="最近刷新">
                {formatUtc(lastUpdatedAt)}
              </Descriptions.Item>
              <Descriptions.Item label="链路标识" span={2}>
                <Typography.Text code copyable>
                  {status.correlation_id}
                </Typography.Text>
              </Descriptions.Item>
            </Descriptions>
          </Card>

          <Card title="功能可用性（后端权威检查）" className="details-card">
            {capabilities.isError ? (
              <Alert
                showIcon
                type="warning"
                title="暂时无法读取功能可用性"
                description={capabilities.error.message}
              />
            ) : null}
            <Row gutter={[16, 16]}>
              {(capabilities.data?.items ?? []).map(
                (item: SystemCapability) => (
                  <Col xs={24} md={12} xl={8} key={item.module_key}>
                    <Card size="small" className="capability-card">
                      <Space
                        orientation="vertical"
                        size={6}
                        style={{ width: "100%" }}
                      >
                        <Space wrap>
                          <Typography.Text strong>
                            {moduleLabels[item.module_key] ?? item.module_key}
                          </Typography.Text>
                          <Tag color={item.available ? "success" : "default"}>
                            {
                              capabilityStatusLabels[
                                item.availability ?? item.data_status
                              ]
                            }
                          </Tag>
                        </Space>
                        <Typography.Text type="secondary">
                          {item.reason}
                        </Typography.Text>
                        <Typography.Text type="secondary">
                          实现：
                          {capabilityStatusLabels[item.implementation_status]} ·
                          数据：
                          {capabilityStatusLabels[item.data_status]} · 配置：
                          {capabilityStatusLabels[item.configuration_status]}
                        </Typography.Text>
                        <Typography.Text type="secondary">
                          最近成功：
                          {formatUtc(item.last_success_at ?? undefined)} ·
                          Provider：
                          {item.provider ?? "—"} · 模式：{item.mode ?? "—"}
                        </Typography.Text>
                        {item.required_actions[0] ? (
                          <Typography.Text>
                            下一步：{item.required_actions[0]}
                          </Typography.Text>
                        ) : null}
                        <Link
                          to={
                            moduleLinks[item.module_key] ?? "/getting-started"
                          }
                        >
                          打开模块
                        </Link>
                      </Space>
                    </Card>
                  </Col>
                ),
              )}
            </Row>
          </Card>
        </>
      ) : null}
    </section>
  );
}
