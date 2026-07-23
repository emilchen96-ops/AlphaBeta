import {
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Empty,
  Flex,
  Input,
  Modal,
  Row,
  Segmented,
  Select,
  Space,
  Spin,
  Statistic,
  Tag,
  Typography,
} from "antd";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import {
  addWatchlistItem,
  createWatchlist,
  deleteWatchlist,
  getBars,
  getInstruments,
  getWatchlist,
  getWatchlists,
  removeWatchlistItem,
  updateWatchlist,
} from "../api/market";
import {
  getActiveSubscriptions,
  getMiniQMTStatus,
  rebuildSubscriptions,
  requestMiniQMTHistoryBackfill,
  setTemporarySubscription,
  syncSubscriptions,
} from "../api/miniqmt";
import { CandlestickChart } from "../components/CandlestickChart/CandlestickChart";
import { PageHeader } from "../components/PageHeader/PageHeader";
import { useMarketQuotes } from "../hooks/useMarketQuotes";
import type {
  Instrument,
  MarketTimeframe,
  PriceAdjustmentMode,
} from "../types/market";
import {
  displayEnum,
  formatDateTime,
  formatInstrument,
  formatNumber,
  formatPrice,
} from "../utils/display";

type MarketViewPeriod = MarketTimeframe | "TIMESHARE";

const periodOptions: { label: string; value: MarketViewPeriod }[] = [
  { label: "分时", value: "TIMESHARE" },
  { label: "日线", value: "DAY_1" },
  { label: "1分钟", value: "MINUTE_1" },
  { label: "5分钟", value: "MINUTE_5" },
  { label: "15分钟", value: "MINUTE_15" },
  { label: "30分钟", value: "MINUTE_30" },
  { label: "60分钟", value: "MINUTE_60" },
];

function miniQMTState(
  configured: boolean | undefined,
  state: string | undefined,
) {
  if (!configured) return { color: "default", text: "尚未配置" };
  if (state === "CONNECTED" || state === "RUNNING")
    return { color: "green", text: "已连接" };
  if (state === "CONNECTING") return { color: "blue", text: "正在连接" };
  if (state === "FAILED") return { color: "red", text: "连接失败" };
  return { color: "orange", text: "等待行情代理" };
}

export function MarketPage() {
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const [searchText, setSearchText] = useState("");
  const [submittedKeyword, setSubmittedKeyword] = useState("");
  const [selectedWatchlist, setSelectedWatchlist] = useState<string>();
  const [selectedInstrument, setSelectedInstrument] = useState<Instrument>();
  const [timeframe, setTimeframe] = useState<MarketViewPeriod>("DAY_1");
  const [adjustmentMode, setAdjustmentMode] =
    useState<PriceAdjustmentMode>("RAW");
  const [watchlistDialog, setWatchlistDialog] = useState<
    "create" | "edit" | null
  >(null);
  const [watchlistName, setWatchlistName] = useState("");
  const [watchlistDescription, setWatchlistDescription] = useState("");
  const [watchlistRealtime, setWatchlistRealtime] = useState(true);

  const instruments = useQuery({
    queryKey: ["instruments", submittedKeyword],
    queryFn: async () => {
      const active = await getInstruments(submittedKeyword);
      if (!submittedKeyword || active.total > 0) return active;
      return getInstruments(submittedKeyword, true);
    },
  });
  const watchlists = useQuery({
    queryKey: ["watchlists"],
    queryFn: getWatchlists,
  });
  const effectiveWatchlist = selectedWatchlist ?? watchlists.data?.[0]?.id;
  const detail = useQuery({
    queryKey: ["watchlist", effectiveWatchlist],
    queryFn: () => getWatchlist(effectiveWatchlist ?? ""),
    enabled: Boolean(effectiveWatchlist),
  });
  const status = useQuery({
    queryKey: ["miniqmt-status"],
    queryFn: getMiniQMTStatus,
    refetchInterval: 10_000,
  });
  const subscriptions = useQuery({
    queryKey: ["miniqmt-active-subscriptions"],
    queryFn: getActiveSubscriptions,
    refetchInterval: 10_000,
  });

  const formalWatchlistItems = (detail.data?.items ?? []).filter(
    (item) =>
      item.instrument.market === "CN_A" &&
      /^\d{6}$/.test(item.instrument.symbol),
  );
  const effectiveInstrument =
    selectedInstrument ?? formalWatchlistItems[0]?.instrument;
  const queryTimeframe: MarketTimeframe =
    timeframe === "TIMESHARE" ? "MINUTE_1" : timeframe;
  const bars = useQuery({
    queryKey: [
      "market-bars",
      effectiveInstrument?.id,
      timeframe,
      adjustmentMode,
    ],
    queryFn: () =>
      getBars(effectiveInstrument?.id ?? "", queryTimeframe, adjustmentMode),
    enabled: Boolean(effectiveInstrument?.is_active),
  });

  useEffect(() => {
    if (!effectiveInstrument?.is_active) return;
    let disposed = false;
    const update = async (enabled: boolean) => {
      await setTemporarySubscription(effectiveInstrument.id, enabled);
      await rebuildSubscriptions();
      await syncSubscriptions();
      if (!disposed) {
        await queryClient.invalidateQueries({
          queryKey: ["miniqmt-active-subscriptions"],
        });
      }
    };
    void update(true).catch(() => undefined);
    return () => {
      disposed = true;
      void update(false).catch(() => undefined);
    };
  }, [effectiveInstrument?.id, effectiveInstrument?.is_active, queryClient]);

  const watchlistIds = formalWatchlistItems.map((item) => item.instrument.id);
  const quoteIds = effectiveInstrument
    ? [...watchlistIds, effectiveInstrument.id]
    : watchlistIds;
  const live = useMarketQuotes(quoteIds);
  const liveQuote = effectiveInstrument
    ? live.quotes[effectiveInstrument.id]
    : undefined;
  const activeSubscription = effectiveInstrument
    ? subscriptions.data?.items.find(
        (item) => item.instrument_id === effectiveInstrument.id,
      )
    : undefined;

  const action = useMutation({
    mutationFn: async (operation: () => Promise<unknown>) => operation(),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["watchlists"] });
      await queryClient.invalidateQueries({
        queryKey: ["watchlist", effectiveWatchlist],
      });
      void message.success("操作已保存");
    },
    onError: (error: Error) => void message.error(error.message),
  });
  const backfill = useMutation({
    mutationFn: async () => {
      if (!effectiveInstrument) throw new Error("请先选择股票");
      const end = new Date();
      const start = new Date(end);
      const requestedTimeframe =
        queryTimeframe === "DAY_1" ? "DAY_1" : "MINUTE_1";
      start.setUTCDate(
        start.getUTCDate() - (requestedTimeframe === "DAY_1" ? 3649 : 10),
      );
      return requestMiniQMTHistoryBackfill({
        instrument_ids: [effectiveInstrument.id],
        timeframe: requestedTimeframe,
        start_at: start.toISOString(),
        end_at: end.toISOString(),
      });
    },
    onSuccess: () => {
      void message.success(
        "MiniQMT 历史补数请求已进入队列，完成后刷新本页即可查看",
      );
    },
    onError: (error: Error) => void message.error(error.message),
  });

  const currentWatchlist = useMemo(
    () => watchlists.data?.find((item) => item.id === effectiveWatchlist),
    [effectiveWatchlist, watchlists.data],
  );
  const latest = bars.data?.items.at(-1);
  const previous = bars.data?.items.at(-2);
  const displayedPrice = liveQuote?.last_price ?? latest?.close;
  const referencePrice = liveQuote?.previous_close ?? previous?.close;
  const change =
    displayedPrice && referencePrice
      ? Number(displayedPrice) - Number(referencePrice)
      : null;
  const changePercent =
    change !== null && referencePrice && Number(referencePrice) !== 0
      ? (change / Number(referencePrice)) * 100
      : null;
  const quoteBarGapMinutes =
    liveQuote?.quote_time && latest?.bar_time
      ? Math.abs(
          new Date(liveQuote.quote_time).getTime() -
            new Date(latest.bar_time).getTime(),
        ) / 60_000
      : null;
  const quoteBarMismatch =
    quoteBarGapMinutes !== null &&
    quoteBarGapMinutes > (queryTimeframe === "DAY_1" ? 24 * 60 : 90);
  const connection = miniQMTState(
    status.data?.configured,
    status.data?.agent?.state ?? status.data?.state,
  );

  function openWatchlistDialog(mode: "create" | "edit") {
    setWatchlistDialog(mode);
    setWatchlistName(mode === "edit" ? (currentWatchlist?.name ?? "") : "");
    setWatchlistDescription(
      mode === "edit" ? (currentWatchlist?.description ?? "") : "",
    );
    setWatchlistRealtime(
      mode === "edit" ? (currentWatchlist?.realtime_enabled ?? true) : true,
    );
  }

  function saveWatchlist() {
    const name = watchlistName.trim();
    if (!name) {
      void message.warning("请输入自选列表名称");
      return;
    }
    action.mutate(() =>
      watchlistDialog === "edit" && effectiveWatchlist
        ? updateWatchlist(
            effectiveWatchlist,
            name,
            watchlistDescription || null,
            watchlistRealtime,
          )
        : createWatchlist(
            name,
            watchlistDescription || null,
            watchlistRealtime,
          ),
    );
    setWatchlistDialog(null);
  }

  return (
    <div className="market-page">
      <PageHeader
        title="行情"
        description="以 MiniQMT 为唯一正式行情源，统一查看 A 股目录、实时快照、历史日线与分钟 K 线。"
        action={
          <Button
            icon={<ReloadOutlined />}
            onClick={() => {
              void Promise.all([
                status.refetch(),
                subscriptions.refetch(),
                bars.refetch(),
              ]);
            }}
          >
            刷新行情
          </Button>
        }
      />

      <Card
        size="small"
        className="market-source-status"
        title="MiniQMT 行情状态"
      >
        <Flex justify="space-between" align="center" wrap gap={12}>
          <Space wrap>
            <Tag color={connection.color}>行情连接：{connection.text}</Tag>
            <Tag color={live.status === "connected" ? "green" : "orange"}>
              页面推送：{displayEnum(live.status.toUpperCase())}
            </Tag>
            <Tag
              color={
                activeSubscription?.status === "SUBSCRIBED" ? "green" : "blue"
              }
            >
              当前标的订阅：
              {effectiveInstrument
                ? displayEnum(activeSubscription?.status ?? "WAITING")
                : "未选择"}
            </Tag>
            <Tag>
              目录标的：{status.data?.agent?.catalog_instrument_count ?? 0}
            </Tag>
            <Tag color="gold">交易能力：关闭（只读行情）</Tag>
          </Space>
          <Typography.Text type="secondary">
            最近行情：
            {formatDateTime(
              status.data?.agent?.last_market_time ??
                status.data?.agent?.last_received_at,
            )}
          </Typography.Text>
        </Flex>
      </Card>

      {!status.data?.configured ? (
        <Alert
          showIcon
          type="warning"
          title="MiniQMT 行情尚未配置"
          description="请登录并保持 MiniQMT 运行，然后启动 Windows 行情代理。本系统不会连接交易接口，也不会下单。"
        />
      ) : status.data?.agent?.error_message ? (
        <Alert
          showIcon
          type="error"
          title="MiniQMT 行情连接异常"
          description={`${status.data.agent.error_code ?? "连接错误"}：${status.data.agent.error_message}`}
        />
      ) : null}

      <Row gutter={[16, 16]}>
        <Col xs={24} xl={5}>
          <Card
            title="自选列表"
            extra={
              <Button
                aria-label="新建自选列表"
                type="text"
                icon={<PlusOutlined />}
                onClick={() => openWatchlistDialog("create")}
              />
            }
          >
            <Flex vertical gap={12}>
              <Select
                aria-label="选择自选列表"
                value={effectiveWatchlist}
                placeholder="选择自选列表"
                options={(watchlists.data ?? []).map((item) => ({
                  value: item.id,
                  label: item.name,
                }))}
                onChange={(value) => {
                  setSelectedWatchlist(value);
                  setSelectedInstrument(undefined);
                }}
              />
              {currentWatchlist ? (
                <Space>
                  <Button
                    size="small"
                    icon={<EditOutlined />}
                    onClick={() => openWatchlistDialog("edit")}
                  >
                    编辑
                  </Button>
                  <Button
                    size="small"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={() => {
                      void modal.confirm({
                        title: "删除自选列表？",
                        content: "仅删除列表，不会删除股票和行情数据。",
                        onOk: () => {
                          setSelectedWatchlist(undefined);
                          action.mutate(() =>
                            deleteWatchlist(currentWatchlist.id),
                          );
                        },
                      });
                    }}
                  >
                    删除
                  </Button>
                </Space>
              ) : null}
              <Spin spinning={detail.isLoading}>
                <div className="market-list" role="list">
                  {formalWatchlistItems.map((item) => (
                    <div
                      key={item.id}
                      role="listitem"
                      className={
                        effectiveInstrument?.id === item.instrument.id
                          ? "market-list-item selected"
                          : "market-list-item"
                      }
                      onClick={() => setSelectedInstrument(item.instrument)}
                    >
                      <div className="market-list-copy">
                        <Typography.Text strong>
                          {formatInstrument(item.instrument)}
                        </Typography.Text>
                        <Typography.Text type="secondary">
                          {live.quotes[item.instrument.id]?.last_price ??
                            "暂无实时价"}
                        </Typography.Text>
                      </div>
                      <Button
                        aria-label={`移除 ${item.instrument.symbol}`}
                        danger
                        type="text"
                        icon={<DeleteOutlined />}
                        onClick={(event) => {
                          event.stopPropagation();
                          action.mutate(() =>
                            removeWatchlistItem(item.watchlist_id, item.id),
                          );
                        }}
                      />
                    </div>
                  ))}
                </div>
                {!detail.isLoading && !formalWatchlistItems.length ? (
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description="暂无自选股"
                  />
                ) : null}
              </Spin>
            </Flex>
          </Card>
        </Col>

        <Col xs={24} xl={6}>
          <Card title="A 股标的目录">
            <Input.Search
              aria-label="搜索 A 股"
              value={searchText}
              placeholder="输入代码或名称，如 300285、300285.SZ"
              allowClear
              enterButton="搜索"
              onChange={(event) => setSearchText(event.target.value)}
              onSearch={(value) => setSubmittedKeyword(value.trim())}
            />
            <Spin spinning={instruments.isFetching}>
              <div className="market-list" role="list">
                {(instruments.data?.items ?? []).map((instrument) => {
                  const added = formalWatchlistItems.some(
                    (item) => item.instrument.id === instrument.id,
                  );
                  return (
                    <div
                      key={instrument.id}
                      role="listitem"
                      className={
                        effectiveInstrument?.id === instrument.id
                          ? "market-list-item selected"
                          : "market-list-item"
                      }
                      onClick={() => setSelectedInstrument(instrument)}
                    >
                      <div className="market-list-copy">
                        <Typography.Text strong>
                          {formatInstrument(instrument)}
                        </Typography.Text>
                        <Typography.Text type="secondary">
                          {instrument.asset_type === "ETF"
                            ? "交易型基金"
                            : "A股"}
                          {!instrument.is_active ? " · 已退市或停用" : ""}
                        </Typography.Text>
                      </div>
                      <Button
                        aria-label={`添加 ${instrument.symbol}`}
                        type="text"
                        icon={<PlusOutlined />}
                        disabled={
                          !effectiveWatchlist || added || !instrument.is_active
                        }
                        onClick={(event) => {
                          event.stopPropagation();
                          if (effectiveWatchlist)
                            action.mutate(() =>
                              addWatchlistItem(
                                effectiveWatchlist,
                                instrument.id,
                              ),
                            );
                        }}
                      />
                    </div>
                  );
                })}
              </div>
              {!instruments.isFetching && !instruments.data?.items.length ? (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description={
                    submittedKeyword
                      ? "MiniQMT 目录中没有匹配的在市 A 股"
                      : "尚未同步 MiniQMT A 股目录"
                  }
                />
              ) : null}
            </Spin>
          </Card>
        </Col>

        <Col xs={24} xl={13}>
          <Card
            title={
              effectiveInstrument
                ? formatInstrument(effectiveInstrument)
                : "行情详情"
            }
            extra={
              <Space wrap>
                <Segmented<MarketViewPeriod>
                  value={timeframe}
                  options={periodOptions}
                  onChange={(value) => {
                    setTimeframe(value);
                    if (value !== "DAY_1") setAdjustmentMode("RAW");
                  }}
                />
                <Select<PriceAdjustmentMode>
                  aria-label="复权方式"
                  value={adjustmentMode}
                  disabled={timeframe !== "DAY_1"}
                  style={{ width: 124 }}
                  options={[
                    { label: "不复权（RAW）", value: "RAW" },
                    { label: "前复权（QFQ）", value: "QFQ" },
                  ]}
                  onChange={setAdjustmentMode}
                />
              </Space>
            }
          >
            {!effectiveInstrument ? (
              <Empty description="请从标的目录或自选列表选择一只股票" />
            ) : (
              <Spin spinning={bars.isFetching}>
                {live.status !== "connected" &&
                effectiveInstrument.is_active ? (
                  <Alert
                    showIcon
                    type="warning"
                    title="页面实时行情推送已断开"
                    description="当前显示的实时价格可能已经过期；历史K线仍可查看。系统不会改用其他行情源。"
                  />
                ) : null}
                {!effectiveInstrument.is_active ? (
                  <Alert
                    showIcon
                    type="warning"
                    title="该标的已退市或停用"
                    description="可查看已经保存的历史行情，但不会发起实时订阅。"
                  />
                ) : null}
                {quoteBarMismatch ? (
                  <Alert
                    showIcon
                    type="warning"
                    title="实时价格与K线末端时间不一致"
                    description="实时价格仍来自 MiniQMT，但本地历史K线尚未更新到同一时间。可在下方补充历史行情。"
                  />
                ) : null}
                <Row gutter={16} className="market-statistics">
                  <Col xs={12} md={6}>
                    <Statistic
                      title="最新价"
                      value={formatPrice(displayedPrice)}
                    />
                  </Col>
                  <Col xs={12} md={6}>
                    <Statistic
                      title="涨跌额 / 涨跌幅"
                      value={
                        change === null
                          ? "—"
                          : `${formatNumber(change, {
                              minimumFractionDigits: 2,
                              maximumFractionDigits: 4,
                            })} / ${formatNumber(changePercent, {
                              minimumFractionDigits: 2,
                              maximumFractionDigits: 2,
                            })}%`
                      }
                      styles={{
                        content: {
                          color:
                            change === null
                              ? undefined
                              : change >= 0
                                ? "#cf1322"
                                : "#08979c",
                        },
                      }}
                    />
                  </Col>
                  <Col xs={12} md={6}>
                    <Statistic
                      title="成交量"
                      value={formatNumber(liveQuote?.volume ?? latest?.volume)}
                    />
                  </Col>
                  <Col xs={12} md={6}>
                    <Typography.Text type="secondary">更新时间</Typography.Text>
                    <br />
                    <Typography.Text>
                      {formatDateTime(
                        liveQuote?.quote_time ??
                          latest?.bar_time ??
                          bars.data?.freshness.latest_received_at,
                      )}
                    </Typography.Text>
                  </Col>
                </Row>
                {!effectiveInstrument.is_active ? (
                  <Empty description="该股票已退市，当前没有实时行情；本地未下载 MiniQMT 历史行情" />
                ) : bars.isError ? (
                  <Alert
                    showIcon
                    type="error"
                    title="历史行情读取失败"
                    description={bars.error.message}
                    action={
                      <Button size="small" onClick={() => void bars.refetch()}>
                        重试
                      </Button>
                    }
                  />
                ) : !bars.isLoading && !bars.data?.items.length ? (
                  <Empty
                    description={
                      timeframe === "DAY_1"
                        ? "该标的尚无 MiniQMT 历史日线"
                        : "该标的尚无 MiniQMT 历史分钟线"
                    }
                  >
                    <Space>
                      <Button
                        type="primary"
                        loading={backfill.isPending}
                        onClick={() => backfill.mutate()}
                      >
                        从 MiniQMT 补充历史行情
                      </Button>
                      <Link to="/market-data-center">查看数据中心</Link>
                    </Space>
                  </Empty>
                ) : (
                  <>
                    <CandlestickChart
                      bars={bars.data?.items ?? []}
                      loading={bars.isLoading}
                      variant={
                        timeframe === "TIMESHARE" ? "line" : "candlestick"
                      }
                    />
                    <Flex justify="space-between" wrap gap={8}>
                      <Typography.Text type="secondary">
                        数据源：MiniQMT ·{" "}
                        {timeframe === "TIMESHARE"
                          ? "分时"
                          : displayEnum(timeframe)}{" "}
                        · {displayEnum(adjustmentMode)}
                      </Typography.Text>
                      <Typography.Text type="secondary">
                        数据范围：
                        {formatDateTime(bars.data?.items[0]?.bar_time)} 至{" "}
                        {formatDateTime(bars.data?.items.at(-1)?.bar_time)}
                      </Typography.Text>
                    </Flex>
                  </>
                )}
              </Spin>
            )}
          </Card>
        </Col>
      </Row>

      <Modal
        title={watchlistDialog === "edit" ? "编辑自选列表" : "新建自选列表"}
        open={watchlistDialog !== null}
        onOk={saveWatchlist}
        onCancel={() => setWatchlistDialog(null)}
        confirmLoading={action.isPending}
      >
        <Space orientation="vertical" style={{ width: "100%" }}>
          <Input
            aria-label="自选列表名称"
            maxLength={128}
            value={watchlistName}
            placeholder="名称"
            onChange={(event) => setWatchlistName(event.target.value)}
          />
          <Input.TextArea
            aria-label="自选列表描述"
            maxLength={1000}
            value={watchlistDescription}
            placeholder="描述（可选）"
            onChange={(event) => setWatchlistDescription(event.target.value)}
          />
          <Typography.Text type="secondary">
            自选列表默认参与 MiniQMT 行情订阅，可在编辑时调整。
          </Typography.Text>
        </Space>
      </Modal>
    </div>
  );
}
