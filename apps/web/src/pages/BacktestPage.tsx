import {
  ExperimentOutlined,
  SafetyCertificateOutlined,
} from "@ant-design/icons";
import {
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Col,
  Collapse,
  Descriptions,
  Empty,
  Form,
  Input,
  InputNumber,
  List,
  Row,
  Select,
  Space,
  Spin,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  createBacktest,
  getBacktestEquity,
  getBacktestFills,
  getBacktestIntegrity,
  getBacktestMetrics,
  getBacktestOrders,
  getBacktestRisks,
  getBacktestSignals,
  getBacktestTimeline,
  getBacktestTrades,
  listBacktests,
} from "../api/backtests";
import {
  createUserStrategy,
  getResearchBacktest,
  getResearchBacktestSummary,
} from "../api/strategySpecs";
import { ApiError } from "../api/client";
import { getBars, getInstrument, getInstruments } from "../api/market";
import { getStrategyCatalog } from "../api/strategies";
import { BacktestLineChart } from "../components/BacktestCharts/BacktestCharts";
import { CandlestickChart } from "../components/CandlestickChart/CandlestickChart";
import { PageHeader } from "../components/PageHeader/PageHeader";
import type {
  BacktestEquityPoint,
  BacktestFill,
  BacktestMetrics,
  BacktestOrder,
  BacktestRiskDecision,
  BacktestRun,
  BacktestSignal,
  BacktestTimelineEvent,
  BacktestTrade,
  CreateBacktestRequest,
} from "../types/backtests";
import type { StrategyParameterDefinition } from "../types/strategies";
import type { Instrument } from "../types/market";
import {
  displayEnum,
  displayParameter,
  displayStrategy,
  formatDateTime,
  formatInstrument,
  formatMoney,
  formatNumber,
  formatPercentRatio,
  formatPrice,
  formatQuantity,
  isTestData,
  localizeReason,
  shortId,
} from "../utils/display";

const statusColor: Record<BacktestRun["status"], string> = {
  CREATED: "default",
  RUNNING: "processing",
  COMPLETED: "success",
  FAILED: "error",
};

const statusText: Record<BacktestRun["status"], string> = {
  CREATED: "已创建",
  RUNNING: "运行中",
  COMPLETED: "已完成",
  FAILED: "失败",
};

const backtestFailureText: Record<
  string,
  { title: string; description: string }
> = {
  MARKET_ADJUSTMENT_FACTOR_NOT_AVAILABLE: {
    title: "前复权数据尚未准备完成",
    description:
      "当前股票缺少所选区间的前复权因子。请先在数据中心补齐复权因子，或在高级设置中改用“不复权”后重新回测。",
  },
  BACKTEST_DATA_NOT_READY: {
    title: "历史行情尚未准备完成",
    description:
      "当前股票在所选区间缺少可用的正式日线，请先在数据中心补齐数据后重试。",
  },
  BACKTEST_NO_MARKET_DATA: {
    title: "没有找到历史行情",
    description:
      "本地数据库中没有该股票在所选区间的日线，请先补齐数据或调整回测区间。",
  },
};

function BoundaryNotice() {
  return (
    <Alert
      showIcon
      type="warning"
      title="历史回测边界"
      description="回测结果不代表未来收益。T 日收盘信号只会在下一根可用日线的开盘阶段尝试执行；当前不使用实时行情、不连接券商、不会产生真实交易。费用与滑点均为模拟配置，部分公司行为可能未完整还原，暂不支持分钟或逐笔（Tick）回测，研究信号（Signal）也不是实时投资建议。"
    />
  );
}

function factText(value: unknown, fallback = "—"): string {
  if (value === null || value === undefined || value === "") return fallback;
  if (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean" ||
    typeof value === "bigint"
  ) {
    return String(value);
  }
  try {
    return JSON.stringify(value);
  } catch {
    return fallback;
  }
}

function ErrorNotice({ error }: { error: unknown }) {
  if (!error) return null;
  const apiError = error instanceof ApiError ? error : null;
  return (
    <Alert
      showIcon
      type="error"
      title={error instanceof Error ? error.message : "请求失败"}
      description={
        apiError?.correlationId
          ? `错误代码：${apiError.code}；Correlation ID：${apiError.correlationId}`
          : undefined
      }
    />
  );
}

const formatDate = formatDateTime;
const percent = formatPercentRatio;

function parameterInput(definition: StrategyParameterDefinition) {
  if (definition.type === "boolean") {
    return (
      <Select
        options={[
          { label: "是", value: true },
          { label: "否", value: false },
        ]}
      />
    );
  }
  if (definition.type === "enum") {
    return <Select options={definition.choices.map((value) => ({ value }))} />;
  }
  if (definition.type === "integer") {
    return (
      <InputNumber
        precision={0}
        min={
          definition.min_value === null
            ? undefined
            : Number(definition.min_value)
        }
        max={
          definition.max_value === null
            ? undefined
            : Number(definition.max_value)
        }
        style={{ width: "100%" }}
      />
    );
  }
  return <Input />;
}

interface BacktestFormValues {
  strategy_key: string;
  instrument_ids: string[];
  start_at: string;
  end_at: string;
  initial_cash: string;
  order_type: "MARKET" | "LIMIT";
  time_in_force: "DAY" | "GTC";
  commission_rate: string;
  minimum_commission: string;
  stamp_duty_rate: string;
  transfer_fee_rate: string;
  slippage_basis_points: string;
  maximum_volume_participation?: string | null;
  idempotency_key?: string;
  strategy_price_adjustment_mode: "RAW" | "QFQ";
  parameters?: Record<string, string | number | boolean>;
}

function newIdempotencyKey() {
  return `backtest:${crypto.randomUUID()}`;
}

export function BacktestPage() {
  const [form] = Form.useForm<BacktestFormValues>();
  const [page, setPage] = useState(1);
  const [instrumentSearch, setInstrumentSearch] = useState("");
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const selectedKey = Form.useWatch("strategy_key", form);
  const catalog = useQuery({
    queryKey: ["strategy-catalog"],
    queryFn: getStrategyCatalog,
  });
  const instruments = useQuery({
    queryKey: ["backtest-instruments", instrumentSearch],
    queryFn: () => getInstruments(instrumentSearch),
  });
  const runs = useQuery({
    queryKey: ["backtests", page],
    queryFn: () => listBacktests(page),
  });
  const strategy = useMemo(
    () =>
      Array.isArray(catalog.data)
        ? catalog.data.find((item) => item.strategy_key === selectedKey)
        : undefined,
    [catalog.data, selectedKey],
  );
  const mutation = useMutation({
    mutationFn: createBacktest,
    onSuccess: (run) => {
      void queryClient.invalidateQueries({ queryKey: ["backtests"] });
      void navigate(`/backtest/${run.id}`);
    },
  });

  const submit = async () => {
    const values = await form.validateFields();
    const parameters = Object.fromEntries(
      Object.entries(values.parameters ?? {}).filter(
        ([, value]) => value !== "",
      ),
    );
    const body: CreateBacktestRequest = {
      strategy_key: values.strategy_key,
      data_source_code: "MINIQMT",
      parameters,
      instrument_ids: values.instrument_ids,
      timeframe: "DAY_1",
      strategy_price_adjustment_mode: values.strategy_price_adjustment_mode,
      start_at: new Date(values.start_at).toISOString(),
      end_at: new Date(values.end_at).toISOString(),
      initial_cash: String(values.initial_cash),
      order_type: values.order_type,
      time_in_force: values.time_in_force,
      fee_configuration: {
        commission_rate: String(Number(values.commission_rate) / 100),
        minimum_commission: String(values.minimum_commission),
        stamp_duty_rate: String(Number(values.stamp_duty_rate) / 100),
        transfer_fee_rate: String(Number(values.transfer_fee_rate) / 100),
      },
      slippage_configuration: {
        basis_points: String(values.slippage_basis_points),
        maximum_slippage: null,
      },
      maximum_volume_participation: !values.maximum_volume_participation?.trim()
        ? null
        : String(Number(values.maximum_volume_participation) / 100),
      benchmark_symbol: null,
      idempotency_key: values.idempotency_key?.trim() || newIdempotencyKey(),
    };
    mutation.mutate(body);
  };

  const columns: ColumnsType<BacktestRun> = [
    {
      title: "创建时间",
      dataIndex: "created_at",
      render: (value: string) => formatDate(value),
    },
    {
      title: "策略",
      dataIndex: "strategy_key",
      render: (value: string, run) => (
        <Link to={`/backtest/${run.id}`}>{displayStrategy(value)}</Link>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      render: (value: BacktestRun["status"]) => (
        <Tag color={statusColor[value]}>{statusText[value]}</Tag>
      ),
    },
    { title: "交易日", dataIndex: "sessions_processed" },
    { title: "研究信号", dataIndex: "signals_generated" },
    { title: "订单", dataIndex: "orders_created" },
    { title: "成交", dataIndex: "fills_generated" },
  ];

  return (
    <section className="backtest-page">
      <PageHeader
        title="快速回测"
        description="选择策略、股票和时间范围，查看收益、回撤与完整模拟交易记录。"
      />
      <BoundaryNotice />
      <Card title="设置回测条件" className="backtest-section">
        <Form
          form={form}
          layout="vertical"
          initialValues={{
            initial_cash: "100000",
            order_type: "LIMIT",
            time_in_force: "DAY",
            commission_rate: "0.03",
            minimum_commission: "5",
            stamp_duty_rate: "0.05",
            transfer_fee_rate: "0.001",
            slippage_basis_points: "2",
            maximum_volume_participation: "10",
            idempotency_key: newIdempotencyKey(),
            strategy_price_adjustment_mode: "RAW",
          }}
        >
          <Row gutter={16}>
            <Col xs={24} md={8}>
              <Form.Item
                name="strategy_key"
                label="策略"
                rules={[{ required: true }]}
              >
                <Select
                  loading={catalog.isLoading}
                  options={catalog.data?.map((item) => ({
                    value: item.strategy_key,
                    label: `${displayStrategy(item.strategy_key)} · ${item.version}`,
                  }))}
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item
                name="strategy_price_adjustment_mode"
                label="策略价格复权模式"
                tooltip="仅影响策略输入和研究信号；开盘成交、费用与账本始终使用不复权价格。"
                rules={[{ required: true }]}
              >
                <Select
                  options={[
                    { value: "RAW", label: "不复权（RAW）" },
                    { value: "QFQ", label: "前复权（QFQ，仅策略）" },
                  ]}
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item label="历史行情来源">
                <Space orientation="vertical" size={2}>
                  <Tag color="green">MiniQMT（只读行情）</Tag>
                  <Typography.Text type="secondary">
                    使用已同步到本地数据库的正式历史日线
                  </Typography.Text>
                </Space>
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item
                name="instrument_ids"
                label="回测股票（可多选）"
                rules={[{ required: true }]}
              >
                <Select
                  mode="multiple"
                  showSearch
                  filterOption={false}
                  onSearch={setInstrumentSearch}
                  loading={instruments.isLoading}
                  options={instruments.data?.items
                    .filter((item) => !isTestData(item))
                    .map((item) => ({
                      value: item.id,
                      label: formatInstrument(item),
                    }))}
                />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col xs={24} md={6}>
              <Form.Item
                name="start_at"
                label="开始日期"
                rules={[{ required: true }]}
              >
                <Input type="date" />
              </Form.Item>
            </Col>
            <Col xs={24} md={6}>
              <Form.Item
                name="end_at"
                label="结束日期（不含）"
                rules={[{ required: true }]}
              >
                <Input type="date" />
              </Form.Item>
            </Col>
            <Col xs={24} md={6}>
              <Form.Item
                name="initial_cash"
                label="初始资金"
                rules={[{ required: true }]}
              >
                <Input />
              </Form.Item>
            </Col>
            <Col xs={12} md={3}>
              <Form.Item name="order_type" label="订单类型">
                <Select
                  options={[
                    { value: "LIMIT", label: "限价单（LIMIT）" },
                    { value: "MARKET", label: "市价单（MARKET）" },
                  ]}
                />
              </Form.Item>
            </Col>
            <Col xs={12} md={3}>
              <Form.Item name="time_in_force" label="订单有效期（TIF）">
                <Select
                  options={[
                    { value: "DAY", label: "当日有效（DAY）" },
                    { value: "GTC", label: "撤销前有效（GTC）" },
                  ]}
                />
              </Form.Item>
            </Col>
          </Row>
          {strategy?.parameters.length ? (
            <Card
              size="small"
              title="策略参数"
              className="backtest-nested-card"
            >
              <Row gutter={16}>
                {strategy.parameters.map((definition) => (
                  <Col xs={24} md={8} key={definition.name}>
                    <Form.Item
                      name={["parameters", definition.name]}
                      label={displayParameter(definition.name)}
                      tooltip={definition.description}
                      initialValue={definition.default ?? undefined}
                    >
                      {parameterInput(definition)}
                    </Form.Item>
                  </Col>
                ))}
              </Row>
            </Card>
          ) : null}
          <Card
            size="small"
            title="费用、滑点与成交量约束"
            className="backtest-nested-card"
          >
            <Row gutter={16}>
              {[
                ["commission_rate", "佣金率（%）"],
                ["minimum_commission", "最低佣金（元）"],
                ["stamp_duty_rate", "印花税率（%）"],
                ["transfer_fee_rate", "过户费率（%）"],
                ["slippage_basis_points", "滑点（基点）"],
              ].map(([name, label]) => (
                <Col xs={24} sm={12} md={4} key={name}>
                  <Form.Item
                    name={name}
                    label={label}
                    rules={[{ required: true }]}
                  >
                    <Input />
                  </Form.Item>
                </Col>
              ))}
              <Col xs={24} sm={12} md={4}>
                <Form.Item
                  name="maximum_volume_participation"
                  label="最大成交量参与率（%，可空）"
                  tooltip="留空表示不额外限制成交量参与率"
                >
                  <Input allowClear placeholder="留空表示不限制" />
                </Form.Item>
              </Col>
            </Row>
          </Card>
          <Space>
            <Button
              type="primary"
              icon={<ExperimentOutlined />}
              loading={mutation.isPending}
              onClick={() => void submit()}
            >
              开始回测
            </Button>
            <Typography.Text type="secondary">
              回测将在当前请求中运行；完成前请勿关闭页面。股票、K线和交易日数量受安全上限控制。
            </Typography.Text>
          </Space>
          <ErrorNotice error={mutation.error} />
        </Form>
      </Card>
      <Card title="我的回测记录" className="backtest-section">
        <ErrorNotice error={runs.error} />
        <Table
          rowKey="id"
          loading={runs.isLoading}
          columns={columns}
          dataSource={runs.data?.items ?? []}
          pagination={{
            current: page,
            pageSize: 20,
            total: runs.data?.total ?? 0,
            onChange: setPage,
          }}
        />
      </Card>
    </section>
  );
}

function MetricCards({ metrics }: { metrics: BacktestMetrics }) {
  const cards = [
    ["初始权益", formatMoney(metrics.initial_equity)],
    ["期末权益", formatMoney(metrics.final_equity)],
    ["总收益", percent(metrics.total_return)],
    ["年化收益", percent(metrics.annualized_return)],
    ["最大回撤", percent(metrics.maximum_drawdown)],
    ["夏普比率（Sharpe）", formatNumber(metrics.sharpe_ratio)],
    ["成交数量", metrics.fill_count],
    [
      "买入 / 卖出成交",
      `${metrics.buy_fill_count} / ${metrics.sell_fill_count}`,
    ],
    ["总成交额", formatMoney(metrics.total_turnover)],
    ["总费用", formatMoney(metrics.total_fees)],
    ["佣金", formatMoney(metrics.total_commission)],
    ["印花税", formatMoney(metrics.total_stamp_duty)],
    ["过户费", formatMoney(metrics.total_transfer_fee)],
    ["其他费用", formatMoney(metrics.total_other_fee)],
    ["已实现盈亏", formatMoney(metrics.realized_pnl)],
    ["胜率", percent(metrics.win_rate)],
    ["亏损率", percent(metrics.loss_rate)],
    ["平均盈利", formatMoney(metrics.average_win)],
    ["平均亏损", formatMoney(metrics.average_loss)],
    ["盈亏比（Profit Factor）", formatNumber(metrics.profit_factor)],
    ["年化波动率", percent(metrics.annualized_volatility)],
    ["平均敞口", percent(metrics.average_exposure)],
    ["最大敞口", percent(metrics.maximum_exposure)],
  ];
  return (
    <Row gutter={[12, 12]}>
      {cards.map(([title, value]) => (
        <Col xs={12} md={6} xl={5} key={String(title)}>
          <Card size="small">
            <Statistic title={title} value={value} />
          </Card>
        </Col>
      ))}
    </Row>
  );
}

type InstrumentMap = Map<string, Instrument>;

function instrumentLabel(id: string, instruments: InstrumentMap) {
  const instrument = instruments.get(id);
  return instrument
    ? formatInstrument(instrument)
    : `未知标的（${shortId(id)}）`;
}

function signalColumns(
  instruments: InstrumentMap,
): ColumnsType<BacktestSignal> {
  return [
    { title: "信号时间", dataIndex: "generated_at", render: formatDate },
    { title: "K线时间", dataIndex: "bar_timestamp", render: formatDate },
    {
      title: "股票名称与代码",
      dataIndex: "instrument_id",
      render: (value: string) => instrumentLabel(value, instruments),
    },
    { title: "类型", dataIndex: "signal_type", render: displayEnum },
    { title: "方向", dataIndex: "side", render: displayEnum },
    { title: "状态", dataIndex: "status", render: displayEnum },
    {
      title: "目标",
      render: (_, item) =>
        item.target_quantity !== null
          ? `数量 ${formatQuantity(item.target_quantity)} 股`
          : item.target_weight !== null
            ? `权重 ${percent(item.target_weight)}`
            : "—",
    },
    {
      title: "参考价",
      dataIndex: "reference_price",
      render: (value: string | null) => formatPrice(value),
    },
    { title: "原因", dataIndex: "reason", render: localizeReason },
  ];
}

function riskColumns(
  instruments: InstrumentMap,
): ColumnsType<BacktestRiskDecision> {
  return [
    { title: "评估时间", dataIndex: "evaluated_at", render: formatDate },
    {
      title: "股票名称与代码",
      dataIndex: "instrument_id",
      render: (value: string) => instrumentLabel(value, instruments),
    },
    { title: "决策", dataIndex: "overall_decision", render: displayEnum },
    {
      title: "估算金额",
      dataIndex: "estimated_notional",
      render: formatMoney,
    },
    {
      title: "标的权重",
      dataIndex: "projected_instrument_weight",
      render: (value: string | null) => percent(value),
    },
    {
      title: "总敞口",
      dataIndex: "projected_total_exposure",
      render: (value: string | null) => percent(value),
    },
    {
      title: "提示",
      dataIndex: "warnings",
      render: (items: string[]) => items.join("；") || "—",
    },
  ];
}

function orderColumns(instruments: InstrumentMap): ColumnsType<BacktestOrder> {
  return [
    { title: "创建时间", dataIndex: "created_at", render: formatDate },
    {
      title: "股票名称与代码",
      dataIndex: "instrument_id",
      render: (value: string) => instrumentLabel(value, instruments),
    },
    { title: "方向", dataIndex: "side", render: displayEnum },
    { title: "类型", dataIndex: "order_type", render: displayEnum },
    { title: "订单有效期", dataIndex: "time_in_force", render: displayEnum },
    { title: "状态", dataIndex: "status", render: displayEnum },
    {
      title: "委托数量",
      dataIndex: "requested_quantity",
      render: formatQuantity,
    },
    { title: "成交数量", dataIndex: "filled_quantity", render: formatQuantity },
    {
      title: "限价",
      dataIndex: "limit_price",
      render: formatPrice,
    },
    {
      title: "均价",
      dataIndex: "average_fill_price",
      render: formatPrice,
    },
    {
      title: "最终时间",
      render: (_, item) =>
        formatDate(
          item.completed_at ??
            item.expired_at ??
            item.submitted_at ??
            item.confirmed_at,
        ),
    },
  ];
}

function fillColumns(instruments: InstrumentMap): ColumnsType<BacktestFill> {
  return [
    { title: "成交时间", dataIndex: "executed_at", render: formatDate },
    {
      title: "股票名称与代码",
      dataIndex: "instrument_id",
      render: (value: string) => instrumentLabel(value, instruments),
    },
    { title: "数量", dataIndex: "quantity", render: formatQuantity },
    { title: "价格", dataIndex: "price", render: formatPrice },
    { title: "成交额", dataIndex: "gross_amount", render: formatMoney },
    { title: "佣金", dataIndex: "commission", render: formatMoney },
    { title: "税费", dataIndex: "tax", render: formatMoney },
    { title: "其他费用", dataIndex: "other_fee", render: formatMoney },
    { title: "净额", dataIndex: "net_amount", render: formatMoney },
    { title: "接收时间", dataIndex: "received_at", render: formatDate },
  ];
}

const timelineColumns: ColumnsType<BacktestTimelineEvent> = [
  { title: "序号", dataIndex: "sequence_number" },
  { title: "权威时间", dataIndex: "occurred_at", render: formatDate },
  { title: "事件类型", dataIndex: "event_type", render: displayEnum },
  { title: "摘要", dataIndex: "summary" },
  {
    title: "详情",
    dataIndex: "details",
    render: (value: Record<string, unknown>) => factText(value),
  },
];

export function BacktestDetailPage() {
  const { backtestId = "" } = useParams();
  const detail = useQuery({
    queryKey: ["backtest-detail", backtestId],
    enabled: Boolean(backtestId),
    queryFn: async () => {
      const run = await getResearchBacktest(backtestId);
      const summary = await getResearchBacktestSummary(backtestId);
      let metrics: BacktestMetrics | null = run.metrics ?? null;
      let metricsError: unknown = null;
      if (run.status === "COMPLETED" && metrics === null) {
        try {
          metrics = (await getBacktestMetrics(backtestId)).metrics;
        } catch (error) {
          metricsError = error;
        }
      }
      const [
        equity,
        trades,
        signals,
        risks,
        orders,
        fills,
        timeline,
        integrity,
      ] = await Promise.all([
        getBacktestEquity(backtestId),
        getBacktestTrades(backtestId),
        getBacktestSignals(backtestId),
        getBacktestRisks(backtestId),
        getBacktestOrders(backtestId),
        getBacktestFills(backtestId),
        getBacktestTimeline(backtestId),
        getBacktestIntegrity(backtestId),
      ]);
      return {
        run,
        summary,
        metrics,
        metricsError,
        equity: equity.items,
        trades: trades.items,
        signals: signals.items,
        risks: risks.items,
        orders: orders.items,
        fills: fills.items,
        timeline: timeline.items,
        integrity,
      };
    },
  });
  const factInstrumentIds = useMemo(() => {
    if (!detail.data) return [];
    return Array.from(
      new Set([
        ...detail.data.trades.map((item) => item.instrument_id),
        ...detail.data.signals.map((item) => item.instrument_id),
        ...detail.data.risks.map((item) => item.instrument_id),
        ...detail.data.orders.map((item) => item.instrument_id),
        ...detail.data.fills.map((item) => item.instrument_id),
      ]),
    );
  }, [detail.data]);
  const configuredInstrumentIds = useMemo(() => {
    const value = detail.data?.run.configuration?.instrument_ids;
    return Array.isArray(value)
      ? value.filter((item): item is string => typeof item === "string")
      : [];
  }, [detail.data]);
  const primaryInstrumentId =
    factInstrumentIds[0] ?? configuredInstrumentIds[0] ?? "";
  const configuredAdjustmentMode =
    detail.data?.run.configuration?.strategy_price_adjustment_mode;
  const chartAdjustmentMode =
    configuredAdjustmentMode === "RAW" ? "RAW" : "QFQ";
  const factInstrumentQueries = useQueries({
    queries: factInstrumentIds.map((id) => ({
      queryKey: ["instrument", id],
      queryFn: () => getInstrument(id),
      staleTime: 5 * 60_000,
    })),
  });
  const factInstruments = new Map(
    factInstrumentQueries
      .map((query) => query.data)
      .filter((item) => item !== undefined)
      .map((item) => [item.id, item]),
  );
  const chartBars = useQuery({
    queryKey: ["backtest-chart-bars", primaryInstrumentId, chartAdjustmentMode],
    enabled: Boolean(primaryInstrumentId),
    queryFn: () => getBars(primaryInstrumentId, "DAY_1", chartAdjustmentMode),
  });
  const saveStrategy = useMutation({
    mutationFn: createUserStrategy,
  });
  if (detail.isLoading) return <Spin size="large" />;
  if (detail.error)
    return (
      <section>
        <PageHeader title="回测详情" description="加载回测事实与结果。" />
        <ErrorNotice error={detail.error} />
      </section>
    );
  if (!detail.data) return <Empty description="回测不存在" />;
  const data = detail.data;
  const bars = chartBars.data?.items ?? [];
  const firstEquityAt = data.equity[0]?.timestamp;
  const lastEquityAt = data.equity.at(-1)?.timestamp;
  const benchmarkBars =
    firstEquityAt && lastEquityAt
      ? bars.filter(
          (bar) =>
            new Date(bar.bar_time).getTime() >=
              new Date(firstEquityAt).getTime() &&
            new Date(bar.bar_time).getTime() <=
              new Date(lastEquityAt).getTime(),
        )
      : [];
  const firstBenchmarkClose = Number(benchmarkBars[0]?.close);
  const initialBenchmarkEquity = Number(
    data.metrics?.initial_equity ?? data.equity[0]?.total_equity ?? 0,
  );
  const benchmark =
    Number.isFinite(firstBenchmarkClose) &&
    firstBenchmarkClose > 0 &&
    Number.isFinite(initialBenchmarkEquity)
      ? benchmarkBars.map((bar) => ({
          timestamp: bar.bar_time,
          value: String(
            (Number(bar.close) / firstBenchmarkClose) * initialBenchmarkEquity,
          ),
        }))
      : [];
  const tradeColumns: ColumnsType<BacktestTrade> = [
    {
      title: "股票名称与代码",
      dataIndex: "instrument_id",
      render: (value: string) => instrumentLabel(value, factInstruments),
    },
    { title: "开仓", dataIndex: "opened_at", render: formatDate },
    { title: "平仓", dataIndex: "closed_at", render: formatDate },
    { title: "数量", dataIndex: "quantity", render: formatQuantity },
    { title: "入场价", dataIndex: "entry_price", render: formatPrice },
    { title: "离场价", dataIndex: "exit_price", render: formatPrice },
    { title: "费用", dataIndex: "fees", render: formatMoney },
    { title: "净盈亏", dataIndex: "net_pnl", render: formatMoney },
  ];
  return (
    <section className="backtest-page">
      <PageHeader
        title={`回测详情 · ${displayStrategy(data.run.strategy_key)}`}
        description="先看收益与风险，再按需展开交易和完整事实链。"
        action={
          <Space wrap>
            <Link to="/research/backtest">再次回测</Link>
            {data.run.strategy_spec ? (
              <Button
                type="link"
                icon={<ExperimentOutlined />}
                loading={saveStrategy.isPending}
                disabled={saveStrategy.isSuccess}
                onClick={() =>
                  saveStrategy.mutate({
                    name: data.run.strategy_spec?.name ?? "我的回测策略",
                    description:
                      data.run.strategy_spec?.description ??
                      "从回测结果保存的策略",
                    spec: data.run.strategy_spec!,
                  })
                }
              >
                {saveStrategy.isSuccess ? "已保存到我的策略" : "保存为我的策略"}
              </Button>
            ) : null}
            <Link
              to={`/research/parameter-comparison${
                data.run.strategy_spec
                  ? `?template=${encodeURIComponent(data.run.strategy_key)}`
                  : ""
              }`}
            >
              参数对比
            </Link>
            {data.run.status === "COMPLETED" ? (
              <Link to={`/research/backtests/${backtestId}/replay`}>
                逐日查看
              </Link>
            ) : null}
            <Link to="/research/history?tab=backtests">返回研究记录</Link>
          </Space>
        }
      />
      <Alert
        showIcon
        type="info"
        title={data.run.simulation_notice ?? "回测仅为历史模拟，不会发送给券商"}
        style={{ marginBottom: 16 }}
      />
      {saveStrategy.error ? (
        <ErrorNotice error={saveStrategy.error} />
      ) : saveStrategy.isSuccess ? (
        <Alert
          showIcon
          type="success"
          title="策略已保存，可在“我的策略”中再次使用"
          style={{ marginBottom: 16 }}
        />
      ) : null}
      {data.run.strategy_preview?.length ? (
        <Card title="本次回测规则（不可变快照）" className="backtest-section">
          <List
            dataSource={data.run.strategy_preview}
            renderItem={(item) => <List.Item>{item}</List.Item>}
          />
        </Card>
      ) : null}
      <Card title="运行概况" className="backtest-section">
        <Space wrap>
          <Tag color={statusColor[data.run.status]}>
            {statusText[data.run.status]}
          </Tag>
          <Tag>日线回测</Tag>
        </Space>
        <Descriptions bordered size="small" column={{ xs: 1, md: 2, xl: 3 }}>
          <Descriptions.Item label="策略版本">
            {data.run.strategy_version}
          </Descriptions.Item>
          <Descriptions.Item label="K线数量">
            {data.run.bars_processed}
          </Descriptions.Item>
          <Descriptions.Item label="交易日数量">
            {data.run.sessions_processed}
          </Descriptions.Item>
          <Descriptions.Item label="创建时间">
            {formatDate(data.run.created_at)}
          </Descriptions.Item>
        </Descriptions>
        {data.run.error_code ? (
          <Alert
            type="error"
            showIcon
            title={
              backtestFailureText[data.run.error_code]?.title ??
              "本次回测未能完成"
            }
            description={
              backtestFailureText[data.run.error_code]?.description ??
              data.run.error_message ??
              "请检查历史数据状态后重试。"
            }
          />
        ) : null}
      </Card>
      <Card title="核心指标" className="backtest-section">
        {data.metrics?.warnings.length ? (
          <Alert
            showIcon
            type="info"
            title="指标计算提示"
            description={data.metrics.warnings.map(localizeReason).join("；")}
          />
        ) : null}
        {data.metrics ? (
          <MetricCards metrics={data.metrics} />
        ) : data.metricsError ? (
          <ErrorNotice error={data.metricsError} />
        ) : (
          <Alert
            showIcon
            type="info"
            title="绩效指标尚未生成"
            description={
              data.run.status === "FAILED"
                ? "本次回测失败，已提交的运行事实仍可在下方查看。"
                : "回测完成后将生成权益曲线和绩效指标。"
            }
          />
        )}
        {(data.summary.explanation?.length ?? 0) > 0 ? (
          <Alert
            showIcon
            type="warning"
            title="为什么没有成交？"
            description={(data.summary.explanation ?? []).join("；")}
            style={{ marginTop: 16 }}
          />
        ) : null}
      </Card>
      <Row gutter={[16, 16]} className="backtest-section">
        <Col xs={24} xl={12}>
          <Card>
            <BacktestLineChart
              points={data.equity}
              field="total_equity"
              title="权益曲线"
              color="#1677ff"
              benchmark={benchmark}
            />
          </Card>
        </Col>
        <Col xs={24} xl={12}>
          <Card>
            <BacktestLineChart
              points={data.equity}
              field="drawdown"
              title="回撤曲线"
              color="#f04438"
              percent
            />
          </Card>
        </Col>
      </Row>
      <Card title="K线买卖点" className="backtest-section">
        <CandlestickChart
          bars={bars}
          loading={chartBars.isLoading}
          markers={data.signals
            .filter(
              (signal) =>
                signal.bar_timestamp &&
                (signal.side === "BUY" || signal.side === "SELL"),
            )
            .map((signal) => ({
              time: signal.bar_timestamp!,
              side: signal.side as "BUY" | "SELL",
              label: `${displayEnum(signal.side)}：${localizeReason(signal.reason)}`,
            }))}
        />
      </Card>
      <Card title="现金与市值" className="backtest-section">
        <Table<BacktestEquityPoint>
          rowKey="id"
          size="small"
          dataSource={data.equity}
          pagination={{ pageSize: 10 }}
          columns={[
            { title: "日期", dataIndex: "timestamp", render: formatDate },
            { title: "现金", dataIndex: "cash", render: formatMoney },
            { title: "市值", dataIndex: "market_value", render: formatMoney },
            { title: "总权益", dataIndex: "total_equity", render: formatMoney },
            {
              title: "总敞口金额",
              dataIndex: "gross_exposure",
              render: formatMoney,
            },
            {
              title: "净敞口金额",
              dataIndex: "net_exposure",
              render: formatMoney,
            },
            { title: "持仓数", dataIndex: "positions_count" },
            {
              title: "回撤",
              dataIndex: "drawdown",
              render: (value: string | null) => percent(value),
            },
            {
              title: "估值提示",
              dataIndex: "warnings",
              render: (items: string[]) =>
                items.map(localizeReason).join("；") || "—",
            },
          ]}
        />
      </Card>
      <Card title="买卖交易记录" className="backtest-section">
        <Table
          rowKey="id"
          dataSource={data.trades}
          columns={tradeColumns}
          pagination={{ pageSize: 10 }}
        />
      </Card>
      <Collapse
        className="backtest-section"
        defaultActiveKey={data.run.strategy_spec ? undefined : ["technical"]}
        items={[
          {
            key: "technical",
            label: "技术详情（策略信号、规则检查、模拟交易事实与审计）",
            children: (
              <>
                <Space wrap style={{ marginBottom: 16 }}>
                  <Tag
                    color={data.integrity.passed ? "green" : "red"}
                    icon={<SafetyCertificateOutlined />}
                  >
                    完整性检查：
                    {data.integrity.passed ? "通过" : "存在差异"}
                  </Tag>
                  <Typography.Text type="secondary">
                    账户：
                    {data.run.account_id ? shortId(data.run.account_id) : "—"}
                  </Typography.Text>
                  <Typography.Text type="secondary">
                    策略运行：
                    {data.run.strategy_run_id
                      ? shortId(data.run.strategy_run_id)
                      : "—"}
                  </Typography.Text>
                </Space>
                <Tabs
                  items={[
                    {
                      key: "signals",
                      label: `策略信号（${data.signals.length}）`,
                      children: (
                        <Table
                          rowKey="id"
                          dataSource={data.signals}
                          columns={signalColumns(factInstruments)}
                          pagination={{ pageSize: 10 }}
                          scroll={{ x: true }}
                        />
                      ),
                    },
                    {
                      key: "risks",
                      label: `规则检查（${data.risks.length}）`,
                      children: (
                        <Table
                          rowKey="id"
                          dataSource={data.risks}
                          columns={riskColumns(factInstruments)}
                          pagination={{ pageSize: 10 }}
                          scroll={{ x: true }}
                        />
                      ),
                    },
                    {
                      key: "orders",
                      label: `模拟交易指令（${data.orders.length}）`,
                      children: (
                        <Table
                          rowKey="id"
                          dataSource={data.orders}
                          columns={orderColumns(factInstruments)}
                          pagination={{ pageSize: 10 }}
                          scroll={{ x: true }}
                        />
                      ),
                    },
                    {
                      key: "fills",
                      label: `模拟成交与费用（${data.fills.length}）`,
                      children: (
                        <Table
                          rowKey="id"
                          dataSource={data.fills}
                          columns={fillColumns(factInstruments)}
                          pagination={{ pageSize: 10 }}
                          scroll={{ x: true }}
                        />
                      ),
                    },
                    {
                      key: "timeline",
                      label: `事件时间线（${data.timeline.length}）`,
                      children: (
                        <Table
                          rowKey="id"
                          dataSource={data.timeline}
                          columns={timelineColumns}
                          pagination={{ pageSize: 10 }}
                          scroll={{ x: true }}
                        />
                      ),
                    },
                  ]}
                />
              </>
            ),
          },
        ]}
      />
      {!data.integrity.passed ? (
        <Alert
          showIcon
          type="error"
          title="完整性检查发现差异"
          description={data.integrity.issues
            .map((item) => `${item.code}: ${item.message}`)
            .join("；")}
        />
      ) : null}
    </section>
  );
}
