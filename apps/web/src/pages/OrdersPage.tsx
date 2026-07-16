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

import { getAccounts } from "../api/accounts";
import { getInstruments } from "../api/market";
import {
  cancelOrder,
  confirmOrder,
  createOrder,
  getOrder,
  getOrders,
  getOrderTimeline,
} from "../api/orders";
import { PageHeader } from "../components/PageHeader/PageHeader";
import type { OrderFactSummary } from "../types/orders";

const stateText: Record<string, string> = {
  WAITING_CONFIRMATION: "等待人工确认",
  QUEUED: "本地指令事实已创建，等待未来投递",
  CANCELLED: "已取消",
  EXPIRED: "已过期",
};

function idempotencyKey(prefix: string, orderId?: string) {
  return `${prefix}:${orderId ?? "new"}:${crypto.randomUUID()}`;
}

export function OrdersPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState<string>();
  const [accountFilter, setAccountFilter] = useState<string>();
  const [instrumentFilter, setInstrumentFilter] = useState<string>();
  const [instrumentSearch, setInstrumentSearch] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [confirming, setConfirming] = useState<OrderFactSummary>();
  const [selectedId, setSelectedId] = useState<string>();
  const [form] = Form.useForm();

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

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["orders"] });
    await queryClient.invalidateQueries({ queryKey: ["order"] });
    await queryClient.invalidateQueries({ queryKey: ["order-timeline"] });
  };
  const action = useMutation({
    mutationFn: (operation: () => Promise<OrderFactSummary>) => operation(),
    onSuccess: async (order) => {
      setSelectedId(order.id);
      setCreateOpen(false);
      setConfirming(undefined);
      if (createOpen) form.resetFields();
      await refresh();
      void message.success("订单事实已更新");
    },
    onError: (error: Error) => {
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
        description="M05 只创建可审计的本地订单与待发布指令事实，不会连接执行器、券商或产生成交。"
        action={
          <Button icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
            创建订单
          </Button>
        }
      />
      <Alert
        showIcon
        type="warning"
        title="当前没有交易级实时行情"
        description="LIMIT 估算金额仅为数量 × 用户限价；MARKET 无法估算成交金额。当前仅完成结构校验，尚未完成资金与组合风控。确认后只创建本地数据库指令事实，尚未发送执行器，不会发送券商，也不会产生成交。"
      />
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
              ]}
            />
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
                title="指令待发布"
                description="OrderCommand PENDING：仅存在于本地数据库。"
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
                title="消息尚未发布"
                description="Outbox PENDING：未写入 Redis。"
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
          </>
        ) : null}
      </Drawer>
    </section>
  );
}
