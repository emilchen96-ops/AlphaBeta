import { Tabs, Typography } from "antd";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

const tabs = [
  { key: "/research/backtest", label: "快速回测" },
  { key: "/research/templates", label: "策略模板" },
  { key: "/research/parameter-comparison", label: "参数对比" },
  { key: "/research/my-strategies", label: "我的策略" },
];

function activeKey(pathname: string) {
  return (
    tabs.find((item) => pathname.startsWith(item.key))?.key ??
    "/research/backtest"
  );
}

export function ResearchWorkspace() {
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <section className="research-workspace">
      <div className="research-workspace-heading">
        <Typography.Title level={1}>策略回测</Typography.Title>
        <Typography.Paragraph type="secondary">
          用自然语言描述策略，确认规则后直接回测；复杂参数与技术细节按需展开。
        </Typography.Paragraph>
      </div>
      <Tabs
        activeKey={activeKey(location.pathname)}
        items={tabs}
        onChange={(key) => void navigate(key)}
      />
      <Outlet />
    </section>
  );
}
