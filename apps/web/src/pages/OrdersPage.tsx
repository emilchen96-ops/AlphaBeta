import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  PlusOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Timeline,
  Typography,
} from "antd";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { getAccounts } from "../api/accounts";
import { ApiError } from "../api/client";
import { getInstruments } from "../api/market";
import {
  cancelOrder,
  confirmOrder,
  createOrder,
  getOrder,
  getExecutionIntegrity,
  getOrderExecutionAttempts,
  getOrderFills,
  getOrders,
  getOrderTimeline,
} from "../api/orders";
import { PageHeader } from "../components/PageHeader/PageHeader";
import { SimulatedExecutionModal } from "../components/SimulatedExecutionModal/SimulatedExecutionModal";
import { getRiskDecision } from "../api/risk";
import { systemCapabilitiesQueryOptions } from "../api/system";
import type { OrderFactSummary } from "../types/orders";

const stateText: Record<string, string> = {
  WAITING_CONFIRMATION: "等待人工确认",
  QUEUED: "本地指令事实已创建，等待未来投递",
  CANCELLED: "已取消",
  EXPIRED: "已过期",
  BROKER_ACCEPTED: "模拟 Broker 已接受",
  PARTIALLY_FILLED: "模拟部分成交",
  FILLED: "模拟全部成交",
  EXECUTOR_REJECTED: "模拟执行拒绝",
  FAILED: "模拟 Broker 拒绝",
};

const executableStatuses = new Set([
  "QUEUED",
  "BROKER_ACCEPTED",
  "PARTIALLY_FILLED",
]);

function idempotencyKey(prefix: string, orderId?: string) {
  return `${prefix}:${orderId ?? "new"}:${crypto.randomUUID()}`;
}

function riskReason(item: Record<string, unknown>, fallback: string) {
  if (typeof item.message === "string") return item.message;
  if (typeof item.reason_code === "string") return item.reason_code;
  return fallback;
}

function factStatus(item: Record<string, unknown> | undefined) {
  return typeof item?.status === "string" ? item.status : "UNKNOWN";
}

export function OrdersPage() {
  const [searchParams] = useSearchParams();
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState<string>();
  const [accountFilter, setAccountFilter] = useState<string>();
  const [instrumentFilter, setInstrumentFilter] = useState<string>();
  const [instrumentSearch, setInstrumentSearch] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [confirming, setConfirming] = useState<OrderFactSummary>();
  const [executing, setExecuting] = useState<OrderFactSummary>();
  const [selectedId, setSelectedId] = useState<string | undefined>(
    searchParams.get("order_id") ?? undefined,
  );
  const [riskOutcome, setRiskOutcome] = useState<{
    kind: "PASS" | "REJECT" | "REVIEW";
    decisionId: string;
    orderId?: string;
    reasons: string[];
  }>();
  const [form] = Form.useForm();
  const capabilities = useQuery(systemCapabilitiesQueryOptions);
  const unavailable =
    capabilities.data?.items?.find((item) => item.module_key === "orders")
      ?.available === false;
  const unavailableReason = capabilities.data?.items?.find(
    (item) => item.module_key === "orders",
  )?.reason;

  const accounts = useQuery({ queryKey: ["accounts"], queryFn: getAccounts });
  const instruments = useQuery({
    queryKey: ["order-instruments", instrumentSearch],
    queryFn: () => getInstruments(instrumentSearch),
  });
  const orders = useQuery({
    queryKey: ["orders", page, status, accountFilter, instrumentFilter],
    queryFn: () =>
      getOrders({
        page,
        pageSize: 20,
        status,
        accountId: accountFilter,
        instrumentId: instrumentFilter,
      }),
  });
  const detail = useQuery({
    queryKey: ["order", selectedId],
    queryFn: () => getOrder(selectedId ?? ""),
    enabled: Boolean(selectedId),
  });
  const timeline = useQuery({
    queryKey: ["order-timeline", selectedId],
    queryFn: () => getOrderTimeline(selectedId ?? ""),
    enabled: Boolean(selectedId),
  });
  const attempts = useQuery({
    queryKey: ["order-execution-attempts", selectedId],
    queryFn: () => getOrderExecutionAttempts(selectedId ?? ""),
    enabled: Boolean(selectedId),
  });
  const fills = useQuery({
    queryKey: ["order-fills", selectedId],
    queryFn: () => getOrderFills(selectedId ?? ""),
    enabled: Boolean(selectedId),
  });
  const integrity = useQuery({
    queryKey: ["order-execution-integrity", selectedId],
    queryFn: () => getExecutionIntegrity(selectedId ?? ""),
    enabled: Boolean(selectedId) && (attempts.data?.total ?? 0) > 0,
  });

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["orders"] }),
      queryClient.invalidateQueries({ queryKey: ["order"] }),
      queryClient.invalidateQueries({ queryKey: ["order-timeline"] }),
      queryClient.invalidateQueries({ queryKey: ["order-execution-attempts"] }),
      queryClient.invalidateQueries({ queryKey: ["order-fills"] }),
      queryClient.invalidateQueries({
        queryKey: ["order-execution-integrity"],
      }),
    ]);
  };
  const action = useMutation({
    mutationFn: (operation: () => Promise<OrderFactSummary>) => operation(),
    onSuccess: async (order) => {
      if (createOpen && order.risk_decision_id) {
        setRiskOutcome({
          kind: "PASS",
          decisionId: order.risk_decision_id,
          orderId: order.id,
          reasons: [],
        });
      }
      setSelectedId(order.id);
      setCreateOpen(false);
      setConfirming(undefined);
      if (createOpen) form.resetFields();
      await refresh();
      void message.success("订单事实已更新");
    },
    onError: async (error: Error) => {
      if (
        error instanceof ApiError &&
        ["RISK_ORDER_REJECTED", "RISK_ORDER_REVIEW_REQUIRED"].includes(
          error.code,
        )
      ) {
        const details = error.details as { risk_decision_id?: string } | null;
        if (details?.risk_decision_id) {
          const decision = await getRiskDecision(details.risk_decision_id);
          setRiskOutcome({
            kind: error.code === "RISK_ORDER_REJECTED" ? "REJECT" : "REVIEW",
            decisionId: decision.id,
            reasons: decision.risk_rule_summary.map((item) =>
              riskReason(item, "需要查看规则详情"),
            ),
          });
          setCreateOpen(false);
        }
      }
      const conflict = error.message.includes("version")
        ? "订单版本已变化，请刷新后重试"
        : error.message;
      void message.error(conflict);
    },
  });

  const submitCreate = async () => {
    const values = (await form.validateFields()) as Record<string, string>;
    action.mutate(() =>
      createOrder({
        account_id: values.account_id,
        instrument_id: values.instrument_id,
        side: values.side as "BUY" | "SELL",
        order_type: values.order_type as "LIMIT" | "MARKET",
        time_in_force: values.time_in_force,
        requested_quantity: values.requested_quantity,
        limit_price: values.order_type === "LIMIT" ? values.limit_price : null,
        expires_at: values.expires_at
          ? new Date(values.expires_at).toISOString()
          : null,
        idempotency_key: idempotencyKey("create"),
      }),
    );
  };

  return (
    <section>
      <PageHeader
        title="订单中心"
        description="人工订单先经过 R01 风控和 M05 确认；仅可使用手工快照执行本地模拟成交，不连接真实券商。"
        action={
          <Button
            icon={<PlusOutlined />}
            disabled={unavailable}
            onClick={() => setCreateOpen(true)}
          >
            创建订单
          </Button>
        }
      />
      <Alert
        showIcon
        type="warning"
        title="订单创建必须通过服务端风控"
        description="LIMIT 估算金额仅为数量 × 用户限价，MARKET 无法估算成交金额。PASS 只创建 WAITING_CONFIRMATION Order；REJECT 或 REVIEW 不创建 Order，也不会自动重试或绕过风控。"
      />
      {unavailable ? (
        <Alert
          showIcon
          type="info"
          title="当前缺少订单前置数据"
          description={unavailableReason}
          style={{ marginTop: 16 }}
        />
      ) : null}
      {riskOutcome ? (
        <Alert
          style={{ marginTop: 16 }}
          showIcon
          type={
            riskOutcome.kind === "PASS"
              ? "success"
              : riskOutcome.kind === "REJECT"
                ? "error"
                : "warning"
          }
          title={
            riskOutcome.kind === "PASS"
              ? "风控通过"
              : riskOutcome.kind === "REJECT"
                ? "风控拒绝"
                : "需要人工复核"
          }
          description={
            <Space orientation="vertical">
              <Typography.Text>
                RiskDecision {riskOutcome.decisionId}
                {riskOutcome.orderId
                  ? `；Order ${riskOutcome.orderId} 已进入 WAITING_CONFIRMATION`
                  : "；未创建 Order"}
              </Typography.Text>
              {riskOutcome.reasons.map((reason) => (
                <Typography.Text key={reason}>{reason}</Typography.Text>
              ))}
              <Space>
                <Link to={`/risk/decisions/${riskOutcome.decisionId}`}>
                  查看风控详情
                </Link>
                {riskOutcome.orderId ? (
                  <Button
                    type="link"
                    onClick={() => setSelectedId(riskOutcome.orderId)}
                  >
                    查看订单详情
                  </Button>
                ) : null}
              </Space>
            </Space>
          }
        />
      ) : null}
      <Card style={{ marginTop: 16 }}>
        <Space wrap style={{ marginBottom: 16 }}>
          <Select<string>
            allowClear
            placeholder="状态筛选"
            style={{ width: 180 }}
            onChange={(value) => {
              setPage(1);
              setStatus(value);
            }}
            options={Object.entries(stateText).map(([value, label]) => ({
              value,
              label,
            }))}
          />
          <Select
            allowClear
            placeholder="模拟账户筛选"
            style={{ width: 220 }}
            onChange={setAccountFilter}
            options={accounts.data?.items.map((item) => ({
              value: item.id,
              label: `${item.account_code} · ${item.name}`,
            }))}
          />
          <Select
            allowClear
            showSearch
            placeholder="标的筛选"
            style={{ width: 220 }}
            filterOption={false}
            onSearch={setInstrumentSearch}
            onChange={setInstrumentFilter}
            options={instruments.data?.items.map((item) => ({
              value: item.id,
              label: `${item.symbol}.${item.exchange} · ${item.name}`,
            }))}
          />
        </Space>
        {orders.isError ? (
          <Alert
            type="error"
            title="订单加载失败"
            description={orders.error.message}
          />
        ) : null}
        <Table<OrderFactSummary>
          rowKey="id"
          loading={orders.isLoading}
          dataSource={orders.data?.items ?? []}
          locale={{ emptyText: <Empty description="暂无订单事实" /> }}
          pagination={{
            current: page,
            pageSize: 20,
            total: orders.data?.total ?? 0,
            onChange: setPage,
          }}
          columns={[
            {
              title: "标的",
              render: (_, item) => `${item.symbol}.${item.exchange}`,
            },
            { title: "方向", dataIndex: "side" },
            { title: "类型", dataIndex: "order_type" },
            { title: "数量", dataIndex: "requested_quantity" },
            {
              title: "限价",
              dataIndex: "limit_price",
              render: (value: string | null) => value ?? "—",
            },
            {
              title: "状态",
              render: (_, item) => (
                <Tag>{stateText[item.status] ?? item.status}</Tag>
              ),
            },
            { title: "版本", dataIndex: "row_version" },
            {
              title: "操作",
              render: (_, item) => (
                <Space>
                  <Button size="small" onClick={() => setSelectedId(item.id)}>
                    详情
                  </Button>
                  {item.capabilities.can_confirm ? (
                    <Button
                      size="small"
                      type="primary"
                      disabled={action.isPending}
                      onClick={() => setConfirming(item)}
                    >
                      人工确认
                    </Button>
                  ) : null}
                  {item.capabilities.can_cancel ? (
                    <Button
                      size="small"
                      danger
                      disabled={action.isPending}
                      onClick={() =>
                        action.mutate(() =>
                          cancelOrder(
                            item.id,
                            item.row_version,
                            idempotencyKey("cancel", item.id),
                          ),
                        )
                      }
                    >
                      取消
                    </Button>
                  ) : null}
                  {executableStatuses.has(item.status) ? (
                    <Button size="small" onClick={() => setExecuting(item)}>
                      模拟执行
                    </Button>
                  ) : null}
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        title="创建人工订单意图"
        open={createOpen}
        confirmLoading={action.isPending}
        onCancel={() => setCreateOpen(false)}
        onOk={() => void submitCreate()}
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{
            side: "BUY",
            order_type: "LIMIT",
            time_in_force: "DAY",
          }}
        >
          <Form.Item
            name="account_id"
            label="模拟账户"
            rules={[{ required: true }]}
          >
            <Select
              options={accounts.data?.items.map((item) => ({
                value: item.id,
                label: `${item.account_code} · ${item.name}`,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="instrument_id"
            label="Instrument"
            rules={[{ required: true }]}
          >
            <Select
              showSearch
              filterOption={false}
              onSearch={setInstrumentSearch}
              options={instruments.data?.items.map((item) => ({
                value: item.id,
                label: `${item.symbol}.${item.exchange} · ${item.name}`,
              }))}
            />
          </Form.Item>
          <Space wrap>
            <Form.Item name="side" label="方向">
              <Select
                style={{ width: 120 }}
                options={[{ value: "BUY" }, { value: "SELL" }]}
              />
            </Form.Item>
            <Form.Item name="order_type" label="类型">
              <Select
                style={{ width: 120 }}
                options={[{ value: "LIMIT" }, { value: "MARKET" }]}
              />
            </Form.Item>
            <Form.Item name="time_in_force" label="TIF">
              <Select
                style={{ width: 120 }}
                options={[{ value: "DAY" }, { value: "GTC" }]}
              />
            </Form.Item>
          </Space>
          <Form.Item
            name="requested_quantity"
            label="数量"
            rules={[{ required: true }]}
          >
            <Input inputMode="decimal" />
          </Form.Item>
          <Form.Item
            noStyle
            shouldUpdate={(
              before: Record<string, unknown>,
              after: Record<string, unknown>,
            ) => before.order_type !== after.order_type}
          >
            {({ getFieldValue }) =>
              getFieldValue("order_type") === "LIMIT" ? (
                <Form.Item
                  name="limit_price"
                  label="限价"
                  rules={[{ required: true }]}
                >
                  <Input inputMode="decimal" />
                </Form.Item>
              ) : (
                <Typography.Text type="secondary">
                  MARKET 无法估算成交金额
                </Typography.Text>
              )
            }
          </Form.Item>
          <Form.Item name="expires_at" label="过期时间（可选）">
            <Input type="datetime-local" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="确认创建本地指令事实"
        open={Boolean(confirming)}
        confirmLoading={action.isPending}
        okText="确认（不发送）"
        onCancel={() => setConfirming(undefined)}
        onOk={() =>
          confirming &&
          action.mutate(() =>
            confirmOrder(
              confirming.id,
              confirming.row_version,
              idempotencyKey("confirm", confirming.id),
            ),
          )
        }
      >
        <Alert
          type="warning"
          showIcon
          description="此操作仅写入 PostgreSQL：OrderCommand PENDING 与 Outbox PENDING。消息尚未发布，不会调用执行器或券商。"
        />
      </Modal>

      <Drawer
        title="订单事实详情"
        size="large"
        open={Boolean(selectedId)}
        onClose={() => setSelectedId(undefined)}
      >
        {detail.isLoading ? <Typography.Text>加载中…</Typography.Text> : null}
        {detail.data ? (
          <>
            <Descriptions
              column={2}
              bordered
              size="small"
              items={[
                {
                  key: "status",
                  label: "状态",
                  children: stateText[detail.data.status] ?? detail.data.status,
                },
                {
                  key: "version",
                  label: "版本",
                  children: detail.data.row_version,
                },
                {
                  key: "account",
                  label: "账户",
                  children: detail.data.account_name,
                },
                {
                  key: "instrument",
                  label: "标的",
                  children: `${detail.data.symbol}.${detail.data.exchange}`,
                },
                {
                  key: "notional",
                  label: "估算金额",
                  children: detail.data.estimated_notional ?? "MARKET 不可估算",
                },
                {
                  key: "correlation",
                  label: "Correlation ID",
                  children: detail.data.correlation_id,
                },
                {
                  key: "risk",
                  label: "风控结果",
                  children: detail.data.risk_decision ?? "—",
                },
                {
                  key: "risk-time",
                  label: "风控评估时间",
                  children: detail.data.risk_evaluated_at
                    ? new Date(detail.data.risk_evaluated_at).toLocaleString()
                    : "—",
                },
              ]}
            />
            <Typography.Title level={5}>RiskDecision</Typography.Title>
            {detail.data.risk_decision_id ? (
              <Space orientation="vertical">
                <Link to={`/risk/decisions/${detail.data.risk_decision_id}`}>
                  查看风控决策 {detail.data.risk_decision_id}
                </Link>
                {detail.data.risk_rule_summary.map((item, index) => (
                  <Typography.Text key={index} type="warning">
                    {riskReason(item, "风控规则提示")}
                  </Typography.Text>
                ))}
              </Space>
            ) : (
              <Typography.Text type="secondary">无关联风控决策</Typography.Text>
            )}
            <Typography.Title level={5}>OrderAction</Typography.Title>
            {detail.data.actions.length ? (
              detail.data.actions.map((item, index) => (
                <Tag key={index}>{String(item.action_type)}</Tag>
              ))
            ) : (
              <Typography.Text type="secondary">暂无动作</Typography.Text>
            )}
            <Typography.Title level={5}>Command</Typography.Title>
            {detail.data.commands.length ? (
              <Alert
                icon={<CheckCircleOutlined />}
                showIcon
                type="info"
                title={`指令状态：${factStatus(detail.data.commands[0])}`}
                description="本地模拟执行后 Command 会变为 CONSUMED，不会发送到外部执行器。"
              />
            ) : (
              <Empty description="尚未创建指令" />
            )}
            <Typography.Title level={5}>Outbox</Typography.Title>
            {detail.data.outbox.length ? (
              <Alert
                icon={<CloseCircleOutlined />}
                showIcon
                type="warning"
                title={`Outbox 状态：${factStatus(detail.data.outbox[0])}`}
                description="本地模拟执行后 Outbox 会被 SUPPRESSED；SUPPRESSED 不等于 PUBLISHED。"
              />
            ) : (
              <Empty description="尚无 Outbox" />
            )}
            <Typography.Title level={5}>Timeline</Typography.Title>
            <Timeline
              items={
                timeline.data?.map((item) => ({
                  content: (
                    <>
                      <strong>{item.kind}</strong> {item.label}
                      <br />
                      <Typography.Text type="secondary">
                        v{item.order_version ?? "—"} ·{" "}
                        {new Date(item.occurred_at).toLocaleString()}
                      </Typography.Text>
                    </>
                  ),
                })) ?? []
              }
            />
            <Typography.Title level={5}>模拟执行</Typography.Title>
            <Alert
              showIcon
              type="warning"
              title="本地模拟成交记录"
              description="显式市场快照不连接真实行情或券商；Fill 会修改模拟账户账本。"
              action={
                executableStatuses.has(detail.data.status) ? (
                  <Button
                    size="small"
                    onClick={() => setExecuting(detail.data)}
                  >
                    模拟执行
                  </Button>
                ) : undefined
              }
            />
            <Table
              rowKey="id"
              size="small"
              loading={attempts.isLoading}
              pagination={false}
              dataSource={attempts.data?.items ?? []}
              locale={{ emptyText: "暂无模拟执行记录" }}
              columns={[
                { title: "#", dataIndex: "attempt_number" },
                { title: "输入状态", dataIndex: "input_order_status" },
                { title: "结果", dataIndex: "result_status" },
                { title: "尝试数量", dataIndex: "attempted_quantity" },
                { title: "成交数量", dataIndex: "filled_quantity" },
                { title: "剩余数量", dataIndex: "remaining_quantity" },
                {
                  title: "均价",
                  dataIndex: "average_fill_price",
                  render: (value: string | null) => value ?? "—",
                },
                {
                  title: "时间",
                  dataIndex: "completed_at",
                  render: (value: string) => new Date(value).toLocaleString(),
                },
              ]}
            />
            <Typography.Title level={5}>Fill 与账本影响</Typography.Title>
            <Table
              rowKey="fill_id"
              size="small"
              loading={fills.isLoading}
              pagination={false}
              dataSource={fills.data?.items ?? []}
              locale={{ emptyText: "暂无成交" }}
              columns={[
                { title: "方向", dataIndex: "side" },
                { title: "数量", dataIndex: "quantity" },
                { title: "价格", dataIndex: "price" },
                { title: "成交额", dataIndex: "gross_amount" },
                { title: "总费用", dataIndex: "total_fee" },
                { title: "现金影响", dataIndex: "net_cash_effect" },
                {
                  title: "执行引用",
                  dataIndex: "execution_reference",
                  ellipsis: true,
                },
              ]}
            />
            {integrity.data ? (
              <Alert
                style={{ marginTop: 12 }}
                showIcon
                type={integrity.data.valid ? "success" : "error"}
                title={
                  integrity.data.valid
                    ? "模拟执行完整性检查通过"
                    : "模拟执行存在差异"
                }
                description={
                  integrity.data.valid
                    ? "Attempt、Fill、账本与订单状态一致。"
                    : integrity.data.issues
                        .map((item) => `${item.code}: ${item.message}`)
                        .join("；")
                }
              />
            ) : null}
          </>
        ) : null}
      </Drawer>
      {executing ? (
        <SimulatedExecutionModal
          order={executing}
          open
          onClose={() => setExecuting(undefined)}
          onSuccess={async (result) => {
            setSelectedId(result.order_id);
            await refresh();
            await Promise.all([
              queryClient.invalidateQueries({ queryKey: ["account-summary"] }),
              queryClient.invalidateQueries({
                queryKey: ["account-live-summary"],
              }),
              queryClient.invalidateQueries({ queryKey: ["cash-ledger"] }),
              queryClient.invalidateQueries({ queryKey: ["position-ledger"] }),
              queryClient.invalidateQueries({
                queryKey: ["account-snapshots"],
              }),
              queryClient.invalidateQueries({
                queryKey: ["account-reconciliations"],
              }),
              queryClient.invalidateQueries({ queryKey: ["fills"] }),
            ]);
          }}
        />
      ) : null}
    </section>
  );
}
