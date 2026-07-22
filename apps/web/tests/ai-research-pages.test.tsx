import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { healthyStatus, renderRoute } from "./test-utils";

const itemId = "11111111-1111-4111-8111-111111111111";
const eventId = "22222222-2222-4222-8222-222222222222";
const analysisId = "33333333-3333-4333-8333-333333333333";
const insightId = "44444444-4444-4444-8444-444444444444";
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
        body = { items: [], page: 1, page_size: 50, total: 0 };
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

test("AI研究页显示 Provider 禁用状态、输入事实与安全边界", async () => {
  renderRoute("/ai-research");
  expect(
    await screen.findByText(/真实 AI Provider 尚未配置/),
  ).toBeInTheDocument();
  expect(screen.getAllByText("AI生成，仅供研究参考。").length).toBeGreaterThan(
    0,
  );
  expect(screen.getByText("资讯原始事实")).toBeInTheDocument();
  expect(screen.getByText("市场事件事实")).toBeInTheDocument();
  expect(screen.getAllByText("EVENT_SUMMARY").length).toBeGreaterThan(0);
  expect(
    screen.getByRole("button", { name: /创建真实研究分析/ }),
  ).toBeDisabled();
  expect(
    screen.queryByRole("button", { name: /买入|卖出|下单|自动交易/ }),
  ).not.toBeInTheDocument();
});

test("分析详情区分 AI 推断、不确定性和可追溯原始证据", async () => {
  renderRoute(`/ai-analyses/${analysisId}`);
  expect(await screen.findByText("AI 研究摘要")).toBeInTheDocument();
  expect(screen.getByText("AI 摘要 / 推断")).toBeInTheDocument();
  expect(screen.getByText("仍需交叉验证。")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "打开原始事实" })).toHaveAttribute(
    "href",
    `/information/${itemId}`,
  );
  expect(screen.getByText("100 / 80 / 合计 180")).toBeInTheDocument();
  expect(screen.getByText("真实服务（REAL）")).toBeInTheDocument();
  expect(screen.getByText("0 USD")).toBeInTheDocument();
});

test("真实 Provider 可用时显示安全端点并允许连接测试", async () => {
  installFetch("REAL_AVAILABLE");
  renderRoute("/ai-research");
  expect(await screen.findByText(/最近连通成功/)).toBeInTheDocument();
  expect(
    screen.getByText("Endpoint：https://ai.example.test"),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: /创建真实研究分析/ }),
  ).toBeEnabled();
  await userEvent.click(
    screen.getByRole("button", { name: "测试真实模型服务连通性" }),
  );
  expect(await screen.findByText(/模型服务连通成功/)).toBeInTheDocument();
  expect(screen.queryByText(/super-secret|api_key/i)).not.toBeInTheDocument();
});

test("Fake 模式明确标为演示并保留独立入口", async () => {
  installFetch("FAKE");
  renderRoute("/ai-research");
  expect(
    await screen.findByText(/Fake Provider 仅用于测试/),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: /运行 Fake AI 演示/ }),
  ).toBeEnabled();
  expect(
    screen.queryByText(/真实 Provider 已配置且最近连通成功/),
  ).not.toBeInTheDocument();
});

test("真实 Provider 不可用时禁用分析且只显示稳定错误码", async () => {
  installFetch("REAL_UNAVAILABLE");
  renderRoute("/ai-research");
  expect(await screen.findByText(/最近连通失败/)).toBeInTheDocument();
  expect(screen.getByText(/AI_PROVIDER_TIMEOUT/)).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: /创建真实研究分析/ }),
  ).toBeDisabled();
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
  expect(await screen.findByText("AI 研究摘要")).toBeInTheDocument();
  expect(screen.getByText("原始来源证据（需人工核对）")).toBeInTheDocument();
  expect(screen.getByText("selected information item")).toBeInTheDocument();
});
