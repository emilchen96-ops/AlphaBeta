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
  Input,
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
  execution_mode: "INDEPENDENT" | "SHARED_PORTFOLIO";
  instrument_id?: string;
  instrument_ids?: string[];
  watchlist_id?: string;
  exclude_st: boolean;
  exclude_bse: boolean;
  exclude_star_market: boolean;
  exclude_chinext: boolean;
  minimum_listing_trading_days: number | null;
  range: [Dayjs, Dayjs];
  initial_cash: number;
  position_size_percent: number;
  maximum_holdings: number;
  maximum_total_exposure_percent: number;
  maximum_instrument_weight_percent: number;
  allow_position_addition: boolean;
  entry_ranking: string;
  benchmark_symbol?: string;
  commission_rate: number | null;
  minimum_commission: number | null;
  stamp_duty_rate: number | null;
  transfer_fee_rate: number | null;
  slippage_basis_points: number | null;
  maximum_volume_participation: number | null;
  execution_price_mode:
    | "NEXT_OPEN"
    | "SIGNAL_CLOSE_LIMIT"
    | "SAME_DAY_NEXT_MINUTE"
    | "INTRADAY_NEXT_MINUTE"
    | "INTRADAY_SIGNAL_CLOSE";
  signal_timeframe: "MINUTE_1" | "MINUTE_5" | "MINUTE_15";
  auto_prepare_minute_data: boolean;
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
  const batchExecutionMode =
    Form.useWatch("execution_mode", form) ?? "SHARED_PORTFOLIO";
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
        signal_timeframe: values.signal_timeframe,
        auto_prepare_minute_data: values.auto_prepare_minute_data,
        optimistic_fill_assumption:
          values.execution_price_mode === "INTRADAY_SIGNAL_CLOSE",
        maximum_entry_gap_ratio:
          (values.execution_price_mode === "NEXT_OPEN" ||
            values.execution_price_mode === "INTRADAY_NEXT_MINUTE") &&
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
        execution_mode: values.execution_mode,
        instrument_ids:
          values.scope === "MANUAL" ? (values.instrument_ids ?? []) : [],
        watchlist_id:
          values.scope === "WATCHLIST" ? (values.watchlist_id ?? null) : null,
        exclude_st: values.exclude_st,
        exclude_bse: values.exclude_bse,
        exclude_star_market: values.exclude_star_market,
        exclude_chinext: values.exclude_chinext,
        minimum_listing_trading_days: values.minimum_listing_trading_days,
        maximum_holdings: values.maximum_holdings,
        maximum_total_exposure: String(
          values.maximum_total_exposure_percent / 100,
        ),
        maximum_instrument_weight: String(
          values.maximum_instrument_weight_percent / 100,
        ),
        allow_position_addition: values.allow_position_addition,
        entry_ranking: values.entry_ranking,
        benchmark_symbol: values.benchmark_symbol?.trim() || null,
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
            execution_mode: "SHARED_PORTFOLIO",
            instrument_id: prefilledInstrumentId ?? undefined,
            exclude_st: true,
            exclude_bse: false,
            exclude_star_market: false,
            exclude_chinext: false,
            minimum_listing_trading_days: null,
            range: [dayjs().subtract(2, "year"), dayjs()],
            initial_cash: 100000,
            position_size_percent: 100,
            maximum_holdings: 5,
            maximum_total_exposure_percent: 100,
            maximum_instrument_weight_percent: 20,
            allow_position_addition: false,
            entry_ranking: "SIGNAL_STRENGTH_VOLUME_SYMBOL",
            benchmark_symbol: "000300.SH",
            commission_rate: 0.03,
            minimum_commission: 5,
            stamp_duty_rate: 0.05,
            transfer_fee_rate: 0.001,
            slippage_basis_points: 2,
            maximum_volume_participation: 10,
            execution_price_mode: "INTRADAY_NEXT_MINUTE",
            signal_timeframe: "MINUTE_1",
            auto_prepare_minute_data: true,
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
                { label: "手选多只股票", value: "MANUAL" },
                { label: "一个自选组合", value: "WATCHLIST" },
                { label: "全部 A 股", value: "ALL_A_SHARES" },
              ]}
              onChange={(event) => {
                const scope = event.target.value as BacktestScope;
                if (scope === "SINGLE") {
                  form.setFieldValue("position_size_percent", 100);
                } else if (
                  form.getFieldValue("execution_mode") === "SHARED_PORTFOLIO"
                ) {
                  form.setFieldValue("position_size_percent", 20);
                }
              }}
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
          ) : backtestScope === "MANUAL" ? (
            <Form.Item
              name="instrument_ids"
              label="回测股票组"
              rules={[{ required: true, message: "请至少选择一只股票" }]}
              extra="可按名称或代码搜索并选择多只股票。"
            >
              <Select
                mode="multiple"
                showSearch
                filterOption={false}
                placeholder="搜索并选择股票"
                loading={instruments.isFetching}
                options={(instruments.data?.items ?? []).map((item) => ({
                  value: item.id,
                  label: formatInstrument(item),
                }))}
                onSearch={(keyword) => setInstrumentKeyword(keyword.trim())}
              />
            </Form.Item>
          ) : backtestScope === "WATCHLIST" ? (
            <Form.Item
              name="watchlist_id"
              label="自选组合"
              rules={[{ required: true, message: "请选择一个自选组合" }]}
              extra={
                batchExecutionMode === "SHARED_PORTFOLIO"
                  ? "组合内股票共享一笔现金和持仓上限，生成一份真实组合报告。"
                  : "组合内每只股票使用相同初始资金独立回测，用于横向比较。"
              }
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
              description={
                batchExecutionMode === "SHARED_PORTFOLIO"
                  ? "系统会按统一时间轴竞争共享资金；日线先筛候选日，再按需加载分钟行情。页面可关闭，任务会继续运行。"
                  : "每只股票都会生成独立账户、成交与绩效；耗时取决于股票数量、本地历史数据完整度和电脑性能。"
              }
              style={{ marginBottom: 16 }}
            />
          )}
          {backtestScope !== "SINGLE" ? (
            <>
              <Form.Item name="execution_mode" label="批量回测方式">
                <Radio.Group
                  optionType="button"
                  buttonStyle="solid"
                  options={[
                    {
                      label: "共享资金组合回测（推荐）",
                      value: "SHARED_PORTFOLIO",
                    },
                    { label: "逐股独立回测", value: "INDEPENDENT" },
                  ]}
                  onChange={(event) =>
                    form.setFieldValue(
                      "position_size_percent",
                      event.target.value === "SHARED_PORTFOLIO" ? 20 : 100,
                    )
                  }
                />
              </Form.Item>
              <Alert
                showIcon
                type="info"
                title={
                  batchExecutionMode === "SHARED_PORTFOLIO"
                    ? "所有股票共享同一账户、现金和持仓"
                    : "每只股票使用独立账户，仅用于比较样本"
                }
                description={
                  batchExecutionMode === "SHARED_PORTFOLIO"
                    ? "同一时刻先处理卖出，再按排序规则处理买入；资金用完后新的买入信号会被拒绝。"
                    : "结果不会合并成组合收益曲线，也不能代表真实组合绩效。"
                }
                style={{ marginBottom: 16 }}
              />
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
                <Form.Item
                  name="exclude_chinext"
                  valuePropName="checked"
                  noStyle
                >
                  <Checkbox>排除创业板</Checkbox>
                </Form.Item>
                <Form.Item name="exclude_bse" valuePropName="checked" noStyle>
                  <Checkbox>排除北交所</Checkbox>
                </Form.Item>
              </Space>
              <Form.Item
                name="minimum_listing_trading_days"
                label="排除上市时间不足（交易日，可空）"
                tooltip="留空表示不按上市天数排除；填写后按筛选截止日之前的实际开市日计算。"
              >
                <InputNumber min={1} max={5000} placeholder="例如 60" />
              </Form.Item>
            </>
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
          {backtestScope !== "SINGLE" &&
          batchExecutionMode === "SHARED_PORTFOLIO" ? (
            <Card
              size="small"
              title="共享资金与持仓规则"
              style={{ marginBottom: 16 }}
            >
              <Space wrap size={24} align="start">
                <Form.Item
                  name="maximum_holdings"
                  label="最多同时持股（只）"
                  rules={[{ required: true }]}
                >
                  <InputNumber min={1} max={5000} />
                </Form.Item>
                <Form.Item
                  name="maximum_total_exposure_percent"
                  label="组合最高仓位（%）"
                  tooltip="所有持仓市值合计最多占组合总权益的比例。"
                  rules={[{ required: true }]}
                >
                  <InputNumber min={1} max={100} addonAfter="%" />
                </Form.Item>
                <Form.Item
                  name="maximum_instrument_weight_percent"
                  label="单只股票最高仓位（%）"
                  rules={[{ required: true }]}
                >
                  <InputNumber min={1} max={100} addonAfter="%" />
                </Form.Item>
                <Form.Item
                  name="entry_ranking"
                  label="同一时刻买入排序"
                  tooltip="多个股票同时出现买入信号而资金不足时的优先顺序。"
                >
                  <Select
                    style={{ width: 300 }}
                    options={[
                      {
                        value: "SIGNAL_STRENGTH_VOLUME_SYMBOL",
                        label: "信号强度 → 成交量比例 → 股票代码",
                      },
                      {
                        value: "VOLUME_RATIO_SIGNAL_STRENGTH_SYMBOL",
                        label: "成交量比例 → 信号强度 → 股票代码",
                      },
                      { value: "SYMBOL", label: "股票代码" },
                    ]}
                  />
                </Form.Item>
                <Form.Item
                  name="benchmark_symbol"
                  label="对照基准"
                  tooltip="用于组合收益对照；默认沪深300。"
                >
                  <Input placeholder="例如 000300.SH" style={{ width: 180 }} />
                </Form.Item>
              </Space>
              <Form.Item
                name="allow_position_addition"
                valuePropName="checked"
                noStyle
              >
                <Checkbox>已有持仓再次出现买入信号时允许加仓</Checkbox>
              </Form.Item>
            </Card>
          ) : null}
          <Typography.Paragraph type="secondary">
            回测固定使用不复权行情，确保信号、开盘成交、费用和账本使用同一套真实价格。
          </Typography.Paragraph>
          <Alert
            showIcon
            type="info"
            title="成交价格规则"
            description={
              executionPriceMode === "INTRADAY_NEXT_MINUTE"
                ? "先用日线安全预筛候选日期，再只加载候选区间的分钟K线。每根分钟K线收完后，用已完成日线和当天截至该分钟的累计行情重新判断；首次满足条件后，下一根有效分钟K线开盘模拟成交，不读取未来数据。"
                : executionPriceMode === "INTRADAY_SIGNAL_CLOSE"
                  ? "乐观研究模式：分钟收盘确认信号后，假设可以按同一分钟收盘价成交。这无法保证真实可成交，仅用于敏感性对照，报告会明确标记乐观假设。"
                  : executionPriceMode === "SAME_DAY_NEXT_MINUTE"
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
                    value: "INTRADAY_NEXT_MINUTE",
                    label: "盘中分钟触发，下一根分钟开盘成交（推荐）",
                  },
                  {
                    value: "NEXT_OPEN",
                    label: "日线收盘确认，下一交易日开盘成交",
                  },
                  {
                    value: "SAME_DAY_NEXT_MINUTE",
                    label: "当日尾盘成交（14:55判断，下一分钟执行）",
                  },
                  {
                    value: "SIGNAL_CLOSE_LIMIT",
                    label: "信号日收盘价限价（可能无法成交）",
                  },
                  {
                    value: "INTRADAY_SIGNAL_CLOSE",
                    label: "分钟触发后按当根收盘成交（乐观对照）",
                  },
                ]}
              />
            </Form.Item>
            <Form.Item
              name="signal_timeframe"
              label="盘中信号周期"
              tooltip="1分钟最精细；5分钟和15分钟只在对应K线完整收盘后判断。"
            >
              <Select
                style={{ width: 220 }}
                disabled={
                  executionPriceMode !== "INTRADAY_NEXT_MINUTE" &&
                  executionPriceMode !== "INTRADAY_SIGNAL_CLOSE"
                }
                options={[
                  { value: "MINUTE_1", label: "1分钟" },
                  { value: "MINUTE_5", label: "5分钟" },
                  { value: "MINUTE_15", label: "15分钟" },
                ]}
              />
            </Form.Item>
            <Form.Item
              name="maximum_entry_gap_percent"
              label="最大允许跳空幅度（%）"
              tooltip="例如填 5：下一交易日或下一分钟开盘价若比信号价高出超过 5%，本次不追高。留空表示不限制。"
            >
              <InputNumber
                min={0}
                max={100}
                step={0.5}
                disabled={
                  executionPriceMode !== "NEXT_OPEN" &&
                  executionPriceMode !== "INTRADAY_NEXT_MINUTE"
                }
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
          {executionPriceMode === "INTRADAY_NEXT_MINUTE" ||
          executionPriceMode === "INTRADAY_SIGNAL_CLOSE" ? (
            <Space orientation="vertical" style={{ marginBottom: 16 }}>
              <Form.Item
                name="auto_prepare_minute_data"
                valuePropName="checked"
                noStyle
              >
                <Checkbox>自动检查并补齐候选交易日的分钟行情</Checkbox>
              </Form.Item>
              <Typography.Text type="secondary">
                系统先用本地日线缩小候选范围，再复用 PostgreSQL
                中已有分钟数据；只向已登录的 MiniQMT
                请求缺口，不会全量加载全部股票的全部分钟K线。
              </Typography.Text>
              {executionPriceMode === "INTRADAY_SIGNAL_CLOSE" ? (
                <Alert
                  showIcon
                  type="warning"
                  title="这是乐观成交假设"
                  description="同一分钟收盘后才知道信号，却假设仍能按该收盘价成交，可能高估策略表现；默认推荐使用下一根分钟开盘成交。"
                />
              ) : null}
            </Space>
          ) : null}
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
                      : `${
                          backtestScope === "MANUAL"
                            ? "手选股票组"
                            : backtestScope === "WATCHLIST"
                              ? "所选自选组合"
                              : "全部 A 股"
                        }（${
                          batchExecutionMode === "SHARED_PORTFOLIO"
                            ? "共享资金组合回测"
                            : "逐股独立回测"
                        }）`}
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
