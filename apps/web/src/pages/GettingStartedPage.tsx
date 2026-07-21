import { CheckCircleOutlined, PlayCircleOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Empty,
  Space,
  Steps,
  Tag,
  Typography,
} from "antd";
import { Link } from "react-router-dom";

import {
  initializeResearch,
  researchStatusQueryOptions,
  verifyResearch,
} from "../api/demo";
import { PageHeader } from "../components/PageHeader/PageHeader";

const journey = [
  [
    "检查系统服务",
    "/",
    "infrastructure",
    "Docker 服务已启动",
    "PostgreSQL 与 Redis 在线",
  ],
  [
    "检查历史行情",
    "/market-data-center",
    "historical_market_data",
    "存在 DAY_1 日线",
    "数据中心显示覆盖率",
  ],
  [
    "执行研究初始化",
    "/getting-started",
    "migrations",
    "迁移位于唯一 head",
    "初始化返回 READY",
  ],
  ["运行 Scanner", "/scanners", "scanner", "研究标的有日线", "扫描运行可打开"],
  [
    "运行 Strategy",
    "/strategies",
    "strategy_research",
    "策略参数合法",
    "StrategyRun 与 Signal 可查看",
  ],
  [
    "运行 Backtest",
    "/backtest",
    "daily_backtest",
    "日线覆盖请求区间",
    "指标与 Integrity 通过",
  ],
  [
    "运行历史回放",
    "/replays",
    "historical_replay",
    "历史日线和 replay_worker 已就绪",
    "可启动、暂停、单步并查看权益与事件",
  ],
  [
    "录入资讯",
    "/information",
    "information_center",
    "提供原始来源",
    "InformationItem 与事件可追溯",
  ],
  [
    "运行 Fake AI 演示",
    "/ai-research",
    "ai_research",
    "选择资讯或事件事实",
    "Insight 含 Evidence",
  ],
  [
    "创建模拟订单",
    "/orders",
    "orders",
    "U01-DEMO 可用",
    "风控决策与订单已保存",
  ],
  [
    "查看模拟成交和账本",
    "/fills",
    "accounting",
    "订单已确认并模拟执行",
    "Fill 与 Reconciliation 可查看",
  ],
] as const;

export function GettingStartedPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const status = useQuery(researchStatusQueryOptions);
  const initialize = useMutation({
    mutationFn: initializeResearch,
    onSuccess: async (result) => {
      message.success(`研究环境初始化完成：${result.status}`);
      await queryClient.invalidateQueries({
        queryKey: ["research-demo-status"],
      });
      await queryClient.invalidateQueries({
        queryKey: ["system-capabilities"],
      });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const verify = useMutation({
    mutationFn: verifyResearch,
    onSuccess: (result) => {
      queryClient.setQueryData(["research-demo-status"], result);
      message.success(`验收完成：${result.status}`);
    },
    onError: (error: Error) => message.error(error.message),
  });

  return (
    <section>
      <PageHeader
        title="开始使用 AlphaDesk"
        description="从空数据库到一套可查看、可重放、可追溯的本地研究流程。"
        action={
          <Space wrap>
            <Button loading={verify.isPending} onClick={() => verify.mutate()}>
              只读验收
            </Button>
            <Button
              type="primary"
              icon={<PlayCircleOutlined />}
              loading={initialize.isPending}
              onClick={() => initialize.mutate("fixture")}
            >
              一键创建演示研究环境
            </Button>
          </Space>
        }
      />
      <Alert
        showIcon
        type="info"
        title="演示模式不会下载外部数据，也不会连接真实券商"
        description="所有演示事实均带 U01_DEMO 标记；AI 使用 Fake Provider，订单只进入本地模拟 Broker。"
      />
      <Card
        title="当前可用性"
        className="details-card"
        loading={status.isLoading}
      >
        {status.isError ? (
          <Alert
            type="warning"
            showIcon
            title="暂时无法读取验收状态"
            description={status.error.message}
          />
        ) : null}
        {status.data?.items.length ? (
          <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
            {status.data.items.map((item) => (
              <Card key={item.key} size="small">
                <Space
                  orientation="vertical"
                  size="small"
                  style={{ width: "100%" }}
                >
                  <Space wrap>
                    <CheckCircleOutlined />
                    <Typography.Text strong>{item.label}</Typography.Text>
                    <Tag
                      color={item.status === "READY" ? "success" : "default"}
                    >
                      {item.status}
                    </Tag>
                    {item.link ? <Link to={item.link}>打开</Link> : null}
                  </Space>
                  <Typography.Text type="secondary">
                    {item.reason}
                  </Typography.Text>
                </Space>
              </Card>
            ))}
          </Space>
        ) : (
          <Empty description="启动 API 后点击“只读验收”" />
        )}
      </Card>
      <Card title="推荐的完整研究路径" className="details-card">
        <Steps
          orientation="vertical"
          size="small"
          items={journey.map(([title, link, key, condition, success]) => {
            const item = status.data?.items.find(
              (candidate) => candidate.key === key,
            );
            return {
              title: (
                <Space>
                  <Link to={link}>{title}</Link>
                  <Tag>{item?.status ?? "待检查"}</Tag>
                </Space>
              ),
              content: (
                <Typography.Text type="secondary">
                  所需条件：{condition}；成功标准：{success}。
                </Typography.Text>
              ),
            };
          })}
        />
      </Card>
    </section>
  );
}
