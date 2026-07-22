import { ExperimentOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Empty,
  Form,
  Input,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Link,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";

import { ApiError } from "../api/client";
import { getInstruments } from "../api/market";
import {
  createStrategyExperiment,
  getStrategyCatalog,
  getStrategyExperiment,
  getStrategyExperimentComparison,
  getStrategyExperimentSignalOverlap,
  listStrategyExperimentRuns,
  listStrategyExperiments,
} from "../api/strategies";
import { systemCapabilitiesQueryOptions } from "../api/system";
import { PageHeader } from "../components/PageHeader/PageHeader";
import type {
  CreateStrategyExperimentRequest,
  ParameterGridValue,
  StrategyExperimentComparisonRow,
  StrategyExperimentRun,
  StrategyExperimentStatus,
  StrategyParameterDefinition,
  StrategySignalOverlap,
} from "../types/strategies";
import { displayEnum, displayParameter } from "../utils/display";
import { estimateCombinationCount } from "./strategyExperimentUtils";

const MAX_COMBINATIONS_HINT = 50;
const statusLabels: Record<StrategyExperimentStatus, string> = {
  CREATED: "已创建",
  RUNNING: "运行中",
  COMPLETED: "全部完成",
  PARTIAL_FAILED: "部分组合失败",
  FAILED: "全部失败",
};
const statusColors: Record<StrategyExperimentStatus, string> = {
  CREATED: "default",
  RUNNING: "processing",
  COMPLETED: "success",
  PARTIAL_FAILED: "warning",
  FAILED: "error",
};

interface ExperimentFormValues {
  strategy_key: string;
  instrument_ids: string[];
  timeframe: string;
  start_at: string;
  end_at: string;
  price_adjustment_mode: "RAW" | "QFQ";
}

function formatDate(value?: string | null) {
  return value ? new Date(value).toLocaleString() : "—";
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
          ? `Correlation ID：${apiError.correlationId}`
          : undefined
      }
    />
  );
}

function ResearchBoundary() {
  return (
    <Alert
      showIcon
      type="warning"
      title="这是历史批量研究，不是回测；研究信号不是订单"
      description="研究信号（Signal）数量只表示触发频率，不代表盈利能力或策略质量。当前没有收益与回撤计算，不调用风控、券商接口（Broker）或 MiniQMT，不创建订单与成交（Fill），不修改现金和持仓，也不进行实时运行。"
    />
  );
}

function ParameterTags({
  values,
}: {
  values: Record<string, ParameterGridValue>;
}) {
  const entries = Object.entries(values);
  if (!entries.length)
    return <Typography.Text type="secondary">使用默认参数</Typography.Text>;
  return (
    <Space wrap size={[4, 4]}>
      {entries.map(([key, value]) => (
        <Tag key={key}>
          {displayParameter(key)}={String(value)}
        </Tag>
      ))}
    </Space>
  );
}

function parseGridValue(
  definition: StrategyParameterDefinition,
  value: string,
): ParameterGridValue {
  if (definition.type === "integer") return Number.parseInt(value, 10);
  if (definition.type === "boolean") return value === "true";
  return value;
}

function GridEditor({
  definition,
  values,
  onChange,
}: {
  definition: StrategyParameterDefinition;
  values: ParameterGridValue[];
  onChange: (values: ParameterGridValue[]) => void;
}) {
  const constraints = [
    definition.min_value !== null
      ? `最小值 ${String(definition.min_value)}`
      : null,
    definition.max_value !== null
      ? `最大值 ${String(definition.max_value)}`
      : null,
    definition.choices.length
      ? `可选值 ${definition.choices.join(" / ")}`
      : null,
  ].filter(Boolean);
  const options =
    definition.type === "boolean"
      ? [
          { value: "true", label: "是" },
          { value: "false", label: "否" },
        ]
      : definition.type === "enum"
        ? definition.choices.map((value) => ({ value, label: value }))
        : undefined;
  return (
    <Card
      size="small"
      title={`${displayParameter(definition.name)} · ${displayEnum(definition.type)}`}
    >
      <Typography.Paragraph type="secondary">
        {definition.description}；默认值：
        {String(definition.default ?? "未设置")}
        {constraints.length ? `；${constraints.join("；")}` : ""}
      </Typography.Paragraph>
      <Select
        aria-label={`${definition.name} 候选值`}
        mode={options ? "multiple" : "tags"}
        style={{ width: "100%" }}
        placeholder="添加候选值；留空时使用默认值"
        options={options}
        value={values.map(String)}
        onChange={(next: string[]) =>
          onChange(next.map((value) => parseGridValue(definition, value)))
        }
      />
    </Card>
  );
}

export function StrategyExperimentsPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [searchParams] = useSearchParams();
  const [form] = Form.useForm<ExperimentFormValues>();
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState<string>();
  const [strategyFilter, setStrategyFilter] = useState<string>();
  const [createdFrom, setCreatedFrom] = useState<string>();
  const [createdTo, setCreatedTo] = useState<string>();
  const [selectedKey, setSelectedKey] = useState<string | undefined>(
    searchParams.get("strategy_key") ?? undefined,
  );
  const [instrumentSearch, setInstrumentSearch] = useState("");
  const [parameterGrid, setParameterGrid] = useState<
    Record<string, ParameterGridValue[]>
  >({});
  const [submitError, setSubmitError] = useState<unknown>();
  const submission = useRef<{ fingerprint: string; key: string } | undefined>(
    undefined,
  );
  const submitting = useRef(false);
  const controller = useRef<AbortController | undefined>(undefined);
  const capabilities = useQuery(systemCapabilitiesQueryOptions);
  const unavailable =
    capabilities.data?.items?.find(
      (item) => item.module_key === "strategy_experiments",
    )?.available === false;
  const unavailableReason = capabilities.data?.items?.find(
    (item) => item.module_key === "strategy_experiments",
  )?.reason;

  const catalog = useQuery({
    queryKey: ["strategy-catalog"],
    queryFn: getStrategyCatalog,
  });
  const instruments = useQuery({
    queryKey: ["strategy-instruments", instrumentSearch],
    queryFn: () => getInstruments(instrumentSearch),
  });
  const experiments = useQuery({
    queryKey: [
      "strategy-experiments",
      page,
      strategyFilter,
      status,
      createdFrom,
      createdTo,
    ],
    queryFn: ({ signal }) =>
      listStrategyExperiments(
        {
          page,
          page_size: 20,
          strategy_key: strategyFilter,
          status,
          created_from: createdFrom
            ? new Date(createdFrom).toISOString()
            : undefined,
          created_to: createdTo ? new Date(createdTo).toISOString() : undefined,
        },
        signal,
      ),
  });
  const selected = useMemo(
    () => catalog.data?.find((item) => item.strategy_key === selectedKey),
    [catalog.data, selectedKey],
  );
  const combinationCount = useMemo(
    () => estimateCombinationCount(parameterGrid),
    [parameterGrid],
  );
  const mutation = useMutation({
    mutationFn: (body: CreateStrategyExperimentRequest) => {
      controller.current = new AbortController();
      return createStrategyExperiment(body, controller.current.signal);
    },
    onSuccess: (result) => {
      void queryClient.invalidateQueries({
        queryKey: ["strategy-experiments"],
      });
      void navigate(`/strategy-experiments/${result.experiment_id}`);
    },
    onError: setSubmitError,
    onSettled: () => {
      submitting.current = false;
    },
  });

  const selectStrategy = useCallback(
    (key: string) => {
      const strategy = catalog.data?.find((item) => item.strategy_key === key);
      setSelectedKey(key);
      setParameterGrid({});
      form.setFieldsValue({
        strategy_key: key,
        timeframe: strategy?.supported_timeframes[0],
      });
    },
    [catalog.data, form],
  );

  useEffect(() => () => controller.current?.abort(), []);
  const submit = async () => {
    if (submitting.current) return;
    submitting.current = true;
    let values: ExperimentFormValues;
    try {
      values = await form.validateFields();
    } catch {
      submitting.current = false;
      return;
    }
    const compactGrid = Object.fromEntries(
      Object.entries(parameterGrid).filter(
        ([, candidates]) => candidates.length,
      ),
    );
    const core = {
      strategy_key: values.strategy_key,
      instrument_ids: values.instrument_ids,
      timeframe: values.timeframe,
      start_at: new Date(values.start_at).toISOString(),
      end_at: new Date(values.end_at).toISOString(),
      price_adjustment_mode: values.price_adjustment_mode,
      parameter_grid: compactGrid,
    };
    const fingerprint = JSON.stringify(core);
    if (submission.current?.fingerprint !== fingerprint) {
      submission.current = {
        fingerprint,
        key: `experiment:${crypto.randomUUID()}`,
      };
    }
    setSubmitError(undefined);
    mutation.mutate({ ...core, idempotency_key: submission.current.key });
  };

  return (
    <section>
      <PageHeader
        title="批量研究实验"
        description="用真实历史数据运行参数组合，并审阅可追溯的 Signal 事实。"
      />
      <ResearchBoundary />
      {unavailable ? (
        <Alert
          showIcon
          type="info"
          title="当前缺少可运行实验的历史行情"
          description={unavailableReason}
          style={{ marginTop: 16 }}
        />
      ) : null}
      <Card title="创建批量研究实验" style={{ marginTop: 16 }}>
        <Form
          form={form}
          layout="vertical"
          initialValues={{
            strategy_key: selectedKey,
            price_adjustment_mode: "RAW",
          }}
        >
          <Space wrap align="start">
            <Form.Item
              name="strategy_key"
              label="策略"
              rules={[{ required: true }]}
            >
              <Select
                style={{ width: 240 }}
                options={catalog.data?.map((item) => ({
                  value: item.strategy_key,
                  label: item.display_name,
                }))}
                onChange={selectStrategy}
              />
            </Form.Item>
            <Form.Item label="策略版本">
              <Input
                style={{ width: 140 }}
                disabled
                value={selected?.version ?? "—"}
              />
            </Form.Item>
            <Form.Item
              key={selected?.strategy_key ?? "timeframe"}
              name="timeframe"
              label="周期"
              initialValue={selected?.supported_timeframes[0]}
              rules={[{ required: true }]}
            >
              <Select
                style={{ width: 160 }}
                options={selected?.supported_timeframes.map((value) => ({
                  value,
                }))}
              />
            </Form.Item>
            <Form.Item
              name="price_adjustment_mode"
              label="价格模式"
              tooltip="QFQ 仅影响每个 StrategyRun 的策略输入和 Signal 参考价。"
              rules={[{ required: true }]}
            >
              <Select
                style={{ width: 190 }}
                options={[
                  { value: "RAW", label: "RAW（未复权）" },
                  { value: "QFQ", label: "QFQ（前复权）" },
                ]}
              />
            </Form.Item>
          </Space>
          <Form.Item
            name="instrument_ids"
            label="标的"
            rules={[{ required: true }]}
          >
            <Select
              mode="multiple"
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
            <Form.Item
              name="start_at"
              label="开始时间"
              rules={[{ required: true }]}
            >
              <Input type="datetime-local" />
            </Form.Item>
            <Form.Item
              name="end_at"
              label="结束时间"
              rules={[{ required: true }]}
            >
              <Input type="datetime-local" />
            </Form.Item>
          </Space>
          {selected ? (
            <Space orientation="vertical" style={{ display: "flex" }}>
              <Typography.Title level={5}>参数网格</Typography.Title>
              {selected.parameters.map((definition) => (
                <GridEditor
                  key={definition.name}
                  definition={definition}
                  values={parameterGrid[definition.name] ?? []}
                  onChange={(values) =>
                    setParameterGrid((current) => ({
                      ...current,
                      [definition.name]: values,
                    }))
                  }
                />
              ))}
              <Alert
                showIcon
                type={
                  combinationCount > MAX_COMBINATIONS_HINT ? "warning" : "info"
                }
                title={`组合数量预览：${combinationCount}`}
                description={
                  combinationCount > MAX_COMBINATIONS_HINT
                    ? `当前预览超过 ${MAX_COMBINATIONS_HINT}。不会截断候选值，最终以上游服务返回的限制为准。`
                    : `当前界面提示上限为 ${MAX_COMBINATIONS_HINT}，最终以上游服务校验为准。`
                }
              />
            </Space>
          ) : null}
          <div style={{ marginTop: 16 }}>
            <ErrorNotice error={submitError} />
            <Button
              type="primary"
              icon={<ExperimentOutlined />}
              loading={mutation.isPending}
              disabled={unavailable || mutation.isPending}
              onClick={() => void submit()}
              style={{ marginTop: submitError ? 12 : 0 }}
            >
              开始批量研究
            </Button>
          </div>
        </Form>
      </Card>

      <Card title="实验记录" style={{ marginTop: 16 }}>
        <Space wrap style={{ marginBottom: 16 }}>
          <Select
            allowClear
            placeholder="策略筛选"
            style={{ width: 220 }}
            options={catalog.data?.map((item) => ({
              value: item.strategy_key,
              label: item.display_name,
            }))}
            onChange={(value: string | undefined) => {
              setStrategyFilter(value);
              setPage(1);
            }}
          />
          <Select
            allowClear
            placeholder="状态筛选"
            style={{ width: 180 }}
            options={Object.entries(statusLabels).map(([value, label]) => ({
              value,
              label,
            }))}
            onChange={(value: string | undefined) => {
              setStatus(value);
              setPage(1);
            }}
          />
          <Input
            aria-label="创建时间起点"
            type="datetime-local"
            onChange={(event) => setCreatedFrom(event.target.value)}
          />
          <Input
            aria-label="创建时间终点"
            type="datetime-local"
            onChange={(event) => setCreatedTo(event.target.value)}
          />
        </Space>
        <ErrorNotice error={experiments.error} />
        <Table
          rowKey="experiment_id"
          loading={experiments.isLoading}
          dataSource={experiments.data?.items ?? []}
          locale={{ emptyText: <Empty description="暂无批量研究实验" /> }}
          pagination={{
            current: page,
            pageSize: 20,
            total: experiments.data?.total ?? 0,
            onChange: setPage,
          }}
          columns={[
            {
              title: "实验 ID",
              dataIndex: "experiment_id",
              render: (value: string) => (
                <Typography.Text code>{value.slice(0, 8)}</Typography.Text>
              ),
            },
            { title: "策略", dataIndex: "strategy_key" },
            { title: "版本", dataIndex: "strategy_version" },
            {
              title: "状态",
              dataIndex: "status",
              render: (value: StrategyExperimentStatus) => (
                <Tag color={statusColors[value]}>{statusLabels[value]}</Tag>
              ),
            },
            { title: "周期", dataIndex: "timeframe" },
            {
              title: "标的数",
              render: (_, item) => item.instrument_ids.length,
            },
            { title: "组合", dataIndex: "combination_count" },
            { title: "完成", dataIndex: "runs_completed" },
            { title: "失败", dataIndex: "runs_failed" },
            { title: "研究信号", dataIndex: "total_signals" },
            { title: "创建时间", dataIndex: "created_at", render: formatDate },
            {
              title: "完成时间",
              dataIndex: "completed_at",
              render: formatDate,
            },
            {
              title: "操作",
              render: (_, item) => (
                <Link to={`/strategy-experiments/${item.experiment_id}`}>
                  查看详情
                </Link>
              ),
            },
          ]}
        />
      </Card>
    </section>
  );
}

function runColumns(): ColumnsType<StrategyExperimentRun> {
  return [
    {
      title: "组合",
      dataIndex: "combination_index",
      sorter: (a, b) => a.combination_index - b.combination_index,
    },
    {
      title: "规范化参数",
      dataIndex: "normalized_parameters",
      render: (value: Record<string, ParameterGridValue>) => (
        <ParameterTags values={value} />
      ),
    },
    {
      title: "状态",
      dataIndex: "run_status",
      filters: ["CREATED", "RUNNING", "COMPLETED", "FAILED"].map((value) => ({
        text: displayEnum(value),
        value,
      })),
      onFilter: (value, item) => item.run_status === value,
    },
    { title: "K 线数", dataIndex: "bars_processed" },
    { title: "研究信号", dataIndex: "signals_generated" },
    {
      title: "提示",
      dataIndex: "warning",
      render: (value: string | null) => value ?? "—",
    },
    {
      title: "查看",
      render: (_, item) =>
        item.strategy_run_id ? (
          <Space>
            <Link to={`/strategy-runs/${item.strategy_run_id}`}>运行详情</Link>
            <Link to={`/signals?strategy_run_id=${item.strategy_run_id}`}>
              研究信号
            </Link>
          </Space>
        ) : (
          "—"
        ),
    },
  ];
}

function comparisonColumns(): ColumnsType<StrategyExperimentComparisonRow> {
  return [
    {
      title: "组合",
      dataIndex: "combination_index",
      defaultSortOrder: "ascend",
      sorter: (a, b) => a.combination_index - b.combination_index,
    },
    {
      title: "参数",
      dataIndex: "normalized_parameters",
      render: (value: Record<string, ParameterGridValue>) => (
        <ParameterTags values={value} />
      ),
    },
    {
      title: "状态",
      dataIndex: "run_status",
      render: (value: StrategyExperimentRun["run_status"]) => (
        <Tag color={value === "FAILED" ? "error" : "success"}>
          {displayEnum(value)}
        </Tag>
      ),
    },
    { title: "K 线数", dataIndex: "bars_processed" },
    {
      title: "研究信号总数",
      dataIndex: "total_signals",
      sorter: (a, b) => a.total_signals - b.total_signals,
    },
    { title: "买入信号", dataIndex: "buy_signals" },
    { title: "卖出信号", dataIndex: "sell_signals" },
    { title: "首次触发", dataIndex: "first_signal_at", render: formatDate },
    { title: "末次触发", dataIndex: "last_signal_at", render: formatDate },
    { title: "触发标的数", dataIndex: "signaled_instrument_count" },
    {
      title: "提示",
      dataIndex: "warning",
      render: (value: string | null) => value ?? "—",
    },
  ];
}

function OverlapMatrix({
  indexes,
  overlaps,
}: {
  indexes: number[];
  overlaps: StrategySignalOverlap[];
}) {
  if (indexes.length < 2 || !overlaps.length) {
    return <Empty description="暂无可比较的 Signal 重合度数据" />;
  }
  const pairs = new Map<string, StrategySignalOverlap>();
  overlaps.forEach((item) => {
    pairs.set(
      `${item.left_combination_index}:${item.right_combination_index}`,
      item,
    );
    pairs.set(
      `${item.right_combination_index}:${item.left_combination_index}`,
      item,
    );
  });
  return (
    <div style={{ overflowX: "auto" }}>
      <table className="overlap-matrix">
        <thead>
          <tr>
            <th>组合</th>
            {indexes.map((index) => (
              <th key={index}>{index}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {indexes.map((row) => (
            <tr key={row}>
              <th>{row}</th>
              {indexes.map((column) => {
                if (row === column) return <td key={column}>1</td>;
                const item = pairs.get(`${row}:${column}`);
                return (
                  <td key={column}>
                    {item ? (
                      <Tooltip
                        title={`交集 ${item.intersection_count}；并集 ${item.union_count}；组合 ${item.left_combination_index} ↔ ${item.right_combination_index}`}
                      >
                        <span>{item.similarity}</span>
                      </Tooltip>
                    ) : (
                      "—"
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function StrategyExperimentDetailPage() {
  const { experimentId = "" } = useParams();
  const detail = useQuery({
    queryKey: ["strategy-experiment", experimentId],
    queryFn: ({ signal }) => getStrategyExperiment(experimentId, signal),
    enabled: Boolean(experimentId),
  });
  const runs = useQuery({
    queryKey: ["strategy-experiment-runs", experimentId],
    queryFn: ({ signal }) => listStrategyExperimentRuns(experimentId, signal),
    enabled: Boolean(experimentId),
  });
  const comparison = useQuery({
    queryKey: ["strategy-experiment-comparison", experimentId],
    queryFn: ({ signal }) =>
      getStrategyExperimentComparison(experimentId, signal),
    enabled: Boolean(experimentId),
  });
  const overlap = useQuery({
    queryKey: ["strategy-experiment-overlap", experimentId],
    queryFn: ({ signal }) =>
      getStrategyExperimentSignalOverlap(experimentId, signal),
    enabled: Boolean(experimentId),
  });
  const item = detail.data;
  const error = detail.error ?? runs.error ?? comparison.error ?? overlap.error;
  const indexes = runs.data?.map((run) => run.combination_index) ?? [];

  return (
    <section>
      <PageHeader
        title="实验结果"
        description={`实验 ${experimentId.slice(0, 8)}`}
      />
      <ResearchBoundary />
      <ErrorNotice error={error} />
      {item ? (
        <>
          <Card title="实验事实" style={{ marginTop: 16 }}>
            <Descriptions column={3} bordered size="small">
              <Descriptions.Item label="策略">
                {item.strategy_key}
              </Descriptions.Item>
              <Descriptions.Item label="版本">
                {item.strategy_version}
              </Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag color={statusColors[item.status]}>
                  {statusLabels[item.status]}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="周期">
                {item.timeframe}
              </Descriptions.Item>
              <Descriptions.Item label="标的">
                {item.instrument_ids.join("、")}
              </Descriptions.Item>
              <Descriptions.Item label="组合数">
                {item.combination_count}
              </Descriptions.Item>
              <Descriptions.Item label="完成数">
                {item.runs_completed}
              </Descriptions.Item>
              <Descriptions.Item label="失败数">
                {item.runs_failed}
              </Descriptions.Item>
              <Descriptions.Item label="研究信号总数">
                {item.total_signals}
              </Descriptions.Item>
              <Descriptions.Item label="研究区间">
                {formatDate(item.start_at)} — {formatDate(item.end_at)}
              </Descriptions.Item>
              <Descriptions.Item label="开始时间">
                {formatDate(item.started_at)}
              </Descriptions.Item>
              <Descriptions.Item label="完成时间">
                {formatDate(item.completed_at)}
              </Descriptions.Item>
              <Descriptions.Item label="参数网格" span={3}>
                {Object.entries(item.parameter_grid).length
                  ? Object.entries(item.parameter_grid).map(([key, values]) => (
                      <Tag key={key}>
                        {key}=[{values.map(String).join(", ")}]
                      </Tag>
                    ))
                  : "使用策略默认参数"}
              </Descriptions.Item>
              <Descriptions.Item label="错误摘要" span={3}>
                {item.error?.message ?? "—"}
              </Descriptions.Item>
              <Descriptions.Item label="Correlation ID" span={3}>
                {item.correlation_id}
              </Descriptions.Item>
            </Descriptions>
          </Card>
          <Card title="参数组合运行" style={{ marginTop: 16 }}>
            <Table
              rowKey="combination_index"
              loading={runs.isLoading}
              dataSource={runs.data ?? []}
              columns={runColumns()}
              locale={{ emptyText: "暂无参数组合" }}
              pagination={false}
            />
          </Card>
          <Card title="研究信号对比" style={{ marginTop: 16 }}>
            <Alert
              type="info"
              showIcon
              title="研究信号数量只表示触发频率，不代表收益或策略质量。"
              style={{ marginBottom: 12 }}
            />
            <Table
              rowKey="combination_index"
              loading={comparison.isLoading}
              dataSource={comparison.data ?? []}
              columns={comparisonColumns()}
              locale={{ emptyText: "暂无 Signal 对比数据" }}
              pagination={false}
            />
          </Card>
          <Card title="研究信号重合度矩阵" style={{ marginTop: 16 }}>
            <Typography.Paragraph type="secondary">
              重合度基于标的、K 线时间和信号方向的杰卡德系数（Jaccard）
              相似度；高重合度不代表更高收益。
            </Typography.Paragraph>
            <OverlapMatrix indexes={indexes} overlaps={overlap.data ?? []} />
          </Card>
        </>
      ) : detail.isLoading ? (
        <Card loading style={{ marginTop: 16 }} />
      ) : null}
    </section>
  );
}
