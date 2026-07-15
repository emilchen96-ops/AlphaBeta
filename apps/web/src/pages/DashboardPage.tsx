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
  Typography,
} from "antd";
import { useOutletContext } from "react-router-dom";

import type { AppOutletContext } from "../components/AppLayout/AppLayout";
import { PageHeader } from "../components/PageHeader/PageHeader";
import { ServiceStatus } from "../components/ServiceStatus/ServiceStatus";

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
        </>
      ) : null}
    </section>
  );
}
