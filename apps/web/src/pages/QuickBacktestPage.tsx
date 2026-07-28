import {
  ExperimentOutlined,
  InfoCircleOutlined,
  SaveOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Collapse,
  DatePicker,
  Form,
  InputNumber,
  List,
  Radio,
  Select,
  Space,
  Typography,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { getInstrument, getInstruments } from "../api/market";
import {
  createQuickBacktest,
  listStrategyTemplates,
  listUserStrategies,
} from "../api/strategySpecs";
import { NaturalLanguageStrategyBuilder } from "../components/StrategyBuilder/NaturalLanguageStrategyBuilder";
import { PageHeader } from "../components/PageHeader/PageHeader";
import type { Instrument } from "../types/market";
import type {
  QuickBacktestRequest,
  StrategySpec,
} from "../types/strategySpecs";
import { formatInstrument } from "../utils/display";

const EXAMPLE = "10日价格突破 + 1.2倍成交量，5日均线退出，单只股票、两年日线";

type StrategySource = "description" | "template" | "saved";

interface BacktestFormValues {
  instrument_id: string;
  range: [Dayjs, Dayjs];
  initial_cash: number;
  price_adjustment_mode: "RAW" | "QFQ";
  commission_rate: number;
  minimum_commission: number;
  stamp_duty_rate: number;
  transfer_fee_rate: number;
  slippage_basis_points: number;
  maximum_volume_participation: number | null;
}

const errorText = (reason: unknown) =>
  reason instanceof ApiError ? reason.message : "回测启动失败，请稍后重试";

export function QuickBacktestPage() {
  const [search] = useSearchParams();
  const navigate = useNavigate();
  const [form] = Form.useForm<BacktestFormValues>();
  const [source, setSource] = useState<StrategySource>(
    search.has("user_strategy_id")
      ? "saved"
      : search.has("template")
        ? "template"
        : "description",
  );
  const [spec, setSpec] = useState<StrategySpec | null>(null);
  const [preview, setPreview] = useState<string[]>([]);
  const [userStrategyId, setUserStrategyId] = useState<string | null>(
    search.get("user_strategy_id"),
  );
  const [instrumentKeyword, setInstrumentKeyword] = useState("长信科技");
  const [selectedInstrument, setSelectedInstrument] =
    useState<Instrument | null>(null);
  const prefilledInstrumentId = search.get("instrument_id");
  const screeningId = search.get("screening_id");

  const templates = useQuery({
    queryKey: ["strategy-templates"],
    queryFn: listStrategyTemplates,
  });
  const saved = useQuery({
    queryKey: ["user-strategies", false],
    queryFn: () => listUserStrategies(false),
  });
  const instruments = useQuery({
    queryKey: ["quick-backtest-instruments", instrumentKeyword],
    queryFn: () => getInstruments(instrumentKeyword),
  });
  const prefilledInstrument = useQuery({
    queryKey: ["quick-backtest-prefilled-instrument", prefilledInstrumentId],
    queryFn: () => getInstrument(prefilledInstrumentId ?? ""),
    enabled: Boolean(prefilledInstrumentId),
  });
  const effectiveSelectedInstrument =
    selectedInstrument ?? prefilledInstrument.data ?? null;

  useEffect(() => {
    const templateKey = search.get("template");
    const template = templates.data?.find((item) => item.key === templateKey);
    if (template?.spec) {
      // Route presets hydrate the editable draft after the async catalog arrives.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSpec(template.spec);
      setPreview(template.preview);
      setUserStrategyId(null);
    }
  }, [search, templates.data]);

  useEffect(() => {
    const id = search.get("user_strategy_id");
    const strategy = saved.data?.items?.find((item) => item.id === id);
    if (strategy) {
      // Route presets hydrate the editable draft after the async catalog arrives.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSpec(strategy.spec);
      setPreview(strategy.preview);
      setUserStrategyId(strategy.id);
    }
  }, [saved.data, search]);

  useEffect(() => {
    if (spec) {
      form.setFieldValue("range", [
        dayjs().subtract(spec.data_range_years, "year"),
        dayjs(),
      ]);
    }
  }, [form, spec]);

  const selectedName = useMemo(
    () =>
      spec?.name ??
      saved.data?.items?.find((item) => item.id === userStrategyId)?.name ??
      "尚未确认策略",
    [saved.data, spec, userStrategyId],
  );

  const run = useMutation({
    mutationFn: async (values: BacktestFormValues) => {
      if (!spec) throw new Error("请先确认策略规则");
      const request: QuickBacktestRequest = {
        instrument_id: values.instrument_id,
        start_at: values.range[0].startOf("day").toISOString(),
        end_at: values.range[1].add(1, "day").startOf("day").toISOString(),
        initial_cash: String(values.initial_cash),
        price_adjustment_mode: values.price_adjustment_mode,
        commission_rate: String(values.commission_rate / 100),
        minimum_commission: String(values.minimum_commission),
        stamp_duty_rate: String(values.stamp_duty_rate / 100),
        transfer_fee_rate: String(values.transfer_fee_rate / 100),
        slippage_basis_points: String(values.slippage_basis_points),
        maximum_volume_participation:
          values.maximum_volume_participation === null
            ? null
            : String(values.maximum_volume_participation / 100),
        idempotency_key: `quick-backtest:${crypto.randomUUID()}`,
        ...(source === "saved" && userStrategyId
          ? { user_strategy_id: userStrategyId }
          : { spec }),
      };
      return createQuickBacktest(request);
    },
    onSuccess: (result) => {
      void navigate(`/research/backtests/${result.id}`);
    },
  });

  const chooseTemplate = (key: string) => {
    const template = templates.data?.find((item) => item.key === key);
    if (!template?.spec) return;
    setSpec(template.spec);
    setPreview(template.preview);
    setUserStrategyId(null);
  };

  const chooseSaved = (id: string) => {
    const strategy = saved.data?.items?.find((item) => item.id === id);
    if (!strategy) return;
    setSpec(strategy.spec);
    setPreview(strategy.preview);
    setUserStrategyId(strategy.id);
  };

  return (
    <section>
      <PageHeader
        title="快速回测"
        description="用一句话或已有模板定义策略，再选择股票和时间范围完成历史模拟。"
      />
      <Alert
        showIcon
        type="info"
        title="历史模拟，不会发送真实订单"
        description="行情来自已同步到本地数据库的 MiniQMT 历史日线；运行会经过信号、风控、模拟订单、成交与账本链路。"
        style={{ marginBottom: 16 }}
      />
      {screeningId && effectiveSelectedInstrument ? (
        <Alert
          showIcon
          type="success"
          title={`已从智能选股带入：${formatInstrument(effectiveSelectedInstrument)}`}
          description="请继续选择或描述策略；系统不会自动开始回测。"
          style={{ marginBottom: 16 }}
        />
      ) : null}

      <Card title="第一步：选择或描述策略">
        <Radio.Group
          value={source}
          optionType="button"
          buttonStyle="solid"
          options={[
            { label: "一句话创建", value: "description" },
            { label: "策略模板", value: "template" },
            { label: "我的策略", value: "saved" },
          ]}
          onChange={(event) => {
            setSource(event.target.value as StrategySource);
            setSpec(null);
            setPreview([]);
            setUserStrategyId(null);
          }}
        />
        <div style={{ marginTop: 16 }}>
          {source === "description" ? (
            <NaturalLanguageStrategyBuilder
              initialText={EXAMPLE}
              onConfirmed={(nextSpec, nextPreview) => {
                setSpec(nextSpec);
                setPreview(nextPreview);
                setUserStrategyId(null);
              }}
            />
          ) : source === "template" ? (
            <Select
              aria-label="选择策略模板"
              style={{ width: "100%" }}
              placeholder="选择一个策略模板"
              loading={templates.isLoading}
              options={(templates.data ?? [])
                .filter((item) => item.spec !== null)
                .map((item) => ({
                  value: item.key,
                  label: `${item.name} · ${item.description}`,
                }))}
              onChange={chooseTemplate}
            />
          ) : (
            <Select
              aria-label="选择我的策略"
              style={{ width: "100%" }}
              placeholder="选择已保存的策略"
              loading={saved.isLoading}
              options={(saved.data?.items ?? []).map((item) => ({
                value: item.id,
                label: `${item.name} · 版本 ${item.current_version}`,
              }))}
              onChange={chooseSaved}
            />
          )}
        </div>
        {spec && source !== "description" ? (
          <Card size="small" title={selectedName} style={{ marginTop: 16 }}>
            <List
              dataSource={preview}
              renderItem={(item) => <List.Item>{item}</List.Item>}
            />
          </Card>
        ) : null}
      </Card>

      <Card title="第二步：设置回测条件" style={{ marginTop: 16 }}>
        <Form<BacktestFormValues>
          form={form}
          layout="vertical"
          initialValues={{
            instrument_id: prefilledInstrumentId ?? undefined,
            range: [dayjs().subtract(2, "year"), dayjs()],
            initial_cash: 100000,
            price_adjustment_mode: "QFQ",
            commission_rate: 0.03,
            minimum_commission: 5,
            stamp_duty_rate: 0.05,
            transfer_fee_rate: 0.001,
            slippage_basis_points: 2,
            maximum_volume_participation: 10,
          }}
          onFinish={(values) => run.mutate(values)}
        >
          <Form.Item
            name="instrument_id"
            label="回测股票"
            rules={[{ required: true, message: "请选择一只股票" }]}
            extra="当前快速回测一次只使用一只股票。"
          >
            <Select
              showSearch
              filterOption={false}
              placeholder="输入名称或代码，例如：长信科技 / 300088"
              loading={instruments.isFetching}
              options={[
                ...(effectiveSelectedInstrument
                  ? [
                      {
                        value: effectiveSelectedInstrument.id,
                        label: formatInstrument(effectiveSelectedInstrument),
                      },
                    ]
                  : []),
                ...(instruments.data?.items ?? [])
                  .filter((item) => item.id !== effectiveSelectedInstrument?.id)
                  .map((item) => ({
                    value: item.id,
                    label: formatInstrument(item),
                  })),
              ]}
              onSearch={(keyword) => setInstrumentKeyword(keyword.trim())}
              onChange={(id) =>
                setSelectedInstrument(
                  instruments.data?.items.find((item) => item.id === id) ??
                    null,
                )
              }
            />
          </Form.Item>
          <Space wrap size={24} align="start">
            <Form.Item
              name="range"
              label="回测时间范围"
              rules={[{ required: true, message: "请选择时间范围" }]}
            >
              <DatePicker.RangePicker allowClear={false} />
            </Form.Item>
            <Form.Item
              name="initial_cash"
              label="初始资金（元）"
              rules={[{ required: true }]}
            >
              <InputNumber min={1000} step={10000} style={{ width: 180 }} />
            </Form.Item>
            <Form.Item
              name="price_adjustment_mode"
              label="价格复权方式"
              tooltip="不复权用于模拟实际成交；前复权适合趋势研究。"
            >
              <Select
                style={{ width: 240 }}
                options={[
                  { value: "RAW", label: "不复权（RAW，推荐模拟成交）" },
                  { value: "QFQ", label: "前复权（QFQ，趋势研究）" },
                ]}
              />
            </Form.Item>
          </Space>
          <Collapse
            ghost
            items={[
              {
                key: "advanced",
                label: "高级设置：费用、滑点与成交量约束",
                children: (
                  <Space wrap size={24} align="start">
                    <Form.Item name="commission_rate" label="佣金率（%）">
                      <InputNumber min={0} step={0.01} />
                    </Form.Item>
                    <Form.Item name="minimum_commission" label="最低佣金（元）">
                      <InputNumber min={0} />
                    </Form.Item>
                    <Form.Item name="stamp_duty_rate" label="印花税率（%）">
                      <InputNumber min={0} step={0.01} />
                    </Form.Item>
                    <Form.Item name="transfer_fee_rate" label="过户费率（%）">
                      <InputNumber min={0} step={0.001} />
                    </Form.Item>
                    <Form.Item
                      name="slippage_basis_points"
                      label="滑点（基点，bps）"
                    >
                      <InputNumber min={0} />
                    </Form.Item>
                    <Form.Item
                      name="maximum_volume_participation"
                      label="最大成交量参与率（%）"
                    >
                      <InputNumber min={0} max={100} />
                    </Form.Item>
                  </Space>
                ),
              },
            ]}
          />
          {spec ? (
            <Alert
              showIcon
              type="success"
              icon={<SaveOutlined />}
              title={`已确认：${selectedName}`}
              description={
                <Space orientation="vertical" size={2}>
                  {preview.map((item) => (
                    <Typography.Text key={item}>{item}</Typography.Text>
                  ))}
                  <Typography.Text type="secondary">
                    股票：
                    {effectiveSelectedInstrument
                      ? formatInstrument(effectiveSelectedInstrument)
                      : "待选择"}
                  </Typography.Text>
                </Space>
              }
              style={{ marginBottom: 16 }}
            />
          ) : (
            <Alert
              showIcon
              type="warning"
              icon={<InfoCircleOutlined />}
              title="请先在第一步确认策略"
              style={{ marginBottom: 16 }}
            />
          )}
          {run.error ? (
            <Alert
              showIcon
              type="error"
              title={errorText(run.error)}
              style={{ marginBottom: 16 }}
            />
          ) : null}
          <Button
            type="primary"
            size="large"
            htmlType="submit"
            icon={<ExperimentOutlined />}
            loading={run.isPending}
            disabled={!spec}
          >
            开始回测
          </Button>
        </Form>
      </Card>
    </section>
  );
}
