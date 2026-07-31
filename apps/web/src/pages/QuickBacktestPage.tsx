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
  Checkbox,
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
import { getWatchlists } from "../api/market";
import {
  createBacktestBatch,
  createQuickBacktest,
  listStrategyTemplates,
  listUserStrategies,
} from "../api/strategySpecs";
import { NaturalLanguageStrategyBuilder } from "../components/StrategyBuilder/NaturalLanguageStrategyBuilder";
import { PageHeader } from "../components/PageHeader/PageHeader";
import type { Instrument } from "../types/market";
import type {
  BacktestBatchRequest,
  BacktestScope,
  QuickBacktestRequest,
  StrategySpec,
} from "../types/strategySpecs";
import { formatInstrument } from "../utils/display";

const EXAMPLE = "10日价格突破 + 1.2倍成交量，5日均线退出，单只股票、两年日线";

type StrategySource = "description" | "template" | "saved";

interface BacktestFormValues {
  scope: BacktestScope;
  instrument_id?: string;
  watchlist_id?: string;
  exclude_st: boolean;
  exclude_bse: boolean;
  exclude_star_market: boolean;
  exclude_chinext: boolean;
  range: [Dayjs, Dayjs];
  initial_cash: number;
  position_size_percent: number;
  commission_rate: number | null;
  minimum_commission: number | null;
  stamp_duty_rate: number | null;
  transfer_fee_rate: number | null;
  slippage_basis_points: number | null;
  maximum_volume_participation: number | null;
  execution_price_mode:
    "NEXT_OPEN" | "SIGNAL_CLOSE_LIMIT" | "SAME_DAY_NEXT_MINUTE";
  maximum_entry_gap_percent: number | null;
  time_in_force: "DAY" | "GTC";
}

const errorText = (reason: unknown) =>
  reason instanceof ApiError ? reason.message : "回测启动失败，请稍后重试";

const numberOrDefault = (value: number | null | undefined, fallback: number) =>
  typeof value === "number" && Number.isFinite(value) ? value : fallback;

export function QuickBacktestPage() {
  const [search] = useSearchParams();
  const navigate = useNavigate();
  const [form] = Form.useForm<BacktestFormValues>();
  const executionPriceMode = Form.useWatch("execution_price_mode", form);
  const backtestScope = Form.useWatch("scope", form) ?? "SINGLE";
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
  const watchlists = useQuery({
    queryKey: ["quick-backtest-watchlists"],
    queryFn: getWatchlists,
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
      const common = {
        start_at: values.range[0].startOf("day").toISOString(),
        end_at: values.range[1].add(1, "day").startOf("day").toISOString(),
        initial_cash: String(values.initial_cash),
        position_size_ratio:
          values.execution_price_mode !== "SIGNAL_CLOSE_LIMIT"
            ? String(values.position_size_percent / 100)
            : null,
        commission_rate: String(
          numberOrDefault(values.commission_rate, 0.03) / 100,
        ),
        minimum_commission: String(
          numberOrDefault(values.minimum_commission, 5),
        ),
        stamp_duty_rate: String(
          numberOrDefault(values.stamp_duty_rate, 0.05) / 100,
        ),
        transfer_fee_rate: String(
          numberOrDefault(values.transfer_fee_rate, 0.001) / 100,
        ),
        slippage_basis_points: String(
          numberOrDefault(values.slippage_basis_points, 2),
        ),
        maximum_volume_participation:
          values.maximum_volume_participation === null
            ? null
            : String(
                numberOrDefault(values.maximum_volume_participation, 10) / 100,
              ),
        execution_price_mode: values.execution_price_mode,
        maximum_entry_gap_ratio:
          values.execution_price_mode === "NEXT_OPEN" &&
          values.maximum_entry_gap_percent !== null
            ? String(values.maximum_entry_gap_percent / 100)
            : null,
        time_in_force: values.time_in_force,
        idempotency_key: `quick-backtest:${crypto.randomUUID()}`,
        ...(source === "saved" && userStrategyId
          ? { user_strategy_id: userStrategyId }
          : { spec }),
      };
      if (values.scope === "SINGLE") {
        if (!values.instrument_id) throw new Error("请选择一只股票");
        const request: QuickBacktestRequest = {
          ...common,
          instrument_id: values.instrument_id,
          price_adjustment_mode: "RAW",
        };
        return {
          kind: "single" as const,
          result: await createQuickBacktest(request),
        };
      }
      const request: BacktestBatchRequest = {
        ...common,
        scope: values.scope,
        watchlist_id:
          values.scope === "WATCHLIST" ? (values.watchlist_id ?? null) : null,
        exclude_st: values.exclude_st,
        exclude_bse: values.exclude_bse,
        exclude_star_market: values.exclude_star_market,
        exclude_chinext: values.exclude_chinext,
        idempotency_key: `backtest-batch:${crypto.randomUUID()}`,
      };
      return {
        kind: "batch" as const,
        result: await createBacktestBatch(request),
      };
    },
    onSuccess: ({ kind, result }) => {
      void navigate(
        kind === "single"
          ? `/research/backtests/${result.id}`
          : `/research/backtest-batches/${result.id}`,
      );
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
            scope: "SINGLE",
            instrument_id: prefilledInstrumentId ?? undefined,
            exclude_st: true,
            exclude_bse: false,
            exclude_star_market: false,
            exclude_chinext: false,
            range: [dayjs().subtract(2, "year"), dayjs()],
            initial_cash: 100000,
            position_size_percent: 100,
            commission_rate: 0.03,
            minimum_commission: 5,
            stamp_duty_rate: 0.05,
            transfer_fee_rate: 0.001,
            slippage_basis_points: 2,
            maximum_volume_participation: 10,
            execution_price_mode: "NEXT_OPEN",
            maximum_entry_gap_percent: 5,
            time_in_force: "DAY",
          }}
          onFinish={(values) => run.mutate(values)}
        >
          <Form.Item name="scope" label="回测范围">
            <Radio.Group
              optionType="button"
              buttonStyle="solid"
              options={[
                { label: "单只股票", value: "SINGLE" },
                { label: "一个自选组合", value: "WATCHLIST" },
                { label: "全部 A 股", value: "ALL_A_SHARES" },
              ]}
            />
          </Form.Item>
          {backtestScope === "SINGLE" ? (
            <Form.Item
              name="instrument_id"
              label="回测股票"
              rules={[{ required: true, message: "请选择一只股票" }]}
              extra="只生成一份回测报告。"
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
                    .filter(
                      (item) => item.id !== effectiveSelectedInstrument?.id,
                    )
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
          ) : backtestScope === "WATCHLIST" ? (
            <Form.Item
              name="watchlist_id"
              label="自选组合"
              rules={[{ required: true, message: "请选择一个自选组合" }]}
              extra="组合内每只股票使用相同初始资金独立回测，不共享资金和持仓。"
            >
              <Select
                placeholder="选择自选列表"
                loading={watchlists.isLoading}
                options={(watchlists.data ?? []).map((item) => ({
                  value: item.id,
                  label: item.name,
                }))}
              />
            </Form.Item>
          ) : (
            <Alert
              showIcon
              type="warning"
              title="全 A 股将创建长期后台任务"
              description="每只股票都会生成独立账户、成交与绩效；耗时取决于股票数量、本地历史数据完整度和电脑性能。页面可关闭，任务会继续运行。"
              style={{ marginBottom: 16 }}
            />
          )}
          {backtestScope !== "SINGLE" ? (
            <Space wrap style={{ marginBottom: 16 }}>
              <Form.Item name="exclude_st" valuePropName="checked" noStyle>
                <Checkbox>排除 ST 与 *ST</Checkbox>
              </Form.Item>
              <Form.Item
                name="exclude_star_market"
                valuePropName="checked"
                noStyle
              >
                <Checkbox>排除科创板</Checkbox>
              </Form.Item>
              <Form.Item name="exclude_chinext" valuePropName="checked" noStyle>
                <Checkbox>排除创业板</Checkbox>
              </Form.Item>
              <Form.Item name="exclude_bse" valuePropName="checked" noStyle>
                <Checkbox>排除北交所</Checkbox>
              </Form.Item>
            </Space>
          ) : null}
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
              name="position_size_percent"
              label="单次买入仓位（%）"
              tooltip="按执行时可用资金的比例计算买入金额，并在计入开盘价、滑点和费用后向下取整为 100 股整手。卖出信号默认卖出该股票的全部可用持仓。"
              rules={[{ required: true, message: "请设置买入仓位" }]}
            >
              <InputNumber
                min={1}
                max={100}
                step={5}
                addonAfter="%"
                disabled={executionPriceMode === "SIGNAL_CLOSE_LIMIT"}
                style={{ width: 180 }}
              />
            </Form.Item>
          </Space>
          <Typography.Paragraph type="secondary">
            回测固定使用不复权行情，确保信号、开盘成交、费用和账本使用同一套真实价格。
          </Typography.Paragraph>
          <Alert
            showIcon
            type="info"
            title="成交价格规则"
            description={
              executionPriceMode === "SAME_DAY_NEXT_MINUTE"
                ? "系统只使用14:55之前已经完整形成的分钟K线估算当日日线条件，并以14:55之后第一根可成交分钟K线的开盘价模拟成交。不会读取15:00收盘结果后倒推当天成交。缺少分钟行情时将直接停止并提示。"
                : "策略在 T 日收盘后确认信号，最早于下一交易日开盘执行。默认按下一交易日开盘价并计入滑点；若买入时高开超过允许幅度，则按下方未成交处理方式处理。"
            }
            style={{ marginBottom: 12 }}
          />
          <Space wrap size={24} align="start">
            <Form.Item
              name="execution_price_mode"
              label="买入执行价格方式"
              tooltip="推荐使用下一交易日开盘价，避免把信号日收盘价误当成实际成交价。"
            >
              <Select
                style={{ width: 320 }}
                options={[
                  {
                    value: "NEXT_OPEN",
                    label: "下一交易日开盘价成交（推荐）",
                  },
                  {
                    value: "SAME_DAY_NEXT_MINUTE",
                    label: "当日尾盘成交（14:55判断，下一分钟执行）",
                  },
                  {
                    value: "SIGNAL_CLOSE_LIMIT",
                    label: "信号日收盘价限价（可能无法成交）",
                  },
                ]}
              />
            </Form.Item>
            <Form.Item
              name="maximum_entry_gap_percent"
              label="最大允许高开幅度（%）"
              tooltip="例如填 5：次日开盘价若比信号日收盘价高出超过 5%，本次不追高。留空表示不限制。"
            >
              <InputNumber
                min={0}
                max={100}
                step={0.5}
                disabled={executionPriceMode !== "NEXT_OPEN"}
                placeholder="留空表示不限制"
                style={{ width: 220 }}
              />
            </Form.Item>
            <Form.Item
              name="time_in_force"
              label="未成交后的处理"
              tooltip="当日取消只尝试下一个交易日一次；继续等待会在后续交易日再次尝试，直到成交或回测结束。"
            >
              <Select
                style={{ width: 260 }}
                options={[
                  { value: "DAY", label: "当天未成交就取消（推荐）" },
                  { value: "GTC", label: "继续等待后续交易日" },
                ]}
              />
            </Form.Item>
          </Space>
          <Collapse
            ghost
            items={[
              {
                key: "advanced",
                label: "高级设置：交易费用与成交约束",
                children: (
                  <Space wrap size={24} align="start">
                    <Form.Item name="commission_rate" label="佣金率（%）">
                      <InputNumber min={0} step={0.01} />
                    </Form.Item>
                    <Form.Item
                      name="minimum_commission"
                      label="最低佣金（元）"
                      extra="不修改或留空时按 5 元计算"
                    >
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
                      label="预计成交价偏差（滑点，基点 bps）"
                      tooltip="模拟下单到成交之间的价格变化。买入价会略高、卖出价会略低；1 个基点等于 0.01%。"
                    >
                      <InputNumber min={0} />
                    </Form.Item>
                    <Form.Item
                      name="maximum_volume_participation"
                      label="单次最多占当日成交量（%）"
                      tooltip="避免回测假设一次买入或卖出超过当天可成交数量。10% 表示单次最多使用当天成交量的十分之一。"
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
                    范围：
                    {backtestScope === "SINGLE"
                      ? effectiveSelectedInstrument
                        ? formatInstrument(effectiveSelectedInstrument)
                        : "待选择"
                      : backtestScope === "WATCHLIST"
                        ? "所选自选组合（逐只独立回测）"
                        : "全部 A 股（逐只独立回测）"}
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
            {backtestScope === "SINGLE" ? "开始回测" : "创建批量回测任务"}
          </Button>
        </Form>
      </Card>
    </section>
  );
}
