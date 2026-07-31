import { LinkOutlined, PlusOutlined } from "@ant-design/icons";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from "antd";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import {
  addManualInformation,
  getInformationItem,
  getInformationItems,
  getInformationSources,
  getMarketEvent,
  getMarketEvents,
} from "../api/information";
import { getInstruments } from "../api/market";
import { PageHeader } from "../components/PageHeader/PageHeader";
import type { InformationDetail } from "../types/information";
import { displayEnum } from "../utils/display";

const eventTypes = [
  "COMPANY_ANNOUNCEMENT",
  "COMPANY_NEWS",
  "INDUSTRY",
  "MACRO",
  "REGULATION",
  "PRODUCT",
  "EARNINGS",
  "OTHER",
];
const directions = ["POSITIVE", "NEGATIVE", "NEUTRAL", "MIXED", "UNKNOWN"];

const disclaimer = (
  <Alert
    showIcon
    type="warning"
    title="外部来源或用户输入，尚未经过 AI 分析"
    description="系统未验证所有事实真实性；内容不构成投资建议，也不会创建研究信号（Signal）或订单。请核对原始来源。"
  />
);

interface ManualValues {
  source_name: string;
  title: string;
  content: string;
  source_url?: string;
  published_at?: string;
  instrument_ids?: string[];
  theme_key?: string;
  theme_name?: string;
  event_type: string;
  direction: string;
  importance?: string;
}

function SourceLink({ item }: { item: InformationDetail }) {
  return item.source_url ? (
    <Typography.Link href={item.source_url} target="_blank" rel="noreferrer">
      <LinkOutlined /> 原始来源
    </Typography.Link>
  ) : (
    <Typography.Text type="secondary">无来源链接</Typography.Text>
  );
}

function FactTable({
  items,
  onOpen,
}: {
  items: InformationDetail[];
  onOpen: (id: string) => void;
}) {
  return (
    <Table<InformationDetail>
      rowKey="item_id"
      dataSource={items}
      columns={[
        { title: "标题", dataIndex: "title" },
        { title: "来源", render: (_, item) => item.source.display_name },
        {
          title: "事件类型",
          render: (_, item) => <Tag>{displayEnum(item.event_type)}</Tag>,
        },
        {
          title: "方向",
          render: (_, item) => <Tag>{displayEnum(item.direction)}</Tag>,
        },
        {
          title: "标的 / 主题",
          render: (_, item) => (
            <Space wrap>
              {item.instruments.map((value) => (
                <Tag key={value.instrument_id}>
                  {value.symbol}.{value.exchange}
                </Tag>
              ))}
              {item.themes.map((value) => (
                <Tag key={value.theme_key}>{value.theme_name}</Tag>
              ))}
            </Space>
          ),
        },
        {
          title: "发布时间",
          render: (_, item) => new Date(item.published_at).toLocaleString(),
        },
        {
          title: "接收时间",
          render: (_, item) => new Date(item.received_at).toLocaleString(),
        },
        { title: "来源", render: (_, item) => <SourceLink item={item} /> },
        {
          title: "操作",
          render: (_, item) => (
            <Button size="small" onClick={() => onOpen(item.item_id)}>
              详情
            </Button>
          ),
        },
      ]}
    />
  );
}

export function InformationCenterPage({
  embedded = false,
}: {
  embedded?: boolean;
}) {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const [form] = Form.useForm<ManualValues>();
  const [showForm, setShowForm] = useState(false);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [sourceId, setSourceId] = useState<string>();
  const [instrumentId, setInstrumentId] = useState<string>();
  const [themeKey, setThemeKey] = useState("");
  const [showDemo, setShowDemo] = useState(false);
  const sources = useQuery({
    queryKey: ["information-sources"],
    queryFn: getInformationSources,
  });
  const instruments = useQuery({
    queryKey: ["information-instruments"],
    queryFn: () => getInstruments(""),
  });
  const items = useQuery({
    queryKey: [
      "information-items",
      page,
      search,
      sourceId,
      instrumentId,
      themeKey,
    ],
    queryFn: () =>
      getInformationItems({
        page,
        page_size: 20,
        search,
        source_id: sourceId,
        instrument_id: instrumentId,
        theme_key: themeKey,
      }),
  });
  const mutation = useMutation({
    mutationFn: addManualInformation,
    onSuccess: (item) => {
      void message.success(
        item.duplicate ? "内容已存在，返回原资讯" : "资讯已录入",
      );
      void navigate(`/information/${item.item_id}`);
    },
    onError: (error: Error) => void message.error(error.message),
  });
  const submit = async () => {
    const values = await form.validateFields();
    mutation.mutate({
      source_name: values.source_name,
      title: values.title,
      content: values.content,
      source_url: values.source_url || null,
      published_at: values.published_at
        ? new Date(values.published_at).toISOString()
        : null,
      instrument_ids: values.instrument_ids ?? [],
      themes:
        values.theme_key && values.theme_name
          ? [{ theme_key: values.theme_key, theme_name: values.theme_name }]
          : [],
      event_type: values.event_type,
      direction: values.direction,
      importance: values.importance || null,
    });
  };
  return (
    <section>
      {!embedded ? (
        <PageHeader
          title="调研资料"
          description="管理 AI 调研使用的原始资料、来源链接和关联对象。"
        />
      ) : null}
      {disclaimer}
      <Space wrap style={{ marginTop: 16 }}>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => setShowForm((value) => !value)}
        >
          添加调研资料
        </Button>
        <Input.Search
          placeholder="搜索标题与正文"
          allowClear
          onSearch={(value) => {
            setPage(1);
            setSearch(value);
          }}
          style={{ width: 240 }}
        />
        <Select
          allowClear
          placeholder="来源筛选"
          style={{ width: 180 }}
          options={sources.data?.map((value) => ({
            value: value.source_id,
            label: value.display_name,
          }))}
          onChange={setSourceId}
        />
        <Select
          allowClear
          showSearch
          placeholder="标的筛选"
          style={{ width: 200 }}
          options={instruments.data?.items.map((value) => ({
            value: value.id,
            label: `${value.symbol}.${value.exchange}`,
          }))}
          onChange={setInstrumentId}
        />
        <Input
          placeholder="主题 key"
          value={themeKey}
          onChange={(event) => setThemeKey(event.target.value)}
          style={{ width: 140 }}
        />
        <Space>
          <Switch checked={showDemo} onChange={setShowDemo} />
          <Typography.Text>显示演示/测试资料</Typography.Text>
        </Space>
      </Space>
      {showForm ? (
        <Card title="添加调研资料" style={{ marginTop: 16 }}>
          <Form
            form={form}
            layout="vertical"
            initialValues={{ event_type: "OTHER", direction: "UNKNOWN" }}
          >
            <Form.Item
              name="source_name"
              label="来源名称"
              rules={[{ required: true }]}
            >
              <Input />
            </Form.Item>
            <Form.Item name="title" label="标题" rules={[{ required: true }]}>
              <Input />
            </Form.Item>
            <Form.Item name="content" label="正文" rules={[{ required: true }]}>
              <Input.TextArea rows={6} />
            </Form.Item>
            <Space wrap>
              <Form.Item name="source_url" label="来源 URL">
                <Input style={{ width: 320 }} />
              </Form.Item>
              <Form.Item name="published_at" label="发布时间">
                <Input type="datetime-local" />
              </Form.Item>
            </Space>
            <Form.Item name="instrument_ids" label="关联标的">
              <Select
                mode="multiple"
                options={instruments.data?.items.map((value) => ({
                  value: value.id,
                  label: `${value.symbol}.${value.exchange} · ${value.name}`,
                }))}
              />
            </Form.Item>
            <Space wrap>
              <Form.Item name="theme_key" label="主题 key">
                <Input />
              </Form.Item>
              <Form.Item name="theme_name" label="主题名称">
                <Input />
              </Form.Item>
              <Form.Item name="event_type" label="事件类型">
                <Select options={eventTypes.map((value) => ({ value }))} />
              </Form.Item>
              <Form.Item name="direction" label="用户指定方向">
                <Select options={directions.map((value) => ({ value }))} />
              </Form.Item>
              <Form.Item name="importance" label="重要度 0-1">
                <Input inputMode="decimal" />
              </Form.Item>
            </Space>
            <Button
              type="primary"
              loading={mutation.isPending}
              onClick={() => void submit()}
            >
              保存原始事实与事件
            </Button>
          </Form>
        </Card>
      ) : null}
      <Card style={{ marginTop: 16 }}>
        <FactTable
          items={(items.data?.items ?? []).filter(
            (item) =>
              showDemo ||
              !/demo|fixture|测试|演示|u01|a01/i.test(
                `${item.title} ${item.source.display_name}`,
              ),
          )}
          onOpen={(id) => void navigate(`/information/${id}`)}
        />
      </Card>
    </section>
  );
}

export function MarketEventsPage() {
  const navigate = useNavigate();
  const [eventType, setEventType] = useState<string>();
  const [direction, setDirection] = useState<string>();
  const [search, setSearch] = useState("");
  const events = useQuery({
    queryKey: ["market-events", eventType, direction, search],
    queryFn: () =>
      getMarketEvents({
        page: 1,
        page_size: 50,
        event_type: eventType,
        direction,
        search,
      }),
  });
  return (
    <section>
      <PageHeader
        title="市场事件"
        description="由用户指定或确定性规则生成的事件事实。"
      />
      {disclaimer}
      <Space wrap style={{ marginTop: 16 }}>
        <Button onClick={() => void navigate("/information")}>资讯中心</Button>
        <Select
          allowClear
          placeholder="事件类型"
          style={{ width: 220 }}
          options={eventTypes.map((value) => ({ value }))}
          onChange={setEventType}
        />
        <Select
          allowClear
          placeholder="方向"
          style={{ width: 160 }}
          options={directions.map((value) => ({ value }))}
          onChange={setDirection}
        />
        <Input.Search
          placeholder="搜索事件标题"
          onSearch={setSearch}
          style={{ width: 220 }}
        />
      </Space>
      <Card style={{ marginTop: 16 }}>
        <FactTable
          items={events.data?.items ?? []}
          onOpen={(id) => void navigate(`/information/${id}`)}
        />
      </Card>
    </section>
  );
}

export function InformationDetailPage({
  eventMode = false,
}: {
  eventMode?: boolean;
}) {
  const { itemId = "", eventId = "" } = useParams();
  const id = eventMode ? eventId : itemId;
  const detail = useQuery({
    queryKey: [eventMode ? "market-event" : "information-item", id],
    queryFn: () => (eventMode ? getMarketEvent(id) : getInformationItem(id)),
    enabled: Boolean(id),
  });
  const item = detail.data;
  return (
    <section>
      <PageHeader
        title={eventMode ? "市场事件详情" : "资讯详情"}
        description={id}
      />
      {disclaimer}
      {item ? (
        <Card style={{ marginTop: 16 }}>
          <Descriptions
            bordered
            column={2}
            items={[
              {
                key: "source",
                label: "来源",
                children: item.source.display_name,
              },
              {
                key: "link",
                label: "原始链接",
                children: <SourceLink item={item} />,
              },
              {
                key: "published",
                label: "发布时间",
                children: new Date(item.published_at).toLocaleString(),
              },
              {
                key: "received",
                label: "接收时间",
                children: new Date(item.received_at).toLocaleString(),
              },
              { key: "type", label: "事件类型", children: item.event_type },
              {
                key: "direction",
                label: "用户指定方向",
                children: item.direction,
              },
              {
                key: "instruments",
                label: "标的",
                children:
                  item.instruments
                    .map((value) => `${value.symbol}.${value.exchange}`)
                    .join(", ") || "无",
              },
              {
                key: "themes",
                label: "主题",
                children:
                  item.themes.map((value) => value.theme_name).join(", ") ||
                  "无",
              },
            ]}
          />
          <Typography.Title level={3}>{item.title}</Typography.Title>
          <Typography.Paragraph>{item.content}</Typography.Paragraph>
          <Typography.Title level={5}>
            原始内容（不可覆盖事实）
          </Typography.Title>
          <pre>{item.raw_content}</pre>
        </Card>
      ) : (
        <Typography.Text>加载中…</Typography.Text>
      )}
    </section>
  );
}
