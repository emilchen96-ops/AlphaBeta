import { FilterOutlined, ReloadOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  Form,
  Input,
  Modal,
  Progress,
  Row,
  Space,
  Statistic,
  Switch,
  Table,
  Tag,
  Typography,
} from "antd";
import { useState } from "react";

import { getScannerSessionDefault } from "../api/scanners";
import {
  createScreening,
  getScreening,
  getScreeningProgress,
  getScreeningResults,
  getScreeningRuns,
  getScreeningTemplates,
} from "../api/screenings";
import { PageHeader } from "../components/PageHeader/PageHeader";
import type {
  ScreeningResult,
  ScreeningStatus,
  ScreeningTemplate,
} from "../types/screenings";

interface ScreeningFormValues {
  as_of_date: string;
  exclude_st: boolean;
  exclude_bse: boolean;
  exclude_star_market: boolean;
  exclude_chinext: boolean;
}

const terminalStatuses = new Set<ScreeningStatus>([
  "COMPLETED",
  "PARTIAL_FAILED",
  "FAILED",
  "CANCELED",
]);

const statusText: Record<ScreeningStatus, string> = {
  CREATED: "已创建",
  QUEUED: "等待后台处理",
  RESOLVING: "正在解析点时股票池",
  CHECKING_DATA: "正在检查历史数据",
  BACKFILLING: "正在补齐历史数据",
  RUNNING: "正在分批筛选",
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

function instrumentText(result: ScreeningResult) {
  const exchange =
    result.exchange === "SSE"
      ? "SH"
      : result.exchange === "SZSE"
        ? "SZ"
        : result.exchange;
  return `${result.instrument_name}（${result.symbol}.${exchange}）`;
}

export function ScannersPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [form] = Form.useForm<ScreeningFormValues>();
  const [selectedTemplate, setSelectedTemplate] =
    useState<ScreeningTemplate>();
  const [activeId, setActiveId] = useState<string>();

  const templates = useQuery({
    queryKey: ["screening-templates"],
    queryFn: getScreeningTemplates,
  });
  const sessionDefault = useQuery({
    queryKey: ["scanner-session-default"],
    queryFn: getScannerSessionDefault,
  });
  const runs = useQuery({
    queryKey: ["screenings"],
    queryFn: getScreeningRuns,
    refetchInterval: 5_000,
  });
  const effectiveActiveId = activeId ?? runs.data?.items[0]?.screening_id;
  const active = useQuery({
    queryKey: ["screening", effectiveActiveId],
    queryFn: () => getScreening(effectiveActiveId as string),
    enabled: Boolean(effectiveActiveId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && terminalStatuses.has(status) ? false : 2_000;
    },
  });
  const progress = useQuery({
    queryKey: ["screening-progress", effectiveActiveId],
    queryFn: () => getScreeningProgress(effectiveActiveId as string),
    enabled: Boolean(effectiveActiveId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && terminalStatuses.has(status) ? false : 2_000;
    },
  });
  const results = useQuery({
    queryKey: ["screening-results", effectiveActiveId],
    queryFn: () => getScreeningResults(effectiveActiveId as string),
    enabled: Boolean(effectiveActiveId) && Boolean(active.data),
    refetchInterval:
      active.data && !terminalStatuses.has(active.data.status) ? 3_000 : false,
  });

  const mutation = useMutation({
    mutationFn: createScreening,
    onSuccess: async (run) => {
      setActiveId(run.screening_id);
      setSelectedTemplate(undefined);
      form.resetFields();
      await queryClient.invalidateQueries({ queryKey: ["screenings"] });
      void message.success(
        run.replayed ? "已打开相同筛选任务" : "全A股筛选任务已进入后台队列",
      );
    },
    onError: (error: Error) => void message.error(error.message),
  });

  const openTemplate = (template: ScreeningTemplate) => {
    setSelectedTemplate(template);
    form.setFieldsValue({
      as_of_date:
        sessionDefault.data?.scan_date ?? template.spec.as_of_date.slice(0, 10),
      exclude_st: true,
      exclude_bse: false,
      exclude_star_market: false,
      exclude_chinext: false,
    });
  };

  const submit = async () => {
    if (!selectedTemplate) return;
    const values = await form.validateFields();
    const spec = selectedTemplate.spec;
    const filterKey = [
      values.exclude_st,
      values.exclude_bse,
      values.exclude_star_market,
      values.exclude_chinext,
    ]
      .map((value) => (value ? "1" : "0"))
      .join("");
    mutation.mutate({
      ...spec,
      as_of_date: values.as_of_date,
      universe_spec: {
        ...spec.universe_spec,
        exclude_st: values.exclude_st,
        exclude_bse: values.exclude_bse,
        exclude_star_market: values.exclude_star_market,
        exclude_chinext: values.exclude_chinext,
      },
      conditions: spec.conditions.map((condition) => ({
        condition_key: condition.condition_key,
        parameters: condition.parameters,
      })),
      idempotency_key: `sc02a:${selectedTemplate.template_key}:${values.as_of_date}:${filterKey}`,
    });
  };

  const current = progress.data ?? active.data;
  const execution = active.data?.execution_stats;
  const noFutureBars = execution?.future_bars_read === 0;
  return (
    <section>
      <PageHeader
        title="智能选股"
        description="使用标准条件目录和MiniQMT本地历史日线，对指定交易日当时存在的全部A股执行后台筛选。"
        action={
          <Button
            icon={<ReloadOutlined />}
            onClick={() => {
              void templates.refetch();
              void runs.refetch();
              if (effectiveActiveId) {
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

      <Alert
        type="info"
        showIcon
        title="SC02-A标准形态验收页"
        description="本页只创建研究筛选任务，不创建研究信号、订单或成交，也不会调用券商交易能力。"
        style={{ marginBottom: 16 }}
      />

      <Row gutter={[16, 16]}>
        {templates.data?.map((template) => (
          <Col xs={24} lg={12} key={template.template_key}>
            <Card
              title={template.display_name}
              extra={
                <Button
                  type="primary"
                  icon={<FilterOutlined />}
                  onClick={() => openTemplate(template)}
                >
                  开始筛选
                </Button>
              }
            >
              <Typography.Paragraph>{template.description}</Typography.Paragraph>
              <Space wrap>
                <Tag color="blue">全部A股</Tag>
                <Tag color="green">MiniQMT本地日线</Tag>
                <Tag>不复权</Tag>
                <Tag>点时股票池</Tag>
              </Space>
            </Card>
          </Col>
        ))}
      </Row>

      <Card title="最近筛选运行" style={{ marginTop: 16 }}>
        <Table
          rowKey="screening_id"
          size="small"
          pagination={false}
          loading={runs.isLoading}
          dataSource={runs.data?.items ?? []}
          onRow={(record) => ({
            onClick: () => setActiveId(record.screening_id),
            style: { cursor: "pointer" },
          })}
          columns={[
            {
              title: "筛选名称",
              dataIndex: "name",
            },
            {
              title: "筛选日期",
              render: (_, record) => record.spec.as_of_date,
            },
            {
              title: "状态",
              render: (_, record) => (
                <Tag color={statusColor[record.status]}>
                  {statusText[record.status]}
                </Tag>
              ),
            },
            {
              title: "进度",
              render: (_, record) => `${record.progress_percent}%`,
            },
            {
              title: "入选",
              render: (_, record) => `${record.matched_count}只`,
            },
          ]}
          locale={{ emptyText: <Empty description="尚无筛选运行" /> }}
        />
      </Card>

      {current ? (
        <Card
          title={`运行详情：${active.data?.name ?? "正在加载"}`}
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
                title="总股票数"
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
                title="数据不足/无法判定"
                value={
                  current.insufficient_data_count + current.indeterminate_count
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
          {active.data?.completed_at ? (
            <Descriptions
              size="small"
              column={{ xs: 1, sm: 3 }}
              style={{ marginTop: 16 }}
              items={[
                {
                  key: "elapsed",
                  label: "耗时",
                  children: `${active.data.elapsed_ms}毫秒`,
                },
                {
                  key: "batches",
                  label: "处理批次",
                  children: active.data.batch_count,
                },
                {
                  key: "no-future",
                  label: "未来数据检查",
                  children: noFutureBars ? "通过（读取0条未来K线）" : "未确认",
                },
              ]}
            />
          ) : null}
        </Card>
      ) : null}

      {effectiveActiveId ? (
        <Card title="筛选结果与入选原因" style={{ marginTop: 16 }}>
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
                      ? "任务运行中，结果将自动刷新"
                      : "本次没有股票满足条件"
                  }
                />
              ),
            }}
          />
        </Card>
      ) : null}

      <Modal
        open={Boolean(selectedTemplate)}
        title={
          selectedTemplate
            ? `运行“${selectedTemplate.display_name}”全A股筛选`
            : "运行全A股筛选"
        }
        okText="开始筛选"
        cancelText="取消"
        confirmLoading={mutation.isPending}
        onOk={() => void submit()}
        onCancel={() => {
          setSelectedTemplate(undefined);
          form.resetFields();
        }}
        destroyOnHidden
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="as_of_date"
            label="筛选日期"
            rules={[{ required: true, message: "请选择筛选日期" }]}
            tooltip="系统只读取该日期及以前的数据，不读取未来K线"
          >
            <Input type="date" />
          </Form.Item>
          <Typography.Title level={5}>股票范围：当日全部A股</Typography.Title>
          <Typography.Paragraph type="secondary">
            系统按筛选日期还原沪深北股票目录，不以今天的在市名单替代历史名单。
          </Typography.Paragraph>
          <Row gutter={16}>
            {[
              ["exclude_st", "排除ST及*ST"],
              ["exclude_bse", "排除北交所"],
              ["exclude_star_market", "排除科创板"],
              ["exclude_chinext", "排除创业板"],
            ].map(([name, label]) => (
              <Col xs={24} sm={12} key={name}>
                <Form.Item
                  name={name}
                  label={label}
                  valuePropName="checked"
                >
                  <Switch checkedChildren="是" unCheckedChildren="否" />
                </Form.Item>
              </Col>
            ))}
          </Row>
        </Form>
      </Modal>
    </section>
  );
}
