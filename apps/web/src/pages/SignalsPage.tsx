import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Empty,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from "antd";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { getAccounts } from "../api/accounts";
import { assessSignalRisk } from "../api/risk";
import { getSignals, getStrategyCatalog } from "../api/strategies";
import { PageHeader } from "../components/PageHeader/PageHeader";
import type { StrategySignal } from "../types/strategies";
import {
  displayEnum,
  displayStrategy,
  formatDateTime,
  formatInstrument,
  formatPercentRatio,
  formatPrice,
  formatQuantity,
  isTestData,
  localizeReason,
} from "../utils/display";

export function SignalsPage() {
  const [search] = useSearchParams();
  const [page, setPage] = useState(1);
  const [runId, setRunId] = useState(search.get("strategy_run_id") ?? "");
  const [strategyKey, setStrategyKey] = useState<string>();
  const [signalType, setSignalType] = useState<string>();
  const [instrumentId, setInstrumentId] = useState("");
  const [generatedFrom, setGeneratedFrom] = useState("");
  const [generatedTo, setGeneratedTo] = useState("");
  const [selectedSignal, setSelectedSignal] = useState<StrategySignal>();
  const [showTestData, setShowTestData] = useState(false);
  const [assessmentId, setAssessmentId] = useState<string>();
  const [assessmentDecision, setAssessmentDecision] = useState<string>();
  const [form] = Form.useForm();
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: getAccounts });
  const catalog = useQuery({
    queryKey: ["strategy-catalog"],
    queryFn: getStrategyCatalog,
  });
  const signals = useQuery({
    queryKey: [
      "signals",
      page,
      runId,
      strategyKey,
      signalType,
      instrumentId,
      generatedFrom,
      generatedTo,
    ],
    queryFn: () =>
      getSignals({
        page,
        page_size: 20,
        strategy_run_id: runId,
        strategy_key: strategyKey,
        signal_type: signalType,
        instrument_id: instrumentId,
        generated_from: generatedFrom
          ? new Date(generatedFrom).toISOString()
          : undefined,
        generated_to: generatedTo
          ? new Date(generatedTo).toISOString()
          : undefined,
      }),
  });
  const assessment = useMutation({
    mutationFn: async (values: Record<string, string>) => {
      if (!selectedSignal) throw new Error("未选择 Signal");
      return assessSignalRisk(selectedSignal.signal_id, {
        account_id: values.account_id,
        quantity: selectedSignal.quantity ?? values.quantity ?? null,
        reference_price:
          values.reference_price || selectedSignal.reference_price,
        idempotency_key: `signal-risk:${selectedSignal.signal_id}:${crypto.randomUUID()}`,
      });
    },
    onSuccess: (result) => {
      setAssessmentId(result.id);
      setAssessmentDecision(result.overall_decision);
      setSelectedSignal(undefined);
      form.resetFields();
    },
  });
  return (
    <section>
      <PageHeader
        title="研究信号（Signal）"
        description="查看策略历史研究输出与来源运行。"
      />
      <Alert
        showIcon
        type="warning"
        title="研究信号（Signal）是研究事实，不是买卖指令"
        description="可发起一次独立风控评估，但只创建风控决策，不创建订单、不发送券商，也不会修改现金、持仓或账本。"
      />
      {assessmentId ? (
        <Alert
          style={{ marginTop: 16 }}
          showIcon
          type={
            assessmentDecision === "ALLOW"
              ? "success"
              : assessmentDecision === "REJECT"
                ? "error"
                : "warning"
          }
          title={
            assessmentDecision === "ALLOW"
              ? "风控通过"
              : assessmentDecision === "REJECT"
                ? "风控拒绝"
                : "需要人工复核"
          }
          description={
            <Space>
              <Typography.Text>研究评估完成，未创建订单。</Typography.Text>
              <Link to={`/risk/decisions/${assessmentId}`}>查看风控决策</Link>
            </Space>
          }
        />
      ) : null}
      <Card style={{ marginTop: 16 }}>
        <Space wrap style={{ marginBottom: 16 }}>
          <Input
            allowClear
            placeholder="策略运行编号"
            value={runId}
            onChange={(event) => {
              setPage(1);
              setRunId(event.target.value);
            }}
            style={{ width: 280 }}
          />
          <Input
            allowClear
            placeholder="内部标的编号"
            value={instrumentId}
            onChange={(event) => {
              setPage(1);
              setInstrumentId(event.target.value);
            }}
            style={{ width: 280 }}
          />
          <Select<string>
            allowClear
            placeholder="策略"
            style={{ width: 200 }}
            options={catalog.data?.map((item) => ({
              value: item.strategy_key,
              label: item.display_name,
            }))}
            onChange={(value) => {
              setPage(1);
              setStrategyKey(value);
            }}
          />
          <Input
            type="datetime-local"
            aria-label="生成开始时间"
            value={generatedFrom}
            onChange={(event) => {
              setPage(1);
              setGeneratedFrom(event.target.value);
            }}
          />
          <Input
            type="datetime-local"
            aria-label="生成结束时间"
            value={generatedTo}
            onChange={(event) => {
              setPage(1);
              setGeneratedTo(event.target.value);
            }}
          />
          <Select<string>
            allowClear
            placeholder="信号类型"
            style={{ width: 180 }}
            options={["ENTRY", "EXIT", "REBALANCE", "ADVICE"].map((value) => ({
              value,
              label: displayEnum(value),
            }))}
            onChange={(value) => {
              setPage(1);
              setSignalType(value);
            }}
          />
          <Space>
            <Switch checked={showTestData} onChange={setShowTestData} />
            <Typography.Text>显示测试数据</Typography.Text>
          </Space>
        </Space>
        <Table<StrategySignal>
          rowKey="signal_id"
          loading={signals.isLoading}
          dataSource={(signals.data?.items ?? []).filter(
            (item) => showTestData || !isTestData(item),
          )}
          locale={{ emptyText: <Empty description="暂无研究信号" /> }}
          pagination={{
            current: page,
            pageSize: 20,
            total: signals.data?.total ?? 0,
            onChange: setPage,
          }}
          columns={[
            {
              title: "策略",
              dataIndex: "strategy_key",
              render: displayStrategy,
            },
            {
              title: "运行时间",
              render: (_, item) => formatDateTime(item.generated_at),
            },
            {
              title: "标的",
              render: (_, item) =>
                formatInstrument(item.instrument, "未知标的"),
            },
            {
              title: "方向",
              render: (_, item) => (
                <Tag color={item.side === "BUY" ? "green" : "red"}>
                  {displayEnum(item.side)}
                </Tag>
              ),
            },
            { title: "类型", dataIndex: "signal_type", render: displayEnum },
            {
              title: "K线时间",
              render: (_, item) => formatDateTime(item.bar_timestamp),
            },
            {
              title: "数量/权重",
              render: (_, item) =>
                item.quantity
                  ? `${formatQuantity(item.quantity)} 股`
                  : item.target_weight
                    ? formatPercentRatio(item.target_weight)
                    : "—",
            },
            {
              title: "参考价",
              dataIndex: "reference_price",
              render: formatPrice,
            },
            {
              title: "置信度",
              dataIndex: "confidence",
              render: (value: string | null) => formatPercentRatio(value),
            },
            { title: "原因", dataIndex: "reason", render: localizeReason },
            {
              title: "风控研究",
              render: (_, item) => (
                <Button size="small" onClick={() => setSelectedSignal(item)}>
                  独立风险评估
                </Button>
              ),
            },
          ]}
        />
      </Card>
      <Modal
        title="研究信号独立风控评估"
        open={Boolean(selectedSignal)}
        confirmLoading={assessment.isPending}
        okText="仅评估风险"
        onCancel={() => setSelectedSignal(undefined)}
        onOk={() =>
          void form
            .validateFields()
            .then((values: Record<string, string>) => assessment.mutate(values))
        }
      >
        <Alert
          showIcon
          type="warning"
          title="研究评估，不是下单"
          description="不会自动转为订单，不会发送券商或 MiniQMT，不会修改现金和持仓。标的与方向由研究信号决定，浏览器不能更改。"
        />
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item
            name="account_id"
            label="模拟账户"
            rules={[{ required: true }]}
          >
            <Select
              options={(accounts.data?.items ?? []).map((item) => ({
                value: item.id,
                label: `${item.account_code} · ${item.name}`,
              }))}
            />
          </Form.Item>
          {!selectedSignal?.quantity ? (
            <Form.Item
              name="quantity"
              label="评估数量"
              rules={[{ required: !selectedSignal?.target_weight }]}
            >
              <Input
                inputMode="decimal"
                placeholder={
                  selectedSignal?.target_weight
                    ? "可选；不填写将进入人工复核"
                    : "请输入数量"
                }
              />
            </Form.Item>
          ) : null}
          <Form.Item name="reference_price" label="参考价（可选）">
            <Input
              inputMode="decimal"
              placeholder={
                selectedSignal?.reference_price ?? "请输入服务端评估参考价"
              }
            />
          </Form.Item>
        </Form>
        {assessment.isError ? (
          <Alert
            type="error"
            title="评估失败"
            description={assessment.error.message}
          />
        ) : null}
      </Modal>
    </section>
  );
}
