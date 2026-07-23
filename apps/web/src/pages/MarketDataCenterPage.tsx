import {
  CheckCircleOutlined,
  CloudDownloadOutlined,
  ReloadOutlined,
  WarningOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  DatePicker,
  Empty,
  Flex,
  Input,
  Progress,
  Row,
  Segmented,
  Select,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import {
  getBars,
  getInstruments,
  getMarketDataCoverage,
  getMarketDataOverview,
  getMarketDataReadiness,
  getMarketReferenceStatus,
  getMarketSyncRuns,
  getQualityRuns,
  verifyMarketDataQuality,
} from "../api/market";
import {
  getIntradayCoverage,
  getIntradayImports,
  getIntradayQualityRuns,
  getIntradayReadiness,
} from "../api/intraday";
import {
  getMiniQMTStatus,
  requestMiniQMTHistoryBackfill,
} from "../api/miniqmt";
import { CandlestickChart } from "../components/CandlestickChart/CandlestickChart";
import { PageHeader } from "../components/PageHeader/PageHeader";
import type { Instrument, MarketTimeframe } from "../types/market";
import {
  displayEnum,
  formatDateTime,
  formatInstrument,
  formatNumber,
} from "../utils/display";

type DataTab = "overview" | "daily" | "minute" | "quality" | "advanced";

const validTabs = new Set<DataTab>([
  "overview",
  "daily",
  "minute",
  "quality",
  "advanced",
]);

function statusColor(value: string | undefined) {
  if (value === "READY" || value === "COMPLETED" || value === "SUCCEEDED")
    return "green";
  if (value === "PARTIAL" || value === "PARTIALLY_SUCCEEDED") return "orange";
  if (value === "FAILED" || value === "NOT_READY") return "red";
  return "default";
}

const readinessCapabilityLabels: Record<string, string> = {
  intraday_1m_ready: "1分钟行情研究",
  intraday_5m_ready: "5分钟行情研究",
  intraday_15m_ready: "15分钟行情研究",
  intraday_30m_ready: "30分钟行情研究",
  intraday_60m_ready: "60分钟行情研究",
  bt02_5m_ready: "5分钟回测（BT02）",
  bt02_15m_ready: "15分钟回测（BT02）",
  replay_intraday_ready: "分钟行情回放",
};

function displayReadinessCapability(value: string | undefined) {
  if (!value) return "—";
  return readinessCapabilityLabels[value] ?? `研究能力（${value}）`;
}

export function MarketDataCenterPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedTab = searchParams.get("tab") as DataTab | null;
  const activeTab =
    requestedTab && validTabs.has(requestedTab) ? requestedTab : "overview";
  const [keyword, setKeyword] = useState("");
  const [submittedKeyword, setSubmittedKeyword] = useState("");
  const [selectedInstrument, setSelectedInstrument] = useState<Instrument>();
  const [range, setRange] = useState<[Dayjs, Dayjs]>([
    dayjs().subtract(5, "year"),
    dayjs(),
  ]);
  const [historyType, setHistoryType] = useState<"DAY_1" | "MINUTE_1">("DAY_1");
  const [previewTimeframe, setPreviewTimeframe] =
    useState<MarketTimeframe>("MINUTE_1");

  const status = useQuery({
    queryKey: ["miniqmt-status"],
    queryFn: getMiniQMTStatus,
    refetchInterval: 10_000,
  });
  const instruments = useQuery({
    queryKey: ["data-center-instruments", submittedKeyword],
    queryFn: () => getInstruments(submittedKeyword),
  });
  const overview = useQuery({
    queryKey: ["market-data-overview"],
    queryFn: getMarketDataOverview,
  });
  const coverage = useQuery({
    queryKey: ["market-data-coverage"],
    queryFn: getMarketDataCoverage,
  });
  const readiness = useQuery({
    queryKey: ["market-data-readiness"],
    queryFn: getMarketDataReadiness,
  });
  const intradayCoverage = useQuery({
    queryKey: ["intraday-coverage"],
    queryFn: () => getIntradayCoverage(),
  });
  const intradayReadiness = useQuery({
    queryKey: ["intraday-readiness"],
    queryFn: getIntradayReadiness,
  });
  const intradayImports = useQuery({
    queryKey: ["intraday-imports"],
    queryFn: getIntradayImports,
  });
  const intradayQuality = useQuery({
    queryKey: ["intraday-quality-runs"],
    queryFn: getIntradayQualityRuns,
  });
  const qualityRuns = useQuery({
    queryKey: ["market-quality-runs"],
    queryFn: () => getQualityRuns(),
  });
  const reference = useQuery({
    queryKey: ["market-reference-status"],
    queryFn: getMarketReferenceStatus,
  });
  const syncRuns = useQuery({
    queryKey: ["market-sync-runs"],
    queryFn: getMarketSyncRuns,
  });

  const effectiveInstrument = selectedInstrument ?? instruments.data?.items[0];
  const minutePreview = useQuery({
    queryKey: [
      "data-center-minute-preview",
      effectiveInstrument?.id,
      previewTimeframe,
    ],
    queryFn: () =>
      getBars(effectiveInstrument?.id ?? "", previewTimeframe, "RAW"),
    enabled: activeTab === "minute" && Boolean(effectiveInstrument),
  });

  const backfill = useMutation({
    mutationFn: () => {
      if (!effectiveInstrument) throw new Error("请先选择股票");
      const requestedRange =
        historyType === "MINUTE_1"
          ? [dayjs().subtract(10, "day"), dayjs()]
          : range;
      return requestMiniQMTHistoryBackfill({
        instrument_ids: [effectiveInstrument.id],
        timeframe: historyType,
        start_at: requestedRange[0].startOf("day").toISOString(),
        end_at: requestedRange[1].endOf("day").toISOString(),
      });
    },
    onSuccess: (result) => {
      void message.success(
        `历史补数已排队，任务编号 ${result.request_id.slice(0, 8)}`,
      );
    },
    onError: (error: Error) => void message.error(error.message),
  });
  const qualityCheck = useMutation({
    mutationFn: verifyMarketDataQuality,
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["market-quality-runs"],
      });
      void message.success("MiniQMT 日线质量检查已完成");
    },
    onError: (error: Error) => void message.error(error.message),
  });

  const refreshAll = async () => {
    await Promise.all([
      status.refetch(),
      overview.refetch(),
      coverage.refetch(),
      readiness.refetch(),
      intradayCoverage.refetch(),
      intradayReadiness.refetch(),
      intradayImports.refetch(),
      intradayQuality.refetch(),
      qualityRuns.refetch(),
      syncRuns.refetch(),
    ]);
  };

  const minuteBars = (intradayCoverage.data?.items ?? []).reduce(
    (total, item) => total + item.bar_count,
    0,
  );
  const connectionState =
    status.data?.agent?.state ?? status.data?.state ?? "NOT_CONFIGURED";

  const selector = (
    <Card size="small" title="MiniQMT 历史补数">
      <Flex vertical gap={12}>
        <Input.Search
          value={keyword}
          placeholder="搜索股票代码或名称"
          enterButton="搜索"
          allowClear
          onChange={(event) => setKeyword(event.target.value)}
          onSearch={(value) => setSubmittedKeyword(value.trim())}
        />
        <Select
          aria-label="选择补数股票"
          value={effectiveInstrument?.id}
          placeholder="选择股票"
          showSearch={false}
          options={(instruments.data?.items ?? []).map((item) => ({
            value: item.id,
            label: formatInstrument(item),
          }))}
          onChange={(id) =>
            setSelectedInstrument(
              instruments.data?.items.find((item) => item.id === id),
            )
          }
        />
        <Segmented
          value={historyType}
          options={[
            { label: "历史日线", value: "DAY_1" },
            { label: "历史1分钟线", value: "MINUTE_1" },
          ]}
          onChange={setHistoryType}
        />
        {historyType === "DAY_1" ? (
          <DatePicker.RangePicker
            value={range}
            allowClear={false}
            onChange={(value) => {
              if (value?.[0] && value[1]) setRange([value[0], value[1]]);
            }}
          />
        ) : (
          <Alert
            showIcon
            type="info"
            title="分钟补数固定请求最近 10 天"
            description="5/15/30/60 分钟线由 MiniQMT 1 分钟线严格聚合生成。"
          />
        )}
        <Button
          type="primary"
          icon={<CloudDownloadOutlined />}
          loading={backfill.isPending}
          disabled={!effectiveInstrument}
          onClick={() => backfill.mutate()}
        >
          从 MiniQMT 补充历史行情
        </Button>
        <Typography.Text type="secondary">
          补数由 Windows 行情代理异步执行。MiniQMT 必须保持登录和运行。
        </Typography.Text>
      </Flex>
    </Card>
  );

  return (
    <div className="market-data-center-page">
      <PageHeader
        title="数据中心"
        description="管理 MiniQMT A 股目录、历史日线、分钟线、覆盖度与质量。这里不提供实时看盘，也不包含交易能力。"
        action={
          <Button icon={<ReloadOutlined />} onClick={() => void refreshAll()}>
            刷新数据状态
          </Button>
        }
      />
      <Alert
        showIcon
        type={
          connectionState === "CONNECTED" || connectionState === "RUNNING"
            ? "success"
            : "warning"
        }
        title="正式行情数据源：MiniQMT"
        description={`行情代理：${displayEnum(connectionState)}；目录最近同步：${formatDateTime(
          status.data?.agent?.last_catalog_sync_at,
        )}。BaoStock、AKShare 和测试数据不参与正式页面的数据读取。`}
      />

      <Tabs
        activeKey={activeTab}
        onChange={(key) => setSearchParams({ tab: key })}
        items={[
          {
            key: "overview",
            label: "数据概况",
            children: (
              <Space
                orientation="vertical"
                size="large"
                style={{ width: "100%" }}
              >
                <Row gutter={[16, 16]}>
                  <Col xs={12} lg={6}>
                    <Card>
                      <Statistic
                        title="本地有效股票"
                        value={
                          status.data?.agent?.catalog_instrument_count ??
                          overview.data?.instrument_count ??
                          0
                        }
                        suffix="只"
                      />
                    </Card>
                  </Col>
                  <Col xs={12} lg={6}>
                    <Card>
                      <Statistic
                        title="研究范围"
                        value={coverage.data?.instrument_count ?? 0}
                        suffix="只"
                      />
                    </Card>
                  </Col>
                  <Col xs={12} lg={6}>
                    <Card>
                      <Statistic
                        title="历史日线"
                        value={overview.data?.market_bar_count ?? 0}
                        suffix="根"
                      />
                    </Card>
                  </Col>
                  <Col xs={12} lg={6}>
                    <Card>
                      <Statistic
                        title="历史分钟线"
                        value={minuteBars}
                        suffix="根"
                      />
                    </Card>
                  </Col>
                </Row>
                <Card title="数据可用性">
                  <Row gutter={[24, 24]}>
                    <Col xs={24} md={8}>
                      <Typography.Text type="secondary">
                        日线覆盖
                      </Typography.Text>
                      <Progress
                        percent={
                          coverage.data?.instrument_count
                            ? Math.round(
                                (coverage.data.instruments_with_data /
                                  coverage.data.instrument_count) *
                                  100,
                              )
                            : 0
                        }
                      />
                    </Col>
                    <Col xs={24} md={8}>
                      <Typography.Text type="secondary">
                        最新日线
                      </Typography.Text>
                      <Typography.Title level={4}>
                        {formatDateTime(overview.data?.latest_bar)}
                      </Typography.Title>
                    </Col>
                    <Col xs={24} md={8}>
                      <Typography.Text type="secondary">
                        最新分钟线
                      </Typography.Text>
                      <Typography.Title level={4}>
                        {formatDateTime(status.data?.latest_minute_bar_time)}
                      </Typography.Title>
                    </Col>
                  </Row>
                </Card>
                <Row gutter={[16, 16]}>
                  <Col xs={24} lg={9}>
                    {selector}
                  </Col>
                  <Col xs={24} lg={15}>
                    <Card title="研究功能就绪度">
                      <Table
                        rowKey="capability_key"
                        pagination={false}
                        dataSource={readiness.data ?? []}
                        columns={[
                          { title: "功能", dataIndex: "display_name" },
                          {
                            title: "状态",
                            dataIndex: "status",
                            render: (value: string) => (
                              <Tag color={statusColor(value)}>
                                {displayEnum(value)}
                              </Tag>
                            ),
                          },
                          {
                            title: "可用标的",
                            render: (_, item) =>
                              `${item.ready_instrument_count} / ${item.total_instrument_count}`,
                          },
                          { title: "说明", dataIndex: "reason" },
                        ]}
                      />
                    </Card>
                  </Col>
                </Row>
              </Space>
            ),
          },
          {
            key: "daily",
            label: "日线行情",
            children: (
              <Row gutter={[16, 16]}>
                <Col xs={24} lg={8}>
                  {selector}
                </Col>
                <Col xs={24} lg={16}>
                  <Card title="日线覆盖明细">
                    <Table
                      rowKey="instrument_id"
                      dataSource={coverage.data?.items ?? []}
                      pagination={{ pageSize: 20 }}
                      columns={[
                        {
                          title: "股票",
                          render: (_, item) =>
                            `${item.name}（${item.symbol}.${item.exchange === "SSE" ? "SH" : item.exchange === "SZSE" ? "SZ" : "BJ"}）`,
                        },
                        {
                          title: "K线数量",
                          dataIndex: "bar_count",
                          render: (value: number) => formatNumber(value),
                        },
                        {
                          title: "最早日期",
                          dataIndex: "earliest_bar",
                          render: formatDateTime,
                        },
                        {
                          title: "最新日期",
                          dataIndex: "latest_bar",
                          render: formatDateTime,
                        },
                        {
                          title: "状态",
                          render: (_, item) =>
                            item.missing_requirements.length ? (
                              <Tag color="orange">数据不足</Tag>
                            ) : (
                              <Tag color="green">可用</Tag>
                            ),
                        },
                      ]}
                    />
                  </Card>
                </Col>
              </Row>
            ),
          },
          {
            key: "minute",
            label: "分钟行情",
            children: (
              <Space
                orientation="vertical"
                size="large"
                style={{ width: "100%" }}
              >
                <Alert
                  showIcon
                  type="info"
                  title="分钟线已经并入统一数据中心"
                  description="MiniQMT 提供 1 分钟原始数据；系统生成 5、15、30、60 分钟聚合数据。实时快照和实时订阅请在“行情”页查看。"
                />
                <Row gutter={[16, 16]}>
                  <Col xs={24} lg={8}>
                    {selector}
                  </Col>
                  <Col xs={24} lg={16}>
                    <Card title="分钟线覆盖">
                      <Table
                        rowKey="timeframe"
                        pagination={false}
                        dataSource={intradayCoverage.data?.items ?? []}
                        columns={[
                          {
                            title: "周期",
                            dataIndex: "timeframe",
                            render: displayEnum,
                          },
                          {
                            title: "标的数",
                            dataIndex: "instrument_count",
                          },
                          {
                            title: "K线数量",
                            dataIndex: "bar_count",
                            render: (value: number) => formatNumber(value),
                          },
                          {
                            title: "数据范围",
                            render: (_, item) =>
                              `${formatDateTime(item.earliest_at)} 至 ${formatDateTime(item.latest_at)}`,
                          },
                          {
                            title: "完整交易日",
                            dataIndex: "complete_session_count",
                          },
                          {
                            title: "质量错误",
                            dataIndex: "quality_error_count",
                            render: (value: number) =>
                              value ? (
                                <Tag color="red">{value}</Tag>
                              ) : (
                                <Tag color="green">0</Tag>
                              ),
                          },
                        ]}
                      />
                    </Card>
                  </Col>
                </Row>
                <Row gutter={[16, 16]}>
                  <Col xs={12} lg={8}>
                    <Card>
                      <Statistic
                        title="当前订阅股票"
                        value={status.data?.active_count ?? 0}
                        suffix="只"
                      />
                    </Card>
                  </Col>
                  <Col xs={12} lg={8}>
                    <Card>
                      <Statistic
                        title="最新1分钟K线"
                        value={formatDateTime(
                          status.data?.latest_minute_bar_time,
                        )}
                      />
                    </Card>
                  </Col>
                  <Col xs={24} lg={8}>
                    <Card>
                      <Statistic
                        title="本地分钟K线"
                        value={minuteBars}
                        suffix="根"
                      />
                    </Card>
                  </Col>
                </Row>
                <Card title="分钟研究就绪度">
                  <Table
                    rowKey="capability_key"
                    pagination={false}
                    dataSource={intradayReadiness.data?.items ?? []}
                    columns={[
                      {
                        title: "研究能力",
                        dataIndex: "capability_key",
                        render: displayReadinessCapability,
                      },
                      {
                        title: "周期",
                        dataIndex: "timeframe",
                        render: displayEnum,
                      },
                      {
                        title: "状态",
                        dataIndex: "status",
                        render: (value: string) => (
                          <Tag color={statusColor(value)}>
                            {displayEnum(value)}
                          </Tag>
                        ),
                      },
                      { title: "需要处理", dataIndex: "required_action" },
                    ]}
                  />
                </Card>
                <Card
                  title="真实分钟K线预览"
                  extra={
                    <Segmented<MarketTimeframe>
                      value={previewTimeframe}
                      options={[
                        { label: "1分钟", value: "MINUTE_1" },
                        { label: "5分钟", value: "MINUTE_5" },
                        { label: "15分钟", value: "MINUTE_15" },
                        { label: "30分钟", value: "MINUTE_30" },
                        { label: "60分钟", value: "MINUTE_60" },
                      ]}
                      onChange={setPreviewTimeframe}
                    />
                  }
                >
                  <Typography.Paragraph type="secondary">
                    {effectiveInstrument
                      ? `${formatInstrument(effectiveInstrument)} · MiniQMT · ${displayEnum(previewTimeframe)}`
                      : "请先搜索并选择股票"}
                  </Typography.Paragraph>
                  <CandlestickChart
                    bars={minutePreview.data?.items ?? []}
                    loading={minutePreview.isLoading}
                  />
                </Card>
              </Space>
            ),
          },
          {
            key: "quality",
            label: "数据质量",
            children: (
              <Space
                orientation="vertical"
                size="large"
                style={{ width: "100%" }}
              >
                <Flex justify="space-between" align="center" wrap gap={12}>
                  <div>
                    <Typography.Title level={4}>
                      MiniQMT 数据质量检查
                    </Typography.Title>
                    <Typography.Text type="secondary">
                      检查缺口、异常价格、重复 K 线和研究所需的最低覆盖度。
                    </Typography.Text>
                  </div>
                  <Button
                    type="primary"
                    icon={<CheckCircleOutlined />}
                    loading={qualityCheck.isPending}
                    onClick={() => qualityCheck.mutate()}
                  >
                    立即检查日线数据
                  </Button>
                </Flex>
                <Card title="日线质量检查记录">
                  <Table
                    rowKey="id"
                    dataSource={qualityRuns.data?.items ?? []}
                    columns={[
                      {
                        title: "开始时间",
                        dataIndex: "started_at",
                        render: formatDateTime,
                      },
                      {
                        title: "状态",
                        dataIndex: "status",
                        render: (value: string) => (
                          <Tag color={statusColor(value)}>
                            {displayEnum(value)}
                          </Tag>
                        ),
                      },
                      { title: "检查标的", dataIndex: "instruments_checked" },
                      { title: "检查K线", dataIndex: "bars_checked" },
                      {
                        title: "错误",
                        dataIndex: "error_count",
                        render: (value: number) =>
                          value ? (
                            <Tag icon={<WarningOutlined />} color="red">
                              {value}
                            </Tag>
                          ) : (
                            "0"
                          ),
                      },
                      { title: "警告", dataIndex: "warning_count" },
                    ]}
                  />
                </Card>
                <Card title="分钟线质量检查记录">
                  <Table
                    rowKey="id"
                    dataSource={intradayQuality.data?.items ?? []}
                    columns={[
                      {
                        title: "开始时间",
                        dataIndex: "started_at",
                        render: formatDateTime,
                      },
                      {
                        title: "状态",
                        dataIndex: "status",
                        render: (value: string) => (
                          <Tag color={statusColor(value)}>
                            {displayEnum(value)}
                          </Tag>
                        ),
                      },
                      {
                        title: "周期",
                        dataIndex: "timeframe",
                        render: displayEnum,
                      },
                      { title: "发现问题", dataIndex: "issues_found" },
                    ]}
                  />
                </Card>
              </Space>
            ),
          },
          {
            key: "advanced",
            label: "高级数据管理",
            children: (
              <Space
                orientation="vertical"
                size="large"
                style={{ width: "100%" }}
              >
                <Alert
                  showIcon
                  type="info"
                  title="高级信息主要用于排查数据问题"
                  description="日常使用只需关注“总览”“历史日线”“历史分钟线”和“数据质量”。"
                />
                <Card title="市场语义数据">
                  {reference.data ? (
                    <Row gutter={[16, 16]}>
                      <Col xs={12} lg={6}>
                        <Statistic
                          title="交易日历"
                          value={reference.data.open_sessions}
                          suffix="日"
                        />
                      </Col>
                      <Col xs={12} lg={6}>
                        <Statistic
                          title="复权因子"
                          value={reference.data.adjustment_factors}
                        />
                      </Col>
                      <Col xs={12} lg={6}>
                        <Statistic
                          title="停复牌记录"
                          value={reference.data.trading_statuses}
                        />
                      </Col>
                      <Col xs={12} lg={6}>
                        <Statistic
                          title="标的生命周期"
                          value={reference.data.lifecycle_events}
                        />
                      </Col>
                    </Row>
                  ) : (
                    <Empty description="暂无市场语义数据" />
                  )}
                </Card>
                <Card title="MiniQMT 历史写入记录">
                  <Table
                    rowKey="id"
                    dataSource={[
                      ...(syncRuns.data ?? []),
                      ...(intradayImports.data?.items ?? []),
                    ]}
                    pagination={{ pageSize: 20 }}
                    columns={[
                      {
                        title: "开始时间",
                        dataIndex: "started_at",
                        render: formatDateTime,
                      },
                      {
                        title: "周期",
                        dataIndex: "timeframe",
                        render: displayEnum,
                      },
                      {
                        title: "状态",
                        dataIndex: "status",
                        render: (value: string) => (
                          <Tag color={statusColor(value)}>
                            {displayEnum(value)}
                          </Tag>
                        ),
                      },
                      { title: "接收", dataIndex: "total_received" },
                      { title: "新增", dataIndex: "total_inserted" },
                      { title: "更新", dataIndex: "total_updated" },
                      { title: "拒绝", dataIndex: "total_rejected" },
                    ]}
                  />
                </Card>
              </Space>
            ),
          },
        ]}
      />
    </div>
  );
}
