import {
  AuditOutlined,
  BankOutlined,
  CalculatorOutlined,
  PlusOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Empty,
  Flex,
  Form,
  Input,
  Modal,
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
import { useState } from "react";

import {
  createAccount,
  getAccounts,
  getAccountSummary,
  getCashLedger,
  getPositionLedger,
  getReconciliations,
  getSnapshots,
  postFunding,
  reconcileAccount,
  valueAccount,
} from "../api/accounts";
import { PageHeader } from "../components/PageHeader/PageHeader";
import type {
  AccountSnapshot,
  CashLedgerEntry,
  Position,
  PositionLedgerEntry,
  Reconciliation,
  ValuationStatus,
} from "../types/accounting";

function decimal(value: string | null | undefined, digits = 2) {
  if (value == null) return "—";
  const [integer, fraction = ""] = value.split(".");
  const sign = integer.startsWith("-") ? "-" : "";
  const grouped = integer
    .replace("-", "")
    .replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${sign}${grouped}.${fraction.padEnd(digits, "0").slice(0, digits)}`;
}

const valuationColor: Record<ValuationStatus, string> = {
  COMPLETE: "success",
  PARTIAL: "warning",
  STALE: "orange",
  UNAVAILABLE: "default",
};

export function PortfolioPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [selectedAccount, setSelectedAccount] = useState<string>();
  const [dialog, setDialog] = useState<
    "create" | "deposit" | "withdraw" | null
  >(null);
  const [form] = Form.useForm();
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: getAccounts });
  const effectiveAccount = selectedAccount ?? accounts.data?.items[0]?.id;
  const summary = useQuery({
    queryKey: ["account-summary", effectiveAccount],
    queryFn: () => getAccountSummary(effectiveAccount ?? ""),
    enabled: Boolean(effectiveAccount),
  });
  const cashLedger = useQuery({
    queryKey: ["cash-ledger", effectiveAccount],
    queryFn: () => getCashLedger(effectiveAccount ?? ""),
    enabled: Boolean(effectiveAccount),
  });
  const positionLedger = useQuery({
    queryKey: ["position-ledger", effectiveAccount],
    queryFn: () => getPositionLedger(effectiveAccount ?? ""),
    enabled: Boolean(effectiveAccount),
  });
  const snapshots = useQuery({
    queryKey: ["account-snapshots", effectiveAccount],
    queryFn: () => getSnapshots(effectiveAccount ?? ""),
    enabled: Boolean(effectiveAccount),
  });
  const reconciliations = useQuery({
    queryKey: ["account-reconciliations", effectiveAccount],
    queryFn: () => getReconciliations(effectiveAccount ?? ""),
    enabled: Boolean(effectiveAccount),
  });

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["accounts"] });
    await queryClient.invalidateQueries({ queryKey: ["account-summary"] });
    await queryClient.invalidateQueries({ queryKey: ["cash-ledger"] });
    await queryClient.invalidateQueries({ queryKey: ["position-ledger"] });
    await queryClient.invalidateQueries({ queryKey: ["account-snapshots"] });
    await queryClient.invalidateQueries({
      queryKey: ["account-reconciliations"],
    });
  };
  const action = useMutation({
    mutationFn: async (operation: () => Promise<unknown>) => operation(),
    onSuccess: async () => {
      await refresh();
      setDialog(null);
      form.resetFields();
      void message.success("操作已完成");
    },
    onError: (error: Error) => void message.error(error.message),
  });

  const snapshot = summary.data?.latest_snapshot;
  const balance = summary.data?.cash_balances[0];
  const valuationWarning = snapshot && snapshot.valuation_status !== "COMPLETE";

  const submitDialog = async () => {
    const values = (await form.validateFields()) as Record<string, string>;
    if (dialog === "create") {
      action.mutate(() =>
        createAccount({
          account_code: values.account_code,
          name: values.name,
          initial_cash: values.amount,
          settlement_policy: "IMMEDIATE",
          idempotency_key: crypto.randomUUID(),
        }),
      );
    } else if (effectiveAccount && dialog) {
      action.mutate(() =>
        postFunding(
          effectiveAccount,
          dialog === "deposit" ? "deposits" : "withdrawals",
          values.amount,
          crypto.randomUUID(),
        ),
      );
    }
  };

  return (
    <section className="portfolio-page">
      <PageHeader
        title="模拟账户与持仓"
        description="资金与持仓均来自可审计账本；本页不提供下单或实盘能力。"
        action={
          <Space wrap>
            <Select
              aria-label="选择模拟账户"
              value={effectiveAccount}
              placeholder="选择模拟账户"
              style={{ minWidth: 220 }}
              options={accounts.data?.items.map((item) => ({
                value: item.id,
                label: `${item.account_code} · ${item.name}`,
              }))}
              onChange={setSelectedAccount}
            />
            <Button icon={<PlusOutlined />} onClick={() => setDialog("create")}>
              新建模拟账户
            </Button>
          </Space>
        }
      />

      {accounts.isLoading ? <Spin /> : null}
      {accounts.isError ? (
        <Alert
          type="error"
          showIcon
          title="账户加载失败"
          description={accounts.error.message}
        />
      ) : null}
      {!accounts.isLoading && accounts.data?.total === 0 ? (
        <Card>
          <Empty description="尚无模拟账户，请先创建账户" />
        </Card>
      ) : null}
      {effectiveAccount && summary.data ? (
        <>
          <Flex
            justify="space-between"
            align="center"
            wrap
            gap={12}
            className="portfolio-actions"
          >
            <Space wrap>
              <Tag
                color={
                  summary.data.account.status === "ACTIVE"
                    ? "success"
                    : "warning"
                }
              >
                {summary.data.account.status}
              </Tag>
              <Typography.Text type="secondary">
                结算规则：{summary.data.account.settlement_policy}
              </Typography.Text>
            </Space>
            <Space wrap>
              <Button onClick={() => setDialog("deposit")}>入金</Button>
              <Button onClick={() => setDialog("withdraw")}>出金</Button>
              <Button
                icon={<CalculatorOutlined />}
                loading={action.isPending}
                onClick={() =>
                  action.mutate(() => valueAccount(effectiveAccount))
                }
              >
                重新估值
              </Button>
              <Button
                icon={<AuditOutlined />}
                loading={action.isPending}
                onClick={() =>
                  action.mutate(() => reconcileAccount(effectiveAccount))
                }
              >
                执行核对
              </Button>
              <Button icon={<ReloadOutlined />} onClick={() => void refresh()}>
                刷新
              </Button>
            </Space>
          </Flex>
          {valuationWarning ? (
            <Alert
              showIcon
              type="warning"
              title={`估值状态：${snapshot.valuation_status}`}
              description="存在缺失或陈旧行情时，总权益不会被伪装成完整数值。"
            />
          ) : null}
          <Row gutter={[16, 16]} className="portfolio-statistics">
            <Col xs={24} sm={12} lg={6}>
              <Card>
                <Statistic
                  title="总权益"
                  value={decimal(snapshot?.total_equity)}
                  prefix="¥"
                />
              </Card>
            </Col>
            <Col xs={24} sm={12} lg={6}>
              <Card>
                <Statistic
                  title="可用资金"
                  value={decimal(balance?.available_cash)}
                  prefix="¥"
                />
              </Card>
            </Col>
            <Col xs={24} sm={12} lg={6}>
              <Card>
                <Statistic
                  title="已实现盈亏"
                  value={decimal(snapshot?.realized_pnl ?? "0")}
                  prefix="¥"
                />
              </Card>
            </Col>
            <Col xs={24} sm={12} lg={6}>
              <Card>
                <Statistic
                  title="未实现盈亏"
                  value={decimal(snapshot?.unrealized_pnl)}
                  prefix="¥"
                />
              </Card>
            </Col>
          </Row>
          <Card>
            <Tabs
              items={[
                {
                  key: "positions",
                  label: "当前持仓",
                  children: (
                    <Table<Position>
                      rowKey="id"
                      dataSource={summary.data.positions}
                      pagination={false}
                      locale={{ emptyText: "暂无持仓" }}
                      columns={[
                        {
                          title: "标的 ID",
                          dataIndex: "instrument_id",
                          ellipsis: true,
                        },
                        { title: "总数量", dataIndex: "total_quantity" },
                        { title: "可用", dataIndex: "available_quantity" },
                        { title: "待结算", dataIndex: "unsettled_quantity" },
                        {
                          title: "平均成本",
                          dataIndex: "average_cost",
                          render: (value: string) => decimal(value),
                        },
                        {
                          title: "最新价",
                          dataIndex: "last_price",
                          render: (value: string | null) => decimal(value),
                        },
                        {
                          title: "市值",
                          dataIndex: "market_value",
                          render: (value: string | null) => decimal(value),
                        },
                        {
                          title: "估值",
                          dataIndex: "valuation_status",
                          render: (value: ValuationStatus) => (
                            <Tag color={valuationColor[value]}>{value}</Tag>
                          ),
                        },
                      ]}
                    />
                  ),
                },
                {
                  key: "cash",
                  label: "资金流水",
                  children: (
                    <Table<CashLedgerEntry>
                      rowKey="id"
                      dataSource={cashLedger.data?.items}
                      loading={cashLedger.isLoading}
                      pagination={false}
                      columns={[
                        { title: "时间", dataIndex: "occurred_at" },
                        { title: "类型", dataIndex: "entry_type" },
                        { title: "变动", dataIndex: "total_delta" },
                        { title: "余额", dataIndex: "total_cash_after" },
                        {
                          title: "费用",
                          dataIndex: "fee_amount",
                          render: (value: string | null) => decimal(value),
                        },
                      ]}
                    />
                  ),
                },
                {
                  key: "position-ledger",
                  label: "持仓流水",
                  children: (
                    <Table<PositionLedgerEntry>
                      rowKey="id"
                      dataSource={positionLedger.data?.items}
                      loading={positionLedger.isLoading}
                      pagination={false}
                      columns={[
                        { title: "时间", dataIndex: "occurred_at" },
                        { title: "类型", dataIndex: "entry_type" },
                        { title: "数量变动", dataIndex: "quantity_delta" },
                        { title: "成本变动", dataIndex: "cost_basis_delta" },
                        {
                          title: "已实现变动",
                          dataIndex: "realized_pnl_delta",
                        },
                      ]}
                    />
                  ),
                },
                {
                  key: "snapshots",
                  label: "估值快照",
                  children: (
                    <Table<AccountSnapshot>
                      rowKey="id"
                      dataSource={snapshots.data?.items}
                      loading={snapshots.isLoading}
                      pagination={false}
                      columns={[
                        { title: "时间", dataIndex: "as_of" },
                        { title: "状态", dataIndex: "valuation_status" },
                        {
                          title: "总权益",
                          dataIndex: "total_equity",
                          render: (value: string | null) => decimal(value),
                        },
                        { title: "已定价", dataIndex: "priced_position_count" },
                        {
                          title: "未定价",
                          dataIndex: "unpriced_position_count",
                        },
                      ]}
                    />
                  ),
                },
                {
                  key: "reconciliation",
                  label: "核对记录",
                  children: (
                    <Table<Reconciliation>
                      rowKey="id"
                      dataSource={reconciliations.data?.items}
                      loading={reconciliations.isLoading}
                      pagination={false}
                      columns={[
                        { title: "开始时间", dataIndex: "started_at" },
                        {
                          title: "状态",
                          dataIndex: "status",
                          render: (value: string) => (
                            <Tag
                              color={value === "MATCHED" ? "success" : "error"}
                            >
                              {value}
                            </Tag>
                          ),
                        },
                        { title: "差异数", dataIndex: "discrepancy_count" },
                      ]}
                    />
                  ),
                },
              ]}
            />
          </Card>
        </>
      ) : null}

      <Modal
        open={dialog !== null}
        title={
          dialog === "create"
            ? "新建模拟账户"
            : dialog === "deposit"
              ? "模拟入金"
              : "模拟出金"
        }
        confirmLoading={action.isPending}
        onCancel={() => {
          setDialog(null);
          form.resetFields();
        }}
        onOk={() => void submitDialog()}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" preserve={false}>
          {dialog === "create" ? (
            <>
              <Form.Item
                name="account_code"
                label="账户编码"
                rules={[{ required: true }]}
              >
                <Input prefix={<BankOutlined />} />
              </Form.Item>
              <Form.Item
                name="name"
                label="账户名称"
                rules={[{ required: true }]}
              >
                <Input />
              </Form.Item>
            </>
          ) : null}
          <Form.Item
            name="amount"
            label={dialog === "create" ? "初始资金" : "金额"}
            rules={[
              { required: true },
              { pattern: /^\d+(\.\d{1,8})?$/, message: "请输入有效金额" },
            ]}
            initialValue={dialog === "create" ? "100000" : undefined}
          >
            <Input inputMode="decimal" prefix="¥" />
          </Form.Item>
        </Form>
      </Modal>
    </section>
  );
}
