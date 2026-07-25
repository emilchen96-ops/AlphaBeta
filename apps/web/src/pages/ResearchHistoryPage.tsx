import { useQuery } from "@tanstack/react-query";
import { Empty, Table, Tabs, Tag } from "antd";
import { Link, useSearchParams } from "react-router-dom";

import { getAIAnalyses } from "../api/aiResearch";
import { listBacktests } from "../api/backtests";
import { getScanRuns } from "../api/scanners";
import { PageHeader } from "../components/PageHeader/PageHeader";
import {
  displayScanner,
  displayStrategy,
  formatDateTime,
} from "../utils/display";

const statusText: Record<string, string> = {
  CREATED: "已创建",
  QUEUED: "排队中",
  RUNNING: "运行中",
  COMPLETED: "已完成",
  PARTIAL: "部分完成",
  FAILED: "失败",
  CANCELED: "已取消",
};

export function ResearchHistoryPage() {
  const [search, setSearch] = useSearchParams();
  const active = search.get("tab") ?? "backtests";
  const backtests = useQuery({
    queryKey: ["research-history", "backtests"],
    queryFn: () => listBacktests(1),
  });
  const scans = useQuery({
    queryKey: ["research-history", "scans"],
    queryFn: () => getScanRuns({ page: 1, page_size: 20 }),
  });
  const analyses = useQuery({
    queryKey: ["research-history", "ai"],
    queryFn: () => getAIAnalyses({ page: 1, page_size: 20 }),
  });

  return (
    <section>
      <PageHeader
        title="研究记录"
        description="在一个入口查看回测、智能选股和 AI 研究历史。"
      />
      <Tabs
        activeKey={active}
        onChange={(tab) => setSearch({ tab })}
        items={[
          {
            key: "backtests",
            label: "回测记录",
            children: (
              <Table
                rowKey="id"
                loading={backtests.isLoading}
                dataSource={backtests.data?.items ?? []}
                locale={{ emptyText: <Empty description="暂无回测记录" /> }}
                pagination={false}
                columns={[
                  {
                    title: "策略",
                    render: (_, item) => (
                      <Link to={`/research/backtests/${item.id}`}>
                        {displayStrategy(item.strategy_key)}
                      </Link>
                    ),
                  },
                  {
                    title: "状态",
                    render: (_, item) => (
                      <Tag>{statusText[item.status] ?? item.status}</Tag>
                    ),
                  },
                  {
                    title: "总收益率",
                    render: (_, item) =>
                      item.metrics
                        ? `${(Number(item.metrics.total_return) * 100).toFixed(2)}%`
                        : "—",
                  },
                  {
                    title: "最大回撤",
                    render: (_, item) =>
                      item.metrics
                        ? `${(Number(item.metrics.maximum_drawdown) * 100).toFixed(2)}%`
                        : "—",
                  },
                  {
                    title: "完成时间",
                    render: (_, item) =>
                      formatDateTime(item.completed_at ?? item.created_at),
                  },
                ]}
              />
            ),
          },
          {
            key: "scans",
            label: "智能选股记录",
            children: (
              <Table
                rowKey="scan_run_id"
                loading={scans.isLoading}
                dataSource={scans.data?.items ?? []}
                locale={{ emptyText: <Empty description="暂无选股记录" /> }}
                pagination={false}
                columns={[
                  {
                    title: "扫描器",
                    render: (_, item) => (
                      <Link to={`/scan-runs/${item.scan_run_id}`}>
                        {displayScanner(item.scanner_key)}
                      </Link>
                    ),
                  },
                  {
                    title: "状态",
                    render: (_, item) => (
                      <Tag>{statusText[item.status] ?? item.status}</Tag>
                    ),
                  },
                  { title: "已扫描", dataIndex: "instruments_scanned" },
                  { title: "符合条件", dataIndex: "matches_found" },
                  {
                    title: "完成时间",
                    render: (_, item) =>
                      item.completed_at
                        ? formatDateTime(item.completed_at)
                        : "—",
                  },
                ]}
              />
            ),
          },
          {
            key: "ai",
            label: "AI研究记录",
            children: (
              <Table
                rowKey="analysis_id"
                loading={analyses.isLoading}
                dataSource={analyses.data?.items ?? []}
                locale={{ emptyText: <Empty description="暂无 AI 研究记录" /> }}
                pagination={false}
                columns={[
                  {
                    title: "研究类型",
                    dataIndex: "analysis_type",
                  },
                  {
                    title: "状态",
                    render: (_, item) => (
                      <Tag>{statusText[item.status] ?? item.status}</Tag>
                    ),
                  },
                  {
                    title: "创建时间",
                    render: (_, item) => formatDateTime(item.created_at),
                  },
                ]}
              />
            ),
          },
        ]}
      />
    </section>
  );
}
