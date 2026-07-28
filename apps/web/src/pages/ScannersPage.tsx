import { FilterOutlined, ReloadOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Collapse,
  Descriptions,
  Empty,
  Input,
  Progress,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from "antd";
import { useEffect, useRef, useState } from "react";

import { getScannerSessionDefault } from "../api/scanners";
import {
  createScreening,
  getScreening,
  getScreeningConditions,
  getScreeningProgress,
  getScreeningResults,
  parseScreeningText,
  previewScreeningSpec,
  validateScreeningSpec,
} from "../api/screenings";
import { PageHeader } from "../components/PageHeader/PageHeader";
import { VisualScreeningEditor } from "../components/ScreeningBuilder/VisualScreeningEditor";
import type {
  ScreeningParseResult,
  ScreeningPreview,
  ScreeningResult,
  ScreeningSpecSnapshot,
  ScreeningStatus,
} from "../types/screenings";

const terminalStatuses = new Set<ScreeningStatus>([
  "COMPLETED",
  "PARTIAL_FAILED",
  "FAILED",
  "CANCELED",
]);

const statusText: Record<ScreeningStatus, string> = {
  CREATED: "已创建",
  QUEUED: "等待后台处理",
  RESOLVING: "正在还原筛选日股票范围",
  CHECKING_DATA: "正在检查历史数据",
  BACKFILLING: "正在补齐历史数据",
  RUNNING: "正在筛选全部A股",
  COMPLETED: "已完成",
  PARTIAL_FAILED: "部分股票无法判定",
  FAILED: "运行失败",
  CANCELED: "已取消",
};

const statusColor: Record<ScreeningStatus, string> = {
  CREATED: "default",
  QUEUED: "processing",
  RESOLVING: "processing",
  CHECKING_DATA: "processing",
  BACKFILLING: "processing",
  RUNNING: "processing",
  COMPLETED: "success",
  PARTIAL_FAILED: "warning",
  FAILED: "error",
  CANCELED: "default",
};

const parseStatusText = {
  COMPLETE: "条件已识别，可以确认",
  PARTIAL: "只识别了部分条件",
  AMBIGUOUS: "需要确认几个参数",
  UNSUPPORTED: "当前条件暂不支持",
} as const;

function instrumentText(result: ScreeningResult) {
  const exchange =
    result.exchange === "SSE"
      ? "SH"
      : result.exchange === "SZSE"
        ? "SZ"
        : result.exchange;
  return `${result.instrument_name}（${result.symbol}.${exchange}）`;
}

function requestKey() {
  const random =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `screening:${random}`;
}

function TextList({
  items,
  numbered = false,
}: {
  items: string[];
  numbered?: boolean;
}) {
  return (
    <ul style={{ margin: 0, paddingInlineStart: 22 }}>
      {items.map((item, index) => (
        <li key={`${index}-${item}`}>
          {numbered ? `${index + 1}. ` : null}
          {item}
        </li>
      ))}
    </ul>
  );
}

function PreviewCard({ preview }: { preview: ScreeningPreview }) {
  return (
    <Card title="中文规则预览">
      <Descriptions
        column={{ xs: 1, lg: 2 }}
        items={[
          { key: "universe", label: "股票范围", children: preview.universe },
          {
            key: "date",
            label: "筛选时间",
            children: preview.screening_time,
          },
          {
            key: "source",
            label: "解析来源",
            children: preview.parser_source,
          },
          {
            key: "ready",
            label: "数据状态",
            children: (
              <Tag color={preview.data_ready ? "success" : "warning"}>
                {preview.data_ready ? "可以执行" : "尚未就绪"}
              </Tag>
            ),
          },
        ]}
      />
      <Typography.Title level={5}>筛选条件</Typography.Title>
      <TextList items={preview.conditions} numbered />
      {preview.ranking.length ? (
        <>
          <Typography.Title level={5}>结果排序</Typography.Title>
          <TextList items={preview.ranking} />
        </>
      ) : null}
      <Alert
        type={preview.data_ready ? "success" : "warning"}
        showIcon
        title={preview.data_readiness_message}
        description={preview.no_future_data_rule}
        style={{ marginTop: 12 }}
      />
      {preview.defaults.length ? (
        <Alert
          type="info"
          showIcon
          title="系统使用的默认解释"
          description={<TextList items={preview.defaults} />}
          style={{ marginTop: 12 }}
        />
      ) : null}
      {preview.notices.map((notice) => (
        <Alert
          key={notice}
          type="info"
          showIcon
          title={notice}
          style={{ marginTop: 12 }}
        />
      ))}
      <Collapse
        ghost
        style={{ marginTop: 8 }}
        items={[
          {
            key: "requirements",
            label: "数据要求与诊断信息",
            children: (
              <>
                <TextList items={preview.data_requirements} />
                <Typography.Paragraph type="secondary">
                  规则来源：{preview.parser_source}
                  。本页不会执行用户代码，也不会创建订单或成交。
                </Typography.Paragraph>
              </>
            ),
          },
        ]}
      />
    </Card>
  );
}

export function ScannersPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const progressAnchor = useRef<HTMLDivElement>(null);
  const previewTimer = useRef<number | undefined>(undefined);
  const idempotencyKey = useRef(requestKey());
  const submissionLock = useRef(false);
  const [text, setText] = useState("");
  const [asOfDate, setAsOfDate] = useState("");
  const [parseResult, setParseResult] = useState<ScreeningParseResult>();
  const [draftSpec, setDraftSpec] = useState<ScreeningSpecSnapshot>();
  const [preview, setPreview] = useState<ScreeningPreview>();
  const [activeId, setActiveId] = useState<string>();

  const sessionDefault = useQuery({
    queryKey: ["scanner-session-default"],
    queryFn: getScannerSessionDefault,
  });
  const definitions = useQuery({
    queryKey: ["screening-conditions"],
    queryFn: getScreeningConditions,
  });
  const resolvedAsOfDate = asOfDate || sessionDefault.data?.scan_date || "";

  useEffect(
    () => () => {
      if (previewTimer.current !== undefined) {
        window.clearTimeout(previewTimer.current);
      }
    },
    [],
  );

  const parseMutation = useMutation({
    mutationFn: parseScreeningText,
    onSuccess: (result) => {
      setParseResult(result);
      setDraftSpec(result.screening_spec ?? undefined);
      setPreview(result.preview ?? undefined);
      idempotencyKey.current = requestKey();
      if (result.parse_status === "COMPLETE") {
        void message.success("已识别选股条件，请检查中文预览和参数");
      }
    },
    onError: (error: Error) => void message.error(error.message),
  });

  const previewMutation = useMutation({
    mutationFn: previewScreeningSpec,
    onSuccess: (result) => setPreview(result.preview),
    onError: (error: Error) => void message.error(error.message),
  });

  const active = useQuery({
    queryKey: ["screening", activeId],
    queryFn: () => getScreening(activeId as string),
    enabled: Boolean(activeId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && terminalStatuses.has(status) ? false : 2_000;
    },
  });
  const progress = useQuery({
    queryKey: ["screening-progress", activeId],
    queryFn: () => getScreeningProgress(activeId as string),
    enabled: Boolean(activeId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && terminalStatuses.has(status) ? false : 2_000;
    },
  });
  const results = useQuery({
    queryKey: ["screening-results", activeId],
    queryFn: () => getScreeningResults(activeId as string),
    enabled: Boolean(activeId) && Boolean(active.data),
    refetchInterval:
      active.data && !terminalStatuses.has(active.data.status) ? 3_000 : false,
  });

  const createMutation = useMutation({
    mutationFn: createScreening,
    onSuccess: async (run) => {
      setActiveId(run.screening_id);
      await queryClient.invalidateQueries({ queryKey: ["screenings"] });
      void message.success(
        run.replayed ? "已打开相同的选股任务" : "选股任务已进入后台队列",
      );
      window.setTimeout(
        () => progressAnchor.current?.scrollIntoView?.({ behavior: "smooth" }),
        50,
      );
    },
    onError: (error: Error) => void message.error(error.message),
    onSettled: () => {
      submissionLock.current = false;
    },
  });

  const parse = () => {
    if (!text.trim()) {
      void message.warning("请先用中文描述选股条件");
      return;
    }
    if (!resolvedAsOfDate) {
      void message.warning("请选择筛选日期");
      return;
    }
    parseMutation.mutate({
      text,
      as_of_date: resolvedAsOfDate,
      universe: {
        universe_key: "ALL_A_SHARES",
        excluded_instrument_ids: [],
        exclude_st: false,
        exclude_bse: false,
        exclude_star_market: false,
        exclude_chinext: false,
      },
      allow_ai_assistance: true,
    });
  };

  const updateDraft = (next: ScreeningSpecSnapshot) => {
    setDraftSpec(next);
    idempotencyKey.current = requestKey();
    if (previewTimer.current !== undefined) {
      window.clearTimeout(previewTimer.current);
    }
    previewTimer.current = window.setTimeout(
      () => previewMutation.mutate(next),
      250,
    );
  };

  const start = async () => {
    if (!draftSpec || createMutation.isPending || submissionLock.current)
      return;
    submissionLock.current = true;
    try {
      const validated = await validateScreeningSpec(draftSpec);
      setDraftSpec(validated.screening_spec);
      setPreview(validated.preview);
      if (!validated.can_execute) {
        void message.error("本地历史日线尚未就绪，暂时不能开始选股");
        submissionLock.current = false;
        return;
      }
      createMutation.mutate({
        ...validated.screening_spec,
        conditions: validated.screening_spec.conditions.map((condition) => ({
          condition_key: condition.condition_key,
          parameters: condition.parameters,
        })),
        idempotency_key: idempotencyKey.current,
      });
    } catch (error) {
      submissionLock.current = false;
      void message.error(
        error instanceof Error ? error.message : "选股条件校验失败",
      );
    }
  };

  const current = progress.data ?? active.data;
  return (
    <section>
      <PageHeader
        title="智能选股"
        description="用中文描述条件，系统会匹配标准规则、生成可读预览，并使用本地MiniQMT历史日线筛选全部A股。"
        action={
          <Button
            icon={<ReloadOutlined />}
            onClick={() => {
              void sessionDefault.refetch();
              void definitions.refetch();
              if (activeId) {
                void active.refetch();
                void progress.refetch();
                void results.refetch();
              }
            }}
          >
            刷新
          </Button>
        }
      />

      <Card title="自然语言选股">
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={8}>
            <Typography.Text strong>股票范围</Typography.Text>
            <Select
              aria-label="股票范围"
              value="ALL_A_SHARES"
              style={{ width: "100%", marginTop: 8 }}
              options={[
                {
                  value: "ALL_A_SHARES",
                  label: "全部A股（沪、深、北）",
                },
              ]}
            />
          </Col>
          <Col xs={24} lg={8}>
            <Typography.Text strong>筛选日期</Typography.Text>
            <Input
              aria-label="筛选日期"
              type="date"
              value={resolvedAsOfDate}
              onChange={(event) => setAsOfDate(event.target.value)}
              style={{ marginTop: 8 }}
            />
          </Col>
          <Col xs={24}>
            <Typography.Text strong>选股描述</Typography.Text>
            <Input.TextArea
              aria-label="选股描述"
              value={text}
              onChange={(event) => setText(event.target.value)}
              autoSize={{ minRows: 3, maxRows: 8 }}
              maxLength={1000}
              showCount
              placeholder="例如：找过去20日涨停过，目前回踩到涨停前收盘价附近3%，并且明显缩量的股票。"
              style={{ marginTop: 8 }}
            />
          </Col>
          <Col xs={24}>
            <Button
              type="primary"
              icon={<FilterOutlined />}
              loading={parseMutation.isPending}
              disabled={!text.trim() || !resolvedAsOfDate}
              onClick={parse}
            >
              解析选股条件
            </Button>
          </Col>
        </Row>
      </Card>

      {parseResult ? (
        <Alert
          style={{ marginTop: 16 }}
          type={
            parseResult.parse_status === "COMPLETE"
              ? "success"
              : parseResult.parse_status === "UNSUPPORTED"
                ? "error"
                : "warning"
          }
          showIcon
          title={parseStatusText[parseResult.parse_status]}
          description={
            <Space orientation="vertical" size={4}>
              {parseResult.ambiguities.map((item) => (
                <span key={item}>{item}</span>
              ))}
              {parseResult.unsupported_fragments.map((item) => (
                <span key={item}>
                  当前系统尚未准备“{item}
                  ”对应的字段或组合语义，不能执行这部分条件。
                </span>
              ))}
            </Space>
          }
        />
      ) : null}

      {preview ? (
        <div style={{ marginTop: 16 }}>
          <PreviewCard preview={preview} />
        </div>
      ) : null}

      {draftSpec && definitions.data ? (
        <Card
          title="确认或修改条件"
          style={{ marginTop: 16 }}
          extra={
            <Tag color={preview?.can_execute ? "success" : "warning"}>
              {preview?.can_execute ? "规则可执行" : "请完成确认"}
            </Tag>
          }
        >
          <VisualScreeningEditor
            definitions={definitions.data}
            value={draftSpec}
            onChange={updateDraft}
          />
          <Button
            type="primary"
            size="large"
            icon={<FilterOutlined />}
            style={{ marginTop: 20 }}
            loading={createMutation.isPending}
            disabled={
              createMutation.isPending ||
              previewMutation.isPending ||
              !preview?.can_execute
            }
            onClick={() => void start()}
          >
            开始选股
          </Button>
        </Card>
      ) : null}

      <div ref={progressAnchor}>
        {current ? (
          <Card
            title="选股进度"
            style={{ marginTop: 16 }}
            extra={
              <Tag color={statusColor[current.status]}>
                {statusText[current.status]}
              </Tag>
            }
          >
            <Progress
              percent={current.progress_percent}
              status={current.status === "FAILED" ? "exception" : "active"}
            />
            <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
              <Col xs={12} md={6}>
                <Statistic
                  title="全部股票"
                  value={current.total_instruments}
                  suffix="只"
                />
              </Col>
              <Col xs={12} md={6}>
                <Statistic
                  title="已处理"
                  value={current.processed_instruments}
                  suffix="只"
                />
              </Col>
              <Col xs={12} md={6}>
                <Statistic
                  title="数据不足或无法判定"
                  value={
                    current.insufficient_data_count +
                    current.indeterminate_count
                  }
                  suffix="只"
                />
              </Col>
              <Col xs={12} md={6}>
                <Statistic
                  title="入选结果"
                  value={current.matched_count}
                  suffix="只"
                />
              </Col>
            </Row>
            {active.data?.error ? (
              <Alert
                type="error"
                showIcon
                title={active.data.error.message}
                style={{ marginTop: 16 }}
              />
            ) : null}
          </Card>
        ) : null}
      </div>

      {activeId ? (
        <Card title="真实筛选结果" style={{ marginTop: 16 }}>
          <Table<ScreeningResult>
            rowKey="result_id"
            size="small"
            pagination={{ pageSize: 20 }}
            loading={results.isLoading}
            dataSource={results.data?.items ?? []}
            columns={[
              { title: "排名", dataIndex: "rank", width: 80 },
              {
                title: "股票",
                render: (_, record) => instrumentText(record),
              },
              {
                title: "参考价",
                render: (_, record) => `${record.reference_price}元`,
              },
              { title: "入选原因", dataIndex: "reason" },
            ]}
            locale={{
              emptyText: (
                <Empty
                  description={
                    current && !terminalStatuses.has(current.status)
                      ? "正在筛选全部A股，结果会自动刷新"
                      : "本次没有股票满足条件"
                  }
                />
              ),
            }}
          />
        </Card>
      ) : null}
    </section>
  );
}
