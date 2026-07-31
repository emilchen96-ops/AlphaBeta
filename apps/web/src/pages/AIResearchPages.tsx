import { RobotOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Collapse,
  Descriptions,
  Form,
  Input,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import { useState } from "react";
import {
  Link,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";

import {
  createAIAnalysis,
  getAIAnalyses,
  getAIAnalysis,
  getAIProviderStatus,
  getResearchInsight,
  getResearchInsights,
  testAIProvider,
} from "../api/aiResearch";
import { getInformationItems, getMarketEvents } from "../api/information";
import { getInstruments } from "../api/market";
import { PageHeader } from "../components/PageHeader/PageHeader";
import { InformationCenterPage } from "./InformationPages";
import type {
  AIAnalysisCreateBody,
  AIAnalysisRun,
  AIAnalysisType,
  ResearchInsight,
} from "../types/aiResearch";

const analysisTypes: Array<{ value: AIAnalysisType; label: string }> = [
  { value: "EVENT_SUMMARY", label: "单事件摘要" },
  { value: "INSTRUMENT_IMPACT", label: "个股影响分析" },
  { value: "MULTI_EVENT_SYNTHESIS", label: "多事件综合" },
  { value: "RESEARCH_QUESTION", label: "研究问题" },
];
const analysisTypeText = Object.fromEntries(
  analysisTypes.map((item) => [item.value, item.label]),
) as Record<string, string>;

const aiDisclaimer = (
  <Alert
    showIcon
    type="warning"
    title="AI生成，仅供研究参考。"
    description="输出是基于所选来源的摘要或推断，不构成投资建议，不创建研究信号（Signal）、订单、成交或持仓。请沿证据链接核对原始事实。"
  />
);

function statusTag(status: AIAnalysisRun["status"]) {
  const color =
    status === "COMPLETED" ? "green" : status === "FAILED" ? "red" : "blue";
  return (
    <Tag color={color}>
      {{
        CREATED: "已创建",
        RUNNING: "运行中",
        COMPLETED: "已完成",
        FAILED: "失败",
      }[status] ?? status}
    </Tag>
  );
}

interface FormValues {
  analysis_type: AIAnalysisType;
  information_item_ids?: string[];
  event_ids?: string[];
  instrument_ids?: string[];
  question?: string;
}

function AIResearchWorkbench() {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [form] = Form.useForm<FormValues>();
  const [page, setPage] = useState(1);
  const [analysisType, setAnalysisType] =
    useState<AIAnalysisType>("EVENT_SUMMARY");
  const provider = useQuery({
    queryKey: ["ai-provider-status"],
    queryFn: getAIProviderStatus,
  });
  const selectedInformation = Form.useWatch("information_item_ids", form) ?? [];
  const selectedEvents = Form.useWatch("event_ids", form) ?? [];
  const providerTest = useMutation({
    mutationFn: testAIProvider,
    onSuccess: async (result) => {
      if (result.success) {
        void message.success(`模型服务连通成功：${result.latency_ms ?? 0}ms`);
      } else {
        void message.error(result.error_code ?? "模型服务连通失败");
      }
      await queryClient.invalidateQueries({ queryKey: ["ai-provider-status"] });
    },
    onError: (error: Error) => void message.error(error.message),
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
        title="AI 调研"
        description="选择可核对的调研资料，生成带来源证据的结构化研究报告。"
      />
      {aiDisclaimer}
      <Alert
        style={{ marginTop: 16 }}
        showIcon
        type={
          provider.data?.mode === "REAL_AVAILABLE"
            ? "success"
            : provider.data?.mode === "FAKE"
              ? "info"
              : provider.data?.configured
                ? "warning"
                : "error"
        }
        title={
          provider.data?.mode === "REAL_AVAILABLE"
            ? "AI 模型服务可用"
            : provider.data?.mode === "FAKE"
              ? "当前使用测试模型"
              : "AI 模型服务尚未就绪"
        }
        description={
          <Space orientation="vertical" size="small">
            <Typography.Text>
              {provider.data?.message ?? "正在读取模型服务状态"}
            </Typography.Text>
            {(provider.data?.warnings ?? []).map((warning) => (
              <Typography.Text key={warning} type="secondary">
                {warning}
              </Typography.Text>
            ))}
            {provider.data?.provider_key === "openai_compatible" ? (
              <Button
                size="small"
                loading={providerTest.isPending}
                disabled={providerTest.isPending}
                onClick={() => providerTest.mutate()}
              >
                测试真实模型服务连通性
              </Button>
            ) : null}
            <Collapse
              ghost
              size="small"
              items={[
                {
                  key: "technical",
                  label: "技术详情",
                  children: (
                    <Space orientation="vertical" size={2}>
                      <Typography.Text type="secondary">
                        服务：{provider.data?.provider_key ?? "检查中"} /{" "}
                        {provider.data?.model_name ?? "-"}
                      </Typography.Text>
                      {provider.data?.base_url_summary ? (
                        <Typography.Text type="secondary">
                          接口地址：{provider.data.base_url_summary}
                        </Typography.Text>
                      ) : null}
                      {provider.data?.last_error_code ? (
                        <Typography.Text type="danger">
                          最近错误代码：{provider.data.last_error_code}
                        </Typography.Text>
                      ) : null}
                    </Space>
                  ),
                },
              ]}
            />
          </Space>
        }
      />
      <Card title="创建有依据的 AI 调研" style={{ marginTop: 16 }}>
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
          <Typography.Paragraph type="secondary">
            当前选择 {selectedInformation.length + selectedEvents.length}{" "}
            条输入资料；外部文本按不可信数据隔离处理。
          </Typography.Paragraph>
          <Button
            type="primary"
            icon={<RobotOutlined />}
            loading={mutation.isPending}
            disabled={
              provider.isLoading ||
              !["FAKE", "REAL_AVAILABLE"].includes(provider.data?.mode ?? "") ||
              mutation.isPending
            }
            onClick={() => void submit()}
          >
            {provider.data?.mode === "FAKE"
              ? "运行 Fake AI 演示"
              : "创建真实研究分析"}
          </Button>
        </Form>
      </Card>
      <Card title="最近的 AI 调研" style={{ marginTop: 16 }}>
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
            {
              title: "调研主题",
              render: (_, run) =>
                run.insight?.title ??
                run.user_question ??
                analysisTypeText[run.analysis_type] ??
                "AI 调研",
            },
            {
              title: "调研类型",
              render: (_, run) =>
                analysisTypeText[run.analysis_type] ?? run.analysis_type,
            },
            { title: "状态", render: (_, run) => statusTag(run.status) },
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
                  查看报告与依据
                </Button>
              ),
            },
          ]}
        />
      </Card>
    </section>
  );
}

export function AIResearchPage() {
  const [search, setSearch] = useSearchParams();
  const active = search.get("tab") ?? "research";
  return (
    <Tabs
      activeKey={active}
      onChange={(tab) => setSearch({ tab })}
      items={[
        {
          key: "research",
          label: "AI 调研",
          children: <AIResearchWorkbench />,
        },
        {
          key: "materials",
          label: "调研资料与来源",
          children: <InformationCenterPage embedded />,
        },
      ]}
    />
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
      {insight.key_facts.length ? (
        <ul>
          {insight.key_facts.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : (
        <Typography.Text type="secondary">暂无关键事实</Typography.Text>
      )}
      <Typography.Title level={5}>不确定性</Typography.Title>
      {insight.uncertainties.length ? (
        <ul>
          {insight.uncertainties.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : (
        <Typography.Text type="secondary">未声明不确定性</Typography.Text>
      )}
      <Typography.Title level={5}>原始来源证据（需人工核对）</Typography.Title>
      <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
        {insight.evidence.map((evidence) => {
          const href = evidence.information_item_id
            ? `/information/${evidence.information_item_id}`
            : `/market-events/${evidence.market_event_id}`;
          return (
            <Card key={evidence.evidence_id} size="small">
              <Space orientation="vertical">
                <Link to={href}>打开原始事实</Link>
                <Typography.Text>{evidence.evidence_text}</Typography.Text>
                <Typography.Text type="secondary">
                  {evidence.evidence_location ?? "未标注位置"}
                </Typography.Text>
              </Space>
            </Card>
          );
        })}
      </Space>
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
      <PageHeader
        title={
          run.data?.insight?.title ??
          run.data?.user_question ??
          (run.data ? analysisTypeText[run.data.analysis_type] : "AI 调研报告")
        }
        description="查看调研结论、引用资料与证据链。"
      />
      {run.data ? (
        <Space orientation="vertical" size="large" style={{ width: "100%" }}>
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
                  key: "type",
                  label: "调研类型",
                  children:
                    analysisTypeText[run.data.analysis_type] ??
                    run.data.analysis_type,
                },
              ]}
            />
            <Collapse
              ghost
              style={{ marginTop: 12 }}
              items={[
                {
                  key: "technical",
                  label: "技术详情",
                  children: (
                    <Descriptions
                      bordered
                      size="small"
                      column={2}
                      items={[
                        {
                          key: "analysis-id",
                          label: "内部调研编号",
                          children: run.data.analysis_id,
                        },
                        {
                          key: "provider",
                          label: "模型服务 / 模型",
                          children: `${run.data.provider_key} / ${run.data.model_name}`,
                        },
                        {
                          key: "provider-mode",
                          label: "分析来源",
                          children: run.data.is_real_provider
                            ? "真实服务（REAL）"
                            : "测试或未启用服务（FAKE / DISABLED）",
                        },
                        {
                          key: "prompt",
                          label: "提示词契约",
                          children: `${run.data.prompt_template_key} v${run.data.prompt_version}`,
                        },
                        {
                          key: "tokens",
                          label: "Token 用量",
                          children: `${run.data.input_token_count ?? "-"} / ${run.data.output_token_count ?? "-"} / 合计 ${run.data.total_token_count ?? "-"}`,
                        },
                        {
                          key: "cost",
                          label: "估算成本（非账单）",
                          children:
                            run.data.estimated_cost === null
                              ? "模型服务未返回用量或未配置价格"
                              : `${run.data.estimated_cost} ${run.data.cost_currency ?? "USD"}`,
                        },
                        {
                          key: "correlation",
                          label: "关联追踪编号",
                          children: run.data.correlation_id,
                        },
                      ]}
                    />
                  ),
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
        title="研究观点目录（ResearchInsight）"
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
      <PageHeader
        title="研究观点证据详情"
        description="查看观点与原始证据的只读关联。"
      />
      {insight.data ? (
        <InsightCard insight={insight.data} />
      ) : (
        <Typography.Text>加载中…</Typography.Text>
      )}
    </section>
  );
}
