import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Empty,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import {
  getRunSignals,
  getStrategyCatalog,
  getStrategyRun,
  getStrategyRuns,
} from "../api/strategies";
import { PageHeader } from "../components/PageHeader/PageHeader";
import type { StrategyRun, StrategySignal } from "../types/strategies";

const statusText: Record<string, string> = {
  CREATED: "已创建",
  RUNNING: "运行中",
  COMPLETED: "已完成",
  FAILED: "运行失败",
};

export function StrategyRunsPage() {
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const [strategyKey, setStrategyKey] = useState<string>();
  const [status, setStatus] = useState<string>();
  const catalog = useQuery({
    queryKey: ["strategy-catalog"],
    queryFn: getStrategyCatalog,
  });
  const runs = useQuery({
    queryKey: ["strategy-runs", page, strategyKey, status],
    queryFn: () =>
      getStrategyRuns({
        page,
        page_size: 20,
        strategy_key: strategyKey,
        status,
      }),
  });
  return (
    <section>
      <PageHeader
        title="研究运行"
        description="历史策略研究运行及其持久化 Signal。"
      />
      <Alert
        showIcon
        type="info"
        title="历史研究运行，不是绩效回测"
        description="不会创建订单、调用风控或 Broker，也不会修改资金和持仓；当前没有实时调度。"
      />
      <Card style={{ marginTop: 16 }}>
        <Space wrap style={{ marginBottom: 16 }}>
          <Select<string>
            allowClear
            placeholder="策略筛选"
            style={{ width: 220 }}
            options={catalog.data?.map((item) => ({
              value: item.strategy_key,
              label: item.display_name,
            }))}
            onChange={(value) => {
              setPage(1);
              setStrategyKey(value);
            }}
          />
          <Select<string>
            allowClear
            placeholder="状态筛选"
            style={{ width: 160 }}
            options={Object.entries(statusText).map(([value, label]) => ({
              value,
              label,
            }))}
            onChange={(value) => {
              setPage(1);
              setStatus(value);
            }}
          />
        </Space>
        <Table<StrategyRun>
          rowKey="run_id"
          dataSource={runs.data?.items ?? []}
          loading={runs.isLoading}
          locale={{ emptyText: <Empty description="暂无研究运行" /> }}
          pagination={{
            current: page,
            pageSize: 20,
            total: runs.data?.total ?? 0,
            onChange: setPage,
          }}
          columns={[
            { title: "运行", render: (_, item) => item.run_id.slice(0, 8) },
            { title: "策略", dataIndex: "strategy_key" },
            { title: "版本", dataIndex: "strategy_version" },
            {
              title: "状态",
              render: (_, item) => <Tag>{statusText[item.status]}</Tag>,
            },
            {
              title: "标的数",
              render: (_, item) => item.instrument_ids.length,
            },
            { title: "周期", dataIndex: "timeframe" },
            { title: "K线", dataIndex: "bars_processed" },
            { title: "Signal", dataIndex: "signals_generated" },
            {
              title: "完成时间",
              render: (_, item) =>
                item.completed_at
                  ? new Date(item.completed_at).toLocaleString()
                  : "—",
            },
            {
              title: "操作",
              render: (_, item) => (
                <Space>
                  <Button
                    size="small"
                    onClick={() =>
                      void navigate(`/strategy-runs/${item.run_id}`)
                    }
                  >
                    详情
                  </Button>
                  <Button
                    size="small"
                    onClick={() =>
                      void navigate(`/signals?strategy_run_id=${item.run_id}`)
                    }
                  >
                    Signal
                  </Button>
                </Space>
              ),
            },
          ]}
        />
      </Card>
    </section>
  );
}

export function StrategyRunDetailPage() {
  const { runId = "" } = useParams();
  const detail = useQuery({
    queryKey: ["strategy-run", runId],
    queryFn: () => getStrategyRun(runId),
    enabled: Boolean(runId),
  });
  const signals = useQuery({
    queryKey: ["strategy-run-signals", runId],
    queryFn: () => getRunSignals(runId),
    enabled: Boolean(runId),
  });
  const item = detail.data;
  return (
    <section>
      <PageHeader title="研究运行详情" description={runId} />
      <Alert
        showIcon
        type="warning"
        title="Signal 不是订单"
        description="reference_price 仅为研究参考价；本运行不创建 Order、Fill，不调用风控或 Broker，不修改资金和持仓。"
      />
      {item ? (
        <Card style={{ marginTop: 16 }}>
          {item.status === "FAILED" ? (
            <Alert
              type="error"
              title="运行失败"
              description={item.error?.message ?? "策略运行失败"}
            />
          ) : null}
          <Descriptions
            bordered
            column={2}
            items={[
              {
                key: "strategy",
                label: "策略",
                children: `${item.strategy_key} v${item.strategy_version}`,
              },
              {
                key: "status",
                label: "状态",
                children: statusText[item.status],
              },
              { key: "timeframe", label: "周期", children: item.timeframe },
              {
                key: "range",
                label: "时间区间",
                children: `${item.start_at} — ${item.end_at}`,
              },
              { key: "bars", label: "K线数", children: item.bars_processed },
              {
                key: "signals",
                label: "Signal数",
                children: item.signals_generated,
              },
              {
                key: "parameters",
                label: "规范化参数",
                children: <pre>{JSON.stringify(item.parameters, null, 2)}</pre>,
              },
              {
                key: "instruments",
                label: "标的",
                children:
                  item.instruments
                    ?.map((value) => `${value.symbol}.${value.exchange}`)
                    .join(", ") || item.instrument_ids.join(", "),
              },
              {
                key: "warnings",
                label: "警告",
                children: item.warnings.join(", ") || "无",
              },
              {
                key: "completed",
                label: "完成时间",
                children: item.completed_at ?? "—",
              },
            ]}
          />
          <Typography.Title level={4}>Signal</Typography.Title>
          <Table<StrategySignal>
            rowKey="signal_id"
            dataSource={signals.data?.items ?? []}
            pagination={false}
            columns={[
              { title: "序号", dataIndex: "sequence_number" },
              {
                title: "标的",
                render: (_, signal) =>
                  `${signal.instrument.symbol}.${signal.instrument.exchange}`,
              },
              { title: "方向", dataIndex: "side" },
              { title: "类型", dataIndex: "signal_type" },
              { title: "参考价", dataIndex: "reference_price" },
              { title: "原因", dataIndex: "reason" },
            ]}
          />
        </Card>
      ) : (
        <Typography.Text>加载中…</Typography.Text>
      )}
    </section>
  );
}
