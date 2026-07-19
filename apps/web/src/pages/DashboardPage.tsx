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
  Table,
  Tag,
  Typography,
} from "antd";
import { useQuery } from "@tanstack/react-query";
import { useOutletContext } from "react-router-dom";

import type { AppOutletContext } from "../components/AppLayout/AppLayout";
import { PageHeader } from "../components/PageHeader/PageHeader";
import { ServiceStatus } from "../components/ServiceStatus/ServiceStatus";
import { systemCapabilitiesQueryOptions } from "../api/system";
import type { SystemCapability } from "../types/system";

const moduleLabels: Record<string, string> = {
  market_data: "历史行情",
  scanner: "条件扫描",
  strategy_research: "策略研究",
  strategy_experiments: "批量研究",
  information_center: "资讯中心",
  ai_research: "AI 研究",
  orders: "订单",
  risk: "风控",
  simulated_broker: "模拟 Broker",
  backtest: "回测",
  realtime_market_data: "实时行情",
  miniqmt: "MiniQMT",
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
        description="查看 AlphaDesk 本地基础设施的真实连接状态。"
        action={
          <Button
            icon={<SyncOutlined />}
            onClick={() => void refresh()}
            loading={isLoading}
          >
            刷新状态
          </Button>
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
            <Table<SystemCapability>
              rowKey="module_key"
              size="small"
              loading={capabilities.isLoading}
              dataSource={capabilities.data?.items ?? []}
              pagination={false}
              scroll={{ x: 900 }}
              columns={[
                {
                  title: "模块",
                  render: (_, item) =>
                    moduleLabels[item.module_key] ?? item.module_key,
                },
                {
                  title: "实现",
                  render: (_, item) =>
                    capabilityStatusLabels[item.implementation_status],
                },
                {
                  title: "数据",
                  render: (_, item) => capabilityStatusLabels[item.data_status],
                },
                {
                  title: "配置",
                  render: (_, item) =>
                    capabilityStatusLabels[item.configuration_status],
                },
                {
                  title: "当前可用",
                  render: (_, item) => (
                    <Tag color={item.available ? "success" : "default"}>
                      {item.available ? "可用" : "不可用"}
                    </Tag>
                  ),
                },
                { title: "说明", dataIndex: "reason" },
              ]}
            />
          </Card>
        </>
      ) : null}
    </section>
  );
}
