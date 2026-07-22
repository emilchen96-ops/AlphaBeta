import {
  CaretRightOutlined,
  PauseOutlined,
  StepForwardOutlined,
  StopOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  DatePicker,
  Descriptions,
  Empty,
  Form,
  Input,
  InputNumber,
  Progress,
  Select,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import dayjs from "dayjs";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  controlReplay,
  createReplay,
  getReplay,
  getReplayEquity,
  getReplayEvents,
  getReplayFills,
  getReplayIntegrity,
  getReplayOrders,
  getReplayRisks,
  getReplaySignals,
  getReplayState,
  listReplays,
  setReplaySpeed,
} from "../api/replays";
import { getInstruments } from "../api/market";
import { getStrategyCatalog } from "../api/strategies";
import { BacktestLineChart } from "../components/BacktestCharts/BacktestCharts";
import { PageHeader } from "../components/PageHeader/PageHeader";
import type {
  CreateReplayRequest,
  ReplayEvent,
  ReplayRun,
  ReplaySpeedMode,
  ReplayState,
} from "../types/replays";

const boundaryDescription =
  "使用 PostgreSQL 本地历史日线；T 日收盘 Signal 最早在下一有效日线 open 执行。播放速度只控制 Session 间隔，不代表真实市场速度。系统不连接券商或 MiniQMT，不产生真实交易；结果不代表未来收益，当前不支持分钟或 Tick 回放。";

function statusColor(status: string) {
  if (status === "COMPLETED") return "success";
  if (status === "RUNNING") return "processing";
  if (status === "FAILED" || status === "STOPPED") return "error";
  if (status === "PAUSED") return "warning";
  return "default";
}

function jsonCell(value: unknown) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  if (typeof value === "string") return value;
  if (typeof value === "number") return value.toString();
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "bigint") return value.toString();
  return "—";
}

function formString(value: unknown) {
  if (typeof value === "string") return value;
  if (typeof value === "number") return value.toString();
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "bigint") return value.toString();
  return "";
}

export function ReplayRunsPage() {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const [form] = Form.useForm();
  const [defaultIdempotencyKey] = useState(() => `replay-ui-${Date.now()}`);
  const strategies = useQuery({
    queryKey: ["strategy-catalog"],
    queryFn: getStrategyCatalog,
  });
  const instruments = useQuery({
    queryKey: ["replay-instruments"],
    queryFn: () => getInstruments(""),
  });
  const runs = useQuery({ queryKey: ["replays"], queryFn: listReplays });
  const selectedStrategy = Form.useWatch<string>("strategy_key", form);
  const metadata = strategies.data?.find(
    (item) => item.strategy_key === selectedStrategy,
  );
  const create = useMutation({
    mutationFn: createReplay,
    onSuccess: (run) => {
      message.success(run.replayed ? "返回已有回放" : "历史回放已创建");
      void navigate(`/replays/${run.id}`);
    },
    onError: (error: Error) => message.error(error.message),
  });

  const submit = (values: Record<string, unknown>) => {
    const range = values.range as [dayjs.Dayjs, dayjs.Dayjs];
    const body: CreateReplayRequest = {
      strategy_key: formString(values.strategy_key),
      parameters: (values.parameters ?? {}) as Record<
        string,
        string | number | boolean
      >,
      instrument_ids: values.instrument_ids as string[],
      start_at: range[0].startOf("day").toISOString(),
      end_at: range[1].endOf("day").toISOString(),
      initial_cash: formString(values.initial_cash),
      order_type: formString(values.order_type),
      time_in_force: formString(values.time_in_force),
      strategy_price_adjustment_mode: values.strategy_price_adjustment_mode as
        "RAW" | "QFQ",
      fee_configuration: {
        commission_rate: formString(values.commission_rate),
        minimum_commission: formString(values.minimum_commission),
        stamp_duty_rate: formString(values.stamp_duty_rate),
        transfer_fee_rate: formString(values.transfer_fee_rate),
      },
      slippage_configuration: {
        basis_points: formString(values.slippage_basis_points),
        maximum_slippage: null,
      },
      maximum_volume_participation:
        values.maximum_volume_participation === null ||
        values.maximum_volume_participation === undefined
          ? null
          : formString(values.maximum_volume_participation),
      risk_configuration_reference: "r01-default-v1",
      speed_mode: values.speed_mode as ReplaySpeedMode,
      data_source_code: null,
      idempotency_key: formString(values.idempotency_key),
    };
    create.mutate(body);
  };

  return (
    <section>
      <PageHeader
        title="日线历史回放"
        description="启动、暂停、单步或加速观察完整 Strategy → Risk → Order → Fill → 账本链路。"
      />
      <Alert
        showIcon
        type="warning"
        title="这是历史行情回放，不是实时市场"
        description={boundaryDescription}
      />
      <Card title="创建独立回放" className="details-card">
        <Form
          form={form}
          layout="vertical"
          initialValues={{
            range: [dayjs().subtract(1, "year"), dayjs()],
            initial_cash: "1000000",
            order_type: "LIMIT",
            time_in_force: "DAY",
            commission_rate: "0.0003",
            minimum_commission: "5",
            stamp_duty_rate: "0.0005",
            transfer_fee_rate: "0.00001",
            slippage_basis_points: "2",
            maximum_volume_participation: "0.1",
            speed_mode: "MANUAL",
            strategy_price_adjustment_mode: "RAW",
            idempotency_key: defaultIdempotencyKey,
          }}
          onFinish={submit}
        >
          <div className="form-grid">
            <Form.Item
              name="strategy_key"
              label="策略"
              rules={[{ required: true }]}
            >
              <Select
                loading={strategies.isLoading}
                options={strategies.data?.map((item) => ({
                  value: item.strategy_key,
                  label: `${item.display_name} · ${item.version}`,
                }))}
              />
            </Form.Item>
            <Form.Item
              name="instrument_ids"
              label="股票标的"
              rules={[{ required: true }]}
            >
              <Select
                mode="multiple"
                maxCount={20}
                showSearch
                optionFilterProp="label"
                loading={instruments.isLoading}
                options={instruments.data?.items.map((item) => ({
                  value: item.id,
                  label: `${item.symbol}.${item.exchange} ${item.name}`,
                }))}
              />
            </Form.Item>
            <Form.Item
              name="range"
              label="历史区间"
              rules={[{ required: true }]}
            >
              <DatePicker.RangePicker style={{ width: "100%" }} />
            </Form.Item>
            <Form.Item
              name="initial_cash"
              label="初始资金"
              rules={[{ required: true }]}
            >
              <Input />
            </Form.Item>
            <Form.Item name="order_type" label="订单类型">
              <Select options={[{ value: "LIMIT" }, { value: "MARKET" }]} />
            </Form.Item>
            <Form.Item name="time_in_force" label="订单有效期（TIF）">
              <Select options={[{ value: "DAY" }, { value: "GTC" }]} />
            </Form.Item>
            <Form.Item
              name="strategy_price_adjustment_mode"
              label="策略价格模式"
              tooltip="QFQ 仅用于策略输入；成交、Fill、费用和账本始终使用 RAW。"
            >
              <Select
                options={[
                  { value: "RAW", label: "RAW（未复权）" },
                  { value: "QFQ", label: "QFQ（前复权，仅策略）" },
                ]}
              />
            </Form.Item>
            <Form.Item name="speed_mode" label="初始速度">
              <Select
                options={["MANUAL", "X1", "X10", "X100"].map((value) => ({
                  value,
                }))}
              />
            </Form.Item>
            <Form.Item
              name="maximum_volume_participation"
              label="最大成交量参与率"
            >
              <Input />
            </Form.Item>
          </div>
          {metadata?.parameters.length ? (
            <Card size="small" title="策略参数">
              <div className="form-grid">
                {metadata.parameters.map((parameter) => (
                  <Form.Item
                    key={parameter.name}
                    name={["parameters", parameter.name]}
                    label={`${parameter.name} · ${parameter.description}`}
                    initialValue={parameter.default}
                    rules={[{ required: parameter.required }]}
                  >
                    {parameter.type === "boolean" ? (
                      <Select options={[{ value: true }, { value: false }]} />
                    ) : parameter.choices.length ? (
                      <Select
                        options={parameter.choices.map((value) => ({ value }))}
                      />
                    ) : parameter.type === "integer" ? (
                      <InputNumber style={{ width: "100%" }} />
                    ) : (
                      <Input />
                    )}
                  </Form.Item>
                ))}
              </div>
            </Card>
          ) : null}
          <Card size="small" title="费用与滑点">
            <div className="form-grid">
              {[
                ["commission_rate", "佣金率"],
                ["minimum_commission", "最低佣金"],
                ["stamp_duty_rate", "印花税率"],
                ["transfer_fee_rate", "过户费率"],
                ["slippage_basis_points", "滑点（bp）"],
              ].map(([name, label]) => (
                <Form.Item key={name} name={name} label={label}>
                  <Input />
                </Form.Item>
              ))}
            </div>
          </Card>
          <Button type="primary" htmlType="submit" loading={create.isPending}>
            创建历史回放
          </Button>
        </Form>
      </Card>
      <Card title="回放运行" className="details-card" loading={runs.isLoading}>
        <Table
          rowKey="id"
          dataSource={runs.data?.items ?? []}
          pagination={false}
          columns={[
            {
              title: "创建时间",
              dataIndex: "created_at",
              render: (value: string) =>
                dayjs(value).format("YYYY-MM-DD HH:mm:ss"),
            },
            { title: "策略", dataIndex: "strategy_key" },
            {
              title: "状态",
              dataIndex: "status",
              render: (value: string) => (
                <Tag color={statusColor(value)}>{value}</Tag>
              ),
            },
            {
              title: "进度",
              render: (_: unknown, item: ReplayRun) =>
                `${item.current_session_index}/${item.total_sessions}`,
            },
            { title: "速度", dataIndex: "speed_mode" },
            {
              title: "操作",
              render: (_: unknown, item: ReplayRun) => (
                <Link to={`/replays/${item.id}`}>打开控制台</Link>
              ),
            },
          ]}
        />
      </Card>
    </section>
  );
}

export function ReplayControlPanel({ run }: { run: ReplayRun }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: async (command: string) => {
      if (["MANUAL", "X1", "X10", "X100"].includes(command)) {
        return setReplaySpeed(
          run.id,
          command as ReplaySpeedMode,
          run.row_version,
        );
      }
      return controlReplay(
        run.id,
        command as "start" | "pause" | "resume" | "step" | "stop",
        run.row_version,
      );
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["replay", run.id] });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const terminal = ["COMPLETED", "STOPPED", "FAILED"].includes(run.status);
  return (
    <Card title="回放控制">
      <Space wrap>
        <Button
          type="primary"
          icon={<CaretRightOutlined />}
          disabled={run.status !== "READY"}
          onClick={() => mutation.mutate("start")}
        >
          启动
        </Button>
        <Button
          icon={<PauseOutlined />}
          disabled={run.status !== "RUNNING"}
          onClick={() => mutation.mutate("pause")}
        >
          暂停
        </Button>
        <Button
          icon={<CaretRightOutlined />}
          disabled={run.status !== "PAUSED"}
          onClick={() => mutation.mutate("resume")}
        >
          恢复
        </Button>
        <Button
          icon={<StepForwardOutlined />}
          disabled={!(["READY", "PAUSED"] as string[]).includes(run.status)}
          onClick={() => mutation.mutate("step")}
        >
          单步一个 Session
        </Button>
        {(["MANUAL", "X1", "X10", "X100"] as ReplaySpeedMode[]).map((speed) => (
          <Button
            key={speed}
            type={run.speed_mode === speed ? "primary" : "default"}
            disabled={terminal}
            onClick={() => mutation.mutate(speed)}
          >
            {speed}
          </Button>
        ))}
        <Button
          danger
          icon={<StopOutlined />}
          disabled={terminal}
          onClick={() => mutation.mutate("stop")}
        >
          停止
        </Button>
      </Space>
    </Card>
  );
}

export function ReplayMarketPanel({
  run,
  state,
}: {
  run: ReplayRun;
  state?: ReplayState;
}) {
  const currentBar = state?.current_bar as Record<string, unknown> | undefined;
  return (
    <Card title="当前历史交易日（Session）/ K 线">
      <Descriptions column={2} size="small">
        <Descriptions.Item label="业务日期">
          {run.current_session_date ?? "尚未推进"}
        </Descriptions.Item>
        <Descriptions.Item label="数据来源">
          本地 PostgreSQL DAY_1
        </Descriptions.Item>
        {Object.entries(currentBar ?? {}).map(([key, value]) => (
          <Descriptions.Item key={key} label={key}>
            {jsonCell(value)}
          </Descriptions.Item>
        ))}
      </Descriptions>
      {!currentBar ? <Empty description="单步或启动后显示当前日线" /> : null}
    </Card>
  );
}

export function ReplayPortfolioPanel({ state }: { state?: ReplayState }) {
  const positions = state?.positions ?? [];
  return (
    <Card title="回放专属账户">
      <Typography.Paragraph>现金：{jsonCell(state?.cash)}</Typography.Paragraph>
      <Table
        size="small"
        rowKey={(item) => String(item.id)}
        dataSource={positions}
        pagination={false}
        columns={[
          { title: "Instrument", dataIndex: "instrument_id" },
          { title: "数量", dataIndex: "total_quantity" },
          { title: "可用", dataIndex: "available_quantity" },
          { title: "成本", dataIndex: "average_cost" },
          { title: "已实现盈亏", dataIndex: "realized_pnl" },
        ]}
      />
    </Card>
  );
}

export function ReplayEventTimeline({ events }: { events: ReplayEvent[] }) {
  return (
    <Table
      size="small"
      rowKey="id"
      dataSource={events}
      pagination={{ pageSize: 20 }}
      columns={[
        { title: "#", dataIndex: "sequence_number", width: 70 },
        { title: "事件", dataIndex: "event_type" },
        { title: "业务时间", dataIndex: "business_time" },
        { title: "摘要", dataIndex: "summary" },
        {
          title: "关联",
          render: (_: unknown, item: ReplayEvent) =>
            [item.related_entity_type, item.related_entity_id]
              .filter(Boolean)
              .join(" · ") || "—",
        },
      ]}
    />
  );
}

function useReplaySocket(id: string | undefined) {
  const queryClient = useQueryClient();
  const lastSequence = useRef(0);
  useEffect(() => {
    if (!id || typeof WebSocket === "undefined") return;
    const base = (
      import.meta.env.VITE_WS_BASE_URL ?? "ws://localhost:8000"
    ).replace(/\/$/, "");
    let socket: WebSocket | undefined;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
    let disposed = false;
    const connect = () => {
      socket = new WebSocket(
        `${base}/ws/replays/${id}?after_sequence=${lastSequence.current}`,
      );
      socket.onmessage = (message) => {
        try {
          const envelope = JSON.parse(String(message.data)) as {
            sequence_number?: number;
            event_type?: string;
          };
          const sequence = envelope.sequence_number ?? 0;
          if (
            envelope.event_type === "HEARTBEAT" ||
            sequence <= lastSequence.current
          )
            return;
          lastSequence.current = sequence;
          void queryClient.invalidateQueries({ queryKey: ["replay", id] });
        } catch {
          // Polling remains the recovery path for malformed display notifications.
        }
      };
      socket.onclose = () => {
        if (!disposed) reconnectTimer = setTimeout(connect, 1000);
      };
    };
    connect();
    return () => {
      disposed = true;
      if (reconnectTimer !== undefined) clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, [id, queryClient]);
}

export function ReplayRunDetailPage() {
  const { replayId } = useParams();
  useReplaySocket(replayId);
  const run = useQuery({
    queryKey: ["replay", replayId],
    queryFn: () => getReplay(replayId!),
    enabled: Boolean(replayId),
    refetchInterval: 1000,
  });
  const state = useQuery({
    queryKey: ["replay", replayId, "state"],
    queryFn: () => getReplayState(replayId!),
    enabled: Boolean(replayId),
    refetchInterval: 1000,
  });
  const equity = useQuery({
    queryKey: ["replay", replayId, "equity"],
    queryFn: () => getReplayEquity(replayId!),
    enabled: Boolean(replayId),
    refetchInterval: 1000,
  });
  const events = useQuery({
    queryKey: ["replay", replayId, "events"],
    queryFn: () => getReplayEvents(replayId!),
    enabled: Boolean(replayId),
    refetchInterval: 1000,
  });
  const signals = useQuery({
    queryKey: ["replay", replayId, "signals"],
    queryFn: () => getReplaySignals(replayId!),
    enabled: Boolean(replayId),
  });
  const risks = useQuery({
    queryKey: ["replay", replayId, "risks"],
    queryFn: () => getReplayRisks(replayId!),
    enabled: Boolean(replayId),
  });
  const orders = useQuery({
    queryKey: ["replay", replayId, "orders"],
    queryFn: () => getReplayOrders(replayId!),
    enabled: Boolean(replayId),
  });
  const fills = useQuery({
    queryKey: ["replay", replayId, "fills"],
    queryFn: () => getReplayFills(replayId!),
    enabled: Boolean(replayId),
  });
  const integrity = useQuery({
    queryKey: ["replay", replayId, "integrity"],
    queryFn: () => getReplayIntegrity(replayId!),
    enabled: Boolean(replayId),
  });
  const progress = run.data
    ? (run.data.current_session_index / run.data.total_sessions) * 100
    : 0;
  const facts = useMemo(
    () =>
      [
        ["Signal", signals.data?.items ?? []],
        ["RiskDecision", risks.data?.items ?? []],
        ["Order", orders.data?.items ?? []],
        ["Fill", fills.data?.items ?? []],
      ] as const,
    [signals.data, risks.data, orders.data, fills.data],
  );
  if (!run.data) return <Card loading={run.isLoading}>加载回放…</Card>;
  return (
    <section>
      <PageHeader
        title="历史回放控制台"
        description={`${run.data.strategy_key} · ${run.data.id}`}
        action={<Link to="/replays">返回回放列表</Link>}
      />
      <Alert
        showIcon
        type="warning"
        title="本页面只控制历史模拟运行"
        description={boundaryDescription}
      />
      {!run.data.worker_online && run.data.status === "RUNNING" ? (
        <Alert
          showIcon
          type="error"
          title="回放执行服务（Replay Worker）离线"
          description="请启动 replay_worker；已提交的事实不会丢失。若 lease 过期，系统会暂停并要求手工恢复。"
        />
      ) : null}
      <Card className="details-card">
        <Space wrap size="large">
          <Statistic title="状态" value={run.data.status} />
          <Statistic
            title="当前交易日（Session）"
            value={run.data.current_session_date ?? "—"}
          />
          <Statistic title="速度" value={run.data.speed_mode} />
          <Statistic title="研究信号" value={run.data.signals_generated} />
          <Statistic
            title="订单 / 成交"
            value={`${run.data.orders_created} / ${run.data.fills_generated}`}
          />
          <Tag color={run.data.worker_online ? "success" : "error"}>
            Worker {run.data.worker_online ? "在线" : "离线"}
          </Tag>
        </Space>
        <Progress percent={Number(progress.toFixed(1))} />
      </Card>
      <ReplayControlPanel run={run.data} />
      <div className="dashboard-grid">
        <ReplayMarketPanel run={run.data} state={state.data?.state} />
        <ReplayPortfolioPanel state={state.data?.state} />
      </div>
      <Card title="动态权益与回撤" className="details-card">
        <BacktestLineChart
          points={equity.data?.items ?? []}
          field="total_equity"
          title="权益曲线"
          color="#1677ff"
        />
        <BacktestLineChart
          points={equity.data?.items ?? []}
          field="drawdown"
          title="回撤曲线"
          color="#ef4444"
          percent
        />
      </Card>
      <Card className="details-card">
        <Tabs
          items={[
            {
              key: "events",
              label: `ReplayEvent (${events.data?.total ?? 0})`,
              children: (
                <ReplayEventTimeline events={events.data?.items ?? []} />
              ),
            },
            ...facts.map(([label, items]) => ({
              key: label,
              label: `${label} (${items.length})`,
              children: (
                <Table
                  size="small"
                  rowKey={(item) => String(item.id)}
                  dataSource={items}
                  scroll={{ x: 900 }}
                  columns={Object.keys(items[0] ?? {})
                    .slice(0, 8)
                    .map((key) => ({
                      title: key,
                      dataIndex: key,
                      render: jsonCell,
                    }))}
                />
              ),
            })),
          ]}
        />
      </Card>
      <Card title="最终指标与完整性检查" className="details-card">
        <Descriptions column={2} bordered size="small">
          {Object.entries(run.data.final_summary ?? {}).map(([key, value]) => (
            <Descriptions.Item key={key} label={key}>
              {jsonCell(value)}
            </Descriptions.Item>
          ))}
        </Descriptions>
        <Alert
          showIcon
          type={integrity.data?.ok ? "success" : "warning"}
          title={
            integrity.data?.ok
              ? "Integrity 通过"
              : "Integrity 尚未通过或仍在运行"
          }
          description={integrity.data?.issues.join("；") || "未发现事实差异"}
        />
      </Card>
    </section>
  );
}
