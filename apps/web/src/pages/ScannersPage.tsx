import {
  CopyOutlined,
  ExperimentOutlined,
  FilterOutlined,
  HeartOutlined,
  ReloadOutlined,
  SaveOutlined,
  StopOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Checkbox,
  Col,
  Collapse,
  Descriptions,
  Empty,
  Input,
  Modal,
  Progress,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import { useEffect, useMemo, useRef, useState, type Key } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import {
  addScreeningResultsToWatchlist,
  archiveUserScreening,
  cancelScreening,
  cloneUserScreening,
  createScreening,
  getScreening,
  getScreeningConditions,
  getScreeningProgress,
  getScreeningResults,
  getScreeningRuns,
  getScreeningTemplates,
  listUserScreenings,
  parseScreeningText,
  previewScreeningSpec,
  restoreUserScreening,
  retryFailedScreening,
  runUserScreening,
  saveUserScreening,
  updateUserScreening,
  validateScreeningSpec,
} from "../api/screenings";
import { createWatchlist, getWatchlists } from "../api/market";
import { getScannerSessionDefault } from "../api/scanners";
import { PageHeader } from "../components/PageHeader/PageHeader";
import { AtomicConditionCatalog } from "../components/ScreeningBuilder/AtomicConditionCatalog";
import {
  conditionFromDefinition,
  VisualScreeningEditor,
} from "../components/ScreeningBuilder/VisualScreeningEditor";
import type {
  ScreeningConditionDefinition,
  ScreeningConditionGroupSpec,
  ScreeningParseResult,
  ScreeningPreview,
  ScreeningResult,
  ScreeningRun,
  ScreeningSpecSnapshot,
  ScreeningStatus,
  ScreeningTemplate,
  UserScreening,
} from "../types/screenings";
import { formatDateTime } from "../utils/display";

const terminalStatuses = new Set<ScreeningStatus>([
  "COMPLETED",
  "PARTIAL_FAILED",
  "FAILED",
  "CANCELED",
]);

const statusText: Record<ScreeningStatus, string> = {
  CREATED: "已创建",
  QUEUED: "等待后台处理",
  PLANNING: "正在分析数据需求",
  CHECKING_COVERAGE: "正在检查本地数据",
  BACKFILLING_MARKET_DATA: "正在补齐历史行情",
  BACKFILLING_REFERENCE_DATA: "正在补齐交易状态",
  VERIFYING_DATA: "正在检查数据质量",
  PREPARING_FEATURES: "正在准备选股指标",
  SCREENING: "正在执行全市场选股",
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
  PLANNING: "processing",
  CHECKING_COVERAGE: "processing",
  BACKFILLING_MARKET_DATA: "processing",
  BACKFILLING_REFERENCE_DATA: "processing",
  VERIFYING_DATA: "processing",
  PREPARING_FEATURES: "processing",
  SCREENING: "processing",
  RESOLVING: "processing",
  CHECKING_DATA: "processing",
  BACKFILLING: "processing",
  RUNNING: "processing",
  COMPLETED: "success",
  PARTIAL_FAILED: "warning",
  FAILED: "error",
  CANCELED: "default",
};

const formatRemainingTime = (seconds: number | null | undefined) => {
  if (seconds === null || seconds === undefined) return "正在计算";
  if (seconds <= 0) return "等待最后写入和数据复检";
  if (seconds < 60) return "不到1分钟";
  const minutes = Math.ceil(seconds / 60);
  if (minutes < 60) return `约${minutes}分钟`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return remainingMinutes > 0
    ? `约${hours}小时${remainingMinutes}分钟`
    : `约${hours}小时`;
};

const displayUnknown = (value: unknown, fallback = "—") => {
  if (typeof value === "string" || typeof value === "number") {
    return String(value);
  }
  return fallback;
};

const parseStatusText = {
  COMPLETE: "条件已识别，可以确认",
  PARTIAL: "只识别了部分条件",
  AMBIGUOUS: "需要确认几个参数",
  UNSUPPORTED: "当前条件暂不支持",
} as const;

// eslint-disable-next-line react-refresh/only-export-components
export function screeningConditionCount(
  spec: ScreeningSpecSnapshot | undefined,
) {
  if (!spec) return 0;
  const countGroup = (group: ScreeningConditionGroupSpec): number =>
    group.children.reduce(
      (total, child) =>
        total +
        (child.node_type === "GROUP" ? countGroup(child) : 1),
      0,
    );
  return spec.root_group
    ? countGroup(spec.root_group)
    : spec.conditions.length;
}

const screeningErrorAdvice: Record<string, string> = {
  SCREENING_DATA_PLAN_FAILED:
    "请确认筛选日期已有交易日历，并重新提交选股任务。",
  SCREENING_PROVIDER_NOT_AVAILABLE:
    "请启动并登录MiniQMT行情端和只读行情代理，然后重新尝试失败股票。",
  SCREENING_BACKFILL_PARTIAL_FAILED:
    "部分股票的历史行情未能补齐；可保留已完成结果并重新尝试失败股票。",
  SCREENING_REFERENCE_DATA_MISSING:
    "缺少交易状态、生命周期或复权资料；请恢复MiniQMT连接后重新尝试。",
  SCREENING_DATA_QUALITY_FAILED:
    "部分历史K线未通过质量检查；请重新补齐对应股票后再试。",
  SCREENING_PREPARATION_CANCELLED:
    "任务已按请求停止；如需继续，请重新开始选股。",
  SCREENING_DATA_STILL_NOT_READY:
    "MiniQMT返回后数据仍不完整；请检查行情端状态并重新尝试失败股票。",
};

function screeningErrorDescription(code: string) {
  return (
    screeningErrorAdvice[code] ??
    "请检查MiniQMT只读行情连接后重试；问题持续时可保留当前任务记录用于排查。"
  );
}

function instrumentText(result: ScreeningResult) {
  const exchange =
    result.exchange === "SSE"
      ? "SH"
      : result.exchange === "SZSE"
        ? "SZ"
        : result.exchange;
  return `${result.instrument_name}（${result.symbol}.${exchange}）`;
}

function metricText(metrics: Record<string, unknown>) {
  const labels: Record<string, string> = {
    limit_up_date: "涨停日期",
    trading_days_since_limit_up: "距涨停",
    distance_to_anchor: "距离起涨价",
    volume_ratio: "成交量比例",
    range_position: "区间位置",
    volume_multiple: "成交量倍数",
    bullish_candle: "是否收阳",
    latest_limit_up_date: "最近涨停日期",
    limit_up_occurrences: "窗口内涨停次数",
  };
  const percentKeys = new Set([
    "distance_to_anchor",
    "volume_ratio",
    "range_position",
  ]);
  return Object.entries(metrics)
    .filter(([key]) => key in labels)
    .map(([key, value]) => {
      const formatted =
        typeof value === "boolean"
          ? value
            ? "是"
            : "否"
          : percentKeys.has(key) && Number.isFinite(Number(value))
            ? `${(Number(value) * 100).toFixed(2)}%`
            : key === "volume_multiple" && Number.isFinite(Number(value))
              ? `${Number(value).toFixed(2)}倍`
              : typeof value === "string" ||
                  typeof value === "number" ||
                  typeof value === "bigint"
                ? String(value)
                : "—";
      return `${labels[key]}：${formatted}`;
    })
    .join("；");
}

function percentMetric(value: unknown) {
  const number = Number(value);
  return Number.isFinite(number) ? `${(number * 100).toFixed(2)}%` : "—";
}

function mainFailureText(
  stats: Record<string, unknown> | undefined,
  definitions: ScreeningConditionDefinition[] | undefined,
) {
  const raw = stats?.condition_failure_counts;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const entries = Object.entries(raw)
    .filter((item): item is [string, number] => typeof item[1] === "number")
    .sort((left, right) => right[1] - left[1]);
  if (!entries.length) return null;
  const [conditionKey, count] = entries[0];
  const name =
    definitions?.find((item) => item.condition_key === conditionKey)
      ?.display_name ?? conditionKey;
  return `淘汰股票最多的条件是“${name}”（${count}只未通过）`;
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

interface NaturalLanguagePaneProps {
  preset?: {
    spec: ScreeningSpecSnapshot;
    sourceText?: string | null;
    nonce: number;
    useLatestDate?: boolean;
  };
  openRunId?: string;
  editing?: UserScreening;
  rerunScreeningId?: string;
}

function NaturalLanguageScreeningPane({
  preset,
  openRunId,
  editing,
  rerunScreeningId,
}: NaturalLanguagePaneProps) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const progressAnchor = useRef<HTMLDivElement>(null);
  const previewTimer = useRef<number | undefined>(undefined);
  const idempotencyKey = useRef(requestKey());
  const submissionLock = useRef(false);
  const [text, setText] = useState(preset?.sourceText ?? "");
  const [asOfDate, setAsOfDate] = useState(
    preset?.useLatestDate ? "" : (preset?.spec.as_of_date ?? ""),
  );
  const [parseResult, setParseResult] = useState<ScreeningParseResult>();
  const [draftSpec, setDraftSpec] = useState<ScreeningSpecSnapshot | undefined>(
    preset?.spec,
  );
  const [preview, setPreview] = useState<ScreeningPreview>();
  const [activeId, setActiveId] = useState<string | undefined>(openRunId);
  const [selectedResultIds, setSelectedResultIds] = useState<Key[]>([]);
  const [saveOpen, setSaveOpen] = useState(false);
  const [saveName, setSaveName] = useState("");
  const [saveDescription, setSaveDescription] = useState("");
  const [watchlistOpen, setWatchlistOpen] = useState(false);
  const [watchlistId, setWatchlistId] = useState<string>();
  const [newWatchlistName, setNewWatchlistName] = useState("");
  const [realtimeMonitor, setRealtimeMonitor] = useState(false);
  const [savedScreeningId, setSavedScreeningId] = useState(rerunScreeningId);
  const [useExistingDataOnly, setUseExistingDataOnly] = useState(false);
  const navigate = useNavigate();

  const sessionDefault = useQuery({
    queryKey: ["scanner-session-default"],
    queryFn: getScannerSessionDefault,
  });
  const definitions = useQuery({
    queryKey: ["screening-conditions"],
    queryFn: getScreeningConditions,
  });
  const watchlists = useQuery({
    queryKey: ["watchlists"],
    queryFn: getWatchlists,
  });
  const resolvedAsOfDate = asOfDate || sessionDefault.data?.scan_date || "";
  const addedConditionKeys = useMemo(() => {
    const keys = new Set<string>();
    const visit = (group: ScreeningConditionGroupSpec) => {
      group.children.forEach((child) => {
        if (child.node_type === "GROUP") visit(child);
        else keys.add(child.condition_key);
      });
    };
    draftSpec?.conditions.forEach((condition) =>
      keys.add(condition.condition_key),
    );
    if (draftSpec?.root_group) visit(draftSpec.root_group);
    return keys;
  }, [draftSpec]);

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
      setSavedScreeningId(undefined);
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

  useEffect(() => {
    if (!preset) return;
    previewMutation.mutate(preset.spec);
    // preset.nonce deliberately re-applies the same saved/template spec.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preset?.nonce]);

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

  const rerunMutation = useMutation({
    mutationFn: ({
      screeningId,
      date,
    }: {
      screeningId: string;
      date: string;
    }) => runUserScreening(screeningId, date, useExistingDataOnly),
    onSuccess: async (run) => {
      setActiveId(run.screening_id);
      await queryClient.invalidateQueries({ queryKey: ["screenings"] });
      await queryClient.invalidateQueries({ queryKey: ["user-screenings"] });
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

  const saveMutation = useMutation({
    mutationFn: (input: Parameters<typeof saveUserScreening>[0]) =>
      editing
        ? updateUserScreening(editing.id, input)
        : saveUserScreening(input),
    onSuccess: async () => {
      setSaveOpen(false);
      setSaveName("");
      setSaveDescription("");
      await queryClient.invalidateQueries({ queryKey: ["user-screenings"] });
      void message.success("选股方案已保存");
    },
    onError: (error: Error) => void message.error(error.message),
  });

  const cancelMutation = useMutation({
    mutationFn: () => {
      if (!activeId) throw new Error("没有可取消的选股任务");
      return cancelScreening(activeId);
    },
    onSuccess: async () => {
      await active.refetch();
      await progress.refetch();
      void message.success("已提交取消请求");
    },
    onError: (error: Error) => void message.error(error.message),
  });

  const retryMutation = useMutation({
    mutationFn: () => {
      if (!activeId) throw new Error("没有可重试的选股任务");
      return retryFailedScreening(activeId);
    },
    onSuccess: async (run) => {
      setActiveId(run.screening_id);
      await queryClient.invalidateQueries({ queryKey: ["screenings"] });
      void message.success("失败股票已重新进入数据准备队列");
    },
    onError: (error: Error) => void message.error(error.message),
  });

  const addWatchlistMutation = useMutation({
    mutationFn: async () => {
      if (!activeId) throw new Error("请先完成一次选股");
      let targetId = watchlistId ?? null;
      if (!realtimeMonitor && !targetId && newWatchlistName.trim()) {
        const created = await createWatchlist(
          newWatchlistName.trim(),
          "由智能选股结果创建",
        );
        targetId = created.id;
      }
      return addScreeningResultsToWatchlist(activeId, {
        instrument_ids: selectedResultIds.map(String),
        watchlist_id: realtimeMonitor ? null : targetId,
        new_watchlist_name:
          realtimeMonitor || targetId ? null : newWatchlistName.trim() || null,
        realtime_monitor: realtimeMonitor,
      });
    },
    onSuccess: async (result) => {
      setWatchlistOpen(false);
      setSelectedResultIds([]);
      setRealtimeMonitor(false);
      await queryClient.invalidateQueries({ queryKey: ["watchlists"] });
      void message.success(
        `已加入${result.succeeded}只，已有${result.already_exists}只，失败${result.failed}只`,
      );
    },
    onError: (error: Error) => void message.error(error.message),
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
    setSavedScreeningId(undefined);
    idempotencyKey.current = requestKey();
    if (previewTimer.current !== undefined) {
      window.clearTimeout(previewTimer.current);
    }
    previewTimer.current = window.setTimeout(
      () => previewMutation.mutate(next),
      250,
    );
  };

  const addCatalogCondition = (
    definition: ScreeningConditionDefinition,
    phrase: string,
  ) => {
    if (addedConditionKeys.has(definition.condition_key)) {
      void message.info("该原子条件已经在当前方案中");
      return;
    }
    const condition = conditionFromDefinition(definition, phrase);
    const nextCustomName = (() => {
      if (
        draftSpec &&
        draftSpec.origin !== "USER_STRUCTURED" &&
        !draftSpec.name.startsWith("自定义选股：")
      ) {
        return draftSpec.name;
      }
      const labels = [
        ...addedConditionKeys,
        definition.condition_key,
      ]
        .map(
          (key) =>
            definitions.data?.find((item) => item.condition_key === key)
              ?.display_name ?? key,
        )
        .slice(0, 4);
      return `自定义选股：${labels.join(" + ")}`;
    })();
    if (!draftSpec) {
      updateDraft({
        schema_version: 1,
        name: nextCustomName,
        origin: "USER_STRUCTURED",
        universe_spec: {
          universe_key: "ALL_A_SHARES",
          excluded_instrument_ids: [],
          exclude_st: false,
          exclude_bse: false,
          exclude_star_market: false,
          exclude_chinext: false,
        },
        as_of_date: resolvedAsOfDate,
        timeframe: "DAY_1",
        conditions: [condition],
        root_group: null,
        exclusions: {},
        ranking_rules: [{ field: "score", direction: "DESC" }],
        top_n: null,
        price_adjustment_mode: "RAW",
      });
      void message.success(`已添加“${definition.display_name}”，请确认参数`);
      return;
    }
    if (draftSpec.root_group) {
      updateDraft({
        ...draftSpec,
        name: nextCustomName,
        schema_version: 2,
        origin: "USER_CORRECTED",
        conditions: [],
        root_group: {
          ...draftSpec.root_group,
          children: [...draftSpec.root_group.children, condition],
        },
      });
    } else {
      updateDraft({
        ...draftSpec,
        name: nextCustomName,
        origin: "USER_CORRECTED",
        conditions: [...draftSpec.conditions, condition],
      });
    }
    void message.success(`已添加“${definition.display_name}”`);
  };

  const start = async () => {
    if (
      !draftSpec ||
      createMutation.isPending ||
      rerunMutation.isPending ||
      submissionLock.current
    )
      return;
    submissionLock.current = true;
    try {
      const validated = await validateScreeningSpec({
        ...draftSpec,
        as_of_date: resolvedAsOfDate,
      });
      setDraftSpec(validated.screening_spec);
      setPreview(validated.preview);
      if (!validated.can_execute) {
        void message.error("当前规则或筛选日期尚未通过校验");
        submissionLock.current = false;
        return;
      }
      if (savedScreeningId) {
        rerunMutation.mutate({
          screeningId: savedScreeningId,
          date: resolvedAsOfDate,
        });
        return;
      }
      createMutation.mutate({
        ...validated.screening_spec,
        conditions: validated.screening_spec.conditions.map((condition) => ({
          condition_key: condition.condition_key,
          parameters: condition.parameters,
        })),
        idempotency_key: idempotencyKey.current,
        use_existing_data_only: useExistingDataOnly,
      });
    } catch (error) {
      submissionLock.current = false;
      void message.error(
        error instanceof Error ? error.message : "选股条件校验失败",
      );
    }
  };

  const current = progress.data ?? active.data;
  const terminal = Boolean(current && terminalStatuses.has(current.status));
  const failureSummary = mainFailureText(
    active.data?.execution_stats,
    definitions.data,
  );
  return (
    <section>
      <div
        style={{
          display: "flex",
          justifyContent: "flex-end",
          marginBottom: 12,
        }}
      >
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
      </div>

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

      {definitions.data ? (
        <AtomicConditionCatalog
          definitions={definitions.data}
          naturalLanguageText={text}
          addedConditionKeys={addedConditionKeys}
          onAdd={addCatalogCondition}
        />
      ) : definitions.isLoading ? (
        <Card loading title="正在加载原子条件目录" style={{ marginTop: 16 }} />
      ) : (
        <Alert
          style={{ marginTop: 16 }}
          type="error"
          showIcon
          title="原子条件目录加载失败"
          description="请确认 AlphaDesk API 在线后点击右上角刷新。"
        />
      )}

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
          <Collapse
            ghost
            style={{ marginTop: 12 }}
            items={[
              {
                key: "advanced-data",
                label: "高级数据设置",
                children: (
                  <Space orientation="vertical">
                    <Checkbox
                      checked={useExistingDataOnly}
                      onChange={(event) =>
                        setUseExistingDataOnly(event.target.checked)
                      }
                    >
                      仅使用当前已有数据运行
                    </Checkbox>
                    <Typography.Text type="secondary">
                      默认会通过MiniQMT只补齐缺失的历史日线；启用后不会下载，
                      数据不完整的股票将单独标记并跳过。
                    </Typography.Text>
                  </Space>
                ),
              },
            ]}
          />
          <Space style={{ marginTop: 20 }}>
            <Button
              type="primary"
              size="large"
              icon={<FilterOutlined />}
              loading={createMutation.isPending || rerunMutation.isPending}
              disabled={
                createMutation.isPending ||
                rerunMutation.isPending ||
                previewMutation.isPending ||
                !preview?.can_execute
              }
              onClick={() => void start()}
            >
              开始选股
            </Button>
            <Button
              size="large"
              icon={<SaveOutlined />}
              onClick={() => {
                setSaveName(editing?.name ?? draftSpec.name);
                setSaveDescription(editing?.description ?? "");
                setSaveOpen(true);
              }}
            >
              保存方案
            </Button>
          </Space>
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
            <Descriptions
              size="small"
              column={{ xs: 1, md: 2, xl: 4 }}
              items={[
                {
                  key: "name",
                  label: "方案",
                  children: active.data?.name ?? draftSpec?.name ?? "临时方案",
                },
                {
                  key: "date",
                  label: "筛选日期",
                  children: active.data?.spec.as_of_date ?? resolvedAsOfDate,
                },
                {
                  key: "universe",
                  label: "股票范围",
                  children: "全部A股（按排除项过滤）",
                },
                {
                  key: "conditions",
                  label: "条件数量",
                  children: `${screeningConditionCount(active.data?.spec ?? draftSpec)}项`,
                },
              ]}
              style={{ marginBottom: 12 }}
            />
            <Alert
              type="info"
              showIcon
              title={progress.data?.stage_label ?? statusText[current.status]}
              description={
                progress.data?.current_action ?? "后台任务正在准备或筛选数据"
              }
              style={{ marginBottom: 12 }}
            />
            {active.data?.data_requirement_plan ? (
              <Descriptions
                size="small"
                column={{ xs: 1, md: 2, xl: 4 }}
                items={[
                  {
                    key: "estimated",
                    label: "预计筛选股票",
                    children: `${displayUnknown(active.data.data_requirement_plan.universe_count)}只`,
                  },
                  {
                    key: "estimated-missing",
                    label: "预计需补数",
                    children: `${displayUnknown(active.data.data_requirement_plan.estimated_missing_instruments)}只`,
                  },
                  {
                    key: "range",
                    label: "预计补数范围",
                    children: `${displayUnknown(active.data.data_requirement_plan.earliest_required_date)} 至 ${displayUnknown(active.data.data_requirement_plan.latest_required_date)}`,
                  },
                  {
                    key: "provider",
                    label: "行情提供方",
                    children: "MiniQMT（只读行情）",
                  },
                  {
                    key: "time",
                    label: "可能耗时",
                    children: "取决于缺失股票数和MiniQMT响应速度",
                  },
                ]}
                style={{ marginBottom: 12 }}
              />
            ) : null}
            {(progress.data?.backfill_total_batches ?? 0) > 0 ? (
              <div
                aria-label="历史行情下载进度"
                style={{
                  padding: "12px 16px",
                  marginBottom: 16,
                  border: "1px solid #d9e8ff",
                  borderRadius: 8,
                  background: "#f6faff",
                }}
              >
                <Row justify="space-between" align="middle" gutter={[12, 8]}>
                  <Col>
                    <Typography.Text strong>历史行情下载进度</Typography.Text>
                  </Col>
                  <Col>
                    <Typography.Text type="secondary">
                      已处理 {progress.data?.backfill_processed_batches ?? 0} /{" "}
                      {progress.data?.backfill_total_batches ?? 0} 批
                    </Typography.Text>
                  </Col>
                </Row>
                <Progress
                  percent={progress.data?.backfill_progress_percent ?? 0}
                  status={current.status === "FAILED" ? "exception" : "active"}
                  strokeColor="#52c41a"
                  style={{ marginTop: 8 }}
                />
                <Row justify="space-between" gutter={[12, 8]}>
                  <Col>
                    <Typography.Text type="secondary">
                      剩余{" "}
                      {progress.data?.backfill_pending_batches === null
                        ? "—"
                        : (progress.data?.backfill_pending_batches ?? 0)}{" "}
                      批
                    </Typography.Text>
                  </Col>
                  <Col>
                    <Typography.Text type="secondary">
                      预计剩余：
                      {formatRemainingTime(
                        progress.data?.backfill_estimated_remaining_seconds,
                      )}
                    </Typography.Text>
                  </Col>
                </Row>
              </div>
            ) : null}
            <Typography.Text type="secondary">整体流程进度</Typography.Text>
            <Progress
              percent={current.progress_percent}
              status={current.status === "FAILED" ? "exception" : "active"}
            />
            <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
              <Col xs={12} md={6} xl={3}>
                <Statistic
                  title="全部股票"
                  value={current.total_instruments}
                  suffix="只"
                />
              </Col>
              <Col xs={12} md={6} xl={3}>
                <Statistic
                  title="已进入条件计算"
                  value={current.processed_instruments}
                  suffix="只"
                />
              </Col>
              <Col xs={12} md={6} xl={3}>
                <Statistic
                  title="正常进入计算"
                  value={current.processed_instruments}
                  suffix="只"
                />
              </Col>
              <Col xs={12} md={6} xl={3}>
                <Statistic
                  title="正在下载"
                  value={progress.data?.downloading_count ?? 0}
                  suffix="只"
                />
              </Col>
              <Col xs={12} md={6} xl={3}>
                <Statistic
                  title="排除ST/板块"
                  value={progress.data?.excluded_count ?? 0}
                  suffix="只"
                />
              </Col>
              <Col xs={12} md={6} xl={3}>
                <Statistic
                  title="上市历史不足"
                  value={progress.data?.listing_history_short_count ?? 0}
                  suffix="只"
                />
              </Col>
              <Col xs={12} md={6} xl={3}>
                <Statistic
                  title="当前停牌"
                  value={progress.data?.currently_suspended_count ?? 0}
                  suffix="只"
                />
              </Col>
              <Col xs={12} md={6} xl={3}>
                <Statistic
                  title="数据过旧"
                  value={progress.data?.stale_data_count ?? 0}
                  suffix="只"
                />
              </Col>
              <Col xs={12} md={6} xl={3}>
                <Statistic
                  title="正常交易日行情缺失"
                  value={progress.data?.data_gap_count ?? 0}
                  suffix="只"
                />
              </Col>
              <Col xs={12} md={6} xl={3}>
                <Statistic
                  title="MiniQMT明确失败"
                  value={progress.data?.provider_failed_count ?? 0}
                  suffix="只"
                />
              </Col>
              <Col xs={12} md={6} xl={3}>
                <Statistic
                  title="数据质量异常"
                  value={progress.data?.quality_failed_count ?? 0}
                  suffix="只"
                />
              </Col>
              <Col xs={12} md={6} xl={3}>
                <Statistic
                  title="交易日历异常"
                  value={progress.data?.calendar_mismatch_count ?? 0}
                  suffix="只"
                />
              </Col>
              <Col xs={12} md={6} xl={3}>
                <Statistic
                  title="符合条件"
                  value={current.matched_count}
                  suffix="只"
                />
              </Col>
            </Row>
            <Space style={{ marginTop: 16 }}>
              {!terminal ? (
                <Button
                  danger
                  icon={<StopOutlined />}
                  loading={cancelMutation.isPending}
                  onClick={() => cancelMutation.mutate()}
                >
                  取消准备和筛选
                </Button>
              ) : null}
              {terminal &&
              ((progress.data?.provider_failed_count ?? 0) > 0 ||
                current.failed_count > 0) ? (
                <Button
                  icon={<ReloadOutlined />}
                  loading={retryMutation.isPending}
                  onClick={() => retryMutation.mutate()}
                >
                  重新尝试失败股票
                </Button>
              ) : null}
            </Space>
            {active.data?.error ? (
              <Alert
                type="error"
                showIcon
                title={active.data.error.message}
                description={screeningErrorDescription(active.data.error.code)}
                style={{ marginTop: 16 }}
              />
            ) : null}
          </Card>
        ) : null}
      </div>

      {terminal &&
      current &&
      current.status !== "FAILED" &&
      current.matched_count === 0 ? (
        <Alert
          type="warning"
          showIcon
          title="本次没有股票满足全部条件"
          description={
            <Space orientation="vertical" size={6}>
              <span>
                已处理{current.processed_instruments}只，其中
                {progress.data?.listing_history_short_count ?? 0}只上市历史不足、
                {progress.data?.currently_suspended_count ?? 0}只当前停牌、
                {progress.data?.stale_data_count ?? 0}只数据过旧、
                {progress.data?.data_gap_count ?? 0}只正常交易日行情缺失、
                {progress.data?.provider_failed_count ?? 0}只MiniQMT明确失败。
              </span>
              {(progress.data?.calendar_mismatch_count ?? 0) > 0 ? (
                <span>
                  检测到大量股票共同缺少
                  {(progress.data?.calendar_mismatch_dates ?? []).join("、") ||
                    "同一市场日期"}
                  行情。该日期在本地日历中被标记为开市，但MiniQMT未返回市场行情；
                  已停止错误补数并标记为交易日历异常。
                </span>
              ) : null}
              {failureSummary ? <span>{failureSummary}。</span> : null}
              {current.insufficient_data_count > 0 &&
              current.processed_instruments === 0 ? (
                <span>
                  请先登录并保持 MiniQMT
                  运行，然后按原日期重新运行；系统会自动检查并补齐缺失历史日线。
                </span>
              ) : (
                <>
                  <span>
                    可以放宽阈值、减少组合条件，或改用较近的交易日后重新运行。
                  </span>
                  <Button
                    size="small"
                    onClick={() =>
                      window.scrollTo({ top: 0, behavior: "smooth" })
                    }
                  >
                    修改选股条件
                  </Button>
                </>
              )}
            </Space>
          }
          style={{ marginTop: 16 }}
        />
      ) : null}
      {terminal &&
      current &&
      current.status === "PARTIAL_FAILED" &&
      current.matched_count > 0 ? (
        <Alert
          type="warning"
          showIcon
          title="结果可用，但部分股票未能完成判断"
          description={`本次有${progress.data?.data_gap_count ?? 0}只正常交易日行情缺失、${progress.data?.provider_failed_count ?? 0}只MiniQMT明确失败、${progress.data?.currently_suspended_count ?? 0}只当前停牌；下表只展示可执行的真实结果。`}
          style={{ marginTop: 16 }}
        />
      ) : null}

      {activeId ? (
        <Card
          title="真实筛选结果"
          style={{ marginTop: 16 }}
          extra={
            <Button
              icon={<HeartOutlined />}
              disabled={!selectedResultIds.length}
              onClick={() => setWatchlistOpen(true)}
            >
              批量加入自选
            </Button>
          }
        >
          <Table<ScreeningResult>
            rowKey="instrument_id"
            size="small"
            pagination={{ pageSize: 20 }}
            loading={results.isLoading}
            dataSource={results.data?.items ?? []}
            rowSelection={{
              selectedRowKeys: selectedResultIds,
              onChange: setSelectedResultIds,
            }}
            columns={[
              { title: "排名", dataIndex: "rank", width: 80 },
              {
                title: "股票",
                render: (_, record) => (
                  <Link
                    to={`/market?instrument_id=${record.instrument_id}&screening_id=${activeId}`}
                  >
                    {instrumentText(record)}
                  </Link>
                ),
              },
              {
                title: "参考价",
                render: (_, record) => `${record.reference_price}元`,
              },
              {
                title: "筛选日涨跌",
                render: (_, record) =>
                  percentMetric(record.metrics.daily_return),
              },
              {
                title: "动态条件值",
                render: (_, record) => metricText(record.metrics) || "—",
              },
              {
                title: "数据提示",
                render: (_, record) => {
                  const warning = record.metrics.data_warning;
                  return typeof warning === "string" ||
                    typeof warning === "number" ||
                    typeof warning === "bigint"
                    ? String(warning)
                    : "数据正常";
                },
              },
              {
                title: "入选原因",
                dataIndex: "reason",
                render: (reason: string) => (
                  <Typography.Paragraph
                    ellipsis={{ rows: 2, expandable: true, symbol: "展开" }}
                    style={{ margin: 0 }}
                  >
                    {reason}
                  </Typography.Paragraph>
                ),
              },
              {
                title: "操作",
                width: 220,
                render: (_, record) => (
                  <Space>
                    <Button
                      size="small"
                      onClick={() => {
                        setSelectedResultIds([record.instrument_id]);
                        setWatchlistOpen(true);
                      }}
                    >
                      加入自选
                    </Button>
                    <Button
                      size="small"
                      icon={<ExperimentOutlined />}
                      onClick={() =>
                        void navigate(
                          `/research/backtest?instrument_id=${record.instrument_id}&screening_id=${activeId}&screening_result_id=${record.result_id}`,
                        )
                      }
                    >
                      快速回测
                    </Button>
                  </Space>
                ),
              },
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
            expandable={{
              rowExpandable: (record) =>
                Array.isArray(record.metrics.condition_evaluations),
              expandedRowRender: (record) => {
                const evaluations = Array.isArray(
                  record.metrics.condition_evaluations,
                )
                  ? record.metrics.condition_evaluations
                  : [];
                return (
                  <Space orientation="vertical" size={8}>
                    <Typography.Text strong>
                      原子条件逐项判断
                    </Typography.Text>
                    {evaluations.map((item, index) => {
                      const detail =
                        typeof item === "object" && item !== null
                          ? (item as Record<string, unknown>)
                          : {};
                      return (
                        <Space key={`${String(detail.condition_key)}-${index}`} wrap>
                          <Tag
                            color={
                              detail.outcome === "MATCHED"
                                ? "success"
                                : detail.outcome === "NOT_MATCHED"
                                  ? "default"
                                  : "warning"
                            }
                          >
                            {detail.outcome === "MATCHED"
                              ? "满足"
                              : detail.outcome === "NOT_MATCHED"
                                ? "不满足"
                                : "无法判断"}
                          </Tag>
                          <Typography.Text strong>
                            {displayUnknown(
                              detail.display_name ??
                                detail.condition_key ??
                                "条件",
                            )}
                          </Typography.Text>
                          <Typography.Text type="secondary">
                            {displayUnknown(detail.reason)}
                          </Typography.Text>
                        </Space>
                      );
                    })}
                  </Space>
                );
              },
            }}
          />
        </Card>
      ) : null}
      <Modal
        title={editing ? "保存方案新版本" : "保存为我的选股方案"}
        open={saveOpen}
        okText="保存方案"
        cancelText="取消"
        confirmLoading={saveMutation.isPending}
        onCancel={() => setSaveOpen(false)}
        onOk={() => {
          if (!draftSpec || !saveName.trim()) {
            void message.warning("请输入方案名称");
            return;
          }
          saveMutation.mutate({
            name: saveName.trim(),
            description: saveDescription.trim() || null,
            source_text: text.trim() || null,
            screening_spec: draftSpec,
            origin: draftSpec.origin,
          });
        }}
      >
        <Typography.Text>方案名称</Typography.Text>
        <Input
          value={saveName}
          maxLength={128}
          onChange={(event) => setSaveName(event.target.value)}
          style={{ marginTop: 8, marginBottom: 16 }}
        />
        <Typography.Text>说明（可选）</Typography.Text>
        <Input.TextArea
          value={saveDescription}
          maxLength={1000}
          onChange={(event) => setSaveDescription(event.target.value)}
          style={{ marginTop: 8 }}
        />
      </Modal>
      <Modal
        title="加入自选股"
        open={watchlistOpen}
        okText="加入自选"
        cancelText="取消"
        confirmLoading={addWatchlistMutation.isPending}
        onCancel={() => setWatchlistOpen(false)}
        onOk={() => addWatchlistMutation.mutate()}
      >
        <Typography.Paragraph>
          已选择{selectedResultIds.length}只股票。重复加入不会报错。
        </Typography.Paragraph>
        <Select
          allowClear
          placeholder="选择现有自选分组"
          style={{ width: "100%", marginBottom: 12 }}
          value={watchlistId}
          options={(watchlists.data ?? []).map((item) => ({
            value: item.id,
            label: item.name,
          }))}
          onChange={setWatchlistId}
        />
        {!watchlistId ? (
          <Input
            placeholder="或输入新分组名称"
            value={newWatchlistName}
            onChange={(event) => setNewWatchlistName(event.target.value)}
          />
        ) : null}
        <Checkbox
          checked={realtimeMonitor}
          onChange={(event) => setRealtimeMonitor(event.target.checked)}
          style={{ marginTop: 16 }}
        >
          同时加入“盘中监控”（会创建或复用该分组，不会自动下单）
        </Checkbox>
      </Modal>
    </section>
  );
}

export function ScannersPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [search, setSearch] = useSearchParams();
  const activeTab = search.get("tab") ?? "natural";
  const [preset, setPreset] = useState<NaturalLanguagePaneProps["preset"]>();
  const [editing, setEditing] = useState<UserScreening>();
  const [rerunScreeningId, setRerunScreeningId] = useState<string>();
  const [openRunId, setOpenRunId] = useState<string>();
  const [historyStatus, setHistoryStatus] = useState<string>();
  const [historyFrom, setHistoryFrom] = useState("");
  const [historyTo, setHistoryTo] = useState("");
  const [historyName, setHistoryName] = useState("");
  const [historySource, setHistorySource] = useState<
    "TEMPLATE" | "CUSTOM" | undefined
  >();

  const templates = useQuery({
    queryKey: ["screening-templates"],
    queryFn: getScreeningTemplates,
  });
  const saved = useQuery({
    queryKey: ["user-screenings"],
    queryFn: () => listUserScreenings(true),
  });
  const history = useQuery({
    queryKey: [
      "screenings",
      historyStatus,
      historyFrom,
      historyTo,
      historyName,
      historySource,
    ],
    queryFn: () =>
      getScreeningRuns({
        status: historyStatus,
        as_of_from: historyFrom,
        as_of_to: historyTo,
        plan_name: historyName.trim(),
        source_type: historySource,
      }),
  });

  const applySpec = (
    spec: ScreeningSpecSnapshot,
    sourceText?: string | null,
    definition?: UserScreening,
    savedScreeningId?: string,
    useLatestDate = false,
  ) => {
    setPreset((previous) => ({
      spec,
      sourceText,
      nonce: (previous?.nonce ?? 0) + 1,
      useLatestDate,
    }));
    setEditing(definition);
    setRerunScreeningId(savedScreeningId);
    setSearch({ tab: "natural" });
  };

  const cloneMutation = useMutation({
    mutationFn: cloneUserScreening,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["user-screenings"] });
      void message.success("已复制选股方案");
    },
    onError: (error: Error) => void message.error(error.message),
  });
  const statusMutation = useMutation({
    mutationFn: ({
      item,
      restore,
    }: {
      item: UserScreening;
      restore: boolean;
    }) =>
      restore ? restoreUserScreening(item.id) : archiveUserScreening(item.id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["user-screenings"] });
      void message.success("方案状态已更新");
    },
    onError: (error: Error) => void message.error(error.message),
  });

  const templateCards = (
    <Row gutter={[16, 16]}>
      {(templates.data ?? []).map((template: ScreeningTemplate) => (
        <Col xs={24} md={12} xl={8} key={template.template_key}>
          <Card
            title={template.display_name}
            extra={<Tag>{template.timeframe}</Tag>}
            actions={[
              <Button
                key="use"
                type="link"
                disabled={!template.enabled}
                onClick={() => applySpec(template.spec)}
              >
                使用此模板
              </Button>,
            ]}
          >
            <Typography.Paragraph>{template.description}</Typography.Paragraph>
            <Typography.Text type="secondary">
              所需数据：{template.required_data}
            </Typography.Text>
          </Card>
        </Col>
      ))}
    </Row>
  );

  const savedTable = (
    <Table<UserScreening>
      rowKey="id"
      loading={saved.isLoading}
      dataSource={saved.data?.items ?? []}
      pagination={{ pageSize: 10 }}
      locale={{ emptyText: <Empty description="还没有保存选股方案" /> }}
      columns={[
        {
          title: "方案名称",
          render: (_, item) => (
            <Space orientation="vertical" size={0}>
              <Typography.Text strong>{item.name}</Typography.Text>
              <Typography.Text type="secondary">
                {item.description ?? item.summary}
              </Typography.Text>
            </Space>
          ),
        },
        {
          title: "版本",
          render: (_, item) => `第${item.current_version}版`,
          width: 100,
        },
        {
          title: "状态",
          render: (_, item) => (
            <Tag color={item.status === "ARCHIVED" ? "default" : "success"}>
              {item.status === "ARCHIVED" ? "已归档" : "使用中"}
            </Tag>
          ),
          width: 100,
        },
        {
          title: "最近使用",
          render: (_, item) =>
            item.last_used_at ? formatDateTime(item.last_used_at) : "尚未运行",
          width: 180,
        },
        {
          title: "操作",
          width: 350,
          render: (_, item) => (
            <Space wrap>
              <Button
                size="small"
                disabled={item.status === "ARCHIVED"}
                onClick={() =>
                  applySpec(item.screening_spec, item.source_text, undefined)
                }
              >
                使用
              </Button>
              <Button
                size="small"
                disabled={item.status === "ARCHIVED"}
                onClick={() =>
                  applySpec(item.screening_spec, item.source_text, item)
                }
              >
                编辑
              </Button>
              <Button
                size="small"
                icon={<CopyOutlined />}
                onClick={() => cloneMutation.mutate(item.id)}
              >
                复制
              </Button>
              <Button
                size="small"
                onClick={() =>
                  statusMutation.mutate({
                    item,
                    restore: item.status === "ARCHIVED",
                  })
                }
              >
                {item.status === "ARCHIVED" ? "恢复" : "归档"}
              </Button>
              <Button
                size="small"
                type="primary"
                disabled={item.status === "ARCHIVED"}
                onClick={() =>
                  applySpec(
                    item.screening_spec,
                    item.source_text,
                    undefined,
                    item.id,
                    true,
                  )
                }
              >
                再次运行
              </Button>
            </Space>
          ),
        },
      ]}
    />
  );

  const historyTable = (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Card size="small">
        <Row gutter={[12, 12]}>
          <Col xs={24} md={6}>
            <Input
              allowClear
              placeholder="按方案名称筛选"
              value={historyName}
              onChange={(event) => setHistoryName(event.target.value)}
            />
          </Col>
          <Col xs={12} md={4}>
            <Select
              allowClear
              placeholder="运行状态"
              style={{ width: "100%" }}
              value={historyStatus}
              onChange={setHistoryStatus}
              options={Object.entries(statusText).map(([value, label]) => ({
                value,
                label,
              }))}
            />
          </Col>
          <Col xs={12} md={4}>
            <Select
              allowClear
              placeholder="方案来源"
              style={{ width: "100%" }}
              value={historySource}
              onChange={setHistorySource}
              options={[
                { value: "TEMPLATE", label: "系统模板" },
                { value: "CUSTOM", label: "自定义方案" },
              ]}
            />
          </Col>
          <Col xs={12} md={5}>
            <Input
              aria-label="筛选开始日期"
              type="date"
              value={historyFrom}
              onChange={(event) => setHistoryFrom(event.target.value)}
            />
          </Col>
          <Col xs={12} md={5}>
            <Input
              aria-label="筛选结束日期"
              type="date"
              value={historyTo}
              onChange={(event) => setHistoryTo(event.target.value)}
            />
          </Col>
        </Row>
      </Card>
      <Table<ScreeningRun>
        rowKey="screening_id"
        loading={history.isLoading}
        dataSource={history.data?.items ?? []}
        pagination={{ pageSize: 10 }}
        locale={{ emptyText: <Empty description="暂无历史选股结果" /> }}
        columns={[
          { title: "方案名称", dataIndex: "name" },
          {
            title: "筛选日期",
            render: (_, item) => item.spec.as_of_date,
            width: 120,
          },
          {
            title: "股票范围",
            render: () => "全部A股",
            width: 110,
          },
          {
            title: "状态",
            render: (_, item) => (
              <Tag color={statusColor[item.status]}>
                {statusText[item.status]}
              </Tag>
            ),
            width: 160,
          },
          { title: "匹配", dataIndex: "matched_count", width: 80 },
          {
            title: "数据不足",
            dataIndex: "insufficient_data_count",
            width: 100,
          },
          {
            title: "耗时",
            render: (_, item) => `${(item.elapsed_ms / 1000).toFixed(2)}秒`,
            width: 100,
          },
          {
            title: "完成时间",
            render: (_, item) =>
              item.completed_at ? formatDateTime(item.completed_at) : "—",
            width: 180,
          },
          {
            title: "操作",
            width: 220,
            render: (_, item) => (
              <Space>
                <Button
                  size="small"
                  onClick={() => {
                    setOpenRunId(item.screening_id);
                    setEditing(undefined);
                    setRerunScreeningId(undefined);
                    setSearch({ tab: "natural" });
                  }}
                >
                  查看结果
                </Button>
                <Button size="small" onClick={() => applySpec(item.spec)}>
                  按原日期重跑
                </Button>
              </Space>
            ),
          },
        ]}
      />
    </Space>
  );

  return (
    <section>
      <PageHeader
        title="智能选股"
        description="从自然语言、标准模板或已保存方案开始，统一查看历史结果并继续加入自选或回测。"
      />
      <Tabs
        activeKey={activeTab}
        onChange={(tab) => setSearch({ tab })}
        items={[
          {
            key: "natural",
            label: "自然语言选股",
            children: (
              <NaturalLanguageScreeningPane
                key={`${preset?.nonce ?? 0}:${openRunId ?? ""}`}
                preset={preset}
                editing={editing}
                rerunScreeningId={rerunScreeningId}
                openRunId={openRunId}
              />
            ),
          },
          { key: "templates", label: "选股模板", children: templateCards },
          { key: "mine", label: "我的选股方案", children: savedTable },
          { key: "history", label: "历史结果", children: historyTable },
        ]}
      />
    </section>
  );
}
