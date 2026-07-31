import { useQuery } from "@tanstack/react-query";
import {
  DatePicker,
  Empty,
  Input,
  Segmented,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { getAIAnalyses } from "../api/aiResearch";
import { listBacktests } from "../api/backtests";
import { getScreeningRuns } from "../api/screenings";
import { listBacktestBatches } from "../api/strategySpecs";
import { PageHeader } from "../components/PageHeader/PageHeader";
import type { BacktestRun } from "../types/backtests";
import { displayStrategy, formatDateTime } from "../utils/display";

const { RangePicker } = DatePicker;

const statusText: Record<string, string> = {
  CREATED: "已创建",
  QUEUED: "排队中",
  RESOLVING: "准备股票范围",
  CHECKING_DATA: "检查行情",
  BACKFILLING: "补充行情",
  RUNNING: "运行中",
  COMPLETED: "已完成",
  PARTIAL: "部分完成",
  PARTIAL_FAILED: "部分失败",
  FAILED: "失败",
  CANCELED: "已取消",
  CANCELLED: "已取消",
};

const aiTypeText: Record<string, string> = {
  EVENT_SUMMARY: "事件摘要调研",
  INSTRUMENT_IMPACT: "个股影响分析",
  MULTI_EVENT_SYNTHESIS: "多事件综合分析",
  RESEARCH_QUESTION: "自定义问题调研",
};

type ArchiveKind = "backtest" | "batch" | "screening" | "ai";

interface ArchiveRow {
  key: string;
  kind: ArchiveKind;
  title: string;
  subtitle: string;
  status: string;
  createdAt: string;
  href: string;
  result: string;
}

const resultPercent = (value: string | null | undefined) =>
  value == null ? "—" : `${(Number(value) * 100).toFixed(2)}%`;

function backtestTitle(item: BacktestRun) {
  return (
    item.display_name ??
    `${item.instrument_display ?? "历史标的"} · ${
      item.strategy_display_name ?? displayStrategy(item.strategy_key)
    }`
  );
}

export function ResearchHistoryPage() {
  const [search, setSearch] = useSearchParams();
  const active = search.get("tab") ?? "all";
  const [backtestMode, setBacktestMode] = useState<"single" | "batch">(
    (search.get("mode") as "single" | "batch") ?? "single",
  );
  const [keyword, setKeyword] = useState("");
  const [status, setStatus] = useState<string>();
  const [dateRange, setDateRange] = useState<[Dayjs, Dayjs] | null>(null);

  const backtests = useQuery({
    queryKey: ["research-archive", "backtests"],
    queryFn: () => listBacktests(1),
  });
  const scans = useQuery({
    queryKey: ["research-archive", "scans"],
    queryFn: () => getScreeningRuns(),
  });
  const batches = useQuery({
    queryKey: ["research-archive", "backtest-batches"],
    queryFn: listBacktestBatches,
    refetchInterval: (query) =>
      query.state.data?.items.some((item) =>
        ["CREATED", "RUNNING"].includes(item.status),
      )
        ? 3000
        : false,
  });
  const analyses = useQuery({
    queryKey: ["research-archive", "ai"],
    queryFn: () => getAIAnalyses({ page: 1, page_size: 100 }),
  });

  const singleRows = useMemo<ArchiveRow[]>(
    () =>
      (backtests.data?.items ?? []).map((item) => ({
        key: `backtest-${item.id}`,
        kind: "backtest",
        title: backtestTitle(item),
        subtitle:
          item.strategy_summary ??
          `${item.backtest_type ?? "单股回测"} · ${item.sessions_processed} 个交易日`,
        status: item.status,
        createdAt: item.completed_at ?? item.created_at,
        href: `/research/backtests/${item.id}`,
        result: `收益 ${resultPercent(item.metrics?.total_return)} · 回撤 ${resultPercent(
          item.metrics?.maximum_drawdown,
        )} · 成交 ${item.fills_generated}`,
      })),
    [backtests.data],
  );
  const batchRows = useMemo<ArchiveRow[]>(
    () =>
      (batches.data?.items ?? []).map((item) => ({
        key: `batch-${item.id}`,
        kind: "batch",
        title: item.name,
        subtitle: `${
          item.scope === "ALL_A_SHARES" ? "全 A 股" : "自选组合"
        }逐股独立回测 · ${item.total_count} 只`,
        status: item.status,
        createdAt: item.completed_at ?? item.created_at,
        href: `/research/backtest-batches/${item.id}`,
        result: `完成 ${item.completed_count} · 失败 ${item.failed_count} · 进度 ${item.progress_percent}%`,
      })),
    [batches.data],
  );
  const scanRows = useMemo<ArchiveRow[]>(
    () =>
      (scans.data?.items ?? []).map((item) => ({
        key: `scan-${item.screening_id}`,
        kind: "screening",
        title: item.name || "自定义智能选股",
        subtitle: `${item.spec.as_of_date} · 全 A 股${
          item.spec.universe_spec.exclude_st ? " · 排除 ST" : ""
        } · ${item.spec.conditions.length} 项条件`,
        status: item.status,
        createdAt: item.completed_at ?? item.created_at,
        href: `/scanners?tab=history&run=${item.screening_id}`,
        result: `检查 ${item.processed_instruments} 只 · 入选 ${item.matched_count} 只 · 数据不足 ${item.insufficient_data_count} 只`,
      })),
    [scans.data],
  );
  const aiRows = useMemo<ArchiveRow[]>(
    () =>
      (analyses.data?.items ?? []).map((item) => ({
        key: `ai-${item.analysis_id}`,
        kind: "ai",
        title:
          item.insight?.title ??
          item.user_question ??
          aiTypeText[item.analysis_type] ??
          "AI 调研",
        subtitle: `${aiTypeText[item.analysis_type] ?? item.analysis_type} · ${
          item.input_document_ids.length
        } 份资料 · ${item.input_event_ids.length} 个事件`,
        status: item.status,
        createdAt: item.completed_at ?? item.created_at,
        href: `/ai-analyses/${item.analysis_id}`,
        result: item.insight?.summary ?? (item.error?.message || "查看调研报告"),
      })),
    [analyses.data],
  );

  const filterRows = (items: ArchiveRow[]) =>
    items.filter((item) => {
      if (status && item.status !== status) return false;
      if (
        keyword &&
        !`${item.title} ${item.subtitle} ${item.result}`
          .toLowerCase()
          .includes(keyword.toLowerCase())
      )
        return false;
      if (dateRange) {
        const value = dayjs(item.createdAt);
        if (
          value.isBefore(dateRange[0].startOf("day")) ||
          value.isAfter(dateRange[1].endOf("day"))
        )
          return false;
      }
      return true;
    });

  const allRows = filterRows([
    ...singleRows,
    ...batchRows,
    ...scanRows,
    ...aiRows,
  ]).sort((a, b) => b.createdAt.localeCompare(a.createdAt));

  const archiveTable = (rows: ArchiveRow[], loading: boolean) => (
    <Table<ArchiveRow>
      rowKey="key"
      loading={loading}
      dataSource={filterRows(rows)}
      locale={{ emptyText: <Empty description="暂无符合条件的档案" /> }}
      pagination={{ pageSize: 20, showSizeChanger: false }}
      columns={[
        {
          title: "档案",
          render: (_, item) => (
            <Space direction="vertical" size={2}>
              <Link to={item.href}>{item.title}</Link>
              <Typography.Text type="secondary">
                {item.subtitle}
              </Typography.Text>
            </Space>
          ),
        },
        {
          title: "类型",
          width: 120,
          render: (_, item) =>
            ({
              backtest: "单股回测",
              batch: "批量回测",
              screening: "智能选股",
              ai: "AI 调研",
            })[item.kind],
        },
        {
          title: "状态",
          width: 120,
          render: (_, item) => (
            <Tag>{statusText[item.status] ?? item.status}</Tag>
          ),
        },
        { title: "结果摘要", dataIndex: "result", ellipsis: true },
        {
          title: "完成/创建时间",
          width: 180,
          render: (_, item) => formatDateTime(item.createdAt),
        },
      ]}
    />
  );

  const loading =
    backtests.isLoading ||
    batches.isLoading ||
    scans.isLoading ||
    analyses.isLoading;

  return (
    <section>
      <PageHeader
        title="研究档案"
        description="统一查看智能选股、策略回测和 AI 调研的可追溯历史。"
      />
      <Space wrap style={{ marginBottom: 16 }}>
        <Input.Search
          allowClear
          placeholder="搜索股票、策略、选股方案或调研主题"
          style={{ width: 320 }}
          onChange={(event) => setKeyword(event.target.value)}
        />
        <Select
          allowClear
          placeholder="状态"
          style={{ width: 150 }}
          options={Object.entries(statusText).map(([value, label]) => ({
            value,
            label,
          }))}
          onChange={setStatus}
        />
        <RangePicker
          placeholder={["开始日期", "结束日期"]}
          onChange={(value) =>
            setDateRange(value ? [value[0]!, value[1]!] : null)
          }
        />
      </Space>
      <Tabs
        activeKey={active}
        onChange={(tab) => setSearch({ tab })}
        items={[
          {
            key: "all",
            label: "全部档案",
            children: archiveTable(allRows, loading),
          },
          {
            key: "backtests",
            label: "策略回测",
            children: (
              <>
                <Segmented
                  value={backtestMode}
                  options={[
                    { label: "单股回测", value: "single" },
                    { label: "批量回测", value: "batch" },
                  ]}
                  onChange={(value) => {
                    const mode = value as "single" | "batch";
                    setBacktestMode(mode);
                    setSearch({ tab: "backtests", mode });
                  }}
                  style={{ marginBottom: 16 }}
                />
                {archiveTable(
                  backtestMode === "single" ? singleRows : batchRows,
                  backtestMode === "single"
                    ? backtests.isLoading
                    : batches.isLoading,
                )}
              </>
            ),
          },
          {
            key: "scans",
            label: "智能选股",
            children: archiveTable(scanRows, scans.isLoading),
          },
          {
            key: "ai",
            label: "AI 调研",
            children: archiveTable(aiRows, analyses.isLoading),
          },
        ]}
      />
    </section>
  );
}
