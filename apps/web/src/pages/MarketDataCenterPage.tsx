import {
  CheckCircleOutlined,
  DatabaseOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Checkbox,
  Col,
  Descriptions,
  Flex,
  Input,
  InputNumber,
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
import { useNavigate } from "react-router-dom";

import {
  getMarketDataCoverage,
  getMarketDataOverview,
  getMarketDataReadiness,
  getMarketReferenceStatus,
  getMarketSyncRuns,
  getQualityRun,
  getQualityRuns,
  updateDailyMarketData,
  syncMarketReference,
  verifyMarketDataQuality,
} from "../api/market";
import { PageHeader } from "../components/PageHeader/PageHeader";
import type {
  InstrumentCoverage,
  MarketDataQualityIssue,
  MarketDataQualityRun,
  MarketSyncRun,
  QualitySeverity,
  ReadinessCapability,
} from "../types/market";
import { displayEnum, formatDateTime, shortId } from "../utils/display";

const readinessColors: Record<string, string> = {
  READY: "success",
  PARTIAL: "warning",
  NOT_READY: "error",
  UNKNOWN: "default",
};

const syncLabels: Record<string, string> = {
  RUNNING: "运行中",
  SUCCEEDED: "全部完成",
  PARTIALLY_SUCCEEDED: "部分失败",
  FAILED: "失败",
  CANCELLED: "已取消",
};

function dateText(value: string | null) {
  return value ? new Date(value).toLocaleDateString("zh-CN") : "—";
}

function count(metadata: Record<string, unknown>, key: string) {
  const value = metadata[key];
  return typeof value === "number" ? value : 0;
}

function operationLabel(metadata: Record<string, unknown>) {
  const value = metadata.operation;
  return displayEnum(typeof value === "string" ? value : "HISTORICAL_SYNC");
}

export function MarketDataCenterPage() {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [targetDate, setTargetDate] = useState("");
  const [maxInstruments, setMaxInstruments] = useState(30);
  const [continueOnError, setContinueOnError] = useState(true);
  const [referenceDryRun, setReferenceDryRun] = useState(true);
  const [selectedQualityRun, setSelectedQualityRun] = useState<string>();
  const [severity, setSeverity] = useState<QualitySeverity | undefined>();
  const [issueType, setIssueType] = useState("");

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
  const referenceStatus = useQuery({
    queryKey: ["market-reference-status"],
    queryFn: getMarketReferenceStatus,
  });
  const syncRuns = useQuery({
    queryKey: ["market-sync-runs"],
    queryFn: getMarketSyncRuns,
  });
  const qualityRuns = useQuery({
    queryKey: ["market-quality-runs"],
    queryFn: () => getQualityRuns(1),
  });
  const effectiveQualityRun =
    selectedQualityRun ?? qualityRuns.data?.items[0]?.id;
  const qualityDetail = useQuery({
    queryKey: ["market-quality-run", effectiveQualityRun, severity, issueType],
    queryFn: () =>
      getQualityRun(effectiveQualityRun ?? "", {
        severity,
        issue_type: issueType.trim() || undefined,
      }),
    enabled: Boolean(effectiveQualityRun),
  });

  const refreshAll = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["market-data-overview"] }),
      queryClient.invalidateQueries({ queryKey: ["market-data-coverage"] }),
      queryClient.invalidateQueries({ queryKey: ["market-data-readiness"] }),
      queryClient.invalidateQueries({ queryKey: ["market-sync-runs"] }),
      queryClient.invalidateQueries({ queryKey: ["market-quality-runs"] }),
      queryClient.invalidateQueries({ queryKey: ["market-reference-status"] }),
    ]);
  };
  const dailyUpdate = useMutation({
    mutationFn: (dryRun: boolean) =>
      updateDailyMarketData({
        target_date: targetDate || null,
        max_instruments: maxInstruments,
        dry_run: dryRun,
        continue_on_error: continueOnError,
      }),
    onSuccess: async (result) => {
      await refreshAll();
      if (result.dry_run) {
        void message.info(`预览完成：${result.requested} 只股票`);
      } else if (result.failed > 0) {
        void message.warning(
          `更新部分失败：成功 ${result.completed}，失败 ${result.failed}`,
        );
      } else {
        void message.success(`更新完成：新增 ${result.bars_inserted} 根日线`);
      }
    },
    onError: (error: Error) => void message.error(error.message),
  });
  const qualityCheck = useMutation({
    mutationFn: verifyMarketDataQuality,
    onSuccess: async (result) => {
      setSelectedQualityRun(result.run.id);
      await refreshAll();
      void message.success(
        `质量检查完成：错误 ${result.run.error_count}，警告 ${result.run.warning_count}`,
      );
    },
    onError: (error: Error) => void message.error(error.message),
  });
  const referenceSync = useMutation({
    mutationFn: (kind: Parameters<typeof syncMarketReference>[0]) =>
      syncMarketReference(kind, referenceDryRun),
    onSuccess: async (result) => {
      await refreshAll();
      void message.success(
        `${result.kind} ${result.dry_run ? "预览" : "同步"}完成：接收 ${result.received}，写入 ${result.persisted}`,
      );
    },
    onError: (error: Error) => void message.error(error.message),
  });

  const insufficient = useMemo(
    () =>
      coverage.data?.items.filter((item) => item.missing_requirements.length) ??
      [],
    [coverage.data],
  );

  return (
    <section className="market-data-center-page">
      <PageHeader
        title="历史行情数据中心"
        description="维护 BaoStock A 股日线、检查数据质量，并判断研究功能是否具备数据条件。"
        action={
          <Button icon={<ReloadOutlined />} onClick={() => void refreshAll()}>
            刷新数据状态
          </Button>
        }
      />
      <Alert
        showIcon
        type="warning"
        title="仅维护历史日线，不提供实时行情，也不连接 MiniQMT"
        description="增量更新是同步长耗时请求，大规模操作受服务端上限限制。请勿重复提交。"
        style={{ marginBottom: 16 }}
      />

      <Card title="1. 数据总览" loading={overview.isLoading}>
        <Row gutter={[16, 16]}>
          <Col xs={12} md={6}>
            <Statistic
              title="活跃 A 股"
              value={overview.data?.active_a_share_count ?? 0}
            />
          </Col>
          <Col xs={12} md={6}>
            <Statistic
              title="研究池股票"
              value={overview.data?.research_universe_count ?? 0}
            />
          </Col>
          <Col xs={12} md={6}>
            <Statistic
              title="研究池日线"
              value={overview.data?.market_bar_count ?? 0}
            />
          </Col>
          <Col xs={12} md={6}>
            <Statistic
              title="最新行情日"
              value={dateText(overview.data?.latest_bar ?? null)}
            />
          </Col>
        </Row>
        <Descriptions
          size="small"
          column={{ xs: 1, md: 3 }}
          style={{ marginTop: 16 }}
        >
          <Descriptions.Item label="数据提供方（Provider）">
            {overview.data?.provider ?? "—"}
          </Descriptions.Item>
          <Descriptions.Item label="周期 / 复权">
            {overview.data
              ? `${displayEnum(overview.data.timeframe)} / ${displayEnum(overview.data.adjustment_type)}`
              : "—"}
          </Descriptions.Item>
          <Descriptions.Item label="覆盖范围">{`${dateText(overview.data?.earliest_bar ?? null)} — ${dateText(overview.data?.latest_bar ?? null)}`}</Descriptions.Item>
          <Descriptions.Item label="条件扫描器">
            <Tag color={overview.data?.scanner_ready ? "success" : "warning"}>
              {overview.data?.scanner_ready ? "可用" : "部分可用或不可用"}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="策略研究">
            <Tag color={overview.data?.strategy_ready ? "success" : "warning"}>
              {overview.data?.strategy_ready ? "可用" : "部分可用或不可用"}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="日线回测（BT01）">
            <Tag
              color={overview.data?.backtest_data_ready ? "success" : "warning"}
            >
              数据{overview.data?.backtest_data_ready ? "可用" : "不可用"} ·
              功能已实现
            </Tag>
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title="2. 市场参考数据与价格语义" style={{ marginTop: 16 }}>
        <Alert
          showIcon
          type="info"
          title="不复权价格（RAW）是成交、成交记录（Fill）、费用与账本的权威价格"
          description="前复权价格（QFQ）仅供技术指标、趋势策略和长期研究使用；涨跌停识别与模拟成交始终读取不复权价格。"
          style={{ marginBottom: 16 }}
        />
        <Flex wrap gap={12} align="center" style={{ marginBottom: 16 }}>
          <Checkbox
            checked={referenceDryRun}
            onChange={(event) => setReferenceDryRun(event.target.checked)}
          >
            试运行预览（Dry-run，不写数据库）
          </Checkbox>
          <Typography.Text type="secondary">
            数据提供方：测试数据（Fixture，离线且结果确定）；Tushare
            未配置时不会联网。
          </Typography.Text>
        </Flex>
        <Tabs
          items={[
            {
              key: "calendar",
              label: "交易日历",
              children: (
                <Descriptions size="small" column={{ xs: 1, md: 3 }}>
                  <Descriptions.Item label="交易所">
                    SHSE / SZSE
                  </Descriptions.Item>
                  <Descriptions.Item label="覆盖日期">
                    {`${referenceStatus.data?.calendar_start ?? "—"} — ${referenceStatus.data?.calendar_end ?? "—"}`}
                  </Descriptions.Item>
                  <Descriptions.Item label="开放日 / 全部">
                    {referenceStatus.data
                      ? `${referenceStatus.data.open_sessions} / ${referenceStatus.data.calendar_sessions}`
                      : "—"}
                  </Descriptions.Item>
                  <Descriptions.Item label="最新已完成交易日">
                    {referenceStatus.data?.latest_completed_session ?? "—"}
                  </Descriptions.Item>
                  <Descriptions.Item label="状态">
                    <Tag
                      color={
                        referenceStatus.data?.calendar_ready
                          ? "success"
                          : "warning"
                      }
                    >
                      {referenceStatus.data?.calendar_ready ? "可用" : "缺失"}
                    </Tag>
                  </Descriptions.Item>
                  <Descriptions.Item label="操作">
                    <Button
                      loading={referenceSync.isPending}
                      onClick={() => referenceSync.mutate("calendar")}
                    >
                      同步交易日历
                    </Button>
                  </Descriptions.Item>
                </Descriptions>
              ),
            },
            {
              key: "adjustments",
              label: "复权因子",
              children: (
                <Descriptions size="small" column={{ xs: 1, md: 3 }}>
                  <Descriptions.Item label="覆盖股票">
                    {referenceStatus.data?.adjustment_instruments ?? 0}
                  </Descriptions.Item>
                  <Descriptions.Item label="因子记录">
                    {referenceStatus.data?.adjustment_factors ?? 0}
                  </Descriptions.Item>
                  <Descriptions.Item label="最新因子日期">
                    {referenceStatus.data?.latest_factor_date ?? "—"}
                  </Descriptions.Item>
                  <Descriptions.Item label="前复权（QFQ）可用股票">
                    {referenceStatus.data?.qfq_ready_instruments ?? 0}
                  </Descriptions.Item>
                  <Descriptions.Item label="状态">
                    <Tag
                      color={
                        referenceStatus.data?.adjusted_price_ready
                          ? "success"
                          : "warning"
                      }
                    >
                      {referenceStatus.data?.adjusted_price_ready
                        ? "可用"
                        : "缺失"}
                    </Tag>
                  </Descriptions.Item>
                  <Descriptions.Item label="操作">
                    <Button
                      loading={referenceSync.isPending}
                      onClick={() => referenceSync.mutate("adjustments")}
                    >
                      同步复权因子
                    </Button>
                  </Descriptions.Item>
                </Descriptions>
              ),
            },
            {
              key: "suspensions",
              label: "停复牌",
              children: (
                <Descriptions size="small" column={{ xs: 1, md: 3 }}>
                  <Descriptions.Item label="状态记录">
                    {referenceStatus.data?.trading_statuses ?? 0}
                  </Descriptions.Item>
                  <Descriptions.Item label="已知停牌日">
                    {referenceStatus.data?.suspended_sessions ?? 0}
                  </Descriptions.Item>
                  <Descriptions.Item label="最新状态日期">
                    {referenceStatus.data?.latest_status_date ?? "—"}
                  </Descriptions.Item>
                  <Descriptions.Item label="兼容规则">
                    缺少状态时附 WARNING，不猜测为停牌
                  </Descriptions.Item>
                  <Descriptions.Item label="操作">
                    <Button
                      loading={referenceSync.isPending}
                      onClick={() => referenceSync.mutate("suspensions")}
                    >
                      同步停复牌
                    </Button>
                  </Descriptions.Item>
                </Descriptions>
              ),
            },
            {
              key: "lifecycle",
              label: "标的生命周期（Instrument）",
              children: (
                <Descriptions size="small" column={{ xs: 1, md: 3 }}>
                  <Descriptions.Item label="生命周期事件">
                    {referenceStatus.data?.lifecycle_events ?? 0}
                  </Descriptions.Item>
                  <Descriptions.Item label="覆盖股票">
                    {referenceStatus.data?.lifecycle_instruments ?? 0}
                  </Descriptions.Item>
                  <Descriptions.Item label="历史语义">
                    上市前、退市后不期待 K 线；inactive 仍可历史研究
                  </Descriptions.Item>
                  <Descriptions.Item label="操作">
                    <Button
                      loading={referenceSync.isPending}
                      onClick={() =>
                        referenceSync.mutate("instrument-lifecycle")
                      }
                    >
                      同步生命周期
                    </Button>
                  </Descriptions.Item>
                </Descriptions>
              ),
            },
            {
              key: "readiness",
              label: "数据语义与可用性（Readiness）",
              children: (
                <Space orientation="vertical" style={{ width: "100%" }}>
                  <Space wrap>
                    {[
                      [
                        "不复权价格（RAW）",
                        referenceStatus.data?.raw_price_ready,
                      ],
                      [
                        "前复权价格（QFQ）",
                        referenceStatus.data?.adjusted_price_ready,
                      ],
                      ["交易日历", referenceStatus.data?.calendar_ready],
                      ["停复牌数据", referenceStatus.data?.suspension_ready],
                      ["条件扫描", referenceStatus.data?.scanner_ready],
                      ["策略研究", referenceStatus.data?.strategy_ready],
                      ["日线回测", referenceStatus.data?.backtest_ready],
                      ["行情回放", referenceStatus.data?.replay_ready],
                    ].map(([label, ready]) => (
                      <Tag
                        key={String(label)}
                        color={ready ? "success" : "warning"}
                      >
                        {String(label)}：{ready ? "可用" : "不可用"}
                      </Tag>
                    ))}
                  </Space>
                  {(referenceStatus.data?.warnings ?? []).map((warning) => (
                    <Alert
                      key={warning}
                      type="warning"
                      showIcon
                      title={warning}
                    />
                  ))}
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Card title="3. 股票池（Universe）覆盖情况" style={{ marginTop: 16 }}>
        <Descriptions size="small" column={{ xs: 1, md: 4 }}>
          <Descriptions.Item label="股票池（Universe）">
            {coverage.data?.name ?? "research"}
          </Descriptions.Item>
          <Descriptions.Item label="有行情">
            {coverage.data?.instruments_with_data ?? 0} /{" "}
            {coverage.data?.instrument_count ?? 0}
          </Descriptions.Item>
          <Descriptions.Item label="数据充足">
            {coverage.data?.sufficient_instruments ?? 0}
          </Descriptions.Item>
          <Descriptions.Item label="数据不足">
            {coverage.data?.insufficient_instruments ?? 0}
          </Descriptions.Item>
        </Descriptions>
        <Table<InstrumentCoverage>
          rowKey="instrument_id"
          size="small"
          loading={coverage.isLoading}
          dataSource={insufficient}
          pagination={{ pageSize: 10 }}
          scroll={{ x: 850 }}
          locale={{ emptyText: "当前没有数据不足标的" }}
          columns={[
            { title: "代码", dataIndex: "symbol" },
            { title: "名称", dataIndex: "name" },
            { title: "交易所", dataIndex: "exchange" },
            { title: "K线数", dataIndex: "bar_count" },
            { title: "最早", render: (_, item) => dateText(item.earliest_bar) },
            { title: "最新", render: (_, item) => dateText(item.latest_bar) },
            {
              title: "标的映射",
              render: (_, item) => (
                <Tag
                  color={item.mapping_status === "MAPPED" ? "success" : "error"}
                >
                  {item.mapping_status === "MAPPED" ? "已映射" : "未映射"}
                </Tag>
              ),
            },
            {
              title: "缺少要求",
              render: (_, item) => item.missing_requirements.join("、") || "—",
            },
          ]}
        />
      </Card>

      <Card title="4. 同步运行与每日更新" style={{ marginTop: 16 }}>
        <Flex wrap gap={12} align="center" style={{ marginBottom: 16 }}>
          <Select
            value="baostock"
            style={{ width: 140 }}
            disabled
            options={[{ value: "baostock", label: "BaoStock" }]}
          />
          <Select
            value="research"
            style={{ width: 180 }}
            disabled
            options={[{ value: "research", label: "研究股票池" }]}
          />
          <Input
            aria-label="目标日期"
            type="date"
            value={targetDate}
            onChange={(event) => setTargetDate(event.target.value)}
            style={{ width: 160 }}
          />
          <InputNumber
            aria-label="最大股票数"
            min={1}
            max={500}
            value={maxInstruments}
            onChange={(value) => setMaxInstruments(value ?? 30)}
          />
          <Checkbox
            checked={continueOnError}
            onChange={(event) => setContinueOnError(event.target.checked)}
          >
            单只失败后继续
          </Checkbox>
          <Button
            disabled={dailyUpdate.isPending}
            onClick={() => dailyUpdate.mutate(true)}
          >
            试运行预览（Dry-run）
          </Button>
          <Button
            type="primary"
            loading={dailyUpdate.isPending}
            disabled={dailyUpdate.isPending}
            icon={<DatabaseOutlined />}
            onClick={() => dailyUpdate.mutate(false)}
          >
            更新到最新日线
          </Button>
        </Flex>
        {dailyUpdate.isPending ? (
          <Alert
            type="info"
            showIcon
            title="正在同步执行，请勿重复提交"
            description="第一版没有后台进度流，完成后页面会自动刷新实际统计。"
            style={{ marginBottom: 12 }}
          />
        ) : null}
        {dailyUpdate.data ? (
          <Alert
            type={dailyUpdate.data.failed ? "warning" : "success"}
            showIcon
            title={
              dailyUpdate.data.dry_run
                ? "更新预览"
                : dailyUpdate.data.failed
                  ? "部分失败"
                  : "更新完成"
            }
            description={`请求 ${dailyUpdate.data.requested}，已最新 ${dailyUpdate.data.up_to_date}，完成 ${dailyUpdate.data.completed}，失败 ${dailyUpdate.data.failed}，新增 ${dailyUpdate.data.bars_inserted}`}
            style={{ marginBottom: 12 }}
          />
        ) : null}
        <Table<MarketSyncRun>
          rowKey="id"
          size="small"
          loading={syncRuns.isLoading}
          dataSource={syncRuns.data ?? []}
          pagination={{ pageSize: 10 }}
          scroll={{ x: 1300 }}
          columns={[
            {
              title: "运行记录",
              render: (_, item) => (
                <Typography.Text code>{shortId(item.id)}</Typography.Text>
              ),
            },
            {
              title: "操作",
              render: (_, item) => operationLabel(item.metadata),
            },
            {
              title: "状态",
              render: (_, item) => (
                <Tag
                  color={
                    item.status === "SUCCEEDED"
                      ? "success"
                      : item.status === "PARTIALLY_SUCCEEDED"
                        ? "warning"
                        : item.status === "FAILED"
                          ? "error"
                          : "processing"
                  }
                >
                  {syncLabels[item.status]}
                </Tag>
              ),
            },
            {
              title: "请求",
              render: (_, item) => item.requested_symbols.length,
            },
            {
              title: "已最新",
              render: (_, item) =>
                count(item.metadata, "up_to_date_instrument_count"),
            },
            {
              title: "成功",
              render: (_, item) =>
                count(item.metadata, "completed_instrument_count") ||
                count(item.metadata, "succeeded_instrument_count"),
            },
            {
              title: "失败",
              render: (_, item) =>
                count(item.metadata, "failed_instrument_count"),
            },
            { title: "获取数量", dataIndex: "total_received" },
            { title: "新增数量", dataIndex: "total_inserted" },
            { title: "更新数量", dataIndex: "total_updated" },
            { title: "无效数量", dataIndex: "total_rejected" },
            {
              title: "开始",
              render: (_, item) => formatDateTime(item.started_at),
            },
            { title: "错误", dataIndex: "error_summary" },
          ]}
        />
      </Card>

      <Card title="5. 数据质量" style={{ marginTop: 16 }}>
        <Space wrap style={{ marginBottom: 16 }}>
          <Button
            icon={<SafetyCertificateOutlined />}
            type="primary"
            loading={qualityCheck.isPending}
            disabled={qualityCheck.isPending}
            onClick={() => qualityCheck.mutate()}
          >
            执行数据质量检查
          </Button>
          <Select
            allowClear
            placeholder="严重程度"
            value={severity}
            onChange={setSeverity}
            style={{ width: 140 }}
            options={["ERROR", "WARNING", "INFO"].map((value) => ({
              value,
              label: displayEnum(value),
            }))}
          />
          <Input.Search
            placeholder="问题类型"
            allowClear
            value={issueType}
            onChange={(event) => setIssueType(event.target.value)}
            style={{ width: 220 }}
          />
        </Space>
        <Table<MarketDataQualityRun>
          rowKey="id"
          size="small"
          dataSource={qualityRuns.data?.items ?? []}
          pagination={false}
          onRow={(item) => ({ onClick: () => setSelectedQualityRun(item.id) })}
          columns={[
            {
              title: "检查记录",
              render: (_, item) => (
                <Typography.Text code>{shortId(item.id)}</Typography.Text>
              ),
            },
            { title: "状态", dataIndex: "status" },
            { title: "股票", dataIndex: "instruments_checked" },
            { title: "K线", dataIndex: "bars_checked" },
            { title: "错误", dataIndex: "error_count" },
            { title: "警告", dataIndex: "warning_count" },
            { title: "提示", dataIndex: "info_count" },
          ]}
        />
        {qualityDetail.data?.integrity_mismatches.length ? (
          <Alert
            type="error"
            title="质量运行完整性不一致"
            description={qualityDetail.data.integrity_mismatches.join("、")}
          />
        ) : null}
        <Table<MarketDataQualityIssue>
          rowKey="id"
          size="small"
          loading={qualityDetail.isFetching}
          dataSource={qualityDetail.data?.issues ?? []}
          pagination={{ pageSize: 10 }}
          scroll={{ x: 1100 }}
          columns={[
            {
              title: "严重程度",
              render: (_, item) => (
                <Tag
                  color={
                    item.severity === "ERROR"
                      ? "error"
                      : item.severity === "WARNING"
                        ? "warning"
                        : "default"
                  }
                >
                  {displayEnum(item.severity)}
                </Tag>
              ),
            },
            {
              title: "问题类型",
              render: (_, item) => displayEnum(item.issue_type),
            },
            {
              title: "内部标的编号",
              render: (_, item) => shortId(item.instrument_id),
            },
            {
              title: "时间范围",
              render: (_, item) =>
                `${dateText(item.first_affected_at)} — ${dateText(item.last_affected_at)}`,
            },
            { title: "说明", dataIndex: "message" },
            { title: "建议操作", dataIndex: "required_action" },
          ]}
        />
      </Card>

      <Card title="6. 功能可用性" style={{ marginTop: 16 }}>
        <Table<ReadinessCapability>
          rowKey="capability_key"
          size="small"
          loading={readiness.isLoading}
          dataSource={readiness.data ?? []}
          pagination={false}
          scroll={{ x: 1000 }}
          columns={[
            { title: "功能", dataIndex: "display_name" },
            {
              title: "状态",
              render: (_, item) => (
                <Tag
                  color={readinessColors[item.status]}
                  icon={
                    item.status === "READY" ? (
                      <CheckCircleOutlined />
                    ) : undefined
                  }
                >
                  {displayEnum(item.status)}
                </Tag>
              ),
            },
            {
              title: "可用股票",
              render: (_, item) =>
                `${item.ready_instrument_count}/${item.total_instrument_count}`,
            },
            {
              title: "最低要求",
              render: (_, item) => `${item.minimum_bars_required} 根`,
            },
            { title: "最新数据", dataIndex: "latest_data_date" },
            { title: "原因", dataIndex: "reason" },
            { title: "建议操作", dataIndex: "required_action" },
            {
              title: "跳转",
              render: (_, item) =>
                item.capability_key.startsWith("scanner") ? (
                  <Button
                    type="link"
                    onClick={() => void navigate("/scanners")}
                  >
                    条件扫描
                  </Button>
                ) : item.capability_key.startsWith("strategy") ? (
                  <Button
                    type="link"
                    onClick={() => void navigate("/strategies")}
                  >
                    策略研究
                  </Button>
                ) : item.capability_key === "backtest_daily" ? (
                  <Button
                    type="link"
                    onClick={() => void navigate("/backtest")}
                  >
                    日线回测
                  </Button>
                ) : (
                  <Typography.Text type="secondary">—</Typography.Text>
                ),
            },
          ]}
        />
        <Alert
          type="success"
          showIcon
          title="BT01 日线回测代码已完成"
          description="能否运行取决于所选标的、时间范围和 D01 数据状态；分钟与 Tick 回测仍未实现。"
          style={{ marginTop: 12 }}
        />
      </Card>
    </section>
  );
}
