import { useQuery } from "@tanstack/react-query";
import { Alert, Card, Empty, Input, Select, Space, Table, Tag } from "antd";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { getSignals, getStrategyCatalog } from "../api/strategies";
import { PageHeader } from "../components/PageHeader/PageHeader";
import type { StrategySignal } from "../types/strategies";

export function SignalsPage() {
  const [search] = useSearchParams();
  const [page, setPage] = useState(1);
  const [runId, setRunId] = useState(search.get("strategy_run_id") ?? "");
  const [strategyKey, setStrategyKey] = useState<string>();
  const [signalType, setSignalType] = useState<string>();
  const [instrumentId, setInstrumentId] = useState("");
  const [generatedFrom, setGeneratedFrom] = useState("");
  const [generatedTo, setGeneratedTo] = useState("");
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
  return (
    <section>
      <PageHeader
        title="研究 Signal"
        description="查看策略历史研究输出与来源运行。"
      />
      <Alert
        showIcon
        type="warning"
        title="Signal 是研究事实，不是买卖指令"
        description="页面不提供买入、卖出、转订单或自动交易操作。reference_price 不是成交价；不会调用风控、Broker 或修改账户。"
      />
      <Card style={{ marginTop: 16 }}>
        <Space wrap style={{ marginBottom: 16 }}>
          <Input
            allowClear
            placeholder="运行 ID"
            value={runId}
            onChange={(event) => {
              setPage(1);
              setRunId(event.target.value);
            }}
            style={{ width: 280 }}
          />
          <Input
            allowClear
            placeholder="标的 ID"
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
            placeholder="Signal 类型"
            style={{ width: 180 }}
            options={["ENTRY", "EXIT", "REBALANCE", "ADVICE"].map((value) => ({
              value,
            }))}
            onChange={(value) => {
              setPage(1);
              setSignalType(value);
            }}
          />
        </Space>
        <Table<StrategySignal>
          rowKey="signal_id"
          loading={signals.isLoading}
          dataSource={signals.data?.items ?? []}
          locale={{ emptyText: <Empty description="暂无 Signal" /> }}
          pagination={{
            current: page,
            pageSize: 20,
            total: signals.data?.total ?? 0,
            onChange: setPage,
          }}
          columns={[
            { title: "策略", dataIndex: "strategy_key" },
            {
              title: "运行",
              render: (_, item) => item.strategy_run_id.slice(0, 8),
            },
            {
              title: "标的",
              render: (_, item) =>
                `${item.instrument.symbol ?? item.instrument_id}.${item.instrument.exchange ?? ""}`,
            },
            {
              title: "方向",
              render: (_, item) => (
                <Tag color={item.side === "BUY" ? "green" : "red"}>
                  {item.side}
                </Tag>
              ),
            },
            { title: "类型", dataIndex: "signal_type" },
            {
              title: "K线时间",
              render: (_, item) =>
                new Date(item.bar_timestamp).toLocaleString(),
            },
            {
              title: "数量/权重",
              render: (_, item) => item.quantity ?? item.target_weight ?? "—",
            },
            { title: "参考价", dataIndex: "reference_price" },
            { title: "置信度", dataIndex: "confidence" },
            { title: "原因", dataIndex: "reason" },
          ]}
        />
      </Card>
    </section>
  );
}
