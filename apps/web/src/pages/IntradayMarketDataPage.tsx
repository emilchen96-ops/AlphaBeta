import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Checkbox,
  Col,
  Descriptions,
  Input,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import { useMemo, useState } from "react";

import {
  aggregateIntraday,
  generateIntradayFixture,
  getIntradayBars,
  getIntradayCoverage,
  getIntradayImports,
  getIntradayProviders,
  getIntradayQualityRuns,
  getIntradayReadiness,
  verifyIntradayQuality,
} from "../api/intraday";
import { getInstruments } from "../api/market";
import { CandlestickChart } from "../components/CandlestickChart/CandlestickChart";
import { PageHeader } from "../components/PageHeader/PageHeader";
import type { MarketBar, MarketTimeframe } from "../types/market";

const timeframes: MarketTimeframe[] = [
  "MINUTE_1",
  "MINUTE_5",
  "MINUTE_15",
  "MINUTE_30",
  "MINUTE_60",
];

const statusColor = (value: string) =>
  value === "READY" || value === "AVAILABLE" || value === "SUCCEEDED"
    ? "success"
    : value === "NOT_IMPLEMENTED" || value === "DISABLED"
      ? "default"
      : "warning";

export function IntradayMarketDataPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [dryRun, setDryRun] = useState(false);
  const [instrumentId, setInstrumentId] = useState<string>();
  const [timeframe, setTimeframe] = useState<MarketTimeframe>("MINUTE_5");
  const [adjustment, setAdjustment] = useState<"RAW" | "QFQ">("RAW");
  const [coverageInstrument, setCoverageInstrument] = useState<string>();
  const [coverageTimeframe, setCoverageTimeframe] = useState<MarketTimeframe>();
  const [coverageStart, setCoverageStart] = useState("");
  const [coverageEnd, setCoverageEnd] = useState("");
  const [aggregationTargets, setAggregationTargets] = useState<
    MarketTimeframe[]
  >(timeframes.slice(1));
  const [aggregationStart, setAggregationStart] = useState("2026-07-06");
  const [aggregationEnd, setAggregationEnd] = useState("2026-07-11");
  const [qualityTimeframe, setQualityTimeframe] =
    useState<MarketTimeframe>("MINUTE_1");
  const [qualityStart, setQualityStart] = useState("2026-07-06");
  const [qualityEnd, setQualityEnd] = useState("2026-07-11");
  const providers = useQuery({
    queryKey: ["intraday-providers"],
    queryFn: getIntradayProviders,
  });
  const coverage = useQuery({
    queryKey: [
      "intraday-coverage",
      coverageInstrument,
      coverageTimeframe,
      coverageStart,
      coverageEnd,
    ],
    queryFn: () =>
      getIntradayCoverage({
        instrumentId: coverageInstrument,
        timeframe: coverageTimeframe,
        startAt: coverageStart ? `${coverageStart}T00:00:00+08:00` : undefined,
        endAt: coverageEnd ? `${coverageEnd}T00:00:00+08:00` : undefined,
      }),
    enabled: Boolean(coverageStart) === Boolean(coverageEnd),
  });
  const readiness = useQuery({
    queryKey: ["intraday-readiness"],
    queryFn: getIntradayReadiness,
  });
  const imports = useQuery({
    queryKey: ["intraday-imports"],
    queryFn: getIntradayImports,
  });
  const quality = useQuery({
    queryKey: ["intraday-quality"],
    queryFn: getIntradayQualityRuns,
  });
  const instruments = useQuery({
    queryKey: ["intraday-instruments"],
    queryFn: () => getInstruments("D03 Fixture"),
  });
  const effectiveInstrument = instrumentId ?? instruments.data?.items[0]?.id;
  const bars = useQuery({
    queryKey: ["intraday-bars", effectiveInstrument, timeframe, adjustment],
    queryFn: () => getIntradayBars(effectiveInstrument!, timeframe, adjustment),
    enabled: Boolean(effectiveInstrument),
  });

  const refresh = async () => {
    await Promise.all(
      [
        "intraday-coverage",
        "intraday-readiness",
        "intraday-imports",
        "intraday-quality",
        "intraday-instruments",
        "intraday-bars",
      ].map((key) => queryClient.invalidateQueries({ queryKey: [key] })),
    );
  };
  const fixture = useMutation({
    mutationFn: () => generateIntradayFixture(dryRun),
    onSuccess: async (result) => {
      await refresh();
      void message.success(
        dryRun
          ? `试运行预览读取 ${result.rows_valid} 根有效分钟K线`
          : `导入 ${result.bars_inserted} 根, 聚合新增 ${result.aggregated_bars_created} 根`,
      );
    },
    onError: (error: Error) => void message.error(error.message),
  });
  const aggregate = useMutation({
    mutationFn: () =>
      aggregateIntraday({
        instrument_id: effectiveInstrument!,
        start_at: `${aggregationStart}T00:00:00+08:00`,
        end_at: `${aggregationEnd}T00:00:00+08:00`,
        targets: aggregationTargets,
        dry_run: dryRun,
      }),
    onSuccess: refresh,
    onError: (error: Error) => void message.error(error.message),
  });
  const verify = useMutation({
    mutationFn: () =>
      verifyIntradayQuality(
        effectiveInstrument!,
        qualityTimeframe,
        `${qualityStart}T00:00:00+08:00`,
        `${qualityEnd}T00:00:00+08:00`,
      ),
    onSuccess: refresh,
    onError: (error: Error) => void message.error(error.message),
  });
  const chartBars = useMemo(
    () =>
      (bars.data?.items ?? []).map((bar): MarketBar => ({
        ...bar,
        source_code: "D03_FIXTURE",
        vwap: null,
        adjustment_mode: adjustment,
        factor: null,
        reference_factor: null,
        raw_bar_id: bar.id,
        quality_status: "NORMAL",
      })),
    [adjustment, bars.data?.items],
  );

  return (
    <section>
      <PageHeader
        title="分钟行情数据中心"
        description="D03历史分钟数据: RAW 1分钟导入、Session聚合、质量与就绪度。不是实时行情。"
        action={<Button onClick={() => void refresh()}>刷新</Button>}
      />
      <Alert
        type="warning"
        showIcon
        title="历史研究数据，不连接实时 WebSocket，不接 MiniQMT"
        description="Bar时间表示区间开始; 数据库存UTC, 页面按Asia/Shanghai理解。BT02与分钟回放代码尚未开发。"
      />
      <Tabs
        items={[
          {
            key: "providers",
            label: "数据提供方状态",
            children: (
              <Table
                rowKey="provider_key"
                pagination={false}
                dataSource={providers.data?.items ?? []}
                columns={[
                  { title: "数据提供方", dataIndex: "provider_key" },
                  {
                    title: "状态",
                    dataIndex: "health",
                    render: (value: string) => (
                      <Tag color={statusColor(value)}>{value}</Tag>
                    ),
                  },
                  {
                    title: "输入",
                    dataIndex: "input_types",
                    render: (value: string[]) => value.join(", ") || "—",
                  },
                  { title: "说明", dataIndex: "message" },
                ]}
              />
            ),
          },
          {
            key: "import",
            label: "导入任务",
            children: (
              <Space
                orientation="vertical"
                size="large"
                style={{ width: "100%" }}
              >
                <Card title="确定性测试数据（Fixture）">
                  <Space wrap>
                    <Checkbox
                      checked={dryRun}
                      onChange={(event) => setDryRun(event.target.checked)}
                    >
                      试运行预览（Dry-run）
                    </Checkbox>
                    <Button
                      type="primary"
                      loading={fixture.isPending}
                      onClick={() => fixture.mutate()}
                    >
                      导入2只股票 × 5个交易日
                    </Button>
                  </Space>
                </Card>
                <Alert
                  type="info"
                  title="本地文件通过命令行（CLI）安全导入；页面不提供无响应的上传按钮"
                  description="python -m alphadesk_api.cli.intraday import-file --path <file.csv> --source-timezone Asia/Shanghai --aggregate 5m,15m,30m,60m"
                />
                <Table
                  rowKey="id"
                  dataSource={imports.data?.items ?? []}
                  columns={[
                    {
                      title: "状态",
                      dataIndex: "status",
                      render: (value: string) => (
                        <Tag color={statusColor(value)}>{value}</Tag>
                      ),
                    },
                    { title: "读取", dataIndex: "total_received" },
                    { title: "插入", dataIndex: "total_inserted" },
                    { title: "更新", dataIndex: "total_updated" },
                    { title: "无效", dataIndex: "total_rejected" },
                    {
                      title: "开始时间",
                      dataIndex: "started_at",
                      render: (value: string) =>
                        new Date(value).toLocaleString("zh-CN"),
                    },
                  ]}
                />
              </Space>
            ),
          },
          {
            key: "coverage",
            label: "覆盖度",
            children: (
              <Space
                orientation="vertical"
                size="large"
                style={{ width: "100%" }}
              >
                <Space wrap>
                  <Select
                    value="D03_FIXTURE"
                    options={[
                      { value: "D03_FIXTURE", label: "D03 Fixture Universe" },
                    ]}
                    style={{ width: 190 }}
                  />
                  <Select
                    allowClear
                    placeholder="全部标的"
                    style={{ width: 240 }}
                    value={coverageInstrument}
                    options={instruments.data?.items.map((item) => ({
                      value: item.id,
                      label: `${item.symbol} ${item.name}`,
                    }))}
                    onChange={setCoverageInstrument}
                  />
                  <Select
                    allowClear
                    placeholder="全部周期"
                    style={{ width: 160 }}
                    value={coverageTimeframe}
                    options={timeframes.map((item) => ({
                      value: item,
                      label: item,
                    }))}
                    onChange={setCoverageTimeframe}
                  />
                  <Input
                    aria-label="覆盖度开始日期"
                    type="date"
                    style={{ width: 160 }}
                    value={coverageStart}
                    onChange={(event) => setCoverageStart(event.target.value)}
                  />
                  <Input
                    aria-label="覆盖度结束日期（不含）"
                    type="date"
                    style={{ width: 160 }}
                    value={coverageEnd}
                    onChange={(event) => setCoverageEnd(event.target.value)}
                  />
                </Space>
                <Row gutter={[16, 16]}>
                  {(coverage.data?.items ?? []).map((item) => (
                    <Col xs={24} md={8} key={item.timeframe}>
                      <Card>
                        <Statistic
                          title={item.timeframe}
                          value={item.bar_count}
                          suffix="Bars"
                        />
                        <Typography.Text type="secondary">
                          {item.instrument_count}个标的 · 完整Session{" "}
                          {item.complete_session_count}· 缺失{" "}
                          {item.missing_session_count}
                          <br />
                          RAW {item.raw_coverage} · QFQ {item.qfq_coverage} ·
                          质量错误 {item.quality_error_count}
                          <br />
                          {item.earliest_at
                            ? new Date(item.earliest_at).toLocaleString("zh-CN")
                            : "暂无"}
                        </Typography.Text>
                      </Card>
                    </Col>
                  ))}
                </Row>
              </Space>
            ),
          },
          {
            key: "aggregation",
            label: "跨周期聚合",
            children: (
              <Card title="不复权（RAW）1分钟 → 5/15/30/60分钟">
                <Space wrap>
                  <Select
                    style={{ width: 260 }}
                    value={effectiveInstrument}
                    placeholder="选择测试标的"
                    options={instruments.data?.items.map((item) => ({
                      value: item.id,
                      label: `${item.symbol} ${item.name}`,
                    }))}
                    onChange={setInstrumentId}
                  />
                  <Select
                    mode="multiple"
                    style={{ minWidth: 320 }}
                    value={aggregationTargets}
                    options={timeframes
                      .slice(1)
                      .map((item) => ({ value: item, label: item }))}
                    onChange={setAggregationTargets}
                  />
                  <Input
                    aria-label="聚合开始日期"
                    type="date"
                    style={{ width: 160 }}
                    value={aggregationStart}
                    onChange={(event) =>
                      setAggregationStart(event.target.value)
                    }
                  />
                  <Input
                    aria-label="聚合结束日期（不含）"
                    type="date"
                    style={{ width: 160 }}
                    value={aggregationEnd}
                    onChange={(event) => setAggregationEnd(event.target.value)}
                  />
                  <Button
                    disabled={
                      !effectiveInstrument || !aggregationTargets.length
                    }
                    loading={aggregate.isPending}
                    onClick={() => aggregate.mutate()}
                  >
                    运行严格完整窗口聚合
                  </Button>
                </Space>
                <Descriptions
                  column={1}
                  size="small"
                  style={{ marginTop: 16 }}
                  items={[
                    {
                      key: "version",
                      label: "版本",
                      children: "D03_SESSION_V1",
                    },
                    {
                      key: "policy",
                      label: "窗口",
                      children: "STRICT_COMPLETE_WINDOW",
                    },
                    {
                      key: "boundary",
                      label: "边界",
                      children: "上午/下午分别锚定, 不跨午休",
                    },
                  ]}
                />
              </Card>
            ),
          },
          {
            key: "quality",
            label: "数据质量",
            children: (
              <Space orientation="vertical" style={{ width: "100%" }}>
                <Space wrap>
                  <Select
                    value={qualityTimeframe}
                    options={timeframes.map((item) => ({
                      value: item,
                      label: item,
                    }))}
                    onChange={setQualityTimeframe}
                  />
                  <Input
                    aria-label="质量开始日期"
                    type="date"
                    style={{ width: 160 }}
                    value={qualityStart}
                    onChange={(event) => setQualityStart(event.target.value)}
                  />
                  <Input
                    aria-label="质量结束日期（不含）"
                    type="date"
                    style={{ width: 160 }}
                    value={qualityEnd}
                    onChange={(event) => setQualityEnd(event.target.value)}
                  />
                </Space>
                <Button
                  disabled={!effectiveInstrument}
                  loading={verify.isPending}
                  onClick={() => verify.mutate()}
                >
                  检查Fixture {qualityTimeframe}质量
                </Button>
                <Table
                  rowKey="id"
                  dataSource={quality.data?.items ?? []}
                  columns={[
                    { title: "周期", dataIndex: "timeframe" },
                    { title: "状态", dataIndex: "status" },
                    { title: "检查Bars", dataIndex: "bars_checked" },
                    { title: "错误", dataIndex: "error_count" },
                    { title: "警告", dataIndex: "warning_count" },
                  ]}
                />
              </Space>
            ),
          },
          {
            key: "readiness",
            label: "Readiness",
            children: (
              <Table
                rowKey="capability_key"
                dataSource={readiness.data?.items ?? []}
                columns={[
                  { title: "功能", dataIndex: "capability_key" },
                  { title: "周期", dataIndex: "timeframe" },
                  {
                    title: "数据状态",
                    dataIndex: "data_status",
                    render: (value: string) => (
                      <Tag color={statusColor(value)}>{value}</Tag>
                    ),
                  },
                  { title: "可用标的", dataIndex: "ready_instrument_count" },
                  {
                    title: "代码状态",
                    dataIndex: "implementation_status",
                    render: (value: string) => (
                      <Tag color={statusColor(value)}>
                        {value === "NOT_IMPLEMENTED" ? "代码尚未开发" : value}
                      </Tag>
                    ),
                  },
                  {
                    title: "建议操作",
                    dataIndex: "required_action",
                    render: (value: string | null) => value ?? "—",
                  },
                ]}
              />
            ),
          },
          {
            key: "preview",
            label: "分钟K线预览",
            children: (
              <Card title="2026-07-06 历史分钟K线">
                <Space wrap style={{ marginBottom: 16 }}>
                  <Select
                    style={{ width: 260 }}
                    value={effectiveInstrument}
                    options={instruments.data?.items.map((item) => ({
                      value: item.id,
                      label: `${item.symbol} ${item.name}`,
                    }))}
                    onChange={setInstrumentId}
                  />
                  <Select
                    value={timeframe}
                    options={timeframes.map((item) => ({
                      value: item,
                      label: item,
                    }))}
                    onChange={setTimeframe}
                  />
                  <Select
                    value={adjustment}
                    options={[
                      { value: "RAW", label: "RAW" },
                      { value: "QFQ", label: "QFQ（研究）" },
                    ]}
                    onChange={setAdjustment}
                  />
                  <Tag color="blue">历史数据 · 非实时</Tag>
                </Space>
                <CandlestickChart bars={chartBars} loading={bars.isLoading} />
                <Typography.Text type="secondary">
                  午休期间没有Bar, 图中自然形成11:30—13:00断点。
                </Typography.Text>
              </Card>
            ),
          },
        ]}
      />
    </section>
  );
}
