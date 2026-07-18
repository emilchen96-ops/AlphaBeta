import {
  ExperimentOutlined,
  SafetyCertificateOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  Form,
  Input,
  InputNumber,
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
  getBacktest,
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
import { ApiError } from "../api/client";
import { getInstruments } from "../api/market";
import { getStrategyCatalog } from "../api/strategies";
import { BacktestLineChart } from "../components/BacktestCharts/BacktestCharts";
import { PageHeader } from "../components/PageHeader/PageHeader";
import type {
  BacktestFact,
  BacktestMetrics,
  BacktestRun,
  BacktestTrade,
  CreateBacktestRequest,
} from "../types/backtests";
import type { StrategyParameterDefinition } from "../types/strategies";

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

function BoundaryNotice() {
  return (
    <Alert
      showIcon
      type="warning"
      title="历史回测边界"
      description="回测结果不代表未来收益。T 日收盘信号只会在下一根可用日线的开盘阶段尝试执行；当前不使用实时行情、不连接券商、不会产生真实交易。费用与滑点均为模拟配置，部分公司行为可能未完整还原，Signal 也不是实时投资建议。"
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

function formatDate(value?: string | null) {
  return value ? new Date(value).toLocaleString("zh-CN") : "—";
}

function percent(value?: string | null) {
  return value === null || value === undefined
    ? "—"
    : `${(Number(value) * 100).toFixed(2)}%`;
}

function parameterInput(definition: StrategyParameterDefinition) {
  if (definition.type === "boolean") {
    return (
      <Select
        options={[
          { label: "true", value: true },
          { label: "false", value: false },
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
  maximum_volume_participation: string;
  parameters?: Record<string, string | number | boolean>;
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
    () => catalog.data?.find((item) => item.strategy_key === selectedKey),
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
      parameters,
      instrument_ids: values.instrument_ids,
      timeframe: "DAY_1",
      start_at: new Date(values.start_at).toISOString(),
      end_at: new Date(values.end_at).toISOString(),
      initial_cash: String(values.initial_cash),
      order_type: values.order_type,
      time_in_force: values.time_in_force,
      fee_configuration: {
        commission_rate: String(values.commission_rate),
        minimum_commission: String(values.minimum_commission),
        stamp_duty_rate: String(values.stamp_duty_rate),
        transfer_fee_rate: String(values.transfer_fee_rate),
      },
      slippage_configuration: {
        basis_points: String(values.slippage_basis_points),
        maximum_slippage: null,
      },
      maximum_volume_participation:
        values.maximum_volume_participation === ""
          ? null
          : String(values.maximum_volume_participation),
      benchmark_symbol: null,
      idempotency_key: `backtest:${crypto.randomUUID()}`,
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
        <Link to={`/backtest/${run.id}`}>{value}</Link>
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
    { title: "Signal", dataIndex: "signals_generated" },
    { title: "订单", dataIndex: "orders_created" },
    { title: "Fill", dataIndex: "fills_generated" },
  ];

  return (
    <section className="backtest-page">
      <PageHeader
        title="A 股日线回测"
        description="使用本地历史日线，按确定性事件时钟运行 Strategy → Risk → Order → 模拟 Broker → 账本。"
      />
      <BoundaryNotice />
      <Card title="创建回测" className="backtest-section">
        <Form
          form={form}
          layout="vertical"
          initialValues={{
            initial_cash: "100000",
            order_type: "LIMIT",
            time_in_force: "DAY",
            commission_rate: "0.0003",
            minimum_commission: "5",
            stamp_duty_rate: "0.0005",
            transfer_fee_rate: "0.00001",
            slippage_basis_points: "2",
            maximum_volume_participation: "0.1",
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
                    label: `${item.display_name} · ${item.version}`,
                  }))}
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={16}>
              <Form.Item
                name="instrument_ids"
                label="Instrument（可多选）"
                rules={[{ required: true }]}
              >
                <Select
                  mode="multiple"
                  showSearch
                  filterOption={false}
                  onSearch={setInstrumentSearch}
                  loading={instruments.isLoading}
                  options={instruments.data?.items.map((item) => ({
                    value: item.id,
                    label: `${item.symbol} · ${item.name} · ${item.exchange}`,
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
                <Select options={[{ value: "LIMIT" }, { value: "MARKET" }]} />
              </Form.Item>
            </Col>
            <Col xs={12} md={3}>
              <Form.Item name="time_in_force" label="TIF">
                <Select options={[{ value: "DAY" }, { value: "GTC" }]} />
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
                      label={definition.name}
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
                ["commission_rate", "佣金率"],
                ["minimum_commission", "最低佣金"],
                ["stamp_duty_rate", "印花税率"],
                ["transfer_fee_rate", "过户费率"],
                ["slippage_basis_points", "滑点（基点）"],
                ["maximum_volume_participation", "最大成交量参与率"],
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
            </Row>
          </Card>
          <Space>
            <Button
              type="primary"
              icon={<ExperimentOutlined />}
              loading={mutation.isPending}
              onClick={() => void submit()}
            >
              同步运行回测
            </Button>
            <Typography.Text type="secondary">
              请求会同步运行，规模受后端 instruments / bars / sessions
              上限控制。
            </Typography.Text>
          </Space>
          <ErrorNotice error={mutation.error} />
        </Form>
      </Card>
      <Card title="回测记录" className="backtest-section">
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
    ["初始权益", metrics.initial_equity],
    ["期末权益", metrics.final_equity],
    ["总收益", percent(metrics.total_return)],
    ["年化收益", percent(metrics.annualized_return)],
    ["最大回撤", percent(metrics.maximum_drawdown)],
    ["Sharpe", metrics.sharpe_ratio ?? "—"],
    ["Fill 数", metrics.fill_count],
    ["总费用", metrics.total_fees],
    ["胜率", percent(metrics.win_rate)],
    ["Profit Factor", metrics.profit_factor ?? "—"],
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

const factColumns: ColumnsType<BacktestFact> = [
  {
    title: "时间",
    render: (_, item) =>
      formatDate(
        factText(item.occurred_at ?? item.generated_at ?? item.created_at, ""),
      ),
  },
  {
    title: "类型 / 状态",
    render: (_, item) =>
      factText(
        item.event_type ??
          item.signal_type ??
          item.overall_decision ??
          item.status ??
          item.side,
      ),
  },
  {
    title: "摘要",
    render: (_, item) =>
      factText(item.summary ?? item.reason ?? item.message ?? item.id),
  },
];

export function BacktestDetailPage() {
  const { backtestId = "" } = useParams();
  const detail = useQuery({
    queryKey: ["backtest-detail", backtestId],
    enabled: Boolean(backtestId),
    queryFn: async () => {
      const [
        run,
        metricResult,
        equity,
        trades,
        signals,
        risks,
        orders,
        fills,
        timeline,
        integrity,
      ] = await Promise.all([
        getBacktest(backtestId),
        getBacktestMetrics(backtestId),
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
        metrics: metricResult.metrics,
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
  const tradeColumns: ColumnsType<BacktestTrade> = [
    { title: "Instrument", dataIndex: "instrument_id" },
    { title: "开仓", dataIndex: "opened_at", render: formatDate },
    { title: "平仓", dataIndex: "closed_at", render: formatDate },
    { title: "数量", dataIndex: "quantity" },
    { title: "入场价", dataIndex: "entry_price" },
    { title: "离场价", dataIndex: "exit_price" },
    { title: "费用", dataIndex: "fees" },
    { title: "净盈亏", dataIndex: "net_pnl" },
  ];
  return (
    <section className="backtest-page">
      <PageHeader
        title={`回测详情 · ${data.run.strategy_key}`}
        description={`Run ${data.run.id}`}
        action={<Link to="/backtest">返回回测列表</Link>}
      />
      <BoundaryNotice />
      <Card className="backtest-section">
        <Space wrap>
          <Tag color={statusColor[data.run.status]}>
            {statusText[data.run.status]}
          </Tag>
          <Tag>BACKTEST</Tag>
          <Tag
            color={data.integrity.passed ? "green" : "red"}
            icon={<SafetyCertificateOutlined />}
          >
            Integrity {data.integrity.passed ? "通过" : "存在差异"}
          </Tag>
        </Space>
        <Descriptions bordered size="small" column={{ xs: 1, md: 2, xl: 3 }}>
          <Descriptions.Item label="策略版本">
            {data.run.strategy_version}
          </Descriptions.Item>
          <Descriptions.Item label="独立账户">
            {data.run.account_id ?? "—"}
          </Descriptions.Item>
          <Descriptions.Item label="StrategyRun">
            {data.run.strategy_run_id ?? "—"}
          </Descriptions.Item>
          <Descriptions.Item label="Bars">
            {data.run.bars_processed}
          </Descriptions.Item>
          <Descriptions.Item label="Sessions">
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
            title={data.run.error_code}
            description={data.run.error_message}
          />
        ) : null}
      </Card>
      <Card title="核心指标" className="backtest-section">
        <MetricCards metrics={data.metrics} />
      </Card>
      <Row gutter={[16, 16]} className="backtest-section">
        <Col xs={24} xl={12}>
          <Card>
            <BacktestLineChart
              points={data.equity}
              field="total_equity"
              title="权益曲线"
              color="#1677ff"
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
      <Card title="现金与市值" className="backtest-section">
        <Table
          rowKey="id"
          size="small"
          dataSource={data.equity}
          pagination={{ pageSize: 10 }}
          columns={[
            { title: "日期", dataIndex: "timestamp", render: formatDate },
            { title: "现金", dataIndex: "cash" },
            { title: "市值", dataIndex: "market_value" },
            { title: "总权益", dataIndex: "total_equity" },
            { title: "回撤", dataIndex: "drawdown", render: percent },
            {
              title: "估值提示",
              dataIndex: "warnings",
              render: (items: string[]) => items.join("；") || "—",
            },
          ]}
        />
      </Card>
      <Card title="闭合交易" className="backtest-section">
        <Table
          rowKey="id"
          dataSource={data.trades}
          columns={tradeColumns}
          pagination={{ pageSize: 10 }}
        />
      </Card>
      <Card className="backtest-section">
        <Tabs
          items={(
            [
              ["signals", `Signal (${data.signals.length})`, data.signals],
              ["risks", `RiskDecision (${data.risks.length})`, data.risks],
              ["orders", `Order (${data.orders.length})`, data.orders],
              ["fills", `Fill / 费用 (${data.fills.length})`, data.fills],
              ["timeline", `Timeline (${data.timeline.length})`, data.timeline],
            ] as [string, string, BacktestFact[]][]
          ).map(([key, label, items]) => ({
            key,
            label,
            children: (
              <Table
                rowKey={(item) => String(item.id ?? item.sequence_number)}
                dataSource={items}
                columns={factColumns}
                pagination={{ pageSize: 10 }}
              />
            ),
          }))}
        />
      </Card>
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
