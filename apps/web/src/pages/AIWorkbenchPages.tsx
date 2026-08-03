import {
  CheckCircleOutlined,
  DownloadOutlined,
  RobotOutlined,
  StopOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Collapse,
  DatePicker,
  Descriptions,
  Empty,
  Form,
  Input,
  Progress,
  Select,
  Space,
  Steps,
  Table,
  Tag,
  Typography,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  cancelAIResearchTask,
  createAIResearchTask,
  getAIProviderStatus,
  getAIResearchExportUrl,
  getAIResearchReport,
  getAIResearchTask,
  getAIResearchTasks,
  retryAIResearchTask,
  testAIProvider,
} from "../api/aiResearch";
import { getInstruments } from "../api/market";
import { PageHeader } from "../components/PageHeader/PageHeader";
import type {
  AIResearchArtifact,
  AIResearchDepth,
  AIResearchTask,
  AIResearchTaskStatus,
  AIResearchWorkflowEvent,
} from "../types/aiResearch";

const { RangePicker } = DatePicker;
const terminal = new Set<AIResearchTaskStatus>([
  "COMPLETED",
  "PARTIALLY_COMPLETED",
  "FAILED",
  "CANCELED",
]);
const statusText: Record<AIResearchTaskStatus, string> = {
  CREATED: "等待开始",
  PREPARING_DATA: "准备资料",
  RUNNING_AGENTS: "多角色分析",
  DEBATING: "多空论证",
  RISK_REVIEW: "风险复核",
  GENERATING_REPORT: "生成报告",
  COMPLETED: "已完成",
  PARTIALLY_COMPLETED: "部分完成",
  FAILED: "失败",
  CANCELED: "已取消",
};
const depthText: Record<AIResearchDepth, string> = {
  FAST: "快速",
  STANDARD: "标准",
  DEEP: "深度",
};
const sectionText: Record<string, string> = {
  research_overview: "一、调研概览",
  market_environment: "二、市场环境",
  technical_analysis: "三、技术面",
  fundamental_analysis: "四、基本面",
  news_events: "五、资讯与事件",
  bull_case: "六、看多论证",
  bear_case: "七、看空论证",
  risk_review: "八、风险与不确定性",
  conclusion: "九、综合结论",
  sources: "十、资料来源",
};
const fieldText: Record<string, string> = {
  title: "标题",
  summary: "摘要",
  findings: "主要发现",
  risks: "风险",
  uncertainties: "不确定性",
  citations: "资料引用",
  items: "资料清单",
  stance: "综合观点",
  confidence: "置信度",
  executive_summary: "执行摘要",
};

interface FormValues {
  instrument_id: string;
  model_name: string;
  question: string;
  depth: AIResearchDepth;
  date_range: [Dayjs, Dayjs];
}

function taskTitle(task: AIResearchTask) {
  return `${task.instrument.name}（${task.instrument.symbol}.${task.instrument.exchange}）`;
}

function taskStatus(task: AIResearchTask) {
  const color = task.status === "FAILED" ? "red" : task.status === "COMPLETED" ? "green" : "blue";
  return <Tag color={color}>{statusText[task.status]}</Tag>;
}

function eventName(event: AIResearchWorkflowEvent) {
  if (event.tool_name) return event.tool_name;
  if (event.node_name) return event.node_name;
  return event.agent_role ?? event.event_type;
}

function eventTypeText(event: AIResearchWorkflowEvent) {
  if (event.event_type === "TOOL_CALL") return "工具调用";
  if (event.event_type === "GRAPH_NODE") return "智能体节点";
  if (event.event_type === "CHECKPOINT") return "执行检查点";
  return event.event_type;
}

function artifactSourceCount(artifacts: AIResearchArtifact[]) {
  return new Set(artifacts.flatMap((artifact) => artifact.source_ids)).size;
}

export function AIResearchWorkbenchPage() {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const [form] = Form.useForm<FormValues>();
  const [keyword, setKeyword] = useState("");
  const provider = useQuery({
    queryKey: ["ai-provider-status"],
    queryFn: getAIProviderStatus,
    refetchInterval: 15_000,
  });
  const instruments = useQuery({
    queryKey: ["ai-research-instruments", keyword],
    queryFn: () => getInstruments(keyword),
  });
  const tasks = useQuery({
    queryKey: ["ai-research-tasks", 1],
    queryFn: () => getAIResearchTasks(1, 10),
    refetchInterval: (query) => {
      const items = query.state.data?.items;
      return Array.isArray(items) && items.some((item) => !terminal.has(item.status))
        ? 3000
        : false;
    },
  });
  const providerTest = useMutation({
    mutationFn: testAIProvider,
    onSuccess: (result) =>
      result.success
        ? void message.success(`${result.model_name} 可用（${result.latency_ms ?? 0}ms）`)
        : void message.error(result.error_code ?? "AI 模型服务不可用"),
    onError: (error: Error) => void message.error(error.message),
  });
  const createTask = useMutation({
    mutationFn: createAIResearchTask,
    onSuccess: (task) => {
      void message.success("AI 调研任务已创建，可安全离开页面");
      void navigate(`/ai-research/tasks/${task.task_id}`);
    },
    onError: (error: Error) => void message.error(error.message),
  });

  useEffect(() => {
    const defaultModel = provider.data?.model_name;
    if (
      defaultModel &&
      defaultModel !== "none" &&
      !form.getFieldValue("model_name")
    ) {
      form.setFieldValue("model_name", defaultModel);
    }
  }, [form, provider.data?.model_name]);

  const submit = async () => {
    const value = await form.validateFields();
    createTask.mutate({
      instrument_id: value.instrument_id,
      model_name: value.model_name,
      question: value.question.trim(),
      depth: value.depth,
      start_date: value.date_range[0].format("YYYY-MM-DD"),
      end_date: value.date_range[1].format("YYYY-MM-DD"),
      idempotency_key: crypto.randomUUID(),
    });
  };

  const providerReady = ["FAKE", "REAL_AVAILABLE"].includes(provider.data?.mode ?? "");
  return (
    <section>
      <PageHeader
        title="AI 调研"
        description="围绕一只 A 股，由多个研究角色协作分析并生成可追溯的结构化报告。"
      />
      <Alert
        showIcon
        type={providerReady ? (provider.data?.mode === "FAKE" ? "warning" : "success") : "error"}
        title={providerReady ? "AI 模型服务已就绪" : "AI 模型服务尚未就绪"}
        description={
          <Space orientation="vertical" size={4}>
            <Typography.Text>
              {provider.data?.mode === "FAKE"
                ? "当前是确定性测试模型，结果不是真实 AI 调研。"
                : provider.data?.message ?? "请在项目根目录 .env 中配置模型服务并重启。"}
            </Typography.Text>
            {provider.data?.provider_key === "openai_compatible" ? (
              <Button
                size="small"
                loading={providerTest.isPending}
                onClick={() => providerTest.mutate(form.getFieldValue("model_name"))}
              >
                测试所选模型连接
              </Button>
            ) : null}
          </Space>
        }
      />
      <Card title="创建 AI 调研" style={{ marginTop: 16 }}>
        <Form
          form={form}
          layout="vertical"
          initialValues={{
            depth: "STANDARD",
            date_range: [dayjs().subtract(3, "month"), dayjs()],
          }}
        >
          <Form.Item name="instrument_id" label="研究股票" rules={[{ required: true, message: "请选择一只股票" }]}>
            <Select
              showSearch
              filterOption={false}
              placeholder="输入股票名称或代码，例如：长信科技 / 300088"
              onSearch={setKeyword}
              options={(instruments.data?.items ?? []).map((item) => ({
                value: item.id,
                label: `${item.name}（${item.symbol}.${item.exchange}）`,
              }))}
            />
          </Form.Item>
          <Form.Item name="question" label="研究问题" rules={[{ required: true, message: "请输入研究问题" }]}>
            <Input.TextArea
              rows={4}
              maxLength={4000}
              showCount
              placeholder="例如：分析长信科技当前基本面、技术面和主要风险"
            />
          </Form.Item>
          <Space size="large" wrap>
            <Form.Item
              name="model_name"
              label="本次调研模型"
              rules={[{ required: true, message: "请选择一个模型" }]}
              extra="本任务的所有分析角色统一使用该模型；重试仍沿用原选择。额度由模型平台管理。"
            >
              <Select
                showSearch
                style={{ width: 300 }}
                placeholder="选择仍有额度的兼容模型"
                options={(provider.data?.selectable_models ?? []).map((model) => ({
                  value: model,
                  label: model,
                }))}
              />
            </Form.Item>
            <Form.Item name="depth" label="调研深度" rules={[{ required: true }]}>
              <Select
                style={{ width: 240 }}
                options={[
                  { value: "FAST", label: "快速（核心角色，较快）" },
                  { value: "STANDARD", label: "标准（完整角色，推荐）" },
                  { value: "DEEP", label: "深度（更完整的多空与风险复核）" },
                ]}
              />
            </Form.Item>
            <Form.Item name="date_range" label="资料时间范围" rules={[{ required: true }]}>
              <RangePicker allowClear={false} />
            </Form.Item>
          </Space>
          <div>
            <Button
              type="primary"
              icon={<RobotOutlined />}
              loading={createTask.isPending}
              disabled={!providerReady || createTask.isPending}
              onClick={() => void submit()}
            >
              开始 AI 调研
            </Button>
          </div>
        </Form>
      </Card>
      <Card title="最近的 AI 调研" style={{ marginTop: 16 }}>
        <Table<AIResearchTask>
          rowKey="task_id"
          loading={tasks.isLoading}
          dataSource={tasks.data?.items ?? []}
          pagination={false}
          locale={{ emptyText: <Empty description="暂无 AI 调研任务" /> }}
          columns={[
            { title: "研究股票", render: (_, task) => <Link to={`/ai-research/tasks/${task.task_id}`}>{taskTitle(task)}</Link> },
            { title: "研究问题", dataIndex: "question", ellipsis: true },
            { title: "深度", render: (_, task) => depthText[task.depth] },
            { title: "模型", dataIndex: "model_name", ellipsis: true },
            { title: "状态", render: (_, task) => taskStatus(task) },
            { title: "进度", render: (_, task) => `${task.progress_percent}%` },
          ]}
        />
      </Card>
    </section>
  );
}

export function AIResearchTaskPage() {
  const { message } = App.useApp();
  const { taskId = "" } = useParams();
  const task = useQuery({
    queryKey: ["ai-research-task", taskId],
    queryFn: () => getAIResearchTask(taskId),
    enabled: Boolean(taskId),
    refetchInterval: (query) =>
      query.state.data && !terminal.has(query.state.data.status) ? 2000 : false,
  });
  const cancel = useMutation({
    mutationFn: () => cancelAIResearchTask(taskId),
    onSuccess: () => void task.refetch(),
    onError: (error: Error) => void message.error(error.message),
  });
  const retry = useMutation({
    mutationFn: () => retryAIResearchTask(taskId),
    onSuccess: () => {
      void message.success("任务已重新进入队列");
      void task.refetch();
    },
    onError: (error: Error) => void message.error(error.message),
  });
  const data = task.data;
  if (!data) return <Typography.Text>加载调研任务…</Typography.Text>;
  return (
    <section>
      <PageHeader title={taskTitle(data)} description={data.question} />
      <Card>
        <Space orientation="vertical" size="large" style={{ width: "100%" }}>
          <Descriptions
            column={3}
            items={[
              { key: "status", label: "状态", children: taskStatus(data) },
              { key: "depth", label: "调研深度", children: depthText[data.depth] },
              { key: "range", label: "资料范围", children: `${data.start_date} 至 ${data.end_date}` },
              { key: "engine", label: "研究引擎", children: `${data.engine_key}${data.engine_version ? ` / ${data.engine_version}` : ""}` },
              { key: "attempt", label: "执行次数", children: `${data.execution_attempt} 次` },
              { key: "artifacts", label: "已保存独立报告", children: `${data.artifacts.length} 份` },
            ]}
          />
          <Progress percent={data.progress_percent} status={data.status === "FAILED" ? "exception" : undefined} />
          <Alert
            showIcon
            type={data.status === "FAILED" ? "error" : data.status === "COMPLETED" ? "success" : "info"}
            title={data.current_stage || statusText[data.status]}
            description={data.error?.message ?? "任务由后台 Worker 持续执行，关闭本页面不会中断。"}
          />
          <Steps
            orientation="vertical"
            items={data.steps.map((step) => ({
              title: step.role_label,
              status: step.status === "COMPLETED" ? "finish" : step.status === "RUNNING" ? "process" : step.status === "FAILED" ? "error" : "wait",
              content: step.summary || (step.status === "PENDING" ? "等待执行" : step.title),
              icon: step.status === "COMPLETED" ? <CheckCircleOutlined /> : undefined,
            }))}
          />
          <Card size="small" title={`执行轨迹（${data.events.length} 条）`}>
            <Table<AIResearchWorkflowEvent>
              rowKey="event_id"
              size="small"
              dataSource={data.events}
              pagination={{ pageSize: 12, hideOnSinglePage: true }}
              locale={{ emptyText: "Graph 完成首个节点后会在这里显示可审计轨迹" }}
              columns={[
                { title: "序号", dataIndex: "sequence", width: 70 },
                { title: "类型", render: (_, event) => eventTypeText(event), width: 110 },
                { title: "智能体 / 工具", render: (_, event) => eventName(event) },
                {
                  title: "状态",
                  render: (_, event) => (
                    <Tag color={event.status === "FAILED" ? "red" : event.status === "COMPLETED" ? "green" : "blue"}>
                      {event.status === "FAILED" ? "失败" : event.status === "COMPLETED" ? "已完成" : "运行中"}
                    </Tag>
                  ),
                  width: 100,
                },
              ]}
            />
          </Card>
          <Space>
            {data.report ? <Button type="primary"><Link to={`/ai-research/tasks/${taskId}/report`}>查看完整报告</Link></Button> : null}
            {!terminal.has(data.status) ? <Button danger icon={<StopOutlined />} loading={cancel.isPending} onClick={() => cancel.mutate()}>取消任务</Button> : null}
            {data.status === "FAILED" ? <Button loading={retry.isPending} onClick={() => retry.mutate()}>重新尝试</Button> : null}
            <Button><Link to="/research/archive?tab=ai">返回研究档案</Link></Button>
          </Space>
        </Space>
      </Card>
    </section>
  );
}

function renderValue(value: unknown) {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const record = value as Record<string, unknown>;
    const title = typeof record.title === "string" ? record.title : null;
    const sourceType = typeof record.source_type === "string" ? record.source_type : null;
    const sourceId = typeof record.source_id === "string" ? record.source_id : null;
    if (title || sourceType || sourceId) {
      return [title, sourceType ? `类型：${sourceType}` : null, sourceId ? `编号：${sourceId}` : null]
        .filter(Boolean)
        .join(" · ");
    }
  }
  return JSON.stringify(value);
}

function renderSection(value: unknown) {
  if (typeof value === "string") return <Typography.Paragraph>{value}</Typography.Paragraph>;
  if (Array.isArray(value)) return <ul>{value.map((item, index) => <li key={index}>{renderValue(item)}</li>)}</ul>;
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return <Space orientation="vertical" size={6}>{Object.entries(record).map(([key, item]) => <div key={key}><Typography.Text strong>{fieldText[key] ?? key}：</Typography.Text>{Array.isArray(item) ? <ul>{item.map((entry, index) => <li key={index}>{renderValue(entry)}</li>)}</ul> : renderValue(item)}</div>)}</Space>;
  }
  return <Typography.Text type="secondary">暂无内容</Typography.Text>;
}

export function AIResearchReportPage() {
  const { taskId = "" } = useParams();
  const task = useQuery({ queryKey: ["ai-research-task", taskId], queryFn: () => getAIResearchTask(taskId), enabled: Boolean(taskId) });
  const report = useQuery({ queryKey: ["ai-research-report", taskId], queryFn: () => getAIResearchReport(taskId), enabled: Boolean(taskId) });
  if (!report.data) return <Typography.Text>加载结构化报告…</Typography.Text>;
  const data = report.data;
  const artifacts = task.data?.artifacts ?? [];
  const events = task.data?.events ?? [];
  const toolEvents = events.filter((event) => event.event_type === "TOOL_CALL");
  const completedTools = toolEvents.filter((event) => event.status === "COMPLETED").length;
  const expectedRoles = task.data?.steps.length ?? 0;
  const roleCoverage = expectedRoles === 0 ? 0 : Math.round((artifacts.length / expectedRoles) * 100);
  return (
    <section>
      <PageHeader title={data.title} description={task.data?.question ?? "多智能体 AI 调研报告"} />
      <Alert showIcon type="warning" title={data.disclaimer} description="请结合资料来源、局限性和自身判断核验报告内容。" />
      <Card style={{ marginTop: 16 }}>
        <Descriptions
          column={3}
          items={[
            { key: "stance", label: "综合观点", children: data.stance },
            { key: "confidence", label: "置信度", children: data.confidence },
            { key: "provider", label: "模型服务", children: `${task.data?.provider_key ?? "-"} / ${task.data?.model_name ?? "-"}` },
            { key: "engine", label: "研究引擎", children: `${task.data?.engine_key ?? "-"}${task.data?.engine_version ? ` / ${task.data.engine_version}` : ""}` },
            { key: "coverage", label: "角色报告覆盖", children: `${artifacts.length} / ${expectedRoles || "-"}` },
            { key: "tools", label: "工具调用", children: `${completedTools} / ${toolEvents.length} 次成功` },
            { key: "sources", label: "可追溯来源", children: `${artifactSourceCount(artifacts)} 项` },
          ]}
        />
        {expectedRoles > 0 ? <Progress percent={Math.min(roleCoverage, 100)} format={() => `角色覆盖 ${artifacts.length}/${expectedRoles}`} /> : null}
        <Typography.Title level={3}>执行摘要</Typography.Title>
        <Typography.Paragraph>{data.executive_summary}</Typography.Paragraph>
      </Card>
      {artifacts.length > 0 ? (
        <Card title="各智能体独立报告" style={{ marginTop: 16 }}>
          <Collapse
            items={artifacts
              .slice()
              .sort((left, right) => left.ordinal - right.ordinal)
              .map((artifact) => ({
                key: artifact.artifact_id,
                label: (
                  <Space>
                    <Typography.Text strong>{artifact.title}</Typography.Text>
                    <Tag>{artifact.source_ids.length} 项来源</Tag>
                  </Space>
                ),
                children: (
                  <>
                    <Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>
                      {artifact.content_markdown}
                    </Typography.Paragraph>
                    {artifact.source_ids.length > 0 ? (
                      <Typography.Text type="secondary">
                        来源编号：{artifact.source_ids.join("、")}
                      </Typography.Text>
                    ) : null}
                  </>
                ),
              }))}
          />
        </Card>
      ) : Object.keys(sectionText).map((key) => (
        <Card key={key} title={sectionText[key]} style={{ marginTop: 16 }}>{renderSection(data.sections[key])}</Card>
      ))}
      {artifacts.length > 0 ? (
        <Card title="完整多智能体报告" style={{ marginTop: 16 }}>
          <Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>{data.markdown}</Typography.Paragraph>
        </Card>
      ) : null}
      <Card title="报告局限" style={{ marginTop: 16 }}>
        <ul>{data.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
      </Card>
      <Space style={{ marginTop: 16 }}>
        <Button icon={<DownloadOutlined />} href={getAIResearchExportUrl(taskId, "markdown")}>下载 Markdown</Button>
        <Button icon={<DownloadOutlined />} href={getAIResearchExportUrl(taskId, "pdf")}>下载 PDF</Button>
        <Button><Link to={`/ai-research/tasks/${taskId}`}>返回任务进度</Link></Button>
      </Space>
    </section>
  );
}
