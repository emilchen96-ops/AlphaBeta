import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Empty,
  Input,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { getAccounts } from "../api/accounts";
import { getInstruments } from "../api/market";
import {
  getActiveRiskLimits,
  getRiskDecision,
  getRiskDecisions,
} from "../api/risk";
import { PageHeader } from "../components/PageHeader/PageHeader";
import type { RiskDecision, RiskRuleResult } from "../types/risk";

const labels = {
  ALLOW: "风控通过",
  REJECT: "风控拒绝",
  REQUIRE_CONFIRMATION: "需要人工复核",
} as const;

function DecisionTag({ value }: { value: keyof typeof labels }) {
  const color =
    value === "ALLOW" ? "green" : value === "REJECT" ? "red" : "orange";
  return <Tag color={color}>{labels[value]}</Tag>;
}

function exact(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean")
    return String(value);
  return JSON.stringify(value);
}

function Snapshot({ value }: { value: Record<string, unknown> }) {
  const entries = Object.entries(value).filter(
    ([key]) => !["positions", "metadata"].includes(key),
  );
  return (
    <Descriptions
      bordered
      size="small"
      column={2}
      items={entries.map(([key, item]) => ({
        key,
        label: key,
        children: typeof item === "object" ? JSON.stringify(item) : exact(item),
      }))}
    />
  );
}

export function RiskDecisionsPage() {
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const [decision, setDecision] = useState<string>();
  const [sourceType, setSourceType] = useState<string>();
  const [accountId, setAccountId] = useState<string>();
  const [instrumentId, setInstrumentId] = useState<string>();
  const [instrumentSearch, setInstrumentSearch] = useState("");
  const [evaluatedFrom, setEvaluatedFrom] = useState("");
  const [evaluatedTo, setEvaluatedTo] = useState("");
  const [hasOrder, setHasOrder] = useState<boolean>();
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: getAccounts });
  const instruments = useQuery({
    queryKey: ["risk-instruments", instrumentSearch],
    queryFn: () => getInstruments(instrumentSearch),
  });
  const decisions = useQuery({
    queryKey: [
      "risk-decisions",
      page,
      decision,
      sourceType,
      accountId,
      instrumentId,
      evaluatedFrom,
      evaluatedTo,
      hasOrder,
    ],
    queryFn: () =>
      getRiskDecisions({
        page,
        pageSize: 20,
        overallDecision: decision,
        sourceType,
        accountId,
        instrumentId,
        evaluatedFrom: evaluatedFrom
          ? new Date(evaluatedFrom).toISOString()
          : undefined,
        evaluatedTo: evaluatedTo
          ? new Date(evaluatedTo).toISOString()
          : undefined,
        hasOrder,
      }),
  });
  const resetPage = () => setPage(1);
  return (
    <section>
      <PageHeader
        title="风控决策"
        description="查看人工订单与研究 Signal 的只读风控审计结果。"
      />
      <Alert
        showIcon
        type="info"
        title="风控通过仅表示当前规则允许创建订单事实，不代表已经成交。"
      />
      <Card style={{ marginTop: 16 }}>
        <Space wrap style={{ marginBottom: 16 }}>
          <Select
            allowClear
            aria-label="决策结果"
            placeholder="决策结果"
            style={{ width: 170 }}
            options={[
              { value: "ALLOW", label: "风控通过" },
              { value: "REJECT", label: "风控拒绝" },
              { value: "REQUIRE_CONFIRMATION", label: "需要人工复核" },
            ]}
            onChange={(value) => {
              resetPage();
              setDecision(value as string | undefined);
            }}
          />
          <Select
            allowClear
            aria-label="来源类型"
            placeholder="来源类型"
            style={{ width: 180 }}
            options={["MANUAL_ORDER", "STRATEGY_SIGNAL", "SYSTEM"].map(
              (value) => ({ value }),
            )}
            onChange={(value) => {
              resetPage();
              setSourceType(value as string | undefined);
            }}
          />
          <Select
            allowClear
            aria-label="账户"
            placeholder="账户"
            style={{ width: 220 }}
            options={accounts.data?.items.map((item) => ({
              value: item.id,
              label: `${item.account_code} · ${item.name}`,
            }))}
            onChange={(value) => {
              resetPage();
              setAccountId(value as string | undefined);
            }}
          />
          <Select
            allowClear
            showSearch
            filterOption={false}
            aria-label="标的"
            placeholder="标的"
            style={{ width: 220 }}
            onSearch={setInstrumentSearch}
            options={instruments.data?.items.map((item) => ({
              value: item.id,
              label: `${item.symbol}.${item.exchange}`,
            }))}
            onChange={(value) => {
              resetPage();
              setInstrumentId(value as string | undefined);
            }}
          />
          <Input
            type="datetime-local"
            aria-label="评估开始时间"
            value={evaluatedFrom}
            onChange={(event) => {
              resetPage();
              setEvaluatedFrom(event.target.value);
            }}
          />
          <Input
            type="datetime-local"
            aria-label="评估结束时间"
            value={evaluatedTo}
            onChange={(event) => {
              resetPage();
              setEvaluatedTo(event.target.value);
            }}
          />
          <Select
            allowClear
            aria-label="订单关联"
            placeholder="订单关联"
            style={{ width: 160 }}
            options={[
              { value: true, label: "有关联订单" },
              { value: false, label: "无关联订单" },
            ]}
            onChange={(value) => {
              resetPage();
              setHasOrder(value as boolean | undefined);
            }}
          />
        </Space>
        {decisions.isError ? (
          <Alert
            type="error"
            title="风控决策加载失败"
            description={decisions.error.message}
          />
        ) : null}
        <Table<RiskDecision>
          rowKey="id"
          loading={decisions.isLoading}
          dataSource={decisions.data?.items ?? []}
          locale={{ emptyText: <Empty description="暂无风控决策" /> }}
          pagination={{
            current: page,
            pageSize: 20,
            total: decisions.data?.total ?? 0,
            onChange: setPage,
          }}
          columns={[
            { title: "Decision ID", render: (_, item) => item.id.slice(0, 8) },
            {
              title: "结果",
              render: (_, item) => (
                <DecisionTag value={item.overall_decision} />
              ),
            },
            {
              title: "来源",
              render: (_, item) =>
                `${item.source_type} · ${item.source_id?.slice(0, 8) ?? "—"}`,
            },
            {
              title: "账户",
              render: (_, item) =>
                item.account.name ??
                item.account.code ??
                item.account_id.slice(0, 8),
            },
            {
              title: "标的",
              render: (_, item) =>
                `${item.instrument.symbol ?? "—"}.${item.instrument.exchange ?? ""}`,
            },
            { title: "方向", dataIndex: "side" },
            { title: "数量", render: (_, item) => exact(item.quantity) },
            {
              title: "估算金额",
              render: (_, item) => exact(item.estimated_notional),
            },
            {
              title: "预计单标的权重",
              render: (_, item) => exact(item.projected_instrument_weight),
            },
            {
              title: "预计总暴露",
              render: (_, item) => exact(item.projected_total_exposure),
            },
            {
              title: "关联 Order",
              render: (_, item) => item.order_id?.slice(0, 8) ?? "—",
            },
            {
              title: "评估时间",
              render: (_, item) => new Date(item.evaluated_at).toLocaleString(),
            },
            {
              title: "操作",
              render: (_, item) => (
                <Button
                  size="small"
                  onClick={() => void navigate(`/risk/decisions/${item.id}`)}
                >
                  详情
                </Button>
              ),
            },
          ]}
          scroll={{ x: 1500 }}
        />
      </Card>
    </section>
  );
}

export function RiskDecisionDetailPage() {
  const { decisionId = "" } = useParams();
  const detail = useQuery({
    queryKey: ["risk-decision", decisionId],
    queryFn: () => getRiskDecision(decisionId),
    enabled: Boolean(decisionId),
  });
  if (detail.isLoading) return <Typography.Text>加载风控决策…</Typography.Text>;
  if (detail.isError)
    return (
      <Alert
        type="error"
        title="风控决策不存在或加载失败"
        description={detail.error.message}
      />
    );
  if (!detail.data) return <Empty description="风控决策不存在" />;
  const item = detail.data;
  return (
    <section>
      <PageHeader title="风控决策详情" description={`Decision ${item.id}`} />
      <Alert
        showIcon
        type={
          item.overall_decision === "ALLOW"
            ? "success"
            : item.overall_decision === "REJECT"
              ? "error"
              : "warning"
        }
        title={<DecisionTag value={item.overall_decision} />}
        description="本页面为不可修改的审计事实，不提供跳过风控或改判操作。"
      />
      <Typography.Title level={4}>1. 风控请求</Typography.Title>
      <Descriptions
        bordered
        column={2}
        items={[
          {
            key: "source",
            label: "来源",
            children: `${item.source_type} · ${item.source_id ?? "—"}`,
          },
          {
            key: "account",
            label: "账户",
            children: item.account.name ?? item.account_id,
          },
          {
            key: "instrument",
            label: "标的",
            children: `${item.instrument.symbol ?? "—"}.${item.instrument.exchange ?? ""}`,
          },
          {
            key: "side",
            label: "方向 / 类型",
            children: `${item.side ?? "—"} / ${item.order_type ?? "—"}`,
          },
          { key: "quantity", label: "数量", children: exact(item.quantity) },
          {
            key: "notional",
            label: "估算金额",
            children: exact(item.estimated_notional),
          },
        ]}
      />
      <Typography.Title level={4}>2. 聚合决策</Typography.Title>
      <DecisionTag value={item.overall_decision} />
      <Typography.Title level={4}>3. 规则明细</Typography.Title>
      <Table<RiskRuleResult>
        rowKey="id"
        pagination={false}
        dataSource={item.rule_results}
        locale={{
          emptyText: <Empty description="规则明细为空，决策事实可能不完整" />,
        }}
        rowClassName={(rule) =>
          rule.decision === "ALLOW" ? "" : "risk-rule-highlight"
        }
        columns={[
          { title: "顺序", dataIndex: "seq" },
          { title: "规则", dataIndex: "rule_key" },
          {
            title: "结果",
            render: (_, rule) => <DecisionTag value={rule.decision} />,
          },
          { title: "原因代码", dataIndex: "reason_code" },
          { title: "说明", dataIndex: "message" },
          { title: "观测值", render: (_, rule) => exact(rule.observed_value) },
          { title: "限制值", render: (_, rule) => exact(rule.limit_value) },
          { title: "级别", dataIndex: "severity" },
          {
            title: "时间",
            render: (_, rule) => new Date(rule.evaluated_at).toLocaleString(),
          },
        ]}
        scroll={{ x: 1200 }}
      />
      <Typography.Title level={4}>4. 账户快照摘要</Typography.Title>
      <Snapshot value={item.account_snapshot} />
      <Typography.Title level={4}>5. 标的快照摘要</Typography.Title>
      <Snapshot value={item.instrument_snapshot} />
      <Typography.Title level={4}>6. 实际使用的风险限制</Typography.Title>
      <Snapshot value={item.limits_snapshot} />
      <Typography.Title level={4}>7. 预计指标</Typography.Title>
      <Descriptions
        bordered
        items={[
          {
            key: "notional",
            label: "估算金额",
            children: exact(item.estimated_notional),
          },
          {
            key: "weight",
            label: "预计单标的权重",
            children: exact(item.projected_instrument_weight),
          },
          {
            key: "exposure",
            label: "预计总暴露",
            children: exact(item.projected_total_exposure),
          },
        ]}
      />
      <Typography.Title level={4}>8. 关联订单</Typography.Title>
      {item.order_id ? (
        <Link to={`/orders?order_id=${item.order_id}`}>
          查看 Order {item.order_id}
        </Link>
      ) : (
        <Typography.Text type="secondary">未创建 Order</Typography.Text>
      )}
      <Typography.Title level={4}>9. 审计信息</Typography.Title>
      <Descriptions
        bordered
        items={[
          {
            key: "correlation",
            label: "Correlation ID",
            children: item.correlation_id,
          },
          {
            key: "evaluated",
            label: "评估时间",
            children: new Date(item.evaluated_at).toLocaleString(),
          },
          {
            key: "warnings",
            label: "Warnings",
            children: item.warnings.join("、") || "无",
          },
        ]}
      />
    </section>
  );
}

export function RiskLimitsPage() {
  const limits = useQuery({
    queryKey: ["active-risk-limits"],
    queryFn: getActiveRiskLimits,
  });
  return (
    <section>
      <PageHeader
        title="当前风控限制"
        description="服务端实际生效限制的只读视图。"
      />
      <Alert
        showIcon
        type="warning"
        title="只读配置"
        description="当前系统没有身份认证，不允许通过浏览器修改风控限制。配置来自服务端，修改后需按本地配置机制重新加载或重启服务。"
      />
      {limits.isError ? (
        <Alert
          style={{ marginTop: 16 }}
          type="error"
          title="配置读取失败"
          description={limits.error.message}
        />
      ) : null}
      {limits.data?.kill_switch_enabled ? (
        <Alert
          style={{ marginTop: 16 }}
          showIcon
          type="error"
          title="Kill Switch 已开启"
          description="当前配置将拒绝新的订单风险请求。此页面不提供关闭按钮。"
        />
      ) : null}
      <Card loading={limits.isLoading} style={{ marginTop: 16 }}>
        {limits.data ? (
          <Descriptions
            bordered
            column={2}
            items={[
              {
                key: "notional",
                label: "单笔最大金额",
                children: limits.data.max_order_notional ?? "未配置限制",
              },
              {
                key: "weight",
                label: "单标的最大权重",
                children: limits.data.max_instrument_weight ?? "未配置限制",
              },
              {
                key: "exposure",
                label: "最大总暴露",
                children: limits.data.max_total_exposure ?? "未配置限制",
              },
              {
                key: "frequency",
                label: "频率限制",
                children: limits.data.max_orders_per_window ?? "未配置限制",
              },
              {
                key: "window",
                label: "时间窗口",
                children: `${limits.data.order_frequency_window_seconds} 秒`,
              },
              {
                key: "market",
                label: "允许市价单",
                children: limits.data.allow_market_orders ? "是" : "否",
              },
              {
                key: "reference",
                label: "市价单要求参考价",
                children: limits.data.require_reference_price_for_market_order
                  ? "是"
                  : "否",
              },
              {
                key: "kill",
                label: "Kill Switch",
                children: limits.data.kill_switch_enabled ? "已开启" : "未开启",
              },
              {
                key: "source",
                label: "配置来源",
                children: limits.data.configuration_source,
              },
              {
                key: "effective",
                label: "生效时间",
                children: new Date(limits.data.effective_at).toLocaleString(),
              },
            ]}
          />
        ) : (
          <Empty description="暂无配置" />
        )}
      </Card>
    </section>
  );
}
