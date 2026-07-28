import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Empty,
  Progress,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import {
  cancelScanRun,
  getScannerCatalog,
  getScanMembers,
  getScanResults,
  getScanRun,
  getScanRuns,
} from "../api/scanners";
import { PageHeader } from "../components/PageHeader/PageHeader";
import type { ScanResult, ScanRun } from "../types/scanners";
import {
  displayParameter,
  displayScanner,
  formatDateTime,
  formatInstrument,
  formatNumber,
  formatPrice,
  shortId,
} from "../utils/display";

const statusText: Record<string, string> = {
  CREATED: "已创建",
  QUEUED: "等待中",
  RESOLVING: "正在解析股票范围",
  CHECKING_DATA: "正在检查历史数据",
  BACKFILLING: "正在补齐历史数据",
  RUNNING: "正在扫描",
  COMPLETED: "已完成",
  PARTIAL: "部分完成",
  PARTIAL_FAILED: "部分股票无法判定",
  FAILED: "运行失败",
  CANCELED: "已取消",
  INCLUDED: "已纳入范围",
  EXCLUDED: "已排除",
  DATA_MISSING: "历史数据不足",
  BACKFILL_REQUESTED: "已请求补数",
  READY: "数据就绪",
  SCANNED: "已扫描未命中",
  MATCHED: "已命中",
  INDETERMINATE: "数据不可判定",
};

const terminalStatuses = new Set([
  "COMPLETED",
  "PARTIAL",
  "PARTIAL_FAILED",
  "FAILED",
  "CANCELED",
]);

function displayMetric(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean" ||
    typeof value === "bigint"
  ) {
    return String(value);
  }
  try {
    return JSON.stringify(value) || "—";
  } catch {
    return "—";
  }
}

export function ScanRunsPage() {
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const [scannerKey, setScannerKey] = useState<string>();
  const [status, setStatus] = useState<string>();
  const catalog = useQuery({
    queryKey: ["scanner-catalog"],
    queryFn: getScannerCatalog,
  });
  const runs = useQuery({
    queryKey: ["scan-runs", page, scannerKey, status],
    queryFn: () =>
      getScanRuns({ page, page_size: 20, scanner_key: scannerKey, status }),
    refetchInterval: 3000,
  });
  return (
    <section>
      <PageHeader
        title="扫描运行"
        description="查看全A股日线扫描任务、数据准备进度和命中数量。"
      />
      <Card>
        <Space wrap style={{ marginBottom: 16 }}>
          <Button type="primary" onClick={() => void navigate("/scanners")}>
            新建全市场扫描
          </Button>
          <Select<string>
            allowClear
            placeholder="扫描器筛选"
            style={{ width: 220 }}
            options={catalog.data?.map((item) => ({
              value: item.scanner_key,
              label: item.display_name,
            }))}
            onChange={(value) => {
              setPage(1);
              setScannerKey(value);
            }}
          />
          <Select<string>
            allowClear
            placeholder="状态筛选"
            style={{ width: 190 }}
            options={[
              "QUEUED",
              "RESOLVING",
              "CHECKING_DATA",
              "BACKFILLING",
              "RUNNING",
              "COMPLETED",
              "PARTIAL",
              "FAILED",
              "CANCELED",
            ].map((value) => ({ value, label: statusText[value] }))}
            onChange={(value) => {
              setPage(1);
              setStatus(value);
            }}
          />
        </Space>
        <Table<ScanRun>
          rowKey="scan_run_id"
          dataSource={runs.data?.items ?? []}
          loading={runs.isLoading}
          locale={{ emptyText: <Empty description="暂无扫描运行" /> }}
          pagination={{
            current: page,
            pageSize: 20,
            total: runs.data?.total ?? 0,
            onChange: setPage,
          }}
          columns={[
            {
              title: "扫描任务",
              render: (_, item) => (
                <Space orientation="vertical" size={0}>
                  <Typography.Text>
                    {displayScanner(item.scanner_key)}
                  </Typography.Text>
                  <Typography.Text type="secondary">
                    {formatDateTime(item.created_at)} ·{" "}
                    {shortId(item.scan_run_id)}
                  </Typography.Text>
                </Space>
              ),
            },
            {
              title: "状态与进度",
              render: (_, item) => (
                <Space orientation="vertical" size={2}>
                  <Tag>{statusText[item.status] ?? item.status}</Tag>
                  <Progress
                    percent={item.progress_percent}
                    size="small"
                    style={{ width: 120 }}
                  />
                </Space>
              ),
            },
            {
              title: "扫描范围",
              render: (_, item) => (
                <Space orientation="vertical" size={0}>
                  <Typography.Text>全部A股</Typography.Text>
                  <Typography.Text type="secondary">
                    总数 {item.total_instruments} · 排除{" "}
                    {item.excluded_instruments}
                  </Typography.Text>
                </Space>
              ),
            },
            { title: "已扫描", dataIndex: "instruments_scanned" },
            { title: "命中", dataIndex: "matches_found" },
            {
              title: "扫描日期",
              render: (_, item) => item.as_of.slice(0, 10),
            },
            {
              title: "操作",
              render: (_, item) => (
                <Button
                  size="small"
                  onClick={() =>
                    void navigate(`/scan-runs/${item.scan_run_id}`)
                  }
                >
                  详情
                </Button>
              ),
            },
          ]}
        />
      </Card>
    </section>
  );
}

export function ScanRunDetailPage() {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const { runId = "" } = useParams();
  const [resultPage, setResultPage] = useState(1);
  const detail = useQuery({
    queryKey: ["scan-run", runId],
    queryFn: () => getScanRun(runId),
    enabled: Boolean(runId),
    refetchInterval: (query) =>
      terminalStatuses.has(query.state.data?.status ?? "") ? false : 2000,
  });
  const results = useQuery({
    queryKey: ["scan-results", runId, resultPage],
    queryFn: () => getScanResults(runId, { page: resultPage, page_size: 50 }),
    enabled: Boolean(runId),
    refetchInterval: () =>
      terminalStatuses.has(detail.data?.status ?? "") ? false : 3000,
  });
  const members = useQuery({
    queryKey: ["scan-members", runId],
    queryFn: () => getScanMembers(runId),
    enabled: Boolean(runId),
    refetchInterval: () =>
      terminalStatuses.has(detail.data?.status ?? "") ? false : 3000,
  });
  const cancel = useMutation({
    mutationFn: () => cancelScanRun(runId),
    onSuccess: () => {
      void message.success("已提交取消请求");
      void detail.refetch();
    },
    onError: (error: Error) => void message.error(error.message),
  });
  const item = detail.data;
  return (
    <section>
      <PageHeader
        title="扫描运行详情"
        description="查看全A股范围解析、MiniQMT数据准备、扫描进度和匹配结果。"
      />
      <Space wrap>
        <Button onClick={() => void navigate("/scan-runs")}>
          返回扫描运行
        </Button>
        <Button onClick={() => void navigate("/market")}>查看行情</Button>
        {item && !terminalStatuses.has(item.status) ? (
          <Button
            danger
            loading={cancel.isPending}
            onClick={() => cancel.mutate()}
          >
            取消任务
          </Button>
        ) : null}
      </Space>
      {item ? (
        <Card style={{ marginTop: 16 }}>
          {item.status === "FAILED" ? (
            <Alert
              type="error"
              title="扫描失败"
              description={item.error?.message ?? "扫描运行失败"}
              style={{ marginBottom: 16 }}
            />
          ) : null}
          {item.status === "PARTIAL" ? (
            <Alert
              type="warning"
              title="扫描已部分完成"
              description="部分股票因历史数据不足或单股计算失败被跳过，请查看下方范围统计。"
              style={{ marginBottom: 16 }}
            />
          ) : null}
          <Progress
            percent={item.progress_percent}
            status={item.status === "FAILED" ? "exception" : undefined}
            format={() => statusText[item.current_phase] ?? item.current_phase}
            style={{ marginBottom: 16 }}
          />
          <Descriptions
            bordered
            column={2}
            items={[
              {
                key: "scanner",
                label: "扫描器",
                children: `${displayScanner(item.scanner_key)} · ${item.scanner_version}`,
              },
              {
                key: "status",
                label: "状态",
                children: statusText[item.status] ?? item.status,
              },
              {
                key: "asof",
                label: "扫描日期",
                children: item.as_of.slice(0, 10),
              },
              { key: "timeframe", label: "数据周期", children: "日线" },
              {
                key: "universe",
                label: "扫描范围",
                children: "全部正常上市A股",
              },
              {
                key: "source",
                label: "数据来源",
                children:
                  item.source_code === "MINIQMT" ? "MiniQMT" : item.source_code,
              },
              {
                key: "scope-count",
                label: "范围统计",
                children: `目录 ${item.total_instruments} · 排除 ${item.excluded_instruments} · 数据就绪 ${item.data_ready_instruments}`,
              },
              {
                key: "scan-count",
                label: "扫描统计",
                children: `已扫描 ${item.instruments_scanned} · 命中 ${item.matches_found} · 历史不足 ${item.insufficient_history} · 失败 ${item.failed_instruments}`,
              },
              {
                key: "params",
                label: "规则参数",
                children: (
                  <Space orientation="vertical" size={2}>
                    {Object.entries(item.parameters).map(([name, value]) => (
                      <Typography.Text key={name}>
                        {displayParameter(name)}：{String(value)}
                      </Typography.Text>
                    ))}
                  </Space>
                ),
              },
              {
                key: "completed",
                label: "完成时间",
                children: item.completed_at
                  ? formatDateTime(item.completed_at)
                  : "—",
              },
            ]}
          />
          <Descriptions
            size="small"
            style={{ marginTop: 16 }}
            items={[
              {
                key: "internal-id",
                label: "扫描任务编号",
                children: (
                  <Typography.Text copyable={{ text: item.scan_run_id }}>
                    {shortId(item.scan_run_id)}
                  </Typography.Text>
                ),
              },
            ]}
          />
          <Typography.Title level={4}>股票范围与数据准备</Typography.Title>
          <Space wrap>
            {Object.entries(members.data?.summary ?? {}).map(
              ([memberStatus, count]) => (
                <Tag key={memberStatus}>
                  {statusText[memberStatus] ?? memberStatus}：{count}
                </Tag>
              ),
            )}
            <Tag>补数请求：{item.backfill_requested}</Tag>
            <Tag>补数入队失败：{item.backfill_failed}</Tag>
          </Space>
          <Typography.Title level={4}>扫描结果</Typography.Title>
          <Table<ScanResult>
            rowKey="scan_result_id"
            dataSource={results.data?.items ?? []}
            pagination={{
              current: resultPage,
              pageSize: 50,
              total: results.data?.total ?? 0,
              onChange: setResultPage,
            }}
            locale={{ emptyText: <Empty description="当前没有匹配结果" /> }}
            columns={[
              { title: "排名", dataIndex: "rank" },
              {
                title: "股票名称与代码",
                render: (_, value) => formatInstrument(value.instrument),
              },
              {
                title: "评分",
                dataIndex: "score",
                render: (value: string | number | null) => formatNumber(value),
              },
              {
                title: "参考价",
                dataIndex: "reference_price",
                render: formatPrice,
              },
              {
                title: "匹配日期",
                render: (_, value) => value.matched_at.slice(0, 10),
              },
              { title: "命中原因", dataIndex: "reason" },
              {
                title: "关键指标",
                render: (_, value) => (
                  <Space orientation="vertical" size={0}>
                    {Object.entries(value.metrics).map(([name, metric]) => (
                      <Typography.Text key={name}>
                        {displayParameter(name)}：{displayMetric(metric)}
                      </Typography.Text>
                    ))}
                  </Space>
                ),
              },
            ]}
          />
        </Card>
      ) : (
        <Typography.Text>加载中…</Typography.Text>
      )}
    </section>
  );
}
