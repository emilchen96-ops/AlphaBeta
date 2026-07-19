import { RobotOutlined } from "@ant-design/icons";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  List,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  createAIAnalysis,
  getAIAnalyses,
  getAIAnalysis,
  getAIProviderStatus,
  getResearchInsight,
  getResearchInsights,
} from "../api/aiResearch";
import { getInformationItems, getMarketEvents } from "../api/information";
import { getInstruments } from "../api/market";
import { PageHeader } from "../components/PageHeader/PageHeader";
import type {
  AIAnalysisCreateBody,
  AIAnalysisRun,
  AIAnalysisType,
  ResearchInsight,
} from "../types/aiResearch";

const analysisTypes: Array<{ value: AIAnalysisType; label: string }> = [
  { value: "EVENT_SUMMARY", label: "单事件摘要" },
  { value: "INSTRUMENT_IMPACT", label: "Instrument 影响研究" },
  { value: "MULTI_EVENT_SYNTHESIS", label: "多事件综合" },
  { value: "RESEARCH_QUESTION", label: "研究问题" },
];

const aiDisclaimer = (
  <Alert
    showIcon
    type="warning"
    title="AI生成，仅供研究参考。"
    description="输出是基于所选来源的摘要或推断，不构成投资建议，不创建 Signal、订单、成交或持仓。请沿证据链接核对原始事实。"
  />
);

function statusTag(status: AIAnalysisRun["status"]) {
  const color =
    status === "COMPLETED" ? "green" : status === "FAILED" ? "red" : "blue";
  return <Tag color={color}>{status}</Tag>;
}

interface FormValues {
  analysis_type: AIAnalysisType;
  information_item_ids?: string[];
  event_ids?: string[];
  instrument_ids?: string[];
  question?: string;
}

export function AIResearchPage() {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const [form] = Form.useForm<FormValues>();
  const [page, setPage] = useState(1);
  const [analysisType, setAnalysisType] =
    useState<AIAnalysisType>("EVENT_SUMMARY");
  const provider = useQuery({
    queryKey: ["ai-provider-status"],
    queryFn: getAIProviderStatus,
  });
  const information = useQuery({
    queryKey: ["ai-information-options"],
    queryFn: () => getInformationItems({ page: 1, page_size: 50 }),
  });
  const events = useQuery({
    queryKey: ["ai-event-options"],
    queryFn: () => getMarketEvents({ page: 1, page_size: 50 }),
  });
  const instruments = useQuery({
    queryKey: ["ai-instrument-options"],
    queryFn: () => getInstruments(""),
  });
  const runs = useQuery({
    queryKey: ["ai-analyses", page],
    queryFn: () => getAIAnalyses({ page, page_size: 20 }),
  });
  const mutation = useMutation({
    mutationFn: createAIAnalysis,
    onSuccess: (run) => {
      void message.success(run.replayed ? "返回已有分析" : "研究运行已记录");
      void navigate(`/ai-analyses/${run.analysis_id}`);
    },
    onError: (error: Error) => void message.error(error.message),
  });
  const submit = async () => {
    const values = await form.validateFields();
    const body: AIAnalysisCreateBody = {
      analysis_type: values.analysis_type,
      information_item_ids: values.information_item_ids ?? [],
      event_ids: values.event_ids ?? [],
      instrument_ids: values.instrument_ids ?? [],
      question: values.question?.trim() || null,
      idempotency_key: crypto.randomUUID(),
    };
    mutation.mutate(body);
  };
  return (
    <section>
      <PageHeader
        title="AI 研究助手"
        description="以 N01 资讯与市场事件为证据边界，生成可追溯的结构化研究记录。"
      />
      {aiDisclaimer}
      <Alert
        style={{ marginTop: 16 }}
        showIcon
        type={provider.data?.configured ? "info" : "error"}
        title={`Provider: ${provider.data?.provider_key ?? "检查中"} / ${provider.data?.model_name ?? "-"}`}
        description={provider.data?.message ?? "正在读取 Provider 状态"}
      />
      <Card title="创建有依据的研究" style={{ marginTop: 16 }}>
        <Form
          form={form}
          layout="vertical"
          initialValues={{ analysis_type: "EVENT_SUMMARY" }}
        >
          <Form.Item
            name="analysis_type"
            label="分析类型"
            rules={[{ required: true }]}
          >
            <Select
              options={analysisTypes}
              onChange={(value: AIAnalysisType) => setAnalysisType(value)}
            />
          </Form.Item>
          <Form.Item name="information_item_ids" label="资讯原始事实">
            <Select
              mode="multiple"
              optionFilterProp="label"
              options={information.data?.items.map((item) => ({
                value: item.item_id,
                label: `${item.title} · ${item.source.display_name}`,
              }))}
            />
          </Form.Item>
          <Form.Item name="event_ids" label="市场事件事实">
            <Select
              mode="multiple"
              optionFilterProp="label"
              options={events.data?.items.map((item) => ({
                value: item.event_id,
                label: `${item.title} · ${item.event_type}`,
              }))}
            />
          </Form.Item>
          <Form.Item name="instrument_ids" label="研究对象（只读关联）">
            <Select
              mode="multiple"
              optionFilterProp="label"
              options={instruments.data?.items.map((item) => ({
                value: item.id,
                label: `${item.symbol}.${item.exchange} · ${item.name}`,
              }))}
            />
          </Form.Item>
          {analysisType === "RESEARCH_QUESTION" ? (
            <Form.Item
              name="question"
              label="研究问题"
              rules={[{ required: true, message: "请输入研究问题" }]}
            >
              <Input.TextArea rows={3} maxLength={4000} />
            </Form.Item>
          ) : null}
          <Button
            type="primary"
            icon={<RobotOutlined />}
            loading={mutation.isPending}
            disabled={
              provider.isLoading ||
              !provider.data?.configured ||
              mutation.isPending
            }
            onClick={() => void submit()}
          >
            创建研究分析
          </Button>
        </Form>
      </Card>
      <Card title="AIAnalysisRun 审计记录" style={{ marginTop: 16 }}>
        <Table<AIAnalysisRun>
          rowKey="analysis_id"
          dataSource={runs.data?.items ?? []}
          pagination={{
            current: page,
            pageSize: 20,
            total: runs.data?.total ?? 0,
            onChange: setPage,
          }}
          columns={[
            { title: "类型", dataIndex: "analysis_type" },
            { title: "状态", render: (_, run) => statusTag(run.status) },
            {
              title: "Provider / 模型",
              render: (_, run) => `${run.provider_key} / ${run.model_name}`,
            },
            { title: "Prompt 版本", dataIndex: "prompt_version" },
            {
              title: "创建时间",
              render: (_, run) => new Date(run.created_at).toLocaleString(),
            },
            {
              title: "操作",
              render: (_, run) => (
                <Button
                  size="small"
                  onClick={() =>
                    void navigate(`/ai-analyses/${run.analysis_id}`)
                  }
                >
                  查看依据
                </Button>
              ),
            },
          ]}
        />
        <Button onClick={() => void navigate("/research-insights")}>
          ResearchInsight 目录
        </Button>
      </Card>
    </section>
  );
}

function InsightCard({ insight }: { insight: ResearchInsight }) {
  return (
    <Card title={insight.title}>
      {aiDisclaimer}
      <Descriptions
        style={{ marginTop: 16 }}
        bordered
        column={2}
        items={[
          { key: "type", label: "研究类型", children: insight.insight_type },
          {
            key: "impact",
            label: "AI 推断方向",
            children: insight.impact_direction,
          },
          {
            key: "importance",
            label: "AI 重要度",
            children: insight.importance_score,
          },
          {
            key: "confidence",
            label: "AI 置信度",
            children: insight.confidence,
          },
        ]}
      />
      <Typography.Title level={4}>AI 摘要 / 推断</Typography.Title>
      <Typography.Paragraph>{insight.summary}</Typography.Paragraph>
      <Typography.Title level={5}>AI 提取的关键事实</Typography.Title>
      <List
        dataSource={insight.key_facts}
        renderItem={(item) => <List.Item>{item}</List.Item>}
      />
      <Typography.Title level={5}>不确定性</Typography.Title>
      <List
        dataSource={insight.uncertainties}
        locale={{ emptyText: "未声明不确定性" }}
        renderItem={(item) => <List.Item>{item}</List.Item>}
      />
      <Typography.Title level={5}>原始来源证据（需人工核对）</Typography.Title>
      <List
        dataSource={insight.evidence}
        renderItem={(evidence) => {
          const href = evidence.information_item_id
            ? `/information/${evidence.information_item_id}`
            : `/market-events/${evidence.market_event_id}`;
          return (
            <List.Item>
              <Space direction="vertical">
                <Link to={href}>打开原始事实</Link>
                <Typography.Text>{evidence.evidence_text}</Typography.Text>
                <Typography.Text type="secondary">
                  {evidence.evidence_location ?? "未标注位置"}
                </Typography.Text>
              </Space>
            </List.Item>
          );
        }}
      />
    </Card>
  );
}

export function AIAnalysisDetailPage() {
  const { analysisId = "" } = useParams();
  const run = useQuery({
    queryKey: ["ai-analysis", analysisId],
    queryFn: () => getAIAnalysis(analysisId),
    enabled: Boolean(analysisId),
  });
  return (
    <section>
      <PageHeader title="AI 分析运行详情" description={analysisId} />
      {run.data ? (
        <Space direction="vertical" size="large" style={{ width: "100%" }}>
          <Card>
            <Descriptions
              bordered
              column={2}
              items={[
                {
                  key: "status",
                  label: "状态",
                  children: statusTag(run.data.status),
                },
                {
                  key: "provider",
                  label: "Provider / 模型",
                  children: `${run.data.provider_key} / ${run.data.model_name}`,
                },
                {
                  key: "prompt",
                  label: "Prompt 契约",
                  children: `${run.data.prompt_template_key} v${run.data.prompt_version}`,
                },
                {
                  key: "tokens",
                  label: "Token 用量",
                  children: `${run.data.input_token_count ?? "-"} / ${run.data.output_token_count ?? "-"}`,
                },
                {
                  key: "cost",
                  label: "估算成本",
                  children: run.data.estimated_cost ?? "-",
                },
                {
                  key: "correlation",
                  label: "Correlation ID",
                  children: run.data.correlation_id,
                },
              ]}
            />
            {run.data.error ? (
              <Alert
                style={{ marginTop: 16 }}
                type="error"
                showIcon
                title={run.data.error.code}
                description={run.data.error.message}
              />
            ) : null}
          </Card>
          {run.data.insight ? (
            <InsightCard insight={run.data.insight} />
          ) : (
            aiDisclaimer
          )}
        </Space>
      ) : (
        <Typography.Text>加载中…</Typography.Text>
      )}
    </section>
  );
}

export function ResearchInsightsPage() {
  const navigate = useNavigate();
  const insights = useQuery({
    queryKey: ["research-insights"],
    queryFn: () => getResearchInsights(),
  });
  return (
    <section>
      <PageHeader
        title="ResearchInsight 目录"
        description="结构化 AI 研究事实及其证据索引。"
      />
      {aiDisclaimer}
      <Card style={{ marginTop: 16 }}>
        <Table<ResearchInsight>
          rowKey="insight_id"
          dataSource={insights.data?.items ?? []}
          columns={[
            { title: "标题", dataIndex: "title" },
            { title: "类型", dataIndex: "insight_type" },
            { title: "方向", dataIndex: "impact_direction" },
            { title: "置信度", dataIndex: "confidence" },
            {
              title: "操作",
              render: (_, insight) => (
                <Button
                  size="small"
                  onClick={() =>
                    void navigate(`/research-insights/${insight.insight_id}`)
                  }
                >
                  证据详情
                </Button>
              ),
            },
          ]}
        />
      </Card>
    </section>
  );
}

export function ResearchInsightDetailPage() {
  const { insightId = "" } = useParams();
  const insight = useQuery({
    queryKey: ["research-insight", insightId],
    queryFn: () => getResearchInsight(insightId),
    enabled: Boolean(insightId),
  });
  return (
    <section>
      <PageHeader title="ResearchInsight 证据详情" description={insightId} />
      {insight.data ? (
        <InsightCard insight={insight.data} />
      ) : (
        <Typography.Text>加载中…</Typography.Text>
      )}
    </section>
  );
}
