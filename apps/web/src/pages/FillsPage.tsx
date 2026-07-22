import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Card,
  DatePicker,
  Descriptions,
  Drawer,
  Empty,
  Input,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { getAccounts } from "../api/accounts";
import { getInstruments } from "../api/market";
import { getFill, getFills } from "../api/orders";
import { PageHeader } from "../components/PageHeader/PageHeader";
import type { FillSummary } from "../types/orders";

export function FillsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [page, setPage] = useState(1);
  const [accountId, setAccountId] = useState<string>();
  const [instrumentId, setInstrumentId] = useState<string>();
  const [orderId, setOrderId] = useState<string>();
  const [side, setSide] = useState<string>();
  const [executedFrom, setExecutedFrom] = useState<string>();
  const [executedTo, setExecutedTo] = useState<string>();
  const [selectedId, setSelectedId] = useState<string | undefined>(
    searchParams.get("fill_id") ?? undefined,
  );
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: getAccounts });
  const instruments = useQuery({
    queryKey: ["fill-instruments"],
    queryFn: () => getInstruments(""),
  });
  const fills = useQuery({
    queryKey: [
      "fills",
      page,
      accountId,
      instrumentId,
      orderId,
      side,
      executedFrom,
      executedTo,
    ],
    queryFn: () =>
      getFills({
        page,
        pageSize: 20,
        accountId,
        instrumentId,
        orderId,
        side,
        executedFrom,
        executedTo,
      }),
  });
  const detail = useQuery({
    queryKey: ["fill", selectedId],
    queryFn: () => getFill(selectedId ?? ""),
    enabled: Boolean(selectedId),
  });

  return (
    <section>
      <PageHeader
        title="成交记录"
        description="只读展示本地模拟 Broker 产生的 Fill、费用拆分和模拟账户现金影响。"
      />
      <Alert
        showIcon
        type="warning"
        title="仅包含本地模拟成交（SIMULATED）"
        description="本页不能创建、编辑、删除或强制记账；不连接真实券商或 MiniQMT，不会产生真实交易。"
      />
      <Card style={{ marginTop: 16 }}>
        <Space wrap style={{ marginBottom: 16 }}>
          <Select
            allowClear
            placeholder="账户"
            style={{ width: 200 }}
            options={accounts.data?.items.map((item) => ({
              value: item.id,
              label: item.name,
            }))}
            onChange={(value) => {
              setPage(1);
              setAccountId(typeof value === "string" ? value : undefined);
            }}
          />
          <Select
            allowClear
            showSearch
            placeholder="标的"
            style={{ width: 220 }}
            options={instruments.data?.items.map((item) => ({
              value: item.id,
              label: `${item.symbol}.${item.exchange}`,
            }))}
            onChange={(value) => {
              setPage(1);
              setInstrumentId(typeof value === "string" ? value : undefined);
            }}
          />
          <Input
            allowClear
            placeholder="关联订单编号"
            style={{ width: 260 }}
            onPressEnter={(event) => {
              setPage(1);
              setOrderId(event.currentTarget.value || undefined);
            }}
            onClear={() => setOrderId(undefined)}
          />
          <Select
            allowClear
            placeholder="方向"
            style={{ width: 120 }}
            options={[{ value: "BUY" }, { value: "SELL" }]}
            onChange={(value) => {
              setPage(1);
              setSide(typeof value === "string" ? value : undefined);
            }}
          />
          <DatePicker
            showTime
            placeholder="成交开始"
            onChange={(value) => setExecutedFrom(value?.toISOString())}
          />
          <DatePicker
            showTime
            placeholder="成交结束"
            onChange={(value) => setExecutedTo(value?.toISOString())}
          />
        </Space>
        {fills.isError ? (
          <Alert
            type="error"
            title="成交加载失败"
            description={fills.error.message}
          />
        ) : null}
        <Table<FillSummary>
          rowKey="fill_id"
          loading={fills.isLoading}
          dataSource={fills.data?.items ?? []}
          locale={{ emptyText: <Empty description="暂无模拟成交" /> }}
          pagination={{
            current: page,
            pageSize: 20,
            total: fills.data?.total ?? 0,
            onChange: setPage,
          }}
          onRow={(item) => ({ onClick: () => setSelectedId(item.fill_id) })}
          columns={[
            { title: "Fill", dataIndex: "fill_id", ellipsis: true },
            {
              title: "标的",
              render: (_, item) =>
                `${item.instrument.symbol}.${item.instrument.exchange}`,
            },
            {
              title: "方向",
              dataIndex: "side",
              render: (value: string) => (
                <Tag color={value === "BUY" ? "red" : "green"}>{value}</Tag>
              ),
            },
            { title: "数量", dataIndex: "quantity" },
            { title: "价格", dataIndex: "price" },
            { title: "成交额", dataIndex: "gross_amount" },
            { title: "总费用", dataIndex: "total_fee" },
            { title: "现金影响", dataIndex: "net_cash_effect" },
            {
              title: "执行时间",
              dataIndex: "executed_at",
              render: (value: string) => new Date(value).toLocaleString(),
            },
          ]}
        />
      </Card>
      <Drawer
        title="成交详情（Fill，只读）"
        open={Boolean(selectedId)}
        onClose={() => {
          setSelectedId(undefined);
          const next = new URLSearchParams(searchParams);
          next.delete("fill_id");
          setSearchParams(next, { replace: true });
        }}
        size="large"
      >
        {detail.data ? (
          <>
            <Descriptions
              bordered
              column={2}
              items={[
                {
                  key: "fill",
                  label: "Fill ID",
                  children: detail.data.fill_id,
                },
                {
                  key: "attempt",
                  label: "ExecutionAttempt",
                  children: detail.data.execution_attempt_id ?? "—",
                },
                {
                  key: "order",
                  label: "Order",
                  children: detail.data.order_id,
                },
                {
                  key: "reference",
                  label: "执行引用",
                  children: detail.data.execution_reference ?? "—",
                },
                {
                  key: "quantity",
                  label: "数量",
                  children: detail.data.quantity,
                },
                { key: "price", label: "价格", children: detail.data.price },
                {
                  key: "gross",
                  label: "成交额",
                  children: detail.data.gross_amount,
                },
                {
                  key: "cash",
                  label: "现金影响",
                  children: detail.data.net_cash_effect,
                },
                {
                  key: "commission",
                  label: "佣金",
                  children: detail.data.commission,
                },
                {
                  key: "stamp",
                  label: "印花税",
                  children: detail.data.stamp_duty,
                },
                {
                  key: "transfer",
                  label: "过户费",
                  children: detail.data.transfer_fee,
                },
                {
                  key: "other",
                  label: "其他费用",
                  children: detail.data.other_fee,
                },
                {
                  key: "total",
                  label: "总费用",
                  children: detail.data.total_fee,
                },
                {
                  key: "time",
                  label: "执行时间",
                  children: new Date(detail.data.executed_at).toLocaleString(),
                },
              ]}
            />
            <Typography.Paragraph type="secondary" style={{ marginTop: 16 }}>
              所有 Decimal 均按后端字符串展示，页面不自行重算权威账本。
            </Typography.Paragraph>
          </>
        ) : null}
      </Drawer>
    </section>
  );
}
