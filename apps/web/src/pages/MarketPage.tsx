import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
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

import {
  addWatchlistItem,
  createWatchlist,
  deleteWatchlist,
  getBars,
  getInstruments,
  getMarketSources,
  getRealtimeMarketStatus,
  getWatchlist,
  getWatchlists,
  removeWatchlistItem,
  reorderWatchlist,
  updateWatchlist,
  updateWatchlistItem,
} from "../api/market";
import { CandlestickChart } from "../components/CandlestickChart/CandlestickChart";
import { PageHeader } from "../components/PageHeader/PageHeader";
import { useMarketQuotes } from "../hooks/useMarketQuotes";
import type {
  AdjustmentType,
  Instrument,
  MarketTimeframe,
  WatchlistItem,
} from "../types/market";

export function MarketPage() {
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const [keyword, setKeyword] = useState("");
  const [debouncedKeyword, setDebouncedKeyword] = useState("");
  const [selectedWatchlist, setSelectedWatchlist] = useState<string>();
  const [selectedInstrument, setSelectedInstrument] = useState<Instrument>();
  const [timeframe, setTimeframe] = useState<MarketTimeframe>("DAY_1");
  const [adjustment, setAdjustment] = useState<AdjustmentType>("NONE");
  const [watchlistDialog, setWatchlistDialog] = useState<
    "create" | "edit" | null
  >(null);
  const [watchlistName, setWatchlistName] = useState("");
  const [watchlistDescription, setWatchlistDescription] = useState("");
  const [noteItem, setNoteItem] = useState<WatchlistItem>();
  const [note, setNote] = useState("");

  useEffect(() => {
    const id = window.setTimeout(() => setDebouncedKeyword(keyword), 250);
    return () => window.clearTimeout(id);
  }, [keyword]);

  const instruments = useQuery({
    queryKey: ["instruments", debouncedKeyword],
    queryFn: () => getInstruments(debouncedKeyword),
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
  const sources = useQuery({
    queryKey: ["market-sources"],
    queryFn: getMarketSources,
    refetchInterval: 30_000,
  });
  const realtimeStatus = useQuery({
    queryKey: ["market-realtime-status"],
    queryFn: getRealtimeMarketStatus,
    refetchInterval: 15_000,
  });
  const effectiveInstrument =
    selectedInstrument ?? detail.data?.items[0]?.instrument;
  const bars = useQuery({
    queryKey: ["market-bars", effectiveInstrument?.id, timeframe, adjustment],
    queryFn: () =>
      getBars(effectiveInstrument?.id ?? "", timeframe, adjustment),
    enabled: Boolean(effectiveInstrument),
  });
  const subscribedIds = (detail.data?.items ?? []).map(
    (item) => item.instrument.id,
  );
  const live = useMarketQuotes(subscribedIds);

  const refreshWatchlists = async () => {
    await queryClient.invalidateQueries({ queryKey: ["watchlists"] });
    await queryClient.invalidateQueries({
      queryKey: ["watchlist", effectiveWatchlist],
    });
  };
  const action = useMutation({
    mutationFn: async (operation: () => Promise<unknown>) => operation(),
    onSuccess: async () => {
      await refreshWatchlists();
      void message.success("操作已保存");
    },
    onError: (error: Error) => void message.error(error.message),
  });

  const currentWatchlist = useMemo(
    () => watchlists.data?.find((item) => item.id === effectiveWatchlist),
    [effectiveWatchlist, watchlists.data],
  );
  const latest = bars.data?.items.at(-1);
  const liveQuote = effectiveInstrument
    ? live.quotes[effectiveInstrument.id]
    : undefined;
  const displayedPrice = liveQuote?.last_price ?? latest?.close;
  const referencePrice = liveQuote?.previous_close ?? latest?.open;
  const change =
    displayedPrice && referencePrice
      ? Number(displayedPrice) - Number(referencePrice)
      : 0;

  function openWatchlistDialog(mode: "create" | "edit") {
    setWatchlistDialog(mode);
    setWatchlistName(mode === "edit" ? (currentWatchlist?.name ?? "") : "");
    setWatchlistDescription(
      mode === "edit" ? (currentWatchlist?.description ?? "") : "",
    );
  }

  function saveWatchlist() {
    const name = watchlistName.trim();
    if (!name) return void message.warning("请输入自选列表名称");
    action.mutate(() =>
      watchlistDialog === "edit" && effectiveWatchlist
        ? updateWatchlist(
            effectiveWatchlist,
            name,
            watchlistDescription || null,
          )
        : createWatchlist(name, watchlistDescription || null),
    );
    setWatchlistDialog(null);
  }

  function moveItem(index: number, direction: -1 | 1) {
    if (!detail.data || !effectiveWatchlist) return;
    const reordered = [...detail.data.items];
    const target = index + direction;
    if (target < 0 || target >= reordered.length) return;
    [reordered[index], reordered[target]] = [
      reordered[target],
      reordered[index],
    ];
    action.mutate(() =>
      reorderWatchlist(
        effectiveWatchlist,
        reordered.map((item) => item.id),
      ),
    );
  }

  return (
    <div className="market-page">
      <PageHeader
        title="行情"
        description="行情工作台：离线演示行情、自选股与可追溯的数据新鲜度"
        action={
          <Space>
            {(sources.data ?? []).map((source) => (
              <Tag
                key={source.id}
                color={source.status === "ACTIVE" ? "green" : "default"}
              >
                {source.source_code} · {source.status}
              </Tag>
            ))}
            <Tag
              color={
                realtimeStatus.data?.enabled &&
                realtimeStatus.data.state !== "FAILED"
                  ? "green"
                  : "default"
              }
            >
              FREE_BEST_EFFORT · {realtimeStatus.data?.state ?? "UNKNOWN"}
            </Tag>
            <Tag color={live.status === "connected" ? "green" : "orange"}>
              实时 · {live.status}
            </Tag>
            <Button
              icon={<ReloadOutlined />}
              onClick={() => void bars.refetch()}
            >
              刷新
            </Button>
          </Space>
        }
      />
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
                      modal.confirm({
                        title: "删除自选列表？",
                        content:
                          "列表内条目会一并删除，行情基础数据不会受影响。",
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
                  {(detail.data?.items ?? []).map((item, index) => (
                    <div
                      key={item.id}
                      role="listitem"
                      className={
                        effectiveInstrument?.id === item.instrument.id
                          ? "market-list-item watchlist-list-item selected"
                          : "market-list-item watchlist-list-item"
                      }
                      onClick={() => setSelectedInstrument(item.instrument)}
                    >
                      <div className="market-list-copy">
                        <Typography.Text
                          strong
                        >{`${item.instrument.symbol} ${item.instrument.name}`}</Typography.Text>
                        <Typography.Text type="secondary">
                          {item.note || item.instrument.exchange}
                        </Typography.Text>
                        <Typography.Text>
                          {live.quotes[item.instrument.id]?.last_price ?? "—"}
                        </Typography.Text>
                      </div>
                      <Space size={0}>
                        <Button
                          aria-label="上移"
                          type="text"
                          size="small"
                          icon={<ArrowUpOutlined />}
                          disabled={index === 0}
                          onClick={(event) => {
                            event.stopPropagation();
                            moveItem(index, -1);
                          }}
                        />
                        <Button
                          aria-label="下移"
                          type="text"
                          size="small"
                          icon={<ArrowDownOutlined />}
                          disabled={
                            index === (detail.data?.items.length ?? 0) - 1
                          }
                          onClick={(event) => {
                            event.stopPropagation();
                            moveItem(index, 1);
                          }}
                        />
                        <Button
                          aria-label="编辑备注"
                          type="text"
                          size="small"
                          icon={<EditOutlined />}
                          onClick={(event) => {
                            event.stopPropagation();
                            setNoteItem(item);
                            setNote(item.note ?? "");
                          }}
                        />
                        <Button
                          aria-label="移除自选股"
                          danger
                          type="text"
                          size="small"
                          icon={<DeleteOutlined />}
                          onClick={(event) => {
                            event.stopPropagation();
                            action.mutate(() =>
                              removeWatchlistItem(item.watchlist_id, item.id),
                            );
                          }}
                        />
                      </Space>
                    </div>
                  ))}
                </div>
                {!detail.isLoading && !detail.data?.items.length ? (
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
          <Card title="标的目录">
            <Input.Search
              aria-label="搜索标的"
              value={keyword}
              placeholder="代码或名称"
              allowClear
              onChange={(event) => setKeyword(event.target.value)}
            />
            <Spin spinning={instruments.isLoading}>
              <div className="market-list" role="list">
                {(instruments.data?.items ?? []).map((instrument) => {
                  const added = detail.data?.items.some(
                    (item) => item.instrument.id === instrument.id,
                  );
                  return (
                    <div
                      key={instrument.id}
                      role="listitem"
                      className="market-list-item"
                      onClick={() => setSelectedInstrument(instrument)}
                    >
                      <div className="market-list-copy">
                        <Typography.Text
                          strong
                        >{`${instrument.symbol} ${instrument.name}`}</Typography.Text>
                        <Typography.Text type="secondary">
                          {`${instrument.exchange} · ${instrument.asset_type}`}
                        </Typography.Text>
                      </div>
                      <Button
                        aria-label={`添加 ${instrument.symbol}`}
                        type="text"
                        icon={<PlusOutlined />}
                        disabled={!effectiveWatchlist || added}
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
            </Spin>
          </Card>
        </Col>
        <Col xs={24} xl={13}>
          <Card
            title={
              effectiveInstrument
                ? `${effectiveInstrument.symbol} ${effectiveInstrument.name}`
                : "行情详情"
            }
            extra={
              <Space wrap>
                <Segmented<MarketTimeframe>
                  value={timeframe}
                  options={[
                    { label: "日线", value: "DAY_1" },
                    { label: "1分钟", value: "MINUTE_1" },
                  ]}
                  onChange={setTimeframe}
                />
                <Select<AdjustmentType>
                  value={adjustment}
                  style={{ width: 100 }}
                  options={[
                    { label: "不复权", value: "NONE" },
                    { label: "前复权", value: "FORWARD" },
                    { label: "后复权", value: "BACKWARD" },
                  ]}
                  onChange={setAdjustment}
                />
              </Space>
            }
          >
            {!effectiveInstrument ? (
              <Empty description="选择一个标的查看行情" />
            ) : (
              <Spin spinning={bars.isFetching}>
                <Row gutter={16} className="market-statistics">
                  <Col span={6}>
                    <Statistic
                      title="最新价"
                      value={displayedPrice ? Number(displayedPrice) : "--"}
                      precision={3}
                    />
                  </Col>
                  <Col span={6}>
                    <Statistic
                      title="区间涨跌"
                      value={change}
                      precision={3}
                      styles={{
                        content: { color: change >= 0 ? "#cf1322" : "#08979c" },
                      }}
                    />
                  </Col>
                  <Col span={6}>
                    <Statistic
                      title="成交量"
                      value={
                        liveQuote?.volume
                          ? Number(liveQuote.volume)
                          : latest
                            ? Number(latest.volume)
                            : 0
                      }
                    />
                  </Col>
                  <Col span={6}>
                    <Typography.Text type="secondary">新鲜度</Typography.Text>
                    <br />
                    <Tag
                      color={
                        bars.data?.freshness.freshness_status === "NORMAL"
                          ? "green"
                          : "orange"
                      }
                    >
                      {liveQuote?.freshness ??
                        bars.data?.freshness.freshness_status ??
                        "UNKNOWN"}
                    </Tag>
                  </Col>
                </Row>
                {bars.isError ? (
                  <Empty description={bars.error.message} />
                ) : (
                  <CandlestickChart
                    bars={bars.data?.items ?? []}
                    loading={bars.isLoading}
                  />
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
        </Space>
      </Modal>
      <Modal
        title="编辑自选股备注"
        open={Boolean(noteItem)}
        confirmLoading={action.isPending}
        onCancel={() => setNoteItem(undefined)}
        onOk={() => {
          if (noteItem) {
            action.mutate(() =>
              updateWatchlistItem(noteItem.watchlist_id, noteItem.id, note),
            );
          }
          setNoteItem(undefined);
        }}
      >
        <Input.TextArea
          aria-label="自选股备注"
          maxLength={500}
          showCount
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />
      </Modal>
    </div>
  );
}
