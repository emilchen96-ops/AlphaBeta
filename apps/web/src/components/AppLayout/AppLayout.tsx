import {
  AppstoreOutlined,
  AuditOutlined,
  BarChartOutlined,
  DatabaseOutlined,
  ExperimentOutlined,
  FilterOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  NotificationOutlined,
  OrderedListOutlined,
  PieChartOutlined,
  RobotOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Button, Layout, Menu, Tag, Typography } from "antd";
import { useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

import { systemStatusQueryOptions } from "../../api/system";
import { useSystemWebSocket } from "../../hooks/useSystemWebSocket";
import type { SystemStatus, WebSocketState } from "../../types/system";
import { ServiceStatus } from "../ServiceStatus/ServiceStatus";

const { Header, Sider, Content, Footer } = Layout;

const menuItems = [
  { key: "/", icon: <AppstoreOutlined />, label: "总览" },
  { key: "/market-data-center", icon: <DatabaseOutlined />, label: "数据中心" },
  { key: "/market", icon: <BarChartOutlined />, label: "行情" },
  { key: "/portfolio", icon: <PieChartOutlined />, label: "持仓" },
  { key: "/scanners", icon: <FilterOutlined />, label: "条件扫描" },
  { key: "/scan-runs", icon: <DatabaseOutlined />, label: "扫描运行" },
  { key: "/information", icon: <NotificationOutlined />, label: "资讯中心" },
  { key: "/market-events", icon: <AuditOutlined />, label: "市场事件" },
  { key: "/ai-research", icon: <RobotOutlined />, label: "AI 研究" },
  { key: "/strategies", icon: <ExperimentOutlined />, label: "策略" },
  {
    key: "/strategy-experiments",
    icon: <ExperimentOutlined />,
    label: "批量研究",
  },
  { key: "/strategy-runs", icon: <DatabaseOutlined />, label: "研究运行" },
  { key: "/signals", icon: <AuditOutlined />, label: "研究 Signal" },
  { key: "/orders", icon: <OrderedListOutlined />, label: "订单" },
  { key: "/fills", icon: <DatabaseOutlined />, label: "成交记录" },
  {
    key: "risk-group",
    icon: <SafetyCertificateOutlined />,
    label: "风控",
    children: [
      { key: "/risk/decisions", label: "风控决策" },
      { key: "/risk/limits", label: "当前限制" },
    ],
  },
  { key: "/backtest", icon: <DatabaseOutlined />, label: "日线回测" },
  { key: "/audit", icon: <AuditOutlined />, label: "审计（计划）" },
  { key: "/settings", icon: <SettingOutlined />, label: "设置（只读）" },
];

export interface AppOutletContext {
  status: SystemStatus | undefined;
  websocketStatus: WebSocketState;
  isLoading: boolean;
  isError: boolean;
  lastUpdatedAt: number;
  refresh: () => Promise<unknown>;
}

export function AppLayout() {
  const [collapsed, setCollapsed] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const statusQuery = useQuery(systemStatusQueryOptions);
  const websocket = useSystemWebSocket();
  const selectedKey = location.pathname.startsWith("/risk/limits")
    ? "/risk/limits"
    : location.pathname.startsWith("/risk")
      ? "/risk/decisions"
      : (menuItems.find(
          (item) => location.pathname.startsWith(item.key) && item.key !== "/",
        )?.key ?? (location.pathname === "/" ? "/" : ""));
  const status = statusQuery.data;

  return (
    <Layout className="app-shell">
      <Sider
        className="app-sider"
        collapsible
        collapsed={collapsed}
        trigger={null}
        width={220}
      >
        <div className="brand-block" aria-label="AlphaDesk">
          <span className="brand-mark">A</span>
          {!collapsed ? <span className="brand-name">AlphaDesk</span> : null}
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selectedKey]}
          items={menuItems}
          onClick={({ key }) => void navigate(key)}
        />
      </Sider>
      <Layout>
        <Header className="app-header">
          <div className="header-left">
            <Button
              type="text"
              aria-label={collapsed ? "展开导航" : "折叠导航"}
              icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
              onClick={() => setCollapsed((current) => !current)}
            />
            <Typography.Text strong>个人量化工作台</Typography.Text>
          </div>
          <div className="header-status">
            <Tag color={status?.environment === "production" ? "red" : "blue"}>
              {status?.environment ?? "本地开发"}
            </Tag>
            <ServiceStatus
              name="系统连接"
              status={statusQuery.isSuccess ? "online" : "offline"}
              compact
            />
          </div>
        </Header>
        <Content className="app-content">
          <Outlet
            context={
              {
                status,
                websocketStatus: websocket.status,
                isLoading: statusQuery.isLoading,
                isError: statusQuery.isError,
                lastUpdatedAt: statusQuery.dataUpdatedAt,
                refresh: statusQuery.refetch,
              } satisfies AppOutletContext
            }
          />
        </Content>
        <Footer className="app-footer">
          <ServiceStatus name="Web" status="normal" compact />
          <ServiceStatus
            name="API"
            status={statusQuery.isSuccess ? "online" : "offline"}
            compact
          />
          <ServiceStatus
            name="PostgreSQL"
            status={status?.postgresql ?? "offline"}
            compact
          />
          <ServiceStatus
            name="Redis"
            status={status?.redis ?? "offline"}
            compact
          />
          <ServiceStatus name="WebSocket" status={websocket.status} compact />
        </Footer>
      </Layout>
    </Layout>
  );
}
