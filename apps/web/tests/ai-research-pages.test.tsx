import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { healthyStatus, renderRoute } from "./test-utils";

const itemId = "11111111-1111-4111-8111-111111111111";
const eventId = "22222222-2222-4222-8222-222222222222";
const analysisId = "33333333-3333-4333-8333-333333333333";
const insightId = "44444444-4444-4444-8444-444444444444";
const taskId = "99999999-9999-4999-8999-999999999999";
const instrumentId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const information = {
  item_id: itemId,
  raw_document_id: "55555555-5555-4555-8555-555555555555",
  event_id: eventId,
  source: {
    source_id: "66666666-6666-4666-8666-666666666666",
    source_key: "manual-a01",
    display_name: "原始公告来源",
    source_type: "MANUAL",
    base_url: null,
    enabled: true,
    configuration: {},
    created_at: "2026-07-19T01:00:00Z",
    updated_at: "2026-07-19T01:00:00Z",
  },
  title: "A01 原始公告",
  content: "原始来源事实",
  raw_title: "A01 原始公告",
  raw_content: "原始来源事实",
  source_url: "https://example.test/a01",
  published_at: "2026-07-19T01:00:00Z",
  received_at: "2026-07-19T01:01:00Z",
  event_type: "COMPANY_ANNOUNCEMENT",
  direction: "UNKNOWN",
  summary: null,
  importance: "0.5",
  status: "ACTIVE",
  instruments: [],
  themes: [],
  duplicate: false,
  capabilities: {},
};
const insight = {
  insight_id: insightId,
  analysis_run_id: analysisId,
  insight_type: "EVENT_SUMMARY",
  title: "AI 研究摘要",
  summary: "这是基于所选来源的 AI 摘要。",
  impact_direction: "UNKNOWN",
  importance_score: "50",
  confidence: "0.5",
  time_horizon: null,
  key_facts: ["仅基于所选来源生成。"],
  uncertainties: ["仍需交叉验证。"],
  research_questions: ["是否有第二来源？"],
  structured_output: { schema_version: 1 },
  schema_version: 1,
  created_at: "2026-07-19T01:02:00Z",
  evidence: [
    {
      evidence_id: "77777777-7777-4777-8777-777777777777",
      information_item_id: itemId,
      market_event_id: null,
      evidence_text: "原始来源事实",
      evidence_location: "selected information item",
    },
  ],
  label: "AI生成，仅供研究参考。",
};
const run = {
  analysis_id: analysisId,
  provider_key: "openai_compatible",
  model_name: "research-model",
  analysis_type: "EVENT_SUMMARY",
  prompt_template_key: "alphadesk_research_grounded",
  prompt_version: "1.1.0",
  input_document_ids: [information.raw_document_id],
  input_event_ids: [eventId],
  instrument_ids: [],
  user_question: null,
  status: "COMPLETED",
  input_token_count: 100,
  output_token_count: 80,
  total_token_count: 180,
  estimated_cost: "0",
  cost_currency: "USD",
  is_real_provider: true,
  started_at: "2026-07-19T01:01:00Z",
  completed_at: "2026-07-19T01:02:00Z",
  failed_at: null,
  error: null,
  correlation_id: "88888888-8888-4888-8888-888888888888",
  created_at: "2026-07-19T01:01:00Z",
  replayed: false,
  insight,
  capabilities: {
    creates_signals: false,
    creates_orders: false,
    modifies_portfolio: false,
  },
};
const task = {
  task_id: taskId,
  instrument: {
    id: instrumentId,
    symbol: "300088",
    exchange: "SZSE",
    name: "长信科技",
  },
  question: "分析长信科技当前基本面、技术面和主要风险",
  depth: "STANDARD",
  start_date: "2026-04-21",
  end_date: "2026-07-21",
  provider_key: "openai_compatible",
  model_name: "research-model",
  engine_key: "tradingagents_graph",
  engine_version: "a33fd4c0f134485a43553a2c23a63cb14adbd88f",
  checkpoint_key: "300088.SZ:2026-07-21:STANDARD",
  execution_attempt: 1,
  last_checkpoint_at: "2026-07-21T01:02:00Z",
  is_real_provider: true,
  status: "COMPLETED",
  progress_percent: 100,
  current_stage: "结构化报告已经生成",
  warnings: [],
  error: null,
  correlation_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
  started_at: "2026-07-21T01:00:00Z",
  completed_at: "2026-07-21T01:02:00Z",
  created_at: "2026-07-21T01:00:00Z",
  updated_at: "2026-07-21T01:02:00Z",
  steps: [
    {
      step_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
      role: "TECHNICAL_ANALYST",
      role_label: "技术面分析师",
      ordinal: 0,
      status: "COMPLETED",
      title: "技术面分析",
      summary: "趋势与波动分析完成",
      structured_output: {},
      citations: [],
      input_token_count: 100,
      output_token_count: 80,
      error: null,
      started_at: "2026-07-21T01:00:00Z",
      completed_at: "2026-07-21T01:01:00Z",
    },
  ],
  events: [],
  artifacts: [],
  report: {
    report_id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
    title: "长信科技多智能体调研报告",
    executive_summary: "多角色分析后的中性结论。",
    stance: "中性",
    confidence: "中等",
    schema_version: 1,
    created_at: "2026-07-21T01:02:00Z",
  },
  capabilities: {},
};

function installFetch(
  providerMode:
    "DISABLED" | "FAKE" | "REAL_AVAILABLE" | "REAL_UNAVAILABLE" = "DISABLED",
) {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string | URL | Request) => {
      const url =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : input.url;
      let body: unknown = healthyStatus;
      if (url.endsWith("/ai/providers/status"))
        body = {
          provider_key: providerMode.startsWith("REAL")
            ? "openai_compatible"
            : providerMode === "FAKE"
              ? "fake"
              : "disabled",
          model_name: providerMode.startsWith("REAL")
            ? "research-model"
            : providerMode === "FAKE"
              ? "alphadesk-fake-v1"
              : "none",
          model: providerMode.startsWith("REAL")
            ? "research-model"
            : providerMode === "FAKE"
              ? "alphadesk-fake-v1"
              : "none",
          selectable_models: providerMode.startsWith("REAL")
            ? ["research-model", "qwen-max"]
            : providerMode === "FAKE"
              ? ["alphadesk-fake-v1"]
              : [],
          configured: providerMode !== "DISABLED",
          available: providerMode === "REAL_AVAILABLE",
          mode: providerMode,
          real_provider_available: providerMode === "REAL_AVAILABLE",
          base_url_summary:
            providerMode === "REAL_AVAILABLE"
              ? "https://ai.example.test"
              : null,
          last_success_at:
            providerMode === "REAL_AVAILABLE" ? "2026-07-21T01:00:00Z" : null,
          last_failure_at: null,
          last_error_code:
            providerMode === "REAL_UNAVAILABLE" ? "AI_PROVIDER_TIMEOUT" : null,
          capabilities: [],
          warnings: [],
          message: {
            DISABLED: "真实 AI Provider 尚未配置; 默认安全禁用",
            FAKE: "Fake Provider 仅用于测试和明确的本地演示",
            REAL_AVAILABLE: "真实 AI Provider 已配置且最近连通成功",
            REAL_UNAVAILABLE: "真实 AI Provider 配置不完整或最近连通失败",
          }[providerMode],
        };
      else if (url.endsWith("/ai/providers/test"))
        body = {
          success: true,
          provider_key: "openai_compatible",
          model_name: "research-model",
          mode: "REAL_AVAILABLE",
          latency_ms: 12,
          error_code: null,
          warnings: [],
        };
      else if (url.includes("/information-items?"))
        body = { items: [information], page: 1, page_size: 50, total: 1 };
      else if (url.includes("/market-events?"))
        body = { items: [information], page: 1, page_size: 50, total: 1 };
      else if (url.includes("/instruments?"))
        body = {
          items: [
            {
              id: instrumentId,
              symbol: "300088",
              exchange: "SZSE",
              name: "长信科技",
            },
          ],
          page: 1,
          page_size: 50,
          total: 1,
        };
      else if (url.endsWith(`/ai/research-tasks/${taskId}/report`))
        body = {
          ...task.report,
          task_id: taskId,
          sections: {
            sources: {
              items: [
                {
                  title: "最近一根本地历史日线",
                  source_id: "market-bar:2026-07-21",
                  source_type: "MARKET_BAR",
                },
              ],
            },
            conclusion: { summary: "综合结论" },
            research_overview: { summary: "调研概览内容" },
            market_environment: { summary: "市场环境内容" },
            technical_analysis: { summary: "技术面内容" },
            fundamental_analysis: { summary: "基本面内容" },
            news_events: { summary: "资讯与事件内容" },
            bull_case: { summary: "看多论证内容" },
            bear_case: { summary: "看空论证内容" },
            risk_review: { summary: "风险复核内容" },
          },
          citations: [],
          limitations: ["依赖本地历史资料"],
          markdown: "# 长信科技多智能体调研报告",
          disclaimer: "AI 生成，仅供研究参考，不构成投资建议。",
        };
      else if (url.endsWith(`/ai/research-tasks/${taskId}`)) body = task;
      else if (url.includes("/ai/research-tasks?"))
        body = { items: [task], page: 1, page_size: 10, total: 1 };
      else if (url.endsWith(`/ai/analyses/${analysisId}`)) body = run;
      else if (url.includes("/ai/analyses?"))
        body = { items: [run], page: 1, page_size: 20, total: 1 };
      else if (url.endsWith(`/research-insights/${insightId}`)) body = insight;
      else if (url.includes("/research-insights?"))
        body = { items: [insight], page: 1, page_size: 20, total: 1 };
      return Promise.resolve(
        new Response(JSON.stringify(body), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }),
  );
}

beforeEach(() => {
  vi.stubGlobal("WebSocket", undefined);
  installFetch();
});
afterEach(() => vi.unstubAllGlobals());

test("AI调研主界面只保留股票、模型、问题、深度与资料范围", async () => {
  renderRoute("/ai-research");
  expect(
    await screen.findByText(/真实 AI Provider 尚未配置/),
  ).toBeInTheDocument();
  expect(screen.getAllByText("研究股票").length).toBeGreaterThan(0);
  expect(screen.getAllByText("研究问题").length).toBeGreaterThan(0);
  expect(screen.getByText("本次调研模型")).toBeInTheDocument();
  expect(screen.getByText("调研深度")).toBeInTheDocument();
  expect(screen.getByText("资料时间范围")).toBeInTheDocument();
  expect(screen.queryByText("资讯原始事实")).not.toBeInTheDocument();
  expect(screen.queryByText("市场事件事实")).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: /开始 AI 调研/ }),
  ).toBeDisabled();
  expect(
    screen.queryByRole("button", { name: /买入|卖出|下单|自动交易/ }),
  ).not.toBeInTheDocument();
});

test("分析详情区分 AI 推断、不确定性和可追溯原始证据", async () => {
  renderRoute(`/ai-analyses/${analysisId}`);
  expect((await screen.findAllByText("AI 研究摘要")).length).toBeGreaterThan(0);
  expect(screen.getByText("AI 摘要 / 推断")).toBeInTheDocument();
  expect(screen.getByText("仍需交叉验证。")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "打开原始事实" })).toHaveAttribute(
    "href",
    `/information/${itemId}`,
  );
  await userEvent.click(screen.getByText("技术详情"));
  expect(screen.getByText("100 / 80 / 合计 180")).toBeInTheDocument();
  expect(screen.getByText("真实服务（REAL）")).toBeInTheDocument();
  expect(screen.getByText("0 USD")).toBeInTheDocument();
});

test("真实 Provider 可用时显示安全端点并允许连接测试", async () => {
  installFetch("REAL_AVAILABLE");
  renderRoute("/ai-research");
  expect(await screen.findByText("AI 模型服务已就绪")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: /开始 AI 调研/ }),
  ).toBeEnabled();
  expect(screen.getAllByText("research-model").length).toBeGreaterThan(0);
  await userEvent.click(
    screen.getByRole("button", { name: "测试所选模型连接" }),
  );
  expect((await screen.findAllByText(/research-model 可用/)).length).toBeGreaterThan(0);
  expect(screen.queryByText(/super-secret|api_key/i)).not.toBeInTheDocument();
});

test("Fake 模式明确标为演示并保留独立入口", async () => {
  installFetch("FAKE");
  renderRoute("/ai-research");
  expect(
    await screen.findByText(/确定性测试模型/),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: /开始 AI 调研/ }),
  ).toBeEnabled();
  expect(
    screen.queryByText(/真实 Provider 已配置且最近连通成功/),
  ).not.toBeInTheDocument();
});

test("真实 Provider 不可用时禁用分析且只显示稳定错误码", async () => {
  installFetch("REAL_UNAVAILABLE");
  renderRoute("/ai-research");
  expect(await screen.findByText("AI 模型服务尚未就绪")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: /开始 AI 调研/ }),
  ).toBeDisabled();
});

test("持久化任务进度与完整报告均可追溯", async () => {
  installFetch("REAL_AVAILABLE");
  renderRoute(`/ai-research/tasks/${taskId}`);
  expect(await screen.findByText("技术面分析师")).toBeInTheDocument();
  expect(screen.getByText("趋势与波动分析完成")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "查看完整报告" })).toHaveAttribute(
    "href",
    `/ai-research/tasks/${taskId}/report`,
  );
});

test("结构化报告固定按一至十展示并格式化来源证据", async () => {
  renderRoute(`/ai-research/tasks/${taskId}/report`);
  expect(await screen.findByText("长信科技多智能体调研报告")).toBeInTheDocument();
  const pageText = document.body.textContent ?? "";
  const headings = [
    "一、调研概览",
    "二、市场环境",
    "三、技术面",
    "四、基本面",
    "五、资讯与事件",
    "六、看多论证",
    "七、看空论证",
    "八、风险与不确定性",
    "九、综合结论",
    "十、资料来源",
  ];
  const positions = headings.map((heading) => pageText.indexOf(heading));
  expect(positions.every((position, index) => position >= 0 && (index === 0 || position > positions[index - 1]))).toBe(true);
  expect(
    screen.getByText(/最近一根本地历史日线 · 类型：MARKET_BAR · 编号：market-bar:2026-07-21/),
  ).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /下载 Markdown/ })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /下载 PDF/ })).toBeInTheDocument();
});

test("ResearchInsight 目录和证据详情均为只读研究页面", async () => {
  renderRoute("/research-insights");
  expect(await screen.findByText("AI 研究摘要")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "证据详情" })).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /创建订单|Signal|Broker/ }),
  ).not.toBeInTheDocument();
});

test("ResearchInsight 详情保留版本化结构与来源证据", async () => {
  renderRoute(`/research-insights/${insightId}`);
  expect((await screen.findAllByText("AI 研究摘要")).length).toBeGreaterThan(0);
  expect(screen.getByText("原始来源证据（需人工核对）")).toBeInTheDocument();
  expect(screen.getByText("selected information item")).toBeInTheDocument();
});
