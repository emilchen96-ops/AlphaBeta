import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { healthyStatus, renderRoute } from "./test-utils";

const spec = {
  schema_version: 1,
  name: "10日价格突破与放量策略",
  description: "用户描述",
  entry: {
    type: "group",
    operator: "AND",
    conditions: [
      {
        type: "comparison",
        left: {
          kind: "FIELD",
          field: "close",
          indicator: null,
          window: null,
          exclude_current: false,
          multiplier: "1",
          value: null,
        },
        operator: "GT",
        right: {
          kind: "INDICATOR",
          field: "high",
          indicator: "ROLLING_HIGHEST",
          window: 10,
          exclude_current: true,
          multiplier: "1",
          value: null,
        },
      },
      {
        type: "comparison",
        left: {
          kind: "FIELD",
          field: "volume",
          indicator: null,
          window: null,
          exclude_current: false,
          multiplier: "1",
          value: null,
        },
        operator: "GT",
        right: {
          kind: "INDICATOR",
          field: "volume",
          indicator: "AVERAGE_VOLUME",
          window: 10,
          exclude_current: true,
          multiplier: "1.2",
          value: null,
        },
      },
    ],
  },
  exit: {
    type: "group",
    operator: "AND",
    conditions: [
      {
        type: "comparison",
        left: {
          kind: "FIELD",
          field: "close",
          indicator: null,
          window: null,
          exclude_current: false,
          multiplier: "1",
          value: null,
        },
        operator: "LT",
        right: {
          kind: "INDICATOR",
          field: "close",
          indicator: "SMA",
          window: 5,
          exclude_current: false,
          multiplier: "1",
          value: null,
        },
      },
    ],
  },
  timeframe: "DAY_1",
  quantity: "100",
  single_instrument: true,
  data_range_years: 2,
  origin: "NATURAL_LANGUAGE",
};

beforeEach(() => {
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
      if (url.includes("/system/capabilities")) {
        body = { generated_at: "", database_reachable: true, counts: {}, items: [] };
      } else if (url.includes("/user-strategies")) {
        body = { items: [], page: 1, page_size: 100, total: 0 };
      } else if (url.endsWith("/strategy-specs/parse")) {
        body = {
          status: "COMPLETE",
          parser_source: "LOCAL_RULES",
          spec,
          preview: [
            "买入：收盘价大于前10日最高价且成交量大于1.2倍前10日平均成交量。",
            "卖出：收盘价小于含当日5日简单移动平均线（SMA）。",
          ],
          warnings: [],
          missing_fields: [],
          ai_assistance: "DISABLED",
        };
      }
      return Promise.resolve(
        new Response(JSON.stringify(body), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("用户可以用自然语言生成并检查结构化规则", async () => {
  renderRoute("/research/my-strategies");
  await userEvent.click(
    await screen.findByRole("button", { name: "用一句话创建第一个策略" }),
  );
  expect(
    screen.getByLabelText("自然语言策略描述"),
  ).toHaveValue(
    "10日价格突破 + 1.2倍成交量，5日均线退出，单只股票、两年日线",
  );

  await userEvent.click(
    screen.getByRole("button", { name: /解析策略$/ }),
  );

  expect(
    await screen.findByText(/收盘价大于前10日最高价/),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: /编辑规则$/ }),
  ).toBeInTheDocument();
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "确认并使用" })).toBeEnabled(),
  );
});
