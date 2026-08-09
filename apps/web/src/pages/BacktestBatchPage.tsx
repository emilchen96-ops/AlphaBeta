import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  Progress,
  Row,
  Segmented,
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
import type {
  BacktestBatchResult,
  BacktestBatchSummary,
} from "../types/strategySpecs";

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

const failureText: Record<string, string> = {
  BACKTEST_TOO_MANY_INSTRUMENTS: "组合股票数量超过系统允许范围",
  BACKTEST_BATCH_ITEM_FAILED: "组合回测执行失败",
};

const percent = (value: string | null) =>
  value === null ? "—" : `${(Number(value) * 100).toFixed(2)}%`;

const decimal = (value: string | null) =>
  value === null ? "—" : Number(value).toFixed(2);

const exposureRatio = (point: {
  gross_exposure: string;
  total_equity: string;
}) => {
  const equity = Number(point.total_equity);
  return equity > 0 ? Number(point.gross_exposure) / equity : 0;
};

export function BacktestBatchPage() {
  const { batchId = "" } = useParams();
  const [resultPage, setResultPage] = useState(1);
  const [equityDisplay, setEquityDisplay] = useState<"收益率" | "金额">(
    "收益率",
  );
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
  const isSharedPortfolio = data?.execution_mode === "SHARED_PORTFOLIO";
  const isSharedPortfolioSummary =
    isSharedPortfolio ||
    summary.data?.batch.execution_mode === "SHARED_PORTFOLIO";
  const sharedPortfolioFailure = results.data?.items.find(
    (item) => item.status === "FAILED",
  );
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
    ...(summary.data?.return_histogram?.map((item) => item.count) ?? [1]),
  );

  return (
    <section>
      <PageHeader
        title={data?.name ?? "批量回测"}
        description={
          isSharedPortfolio
            ? "所有股票共享一套资金、持仓与时间线，按真实组合顺序执行买卖。"
            : "每只股票使用独立初始资金、独立账户和独立绩效，不共享持仓。"
        }
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
              cancel.error instanceof Error
                ? cancel.error.message
                : "请稍后重试"
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
              {
                key: "total",
                label: "股票总数",
                children: data.instrument_count ?? data.total_count,
              },
              {
                key: "done",
                label: isSharedPortfolio ? "组合运行" : "已完成",
                children: isSharedPortfolio
                  ? (statusText[data.status] ?? data.status)
                  : data.completed_count,
              },
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
        {summary.data &&
        (summary.data.data_preparation.required_sessions > 0 ||
          summary.data.data_preparation.preparing_stocks > 0) ? (
          <div style={{ marginTop: 20 }}>
            <Typography.Text strong>分钟行情准备进度</Typography.Text>
            <Progress
              percent={summary.data.data_preparation.progress_percent}
              status={
                data?.status === "FAILED" &&
                summary.data.data_preparation.missing_sessions > 0
                  ? "exception"
                  : "active"
              }
              style={{ marginTop: 8 }}
            />
            <Typography.Text type="secondary">
              已准备 {summary.data.data_preparation.ready_sessions} /{" "}
              {summary.data.data_preparation.required_sessions} 个候选交易日；
              尚缺 {summary.data.data_preparation.missing_sessions} 个，正在准备{" "}
              {summary.data.data_preparation.preparing_stocks} 只股票。
            </Typography.Text>
          </div>
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
        title={isSharedPortfolio ? "共享资金组合报告" : "逐股独立回测总报告"}
        loading={summary.isLoading}
        style={{ marginTop: 16 }}
        extra={
          <Button href={backtestBatchCsvUrl(batchId)} download>
            导出明细（CSV）
          </Button>
        }
      >
        {summary.error ? (
          <Alert
            showIcon
            type="error"
            title="无法读取回测报告"
            description="任务记录仍然保留，请刷新页面后重试。"
          />
        ) : summary.data ? (
          isSharedPortfolioSummary ? (
            summary.data.portfolio ? (
              <SharedPortfolioReport
                portfolio={summary.data.portfolio}
                notice={summary.data.notice}
                equityDisplay={equityDisplay}
                onEquityDisplayChange={setEquityDisplay}
              />
            ) : (
              <Alert
                showIcon
                type={data?.status === "FAILED" ? "error" : "info"}
                title={
                  data?.status === "FAILED"
                    ? "共享资金组合回测失败"
                    : "共享资金组合报告尚未生成"
                }
                description={
                  <Space orientation="vertical" size={4}>
                    <span>{summary.data.notice}</span>
                    {sharedPortfolioFailure ? (
                      <span>
                        失败原因：
                        {failureText[sharedPortfolioFailure.error_code ?? ""] ??
                          sharedPortfolioFailure.error_message ??
                          "请重试任务或查看服务日志"}
                      </span>
                    ) : null}
                  </Space>
                }
              />
            )
          ) : (
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
              <Card
                size="small"
                title="分钟触发执行统计"
                style={{ marginTop: 16 }}
              >
                <Row gutter={[16, 16]}>
                  <Col xs={12} md={6}>
                    <Statistic
                      title="日线预筛候选日"
                      value={
                        summary.data.intraday_execution
                          .daily_prefilter_candidates
                      }
                    />
                  </Col>
                  <Col xs={12} md={6}>
                    <Statistic
                      title="日线安全排除日"
                      value={
                        summary.data.intraday_execution.daily_prefilter_excluded
                      }
                    />
                  </Col>
                  <Col xs={12} md={6}>
                    <Statistic
                      title="加载分钟交易日"
                      value={
                        summary.data.intraday_execution.minute_sessions_loaded
                      }
                    />
                  </Col>
                  <Col xs={12} md={6}>
                    <Statistic
                      title="处理分钟K线"
                      value={
                        summary.data.intraday_execution.minute_bars_processed
                      }
                    />
                  </Col>
                  <Col xs={12} md={6}>
                    <Statistic
                      title="产生信号股票"
                      value={
                        summary.data.intraday_execution.stocks_with_signals
                      }
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
                      value={
                        summary.data.intraday_execution.data_preparation_seconds
                      }
                      precision={1}
                      suffix="秒"
                    />
                  </Col>
                  <Col xs={12} md={6}>
                    <Statistic
                      title="策略回放耗时"
                      value={
                        summary.data.intraday_execution.strategy_replay_seconds
                      }
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
                  <Card size="small" title="逐股独立回测：收益与风险分布">
                    {summary.data.return_drawdown_scatter.length ? (
                      <IndependentRiskScatter
                        points={summary.data.return_drawdown_scatter}
                      />
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
          )
        ) : null}
      </Card>
      {!isSharedPortfolio ? (
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
      ) : null}
    </section>
  );
}

type SharedPortfolio = NonNullable<BacktestBatchSummary["portfolio"]>;

function numberValue(value: unknown, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function optionalNumber(value: unknown) {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function textValue(value: unknown, fallback = "—") {
  return typeof value === "string" || typeof value === "number"
    ? String(value)
    : fallback;
}

function money(value: unknown) {
  return `¥${numberValue(value).toLocaleString("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function SharedPortfolioReport({
  portfolio,
  notice,
  equityDisplay,
  onEquityDisplayChange,
}: {
  portfolio: SharedPortfolio;
  notice: string;
  equityDisplay: "收益率" | "金额";
  onEquityDisplayChange: (value: "收益率" | "金额") => void;
}) {
  const metrics = portfolio.metrics ?? {};
  const latest = portfolio.equity_curve.at(-1);
  const configuration = portfolio.configuration;
  const derived = portfolio.summary;

  return (
    <>
      <Alert
        showIcon
        type="success"
        title="真实共享资金组合"
        description={notice}
        style={{ marginBottom: 20 }}
      />
      <Row gutter={[16, 16]}>
        <Col xs={12} md={6}>
          <Statistic
            title="组合总收益"
            value={percent(String(metrics.total_return ?? 0))}
          />
        </Col>
        <Col xs={12} md={6}>
          <Statistic
            title="同期基准收益"
            value={percent(derived.benchmark_total_return)}
          />
        </Col>
        <Col xs={12} md={6}>
          <Statistic
            title="相对基准超额收益"
            value={percent(derived.excess_return)}
          />
        </Col>
        <Col xs={12} md={6}>
          <Statistic
            title="最大回撤"
            value={percent(String(metrics.maximum_drawdown ?? 0))}
          />
        </Col>
        <Col xs={12} md={6}>
          <Statistic title="期初资金" value={money(metrics.initial_equity)} />
        </Col>
        <Col xs={12} md={6}>
          <Statistic title="期末权益" value={money(metrics.final_equity)} />
        </Col>
        <Col xs={12} md={6}>
          <Statistic
            title="年化收益"
            value={percent(
              metrics.annualized_return == null
                ? null
                : String(metrics.annualized_return),
            )}
          />
        </Col>
        <Col xs={12} md={6}>
          <Statistic
            title="夏普比率"
            value={decimal(
              metrics.sharpe_ratio == null
                ? null
                : String(metrics.sharpe_ratio),
            )}
          />
        </Col>
        <Col xs={12} md={6}>
          <Statistic title="成交笔数" value={numberValue(metrics.fill_count)} />
        </Col>
        <Col xs={12} md={6}>
          <Statistic
            title="胜率"
            value={percent(
              metrics.win_rate == null ? null : String(metrics.win_rate),
            )}
          />
        </Col>
        <Col xs={12} md={6}>
          <Statistic
            title="平均盈利"
            value={
              metrics.average_profit == null
                ? "—"
                : money(metrics.average_profit)
            }
          />
        </Col>
        <Col xs={12} md={6}>
          <Statistic
            title="平均亏损"
            value={
              metrics.average_loss == null ? "—" : money(metrics.average_loss)
            }
          />
        </Col>
        <Col xs={12} md={6}>
          <Statistic
            title="盈亏比"
            value={
              metrics.profit_factor == null
                ? "—"
                : decimal(String(metrics.profit_factor))
            }
          />
        </Col>
        <Col xs={12} md={6}>
          <Statistic
            title="平均持仓天数"
            value={
              derived.average_holding_days == null
                ? "—"
                : numberValue(derived.average_holding_days).toFixed(1)
            }
            suffix={derived.average_holding_days == null ? undefined : "天"}
          />
        </Col>
        <Col xs={12} md={6}>
          <Statistic
            title="最长回撤持续"
            value={derived.longest_drawdown_sessions}
            suffix="个快照"
          />
        </Col>
      </Row>
      <Descriptions
        size="small"
        bordered
        column={{ xs: 1, sm: 2, lg: 4 }}
        style={{ marginTop: 16 }}
        items={[
          {
            key: "position",
            label: "单次目标仓位",
            children: percent(
              optionalNumber(configuration.position_size_ratio)?.toString() ??
                null,
            ),
          },
          {
            key: "holdings",
            label: "最多同时持股",
            children: `${textValue(configuration.maximum_holdings)} 只`,
          },
          {
            key: "exposure",
            label: "组合仓位上限",
            children: percent(
              optionalNumber(
                configuration.maximum_total_exposure,
              )?.toString() ?? null,
            ),
          },
          {
            key: "ranking",
            label: "同刻买入排序",
            children: "信号强度 → 量比 → 股票代码",
          },
          {
            key: "average-exposure",
            label: "平均资金使用率",
            children: percent(derived.average_exposure),
          },
          {
            key: "idle-cash",
            label: "平均闲置资金比例",
            children: percent(derived.average_idle_cash_ratio),
          },
          {
            key: "maximum-positions",
            label: "实际最多同时持股",
            children: `${derived.maximum_positions} 只`,
          },
          {
            key: "current",
            label: "期末账户状态",
            children: `现金 ${money(latest?.cash)}；持仓市值 ${money(latest?.market_value)}；${latest?.positions_count ?? 0} 只股票`,
          },
        ]}
      />
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} xl={14}>
          <Card
            size="small"
            title="组合累计收益曲线"
            extra={
              <Segmented
                size="small"
                options={["收益率", "金额"]}
                value={equityDisplay}
                onChange={(value) =>
                  onEquityDisplayChange(value as "收益率" | "金额")
                }
              />
            }
          >
            <PortfolioEquityChart
              points={portfolio.equity_curve}
              benchmark={portfolio.benchmark}
              landmarks={portfolio.drawdown_landmarks}
              display={equityDisplay}
            />
            <Typography.Text type="secondary">
              默认从 0% 起展示组合累计收益；切换到金额可核对真实共享账户权益。
            </Typography.Text>
          </Card>
        </Col>
        <Col xs={24} xl={10}>
          <Card size="small" title="历史回撤（从此前最高权益下跌的幅度）">
            <PortfolioDrawdownChart
              points={portfolio.equity_curve}
              landmarks={portfolio.drawdown_landmarks}
            />
          </Card>
        </Col>
      </Row>
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} xl={12}>
          <Card size="small" title="股票收益贡献">
            <Table
              size="small"
              rowKey="instrument_id"
              pagination={{ pageSize: 8, hideOnSinglePage: true }}
              dataSource={portfolio.contributions}
              columns={[
                { title: "股票", dataIndex: "instrument_display" },
                {
                  title: "总收益贡献",
                  dataIndex: "total_contribution",
                  sorter: (a, b) =>
                    numberValue(a.total_contribution) -
                    numberValue(b.total_contribution),
                  render: money,
                },
                { title: "已实现", dataIndex: "realized_pnl", render: money },
                { title: "未实现", dataIndex: "unrealized_pnl", render: money },
                { title: "交易次数", dataIndex: "trade_count" },
              ]}
            />
          </Card>
        </Col>
        <Col xs={24} xl={12}>
          <Card size="small" title="组合交易与约束">
            <Row gutter={[16, 16]}>
              <Col span={8}>
                <Statistic title="成交笔数" value={portfolio.fills.length} />
              </Col>
              <Col span={8}>
                <Statistic title="已平仓交易" value={portfolio.trades.length} />
              </Col>
              <Col span={8}>
                <Statistic
                  title="拒绝/复核"
                  value={portfolio.rejections.length}
                />
              </Col>
            </Row>
            {portfolio.rejections.length ? (
              <Table
                style={{ marginTop: 12 }}
                size="small"
                rowKey={(row) => String(row.id)}
                pagination={{ pageSize: 5, hideOnSinglePage: true }}
                dataSource={portfolio.rejections}
                columns={[
                  { title: "时间", dataIndex: "created_at" },
                  { title: "股票", dataIndex: "instrument_display" },
                  {
                    title: "结果",
                    dataIndex: "overall_decision",
                    render: (value) =>
                      value === "ALLOW"
                        ? "通过"
                        : value === "REJECT"
                          ? "拒绝"
                          : "需要复核",
                  },
                  { title: "代码", dataIndex: "reason_code" },
                  {
                    title: "原因",
                    key: "reason",
                    render: (_, row) =>
                      textValue(row.reason ?? row.reason_code),
                  },
                ]}
              />
            ) : (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="没有风控拒绝或人工复核"
              />
            )}
          </Card>
        </Col>
      </Row>
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} xl={12}>
          <Card size="small" title="完整交易（买入至卖出）">
            <Table
              size="small"
              rowKey={(row) => String(row.id)}
              pagination={{ pageSize: 8, hideOnSinglePage: true }}
              dataSource={portfolio.trades}
              columns={[
                { title: "股票", dataIndex: "instrument_display" },
                {
                  title: "买入时间",
                  dataIndex: "opened_at",
                  render: (value) =>
                    new Date(String(value)).toLocaleString("zh-CN"),
                },
                {
                  title: "卖出时间",
                  dataIndex: "closed_at",
                  render: (value) =>
                    new Date(String(value)).toLocaleString("zh-CN"),
                },
                { title: "数量", dataIndex: "quantity" },
                { title: "净盈亏", dataIndex: "net_pnl", render: money },
              ]}
            />
          </Card>
        </Col>
        <Col xs={24} xl={12}>
          <Card size="small" title="实际成交明细">
            <Table
              size="small"
              rowKey={(row) => String(row.id)}
              pagination={{ pageSize: 8, hideOnSinglePage: true }}
              dataSource={portfolio.fills}
              columns={[
                {
                  title: "时间",
                  dataIndex: "filled_at",
                  render: (value) =>
                    new Date(String(value)).toLocaleString("zh-CN"),
                },
                { title: "股票", dataIndex: "instrument_display" },
                {
                  title: "方向",
                  dataIndex: "side",
                  render: (value) =>
                    value === "BUY"
                      ? "买入"
                      : value === "SELL"
                        ? "卖出"
                        : String(value ?? "—"),
                },
                { title: "数量", dataIndex: "quantity" },
                { title: "价格", dataIndex: "price" },
                {
                  title: "费用",
                  key: "fees",
                  render: (_, row) =>
                    money(
                      numberValue(row.commission) +
                        numberValue(row.stamp_duty) +
                        numberValue(row.transfer_fee) +
                        numberValue(row.other_fee),
                    ),
                },
              ]}
            />
          </Card>
        </Col>
      </Row>
      <Card
        size="small"
        title="组合每日权益与持仓快照"
        style={{ marginTop: 16 }}
      >
        <Table
          size="small"
          rowKey="timestamp"
          pagination={{ pageSize: 10, hideOnSinglePage: true }}
          dataSource={portfolio.equity_curve}
          columns={[
            {
              title: "时间",
              dataIndex: "timestamp",
              render: (value) =>
                new Date(String(value)).toLocaleString("zh-CN"),
            },
            { title: "总权益", dataIndex: "total_equity", render: money },
            { title: "现金", dataIndex: "cash", render: money },
            { title: "持仓市值", dataIndex: "market_value", render: money },
            {
              title: "累计收益",
              dataIndex: "cumulative_return",
              render: percent,
            },
            { title: "回撤", dataIndex: "drawdown", render: percent },
            {
              title: "资金使用率",
              render: (_, point) => percent(exposureRatio(point).toString()),
            },
            {
              title: "持股数",
              dataIndex: "positions_count",
              render: (value) => `${value} 只`,
            },
          ]}
        />
      </Card>
    </>
  );
}

function chartGeometry(
  values: number[],
  width = 720,
  height = 240,
  bounds?: { minimum?: number; maximum?: number },
) {
  const left = 48;
  const right = 14;
  const top = 16;
  const bottom = 34;
  const minimum = bounds?.minimum ?? Math.min(...values, 0);
  const maximum = bounds?.maximum ?? Math.max(...values, 0);
  const padding = Math.max((maximum - minimum) * 0.08, 0.001);
  const low = bounds?.minimum === undefined ? minimum - padding : minimum;
  const high = bounds?.maximum === undefined ? maximum + padding : maximum;
  const x = (index: number) =>
    left + (index / Math.max(1, values.length - 1)) * (width - left - right);
  const y = (value: number) =>
    top +
    ((high - value) / Math.max(0.000001, high - low)) * (height - top - bottom);
  return { width, height, left, right, top, bottom, low, high, x, y };
}

function PortfolioEquityChart({
  points,
  benchmark,
  landmarks,
  display,
}: {
  points: SharedPortfolio["equity_curve"];
  benchmark: SharedPortfolio["benchmark"];
  landmarks: SharedPortfolio["drawdown_landmarks"];
  display: "收益率" | "金额";
}) {
  if (!points.length) return <Empty description="暂无组合权益快照" />;
  const values = points.map((point) =>
    display === "收益率"
      ? numberValue(point.cumulative_return) * 100
      : numberValue(point.total_equity),
  );
  const benchmarkValues =
    display === "收益率"
      ? benchmark.curve.map(
          (point) => numberValue(point.cumulative_return) * 100,
        )
      : [];
  const geometry = chartGeometry([...values, ...benchmarkValues]);
  const timestamps = points.map((point) => new Date(point.timestamp).getTime());
  const benchmarkTimestamps = benchmark.curve.map((point) =>
    new Date(point.timestamp).getTime(),
  );
  const validTimes = [...timestamps, ...benchmarkTimestamps].filter(
    Number.isFinite,
  );
  const minimumTime = Math.min(...validTimes);
  const maximumTime = Math.max(...validTimes);
  const timeX = (value: number) =>
    geometry.left +
    ((value - minimumTime) / Math.max(1, maximumTime - minimumTime)) *
      (geometry.width - geometry.left - geometry.right);
  const pointX = (index: number) =>
    Number.isFinite(timestamps[index])
      ? timeX(timestamps[index])
      : geometry.x(index);
  const path = values
    .map(
      (value, index) =>
        `${index ? "L" : "M"}${pointX(index)},${geometry.y(value)}`,
    )
    .join(" ");
  const benchmarkPath = benchmarkValues
    .map(
      (value, index) =>
        `${index ? "L" : "M"}${Number.isFinite(benchmarkTimestamps[index]) ? timeX(benchmarkTimestamps[index]) : geometry.x(index)},${geometry.y(value)}`,
    )
    .join(" ");
  const zeroY = geometry.y(0);
  const yTicks = [
    geometry.low,
    (geometry.low + geometry.high) / 2,
    geometry.high,
  ];
  const dateTicks = [minimumTime, (minimumTime + maximumTime) / 2, maximumTime];
  const peakTime = landmarks
    ? new Date(landmarks.peak_at).getTime()
    : Number.NaN;
  const endTime = landmarks
    ? new Date(
        landmarks.recovered_at ??
          points.at(-1)?.timestamp ??
          landmarks.trough_at,
      ).getTime()
    : Number.NaN;
  return (
    <>
      <svg
        viewBox={`0 0 ${geometry.width} ${geometry.height}`}
        role="img"
        aria-label="共享资金组合累计收益曲线"
        style={{ width: "100%", minHeight: 230 }}
      >
        {Number.isFinite(peakTime) && Number.isFinite(endTime) ? (
          <rect
            x={timeX(peakTime)}
            y={geometry.top}
            width={Math.max(1, timeX(endTime) - timeX(peakTime))}
            height={geometry.height - geometry.top - geometry.bottom}
            fill="rgba(255,77,79,0.07)"
          >
            <title>最大回撤区间</title>
          </rect>
        ) : null}
        {yTicks.map((tick) => (
          <g key={tick}>
            <line
              x1={geometry.left}
              y1={geometry.y(tick)}
              x2={geometry.width - geometry.right}
              y2={geometry.y(tick)}
              stroke="#f0f0f0"
            />
            <text
              x={geometry.left - 6}
              y={geometry.y(tick) + 4}
              textAnchor="end"
              fontSize="11"
              fill="#8c8c8c"
            >
              {display === "收益率" ? `${tick.toFixed(1)}%` : money(tick)}
            </text>
          </g>
        ))}
        <line
          x1={geometry.left}
          y1={zeroY}
          x2={geometry.width - geometry.right}
          y2={zeroY}
          stroke="#d9d9d9"
          strokeDasharray="4 4"
        />
        <path d={path} fill="none" stroke="#1677ff" strokeWidth="3" />
        {benchmarkPath ? (
          <path
            d={benchmarkPath}
            fill="none"
            stroke="#8c8c8c"
            strokeWidth="2"
            strokeDasharray="6 5"
          />
        ) : null}
        {points.map((point, index) => (
          <circle
            key={point.timestamp}
            cx={pointX(index)}
            cy={geometry.y(values[index])}
            r="7"
            fill="transparent"
          >
            <title>{`${new Date(point.timestamp).toLocaleString("zh-CN")}；策略累计收益 ${(numberValue(point.cumulative_return) * 100).toFixed(2)}%；当日总权益 ${money(point.total_equity)}；现金 ${money(point.cash)}；持仓市值 ${money(point.market_value)}；总仓位 ${(exposureRatio(point) * 100).toFixed(1)}%`}</title>
          </circle>
        ))}
        {dateTicks.map((tick) => (
          <text
            key={tick}
            x={timeX(tick)}
            y={geometry.height - 10}
            textAnchor="middle"
            fontSize="11"
            fill="#8c8c8c"
          >
            {new Date(tick).toLocaleDateString("zh-CN")}
          </text>
        ))}
        <text
          x={geometry.left + 8}
          y={geometry.top + 14}
          fontSize="12"
          fill="#1677ff"
        >
          组合
        </text>
        {benchmarkPath ? (
          <text
            x={geometry.left + 58}
            y={geometry.top + 14}
            fontSize="12"
            fill="#8c8c8c"
          >
            {benchmark.name ?? benchmark.symbol}（基准）
          </text>
        ) : null}
      </svg>
      {benchmark.warning ? (
        <Typography.Text type="secondary">{benchmark.warning}</Typography.Text>
      ) : null}
    </>
  );
}

type RiskScatterPoint = BacktestBatchSummary["return_drawdown_scatter"][number];

function median(values: number[]) {
  const ordered = [...values].sort((left, right) => left - right);
  const middle = Math.floor(ordered.length / 2);
  return ordered.length % 2
    ? ordered[middle]
    : (ordered[middle - 1] + ordered[middle]) / 2;
}

function IndependentRiskScatter({ points }: { points: RiskScatterPoint[] }) {
  const width = 640;
  const height = 286;
  const left = 58;
  const right = 18;
  const top = 28;
  const bottom = 48;
  const plotted = points.map((point) => ({
    point,
    returns: numberValue(point.total_return) * 100,
    drawdown: Math.abs(numberValue(point.maximum_drawdown)) * 100,
  }));
  const returnMedian = median(plotted.map((item) => item.returns));
  const drawdownMedian = median(plotted.map((item) => item.drawdown));
  const returnMinimum = Math.min(0, ...plotted.map((item) => item.returns));
  const returnMaximum = Math.max(0, ...plotted.map((item) => item.returns));
  const drawdownMaximum = Math.max(
    0.1,
    ...plotted.map((item) => item.drawdown),
  );
  const returnPadding = Math.max((returnMaximum - returnMinimum) * 0.12, 0.5);
  const drawdownPadding = Math.max(drawdownMaximum * 0.08, 0.25);
  const lowReturn = returnMinimum - returnPadding;
  const highReturn = returnMaximum + returnPadding;
  const highDrawdown = drawdownMaximum + drawdownPadding;
  const x = (value: number) =>
    left + (value / highDrawdown) * (width - left - right);
  const y = (value: number) =>
    top +
    ((highReturn - value) / Math.max(0.0001, highReturn - lowReturn)) *
      (height - top - bottom);
  const returnTicks = [lowReturn, (lowReturn + highReturn) / 2, highReturn];
  const drawdownTicks = [0, highDrawdown / 2, highDrawdown];

  return (
    <>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="逐股收益与最大回撤散点图"
        style={{ width: "100%", minHeight: 250 }}
      >
        <rect
          x={left}
          y={top}
          width={x(drawdownMedian) - left}
          height={y(returnMedian) - top}
          fill="rgba(82,196,26,0.06)"
        />
        <rect
          x={x(drawdownMedian)}
          y={top}
          width={width - right - x(drawdownMedian)}
          height={y(returnMedian) - top}
          fill="rgba(250,173,20,0.06)"
        />
        <rect
          x={left}
          y={y(returnMedian)}
          width={x(drawdownMedian) - left}
          height={height - bottom - y(returnMedian)}
          fill="rgba(22,119,255,0.04)"
        />
        <rect
          x={x(drawdownMedian)}
          y={y(returnMedian)}
          width={width - right - x(drawdownMedian)}
          height={height - bottom - y(returnMedian)}
          fill="rgba(255,77,79,0.05)"
        />
        <line
          x1={left}
          y1={y(0)}
          x2={width - right}
          y2={y(0)}
          stroke="#8c8c8c"
          strokeDasharray="5 4"
        />
        <line
          x1={left}
          y1={y(returnMedian)}
          x2={width - right}
          y2={y(returnMedian)}
          stroke="#bfbfbf"
          strokeDasharray="3 4"
        />
        <line
          x1={x(drawdownMedian)}
          y1={top}
          x2={x(drawdownMedian)}
          y2={height - bottom}
          stroke="#bfbfbf"
          strokeDasharray="3 4"
        />
        <line
          x1={left}
          y1={top}
          x2={left}
          y2={height - bottom}
          stroke="#d9d9d9"
        />
        <line
          x1={left}
          y1={height - bottom}
          x2={width - right}
          y2={height - bottom}
          stroke="#d9d9d9"
        />
        {returnTicks.map((tick) => (
          <text
            key={tick}
            x={left - 6}
            y={y(tick) + 4}
            textAnchor="end"
            fontSize="11"
            fill="#8c8c8c"
          >
            {tick.toFixed(1)}%
          </text>
        ))}
        {drawdownTicks.map((tick) => (
          <text
            key={tick}
            x={x(tick)}
            y={height - bottom + 18}
            textAnchor="middle"
            fontSize="11"
            fill="#8c8c8c"
          >
            {tick.toFixed(1)}%
          </text>
        ))}
        <text x={left + 8} y={top + 14} fontSize="11" fill="#389e0d">
          高收益、低回撤
        </text>
        <text
          x={x(drawdownMedian) + 8}
          y={top + 14}
          fontSize="11"
          fill="#d48806"
        >
          高收益、高回撤
        </text>
        <text x={left + 8} y={height - bottom - 8} fontSize="11" fill="#1677ff">
          低收益、低回撤
        </text>
        <text
          x={x(drawdownMedian) + 8}
          y={height - bottom - 8}
          fontSize="11"
          fill="#cf1322"
        >
          低收益、高回撤
        </text>
        {plotted.map(({ point, returns, drawdown }) => {
          const circle = (
            <circle
              cx={x(drawdown)}
              cy={y(returns)}
              r={point.fill_count ? 5 : 4}
              fill={point.fill_count ? "#1677ff" : "#bfbfbf"}
              opacity="0.72"
            >
              <title>{`${point.instrument_display}；收益 ${returns.toFixed(2)}%；最大回撤 ${drawdown.toFixed(2)}%；成交 ${point.fill_count} 笔${point.fill_count ? "" : "（无成交）"}`}</title>
            </circle>
          );
          return point.backtest_run_id ? (
            <Link
              key={point.instrument_id}
              to={`/research/backtests/${point.backtest_run_id}`}
            >
              {circle}
            </Link>
          ) : (
            <g key={point.instrument_id}>{circle}</g>
          );
        })}
        <text
          x={width - right}
          y={height - 8}
          textAnchor="end"
          fontSize="12"
          fill="#595959"
        >
          最大回撤绝对值 →
        </text>
        <text x="6" y="16" fontSize="12" fill="#595959">
          总收益率 ↑
        </text>
      </svg>
      <Typography.Text type="secondary">
        虚线分别表示收益 0%、收益中位数 {returnMedian.toFixed(2)}% 和回撤中位数{" "}
        {drawdownMedian.toFixed(2)}
        %；灰点为没有成交的股票，点击蓝点可查看单股报告。
      </Typography.Text>
    </>
  );
}

function PortfolioDrawdownChart({
  points,
  landmarks,
}: {
  points: SharedPortfolio["equity_curve"];
  landmarks: SharedPortfolio["drawdown_landmarks"];
}) {
  if (!points.length) return <Empty description="暂无组合回撤快照" />;
  const values = points.map((point) => numberValue(point.drawdown) * 100);
  const minimumDrawdown = Math.min(...values, -0.0001);
  const geometry = chartGeometry(values, 540, 240, {
    minimum: minimumDrawdown * 1.08,
    maximum: 0,
  });
  const timestamps = points.map((point) => new Date(point.timestamp).getTime());
  const minimumTime = Math.min(...timestamps);
  const maximumTime = Math.max(...timestamps);
  const timeX = (value: number) =>
    geometry.left +
    ((value - minimumTime) / Math.max(1, maximumTime - minimumTime)) *
      (geometry.width - geometry.left - geometry.right);
  const pointX = (index: number) => timeX(timestamps[index]);
  const line = values
    .map(
      (value, index) =>
        `${index ? "L" : "M"}${pointX(index)},${geometry.y(value)}`,
    )
    .join(" ");
  const area = `${line} L${pointX(values.length - 1)},${geometry.y(0)} L${pointX(0)},${geometry.y(0)} Z`;
  const yTicks = [geometry.low, geometry.low / 2, 0];
  const dateTicks = [minimumTime, (minimumTime + maximumTime) / 2, maximumTime];
  const peakX = landmarks ? timeX(new Date(landmarks.peak_at).getTime()) : null;
  const troughX = landmarks
    ? timeX(new Date(landmarks.trough_at).getTime())
    : null;
  const recoveryX = landmarks?.recovered_at
    ? timeX(new Date(landmarks.recovered_at).getTime())
    : null;
  return (
    <>
      {landmarks ? (
        <Row gutter={[8, 8]} style={{ marginBottom: 8 }}>
          <Col span={12}>
            <Statistic
              title="最大回撤"
              value={percent(landmarks.maximum_drawdown)}
            />
          </Col>
          <Col span={12}>
            <Statistic
              title="当前回撤"
              value={percent(landmarks.current_drawdown)}
            />
          </Col>
          <Col span={12}>
            <Statistic
              title="最长回撤持续"
              value={landmarks.longest_drawdown_sessions}
              suffix="个快照"
            />
          </Col>
          <Col span={12}>
            <Statistic
              title="恢复状态"
              value={landmarks.recovered ? "已恢复新高" : "尚未恢复"}
            />
          </Col>
        </Row>
      ) : null}
      <svg
        viewBox={`0 0 ${geometry.width} ${geometry.height}`}
        role="img"
        aria-label="共享资金组合回撤曲线"
        style={{ width: "100%", minHeight: 230 }}
      >
        {yTicks.map((tick) => (
          <g key={tick}>
            <line
              x1={geometry.left}
              y1={geometry.y(tick)}
              x2={geometry.width - geometry.right}
              y2={geometry.y(tick)}
              stroke={tick === 0 ? "#d9d9d9" : "#f0f0f0"}
            />
            <text
              x={geometry.left - 6}
              y={geometry.y(tick) + 4}
              textAnchor="end"
              fontSize="11"
              fill="#8c8c8c"
            >
              {tick.toFixed(1)}%
            </text>
          </g>
        ))}
        <path d={area} fill="rgba(255,77,79,0.18)" />
        <path d={line} fill="none" stroke="#ff4d4f" strokeWidth="2.5" />
        {points.map((point, index) => (
          <circle
            key={point.timestamp}
            cx={pointX(index)}
            cy={geometry.y(values[index])}
            r="6"
            fill="transparent"
          >
            <title>{`${new Date(point.timestamp).toLocaleString("zh-CN")}；回撤 ${values[index].toFixed(2)}%`}</title>
          </circle>
        ))}
        {landmarks && peakX !== null ? (
          <circle cx={peakX} cy={geometry.y(0)} r="4" fill="#fa8c16">
            <title>最大回撤开始</title>
          </circle>
        ) : null}
        {landmarks && troughX !== null ? (
          <circle
            cx={troughX}
            cy={geometry.y(numberValue(landmarks.maximum_drawdown) * 100)}
            r="5"
            fill="#cf1322"
          >
            <title>最大回撤最低点</title>
          </circle>
        ) : null}
        {landmarks && recoveryX !== null ? (
          <circle cx={recoveryX} cy={geometry.y(0)} r="4" fill="#52c41a">
            <title>恢复前高</title>
          </circle>
        ) : null}
        {dateTicks.map((tick) => (
          <text
            key={tick}
            x={timeX(tick)}
            y={geometry.height - 10}
            textAnchor="middle"
            fontSize="11"
            fill="#8c8c8c"
          >
            {new Date(tick).toLocaleDateString("zh-CN")}
          </text>
        ))}
      </svg>
      {landmarks ? (
        <Typography.Text type="secondary">
          最大回撤 {percent(landmarks.maximum_drawdown)}；高点{" "}
          {new Date(landmarks.peak_at).toLocaleDateString("zh-CN")}；低点{" "}
          {new Date(landmarks.trough_at).toLocaleDateString("zh-CN")}；
          {landmarks.recovered && landmarks.recovered_at
            ? `于 ${new Date(landmarks.recovered_at).toLocaleDateString("zh-CN")} 修复`
            : "截至回测结束尚未修复"}
          。
        </Typography.Text>
      ) : null}
    </>
  );
}
