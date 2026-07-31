import {
  AppstoreOutlined,
  BarChartOutlined,
  DatabaseOutlined,
  ExperimentOutlined,
  FilterOutlined,
  HistoryOutlined,
  HeartOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  NotificationOutlined,
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
  { key: "/", icon: <AppstoreOutlined />, label: "首页" },
  { key: "/market", icon: <BarChartOutlined />, label: "行情" },
  { key: "/watchlists", icon: <HeartOutlined />, label: "自选股" },
  { key: "/scanners", icon: <FilterOutlined />, label: "智能选股" },
  {
    key: "/research/backtest",
    icon: <ExperimentOutlined />,
    label: "策略回测",
  },
  { key: "/ai-research", icon: <NotificationOutlined />, label: "AI调研" },
  { key: "/research/archive", icon: <HistoryOutlined />, label: "研究档案" },
  {
    key: "/market-data-center",
    icon: <DatabaseOutlined />,
    label: "数据中心",
  },
  { key: "/settings", icon: <SettingOutlined />, label: "设置" },
];

function selectedMenuKey(pathname: string) {
  if (
    [
      "/backtest",
      "/strategies",
      "/strategy-experiments",
      "/strategy-runs",
      "/signals",
      "/replays",
      "/research/backtest",
      "/research/templates",
      "/research/parameter-comparison",
      "/research/my-strategies",
    ].some((prefix) => pathname.startsWith(prefix))
  ) {
    return "/research/backtest";
  }
  if (
    pathname.startsWith("/research/history") ||
    pathname.startsWith("/research/archive")
  )
    return "/research/archive";
  if (pathname.startsWith("/watchlists")) return "/watchlists";
  if (
    [
      "/information",
      "/market-events",
      "/ai-research",
      "/ai-analyses",
      "/research-insights",
    ].some((prefix) => pathname.startsWith(prefix))
  ) {
    return "/ai-research";
  }
  if (pathname.startsWith("/scan-runs")) return "/scanners";
  if (
    pathname.startsWith("/getting-started") ||
    pathname.startsWith("/audit") ||
    pathname.startsWith("/portfolio") ||
    pathname.startsWith("/orders") ||
    pathname.startsWith("/fills") ||
    pathname.startsWith("/risk")
  ) {
    return "/settings";
  }
  if (pathname.startsWith("/market-data-center")) return "/market-data-center";
  return (
    menuItems.find((item) => pathname.startsWith(item.key) && item.key !== "/")
      ?.key ?? (pathname === "/" ? "/" : "")
  );
}

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
  const selectedKey = selectedMenuKey(location.pathname);
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
            <Tag
              color={
                status?.product_mode === "FULL_SIMULATION" ? "orange" : "blue"
              }
            >
              {status?.product_mode === "FULL_SIMULATION"
                ? "完整模拟模式"
                : "研究模式"}
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
