import {
  Alert,
  Button,
  Card,
  Descriptions,
  Space,
  Tag,
  Typography,
} from "antd";
import { Link, useOutletContext, useSearchParams } from "react-router-dom";

import type { AppOutletContext } from "../components/AppLayout/AppLayout";
import { PageHeader } from "../components/PageHeader/PageHeader";

export function SettingsPage() {
  const { status } = useOutletContext<AppOutletContext>();
  const [searchParams] = useSearchParams();
  const isResearchOnly = status?.product_mode !== "FULL_SIMULATION";

  return (
    <section>
      <PageHeader
        title="设置"
        description="查看当前产品模式、行情数据和高级诊断入口。"
      />
      {searchParams.get("restricted") === "trading" ? (
        <Alert
          type="info"
          showIcon
          title="当前为研究模式，交易类页面未启用"
          description="你仍可使用策略回测。回测中的订单和成交属于隔离的历史模拟事实，不会发送到 MiniQMT 或券商。"
        />
      ) : null}
      <Card title="当前产品模式" className="backtest-section">
        <Descriptions column={1}>
          <Descriptions.Item label="模式">
            <Tag color={isResearchOnly ? "blue" : "orange"}>
              {isResearchOnly ? "研究模式" : "完整模拟模式"}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="说明">
            {isResearchOnly
              ? "主界面聚焦行情、选股、策略回测和资讯研究；独立订单、成交、持仓和风控操作已隐藏。"
              : "已开放本地模拟账户、订单、成交和风控页面，但仍不代表实盘交易。"}
          </Descriptions.Item>
          <Descriptions.Item label="正式行情源">
            MiniQMT（只读）
          </Descriptions.Item>
        </Descriptions>
      </Card>
      <Card title="数据与帮助" className="backtest-section">
        <Typography.Paragraph type="secondary">
          日常使用不需要进入底层数据页面。只有行情缺失、K
          线不完整或需要检查同步质量时，再打开数据中心。
        </Typography.Paragraph>
        <Space wrap>
          <Link to="/market-data-center">
            <Button>打开数据中心</Button>
          </Link>
          <Link to="/getting-started">
            <Button>查看开始使用</Button>
          </Link>
          <Link to="/audit">
            <Button>高级诊断</Button>
          </Link>
        </Space>
      </Card>
      <Alert
        className="backtest-section"
        type="warning"
        showIcon
        title="仅限本机使用"
        description="当前未启用用户登录和权限系统，请勿直接部署到公网。密钥和 MiniQMT 配置只应保存在本机未跟踪的 .env 中。"
      />
    </section>
  );
}
