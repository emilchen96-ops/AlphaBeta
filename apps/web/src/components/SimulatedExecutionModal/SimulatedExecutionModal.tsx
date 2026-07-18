import {
  Alert,
  App,
  Descriptions,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Switch,
  Tag,
  Typography,
} from "antd";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import {
  executeSimulatedOrder,
  getOrderExecutionAttempts,
} from "../../api/orders";
import type {
  CreateSimulatedExecutionRequest,
  OrderFactSummary,
  SimulatedExecutionResult,
} from "../../types/orders";

interface Props {
  order: OrderFactSummary | undefined;
  open: boolean;
  onClose: () => void;
  onSuccess: (result: SimulatedExecutionResult) => Promise<void> | void;
}

const resultText: Record<string, string> = {
  FILLED: "模拟全部成交",
  PARTIALLY_FILLED: "模拟部分成交",
  NO_FILL: "当前市场条件未成交",
  REJECTED: "模拟 Broker 拒绝",
  EXPIRED: "订单已过期",
};

function localTimestamp() {
  const now = new Date(Date.now() - new Date().getTimezoneOffset() * 60_000);
  return now.toISOString().slice(0, 16);
}

export function SimulatedExecutionModal({
  order,
  open,
  onClose,
  onSuccess,
}: Props) {
  const { modal, message } = App.useApp();
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<SimulatedExecutionResult>();
  const attempts = useQuery({
    queryKey: ["order-execution-attempts", order?.id],
    queryFn: () => getOrderExecutionAttempts(order?.id ?? ""),
    enabled: open && Boolean(order),
  });
  const latestAttempt = attempts.data?.items.at(-1);

  const submit = async () => {
    if (!order) return;
    const values = (await form.validateFields()) as Record<
      string,
      string | boolean
    >;
    modal.confirm({
      title: "确认执行本地模拟成交？",
      content:
        "这不会连接真实行情或券商，但成交 Fill 会真实修改 DEMO 模拟账户的现金、持仓和账本。",
      okText: "确认模拟执行",
      cancelText: "返回检查",
      onOk: async () => {
        setSubmitting(true);
        try {
          const optional = (name: string) => {
            const value = values[name];
            return typeof value === "string" && value.trim()
              ? value.trim()
              : null;
          };
          const payload: CreateSimulatedExecutionRequest = {
            idempotency_key: String(values.idempotency_key),
            timestamp: new Date(String(values.timestamp)).toISOString(),
            trading_status:
              values.trading_status as CreateSimulatedExecutionRequest["trading_status"],
            open: optional("open"),
            high: optional("high"),
            low: optional("low"),
            close: optional("close"),
            last_price: optional("last_price"),
            bid_price: optional("bid_price"),
            ask_price: optional("ask_price"),
            available_volume: optional("available_volume"),
            price_limit_up: optional("price_limit_up"),
            price_limit_down: optional("price_limit_down"),
            source: String(values.source),
            is_stale: Boolean(values.is_stale),
          };
          const next = await executeSimulatedOrder(order.id, payload);
          setResult(next);
          await onSuccess(next);
          void message.success(
            resultText[next.result_status] ?? next.result_status,
          );
        } finally {
          setSubmitting(false);
        }
      },
    });
  };

  const close = () => {
    setResult(undefined);
    form.resetFields();
    onClose();
  };

  return (
    <Modal
      width={760}
      title="模拟执行"
      open={open}
      okText="检查并继续"
      confirmLoading={submitting}
      onCancel={close}
      onOk={() => void submit()}
      destroyOnHidden
    >
      <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
        <Alert
          showIcon
          type="warning"
          title="仅限本地模拟成交"
          description="市场快照由你手工输入，不连接真实行情、券商或 MiniQMT，也不会产生真实交易；若产生成交，将写入模拟账户账本。R01 风控通过不代表一定成交。"
        />
        {order ? (
          <Descriptions
            size="small"
            bordered
            column={2}
            items={[
              { key: "account", label: "账户", children: order.account_name },
              {
                key: "instrument",
                label: "标的",
                children: `${order.symbol}.${order.exchange}`,
              },
              { key: "side", label: "方向", children: order.side },
              { key: "type", label: "类型", children: order.order_type },
              {
                key: "quantity",
                label: "原始数量",
                children: order.requested_quantity,
              },
              {
                key: "filled",
                label: "累计已成交",
                children: latestAttempt
                  ? `${latestAttempt.previously_filled_quantity} + ${latestAttempt.filled_quantity}`
                  : "0",
              },
              {
                key: "remaining",
                label: "剩余数量",
                children:
                  latestAttempt?.remaining_quantity ?? order.requested_quantity,
              },
              {
                key: "limit",
                label: "限价",
                children: order.limit_price ?? "—",
              },
              {
                key: "status",
                label: "当前状态",
                children: <Tag>{order.status}</Tag>,
              },
            ]}
          />
        ) : null}
        {result ? (
          <Space orientation="vertical" style={{ width: "100%" }}>
            <Alert
              showIcon
              type={
                result.result_status === "FILLED"
                  ? "success"
                  : result.result_status === "REJECTED"
                    ? "error"
                    : "info"
              }
              title={resultText[result.result_status] ?? result.result_status}
              description={result.message}
            />
            <Descriptions
              size="small"
              bordered
              column={2}
              items={[
                {
                  key: "attempted",
                  label: "尝试数量",
                  children: result.attempted_quantity,
                },
                {
                  key: "filled",
                  label: "成交数量",
                  children: result.filled_quantity,
                },
                {
                  key: "remaining",
                  label: "剩余数量",
                  children: result.remaining_quantity,
                },
                {
                  key: "price",
                  label: "成交均价",
                  children: result.average_fill_price ?? "—",
                },
                {
                  key: "fee",
                  label: "总费用",
                  children: result.total_fee,
                },
                {
                  key: "rejection",
                  label: "拒绝原因",
                  children: result.rejection_code ?? "—",
                },
                {
                  key: "order-status",
                  label: "订单最新状态",
                  children: result.order_status,
                },
                {
                  key: "attempt",
                  label: "ExecutionAttempt",
                  children: (
                    <Link to={`/orders?order_id=${result.order_id}`}>
                      {result.execution_attempt_id}
                    </Link>
                  ),
                },
                {
                  key: "fills",
                  label: "Fill",
                  span: 2,
                  children: result.fill_ids.length
                    ? result.fill_ids.map((fillId, index) => (
                        <span key={fillId}>
                          {index ? "、" : null}
                          <Link to={`/fills?fill_id=${fillId}`}>{fillId}</Link>
                        </span>
                      ))
                    : "无 Fill",
                },
              ]}
            />
            {result.warnings.length ? (
              <Alert
                type="warning"
                title="完整性提示"
                description={result.warnings.join("；")}
              />
            ) : null}
          </Space>
        ) : null}
        <Form
          form={form}
          layout="vertical"
          initialValues={{
            timestamp: localTimestamp(),
            trading_status: "TRADING",
            source: "MANUAL_SIMULATED_SNAPSHOT",
            is_stale: false,
            idempotency_key: `web:${order?.id ?? "order"}:${crypto.randomUUID()}`,
          }}
        >
          <Space wrap align="start">
            <Form.Item
              name="timestamp"
              label="市场时间"
              rules={[{ required: true }]}
            >
              <Input type="datetime-local" />
            </Form.Item>
            <Form.Item
              name="trading_status"
              label="交易状态"
              rules={[{ required: true }]}
            >
              <Select
                style={{ width: 160 }}
                options={["TRADING", "SUSPENDED", "CLOSED", "UNKNOWN"].map(
                  (value) => ({ value }),
                )}
              />
            </Form.Item>
            <Form.Item
              name="source"
              label="数据来源"
              rules={[{ required: true }]}
            >
              <Input />
            </Form.Item>
            <Form.Item name="is_stale" label="是否陈旧" valuePropName="checked">
              <Switch />
            </Form.Item>
          </Space>
          <Typography.Title level={5}>
            价格与可成交量（Decimal 字符串）
          </Typography.Title>
          <Space wrap align="start">
            {[
              ["bid_price", "Bid"],
              ["ask_price", "Ask"],
              ["last_price", "Last"],
              ["close", "Close"],
              ["available_volume", "可成交量"],
              ["price_limit_up", "涨停价"],
              ["price_limit_down", "跌停价"],
            ].map(([name, label]) => (
              <Form.Item
                key={name}
                name={name}
                label={label}
                rules={[
                  {
                    pattern: /^\d+(\.\d+)?$/,
                    message: "请输入非负十进制字符串",
                  },
                ]}
              >
                <Input inputMode="decimal" style={{ width: 140 }} />
              </Form.Item>
            ))}
          </Space>
          <Typography.Text type="secondary">
            OHLC 必须同时提供；一般演示只需 Bid、Ask、Last、Close 和可成交量。
          </Typography.Text>
          <Space wrap align="start" style={{ marginTop: 12 }}>
            {["open", "high", "low"].map((name) => (
              <Form.Item key={name} name={name} label={name.toUpperCase()}>
                <Input inputMode="decimal" style={{ width: 140 }} />
              </Form.Item>
            ))}
          </Space>
          <Form.Item
            name="idempotency_key"
            label="幂等键"
            rules={[{ required: true, max: 128 }]}
          >
            <Input />
          </Form.Item>
        </Form>
      </Space>
    </Modal>
  );
}
