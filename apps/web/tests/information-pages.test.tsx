import { fireEvent, screen } from "@testing-library/react";

import { healthyStatus, renderRoute } from "./test-utils";

const itemId = "33333333-3333-4333-8333-333333333333";
const item = {
  item_id: itemId,
  raw_document_id: "44444444-4444-4444-8444-444444444444",
  event_id: "55555555-5555-4555-8555-555555555555",
  source: {
    source_id: "66666666-6666-4666-8666-666666666666",
    source_key: "manual-user",
    display_name: "用户来源",
    source_type: "MANUAL",
    base_url: null,
    enabled: true,
    configuration: {},
    created_at: "2026-07-18T02:00:00Z",
    updated_at: "2026-07-18T02:00:00Z",
  },
  title: "公司公告",
  content: "规范化正文",
  raw_title: " 公司公告 ",
  raw_content: "原始 正文 内容",
  source_url: "https://example.test/news/1",
  published_at: "2026-07-18T01:00:00Z",
  received_at: "2026-07-18T02:00:00Z",
  event_type: "COMPANY_ANNOUNCEMENT",
  direction: "UNKNOWN",
  summary: null,
  importance: "0.8",
  status: "ACTIVE",
  instruments: [
    {
      instrument_id: "11111111-1111-4111-8111-111111111111",
      symbol: "600000",
      exchange: "SSE",
      name: "浦发银行",
    },
  ],
  themes: [{ theme_key: "bank", theme_name: "银行" }],
  duplicate: false,
  capabilities: {
    ai_analyzed: false,
    facts_verified: false,
    creates_signals: false,
    creates_orders: false,
    modifies_portfolio: false,
  },
};

function installFetch() {
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
      if (url.endsWith("/information-sources")) body = [item.source];
      else if (url.includes("/information-items?"))
        body = { items: [item], page: 1, page_size: 20, total: 1 };
      else if (url.includes("/market-events?"))
        body = { items: [item], page: 1, page_size: 20, total: 1 };
      else if (url.endsWith(`/information-items/${itemId}`)) body = item;
      else if (url.includes("/instruments?"))
        body = { items: item.instruments, page: 1, page_size: 50, total: 1 };
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

test("资讯中心展示来源、双时间和安全边界", async () => {
  renderRoute("/ai-research?tab=materials");
  expect(await screen.findByText("调研资料与来源")).toBeInTheDocument();
  expect((await screen.findAllByText("公司公告")).length).toBeGreaterThan(0);
  expect(screen.getByText(/尚未经过 AI 分析/)).toBeInTheDocument();
  expect(screen.getByText("发布时间")).toBeInTheDocument();
  expect(screen.getByText("接收时间")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /原始来源/ })).toHaveAttribute(
    "href",
    "https://example.test/news/1",
  );
});

test("手工录入表单支持来源、正文、Instrument与主题", async () => {
  renderRoute("/ai-research?tab=materials");
  fireEvent.click(screen.getByRole("button", { name: /添加调研资料/ }));
  expect(await screen.findByLabelText("来源名称")).toBeInTheDocument();
  expect(screen.getByLabelText("正文")).toBeInTheDocument();
  expect(screen.getByText("关联标的")).toBeInTheDocument();
  expect(screen.getByLabelText("主题 key")).toBeInTheDocument();
});

test("旧市场事件入口收口到 AI 调研资料", async () => {
  renderRoute("/market-events");
  expect(await screen.findByText("调研资料与来源")).toBeInTheDocument();
  expect((await screen.findAllByText("公司公告")).length).toBeGreaterThan(0);
  expect(screen.queryByRole("heading", { name: "市场事件" })).not.toBeInTheDocument();
});

test("资讯详情保留原始内容并区分发布时间与接收时间", async () => {
  renderRoute(`/information/${itemId}`);
  expect(await screen.findByText("规范化正文")).toBeInTheDocument();
  expect(screen.getByText("原始 正文 内容")).toBeInTheDocument();
  expect(screen.getByText(/原始内容（不可覆盖事实）/)).toBeInTheDocument();
  expect(screen.getByText("用户指定方向")).toBeInTheDocument();
});

test.each([
  "/ai-research?tab=materials",
  "/information",
  "/market-events",
  `/information/${itemId}`,
])(
  "%s 没有 AI 冒充或交易动作",
  async (route) => {
    renderRoute(route);
    expect(
      (await screen.findAllByText(/资讯|事件|AI 分析/)).length,
    ).toBeGreaterThan(0);
    expect(
      screen.queryByRole("button", {
        name: /AI分析|买入|卖出|下单|创建订单|自动交易/,
      }),
    ).not.toBeInTheDocument();
  },
);
