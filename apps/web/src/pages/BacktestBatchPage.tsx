import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  Progress,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from "antd";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  backtestBatchCsvUrl,
  cancelBacktestBatch,
  getBacktestBatch,
  getBacktestBatchResults,
  getBacktestBatchSummary,
  retryFailedBacktestBatch,
} from "../api/strategySpecs";
import { PageHeader } from "../components/PageHeader/PageHeader";
import type { BacktestBatchResult } from "../types/strategySpecs";

const terminal = new Set([
  "COMPLETED",
  "PARTIAL_FAILED",
  "FAILED",
  "CANCELLED",
]);

const statusText: Record<string, string> = {
  CREATED: "已创建",
  RUNNING: "运行中",
  COMPLETED: "已完成",
  PARTIAL_FAILED: "部分失败",
  FAILED: "失败",
  CANCELLED: "已取消",
  PENDING: "等待中",
};

const percent = (value: string | null) =>
  value === null ? "—" : `${(Number(value) * 100).toFixed(2)}%`;

const decimal = (value: string | null) =>
  value === null ? "—" : Number(value).toFixed(2);

export function BacktestBatchPage() {
  const { batchId = "" } = useParams();
  const [resultPage, setResultPage] = useState(1);
  const resultPageSize = 50;
  const queryClient = useQueryClient();
  const batch = useQuery({
    queryKey: ["backtest-batch", batchId],
    queryFn: () => getBacktestBatch(batchId),
    enabled: Boolean(batchId),
    refetchInterval: (query) =>
      terminal.has(query.state.data?.status ?? "") ? false : 1500,
  });
  const results = useQuery({
    queryKey: ["backtest-batch-results", batchId, resultPage],
    queryFn: () => getBacktestBatchResults(batchId, resultPage, resultPageSize),
    enabled: Boolean(batchId),
    refetchInterval: () =>
      terminal.has(batch.data?.status ?? "") ? false : 3000,
  });
  const summary = useQuery({
    queryKey: ["backtest-batch-summary", batchId],
    queryFn: () => getBacktestBatchSummary(batchId),
    enabled: Boolean(batchId),
    refetchInterval: () =>
      terminal.has(batch.data?.status ?? "") ? false : 5000,
  });
  const data = batch.data;
  const refreshBatch = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["backtest-batch", batchId] }),
      queryClient.invalidateQueries({
        queryKey: ["backtest-batch-results", batchId],
      }),
      queryClient.invalidateQueries({
        queryKey: ["backtest-batch-summary", batchId],
      }),
    ]);
  };
  const cancel = useMutation({
    mutationFn: () => cancelBacktestBatch(batchId),
    onSuccess: refreshBatch,
  });
  const retryFailed = useMutation({
    mutationFn: () => retryFailedBacktestBatch(batchId),
    onSuccess: refreshBatch,
  });
  const maxHistogramCount = Math.max(
    1,
    ...(summary.data?.return_histogram.map((item) => item.count) ?? [1]),
  );

  return (
    <section>
      <PageHeader
        title={data?.name ?? "批量独立回测"}
        description="每只股票使用独立初始资金、独立账户和独立绩效，不共享持仓。"
        action={
          <Button>
            <Link to="/research/backtest">新建回测</Link>
          </Button>
        }
      />
      {batch.error ? (
        <Alert
          showIcon
          type="error"
          title="无法读取批量回测任务"
          style={{ marginBottom: 16 }}
        />
      ) : null}
      <Card title="任务进度" loading={batch.isLoading}>
        {cancel.error ? (
          <Alert
            showIcon
            type="error"
            title="取消批量任务失败"
            description={
              cancel.error instanceof Error ? cancel.error.message : "请稍后重试"
            }
            style={{ marginBottom: 16 }}
          />
        ) : null}
        {retryFailed.error ? (
          <Alert
            showIcon
            type="error"
            title="重新运行失败或已取消股票失败"
            description={
              retryFailed.error instanceof Error
                ? retryFailed.error.message
                : "请稍后重试"
            }
            style={{ marginBottom: 16 }}
          />
        ) : null}
        <Progress
          percent={data?.progress_percent ?? 0}
          status={data?.status === "FAILED" ? "exception" : undefined}
        />
        {data ? (
          <Descriptions
            column={{ xs: 2, sm: 3, md: 6 }}
            items={[
              { key: "total", label: "股票总数", children: data.total_count },
              { key: "done", label: "已完成", children: data.completed_count },
              {
                key: "running",
                label: "正在运行",
                children: data.running_count,
              },
              { key: "pending", label: "等待中", children: data.pending_count },
              { key: "failed", label: "失败", children: data.failed_count },
              {
                key: "status",
                label: "任务状态",
                children: <Tag>{statusText[data.status] ?? data.status}</Tag>,
              },
            ]}
          />
        ) : null}
        {data ? (
          <Space style={{ marginTop: 16 }}>
            {!terminal.has(data.status) ? (
              <Button
                danger
                loading={cancel.isPending}
                onClick={() => cancel.mutate()}
              >
                取消批量任务
              </Button>
            ) : null}
            {data.failed_count + data.cancelled_count > 0 ? (
              <Button
                loading={retryFailed.isPending}
                onClick={() => retryFailed.mutate()}
              >
                仅重试失败或已取消股票
              </Button>
            ) : null}
          </Space>
        ) : null}
        <Alert
          showIcon
          type="info"
          title="可安全关闭本页面"
          description="后台任务会继续逐只运行；以后从研究档案重新进入即可查看进度和结果。"
          style={{ marginTop: 16 }}
        />
      </Card>
      <Card
        title="批量回测总报告"
        loading={summary.isLoading}
        style={{ marginTop: 16 }}
        extra={
          <Button href={backtestBatchCsvUrl(batchId)} download>
            导出明细（CSV）
          </Button>
        }
      >
        {summary.data ? (
          <>
            <Alert
              showIcon
              type="info"
              title="逐股独立样本统计"
              description={summary.data.notice}
              style={{ marginBottom: 20 }}
            />
            <Row gutter={[16, 16]}>
              <Col xs={12} md={6}>
                <Statistic
                  title="完成 / 总数"
                  value={`${summary.data.counts.completed} / ${summary.data.counts.total}`}
                />
              </Col>
              <Col xs={12} md={6}>
                <Statistic
                  title="产生交易的股票占比"
                  value={percent(summary.data.ratios.traded)}
                />
              </Col>
              <Col xs={12} md={6}>
                <Statistic
                  title="盈利股票占比"
                  value={percent(summary.data.ratios.profitable)}
                />
              </Col>
              <Col xs={12} md={6}>
                <Statistic
                  title="失败股票"
                  value={summary.data.counts.failed}
                  suffix="只"
                />
              </Col>
              <Col xs={12} md={6}>
                <Statistic
                  title="平均收益"
                  value={percent(summary.data.returns.average)}
                />
              </Col>
              <Col xs={12} md={6}>
                <Statistic
                  title="收益中位数"
                  value={percent(summary.data.returns.median)}
                />
              </Col>
              <Col xs={12} md={6}>
                <Statistic
                  title="平均最大回撤"
                  value={percent(summary.data.drawdowns.average)}
                />
              </Col>
              <Col xs={12} md={6}>
                <Statistic
                  title="回撤中位数"
                  value={percent(summary.data.drawdowns.median)}
                />
              </Col>
            </Row>
            <Card size="small" title="分钟触发执行统计" style={{ marginTop: 16 }}>
              <Row gutter={[16, 16]}>
                <Col xs={12} md={6}>
                  <Statistic
                    title="日线预筛候选日"
                    value={summary.data.intraday_execution.daily_prefilter_candidates}
                  />
                </Col>
                <Col xs={12} md={6}>
                  <Statistic
                    title="日线安全排除日"
                    value={summary.data.intraday_execution.daily_prefilter_excluded}
                  />
                </Col>
                <Col xs={12} md={6}>
                  <Statistic
                    title="加载分钟交易日"
                    value={summary.data.intraday_execution.minute_sessions_loaded}
                  />
                </Col>
                <Col xs={12} md={6}>
                  <Statistic
                    title="处理分钟K线"
                    value={summary.data.intraday_execution.minute_bars_processed}
                  />
                </Col>
                <Col xs={12} md={6}>
                  <Statistic
                    title="产生信号股票"
                    value={summary.data.intraday_execution.stocks_with_signals}
                    suffix="只"
                  />
                </Col>
                <Col xs={12} md={6}>
                  <Statistic
                    title="产生成交股票"
                    value={summary.data.intraday_execution.stocks_with_fills}
                    suffix="只"
                  />
                </Col>
                <Col xs={12} md={6}>
                  <Statistic
                    title="数据准备耗时"
                    value={summary.data.intraday_execution.data_preparation_seconds}
                    precision={1}
                    suffix="秒"
                  />
                </Col>
                <Col xs={12} md={6}>
                  <Statistic
                    title="策略回放耗时"
                    value={summary.data.intraday_execution.strategy_replay_seconds}
                    precision={1}
                    suffix="秒"
                  />
                </Col>
              </Row>
            </Card>
            <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
              <Col xs={24} lg={12}>
                <Card size="small" title="收益分布">
                  {summary.data.return_histogram.length ? (
                    <div style={{ display: "grid", gap: 8 }}>
                      {summary.data.return_histogram.map((bucket, index) => (
                        <div
                          key={`${bucket.minimum}-${index}`}
                          style={{
                            display: "grid",
                            gridTemplateColumns: "150px 1fr 40px",
                            alignItems: "center",
                            gap: 8,
                          }}
                        >
                          <Typography.Text type="secondary">
                            {(bucket.minimum * 100).toFixed(1)}% ～{" "}
                            {(bucket.maximum * 100).toFixed(1)}%
                          </Typography.Text>
                          <div
                            style={{
                              height: 16,
                              borderRadius: 4,
                              background: "#edf2f7",
                            }}
                          >
                            <div
                              style={{
                                height: "100%",
                                width: `${(bucket.count / maxHistogramCount) * 100}%`,
                                borderRadius: 4,
                                background: "#1677ff",
                              }}
                            />
                          </div>
                          <Typography.Text>{bucket.count}</Typography.Text>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <Empty description="任务完成后显示收益分布" />
                  )}
                </Card>
              </Col>
              <Col xs={24} lg={12}>
                <Card size="small" title="收益与回撤关系">
                  {summary.data.return_drawdown_scatter.length ? (
                    <svg
                      viewBox="0 0 640 240"
                      role="img"
                      aria-label="逐股收益与最大回撤散点图"
                      style={{ width: "100%", minHeight: 220 }}
                    >
                      <line x1="42" y1="10" x2="42" y2="210" stroke="#d9d9d9" />
                      <line
                        x1="42"
                        y1="210"
                        x2="630"
                        y2="210"
                        stroke="#d9d9d9"
                      />
                      {summary.data.return_drawdown_scatter.map((point) => {
                        const returns = Number(point.total_return);
                        const drawdown = Math.abs(
                          Number(point.maximum_drawdown),
                        );
                        const x = 42 + Math.min(1, drawdown) * 570;
                        const y = 110 - Math.max(-1, Math.min(1, returns)) * 95;
                        return (
                          <circle
                            key={point.instrument_id}
                            cx={x}
                            cy={y}
                            r="4"
                            fill="#1677ff"
                            opacity="0.65"
                          >
                            <title>
                              {point.instrument_display}：收益{" "}
                              {percent(point.total_return)}，回撤{" "}
                              {percent(point.maximum_drawdown)}
                            </title>
                          </circle>
                        );
                      })}
                      <text x="480" y="232" fontSize="12" fill="#8c8c8c">
                        最大回撤 →
                      </text>
                      <text x="4" y="22" fontSize="12" fill="#8c8c8c">
                        收益
                      </text>
                    </svg>
                  ) : (
                    <Empty description="任务完成后显示散点图" />
                  )}
                </Card>
              </Col>
              <Col xs={24} lg={12}>
                <Card size="small" title="收益最高">
                  <Table
                    size="small"
                    rowKey="item_id"
                    pagination={false}
                    dataSource={summary.data.top.slice(0, 5)}
                    columns={[
                      { title: "股票", dataIndex: "instrument_display" },
                      {
                        title: "总收益",
                        dataIndex: "total_return",
                        render: percent,
                      },
                    ]}
                  />
                </Card>
              </Col>
              <Col xs={24} lg={12}>
                <Card size="small" title="收益最低">
                  <Table
                    size="small"
                    rowKey="item_id"
                    pagination={false}
                    dataSource={summary.data.bottom.slice(0, 5)}
                    columns={[
                      { title: "股票", dataIndex: "instrument_display" },
                      {
                        title: "总收益",
                        dataIndex: "total_return",
                        render: percent,
                      },
                    ]}
                  />
                </Card>
              </Col>
            </Row>
            {summary.data.failure_reasons.length ? (
              <Alert
                style={{ marginTop: 16 }}
                type="warning"
                title="失败原因统计"
                description={summary.data.failure_reasons
                  .map((item) => `${item.code}：${item.count} 只`)
                  .join("；")}
              />
            ) : null}
          </>
        ) : null}
      </Card>
      <Card title="逐股独立回测明细" style={{ marginTop: 16 }}>
        <Table<BacktestBatchResult>
          rowKey="item_id"
          loading={results.isLoading}
          dataSource={results.data?.items ?? []}
          pagination={{
            current: resultPage,
            pageSize: resultPageSize,
            total: results.data?.total ?? 0,
            showSizeChanger: false,
            showTotal: (total) => `共 ${total} 只`,
            onChange: setResultPage,
          }}
          columns={[
            {
              title: "股票",
              key: "instrument",
              render: (_, row) =>
                `${row.name}（${row.symbol}.${row.exchange}）`,
            },
            {
              title: "状态",
              dataIndex: "status",
              filters: Object.entries(statusText).map(([value, text]) => ({
                text,
                value,
              })),
              onFilter: (value, row) => row.status === value,
              render: (value: string) => (
                <Tag>{statusText[value] ?? value}</Tag>
              ),
            },
            {
              title: "总收益",
              dataIndex: "total_return",
              render: percent,
              sorter: (a, b) =>
                Number(a.total_return ?? -Infinity) -
                Number(b.total_return ?? -Infinity),
            },
            {
              title: "年化收益",
              dataIndex: "annualized_return",
              render: percent,
            },
            {
              title: "最大回撤",
              dataIndex: "maximum_drawdown",
              render: percent,
            },
            {
              title: "夏普比率",
              dataIndex: "sharpe_ratio",
              render: decimal,
              sorter: (a, b) =>
                Number(a.sharpe_ratio ?? -Infinity) -
                Number(b.sharpe_ratio ?? -Infinity),
            },
            {
              title: "成交数",
              dataIndex: "fill_count",
              render: (value: number | null) => value ?? "—",
              filters: [
                { text: "有成交", value: "traded" },
                { text: "无成交", value: "untraded" },
              ],
              onFilter: (value, row) =>
                value === "traded"
                  ? (row.fill_count ?? 0) > 0
                  : (row.fill_count ?? 0) === 0,
            },
            {
              title: "操作",
              key: "action",
              render: (_, row) =>
                row.backtest_run_id ? (
                  <Space>
                    <Link to={`/research/backtests/${row.backtest_run_id}`}>
                      查看报告
                    </Link>
                  </Space>
                ) : (
                  (row.error_message ?? "—")
                ),
            },
          ]}
        />
      </Card>
    </section>
  );
}
