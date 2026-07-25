import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { healthyStatus, renderRoute } from "./test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

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

test("一句话策略可以确认并提交到完整快速回测入口", async () => {
  let submitted: Record<string, unknown> | null = null;
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : input.url;
      let body: unknown = healthyStatus;
      if (url.includes("/system/capabilities")) {
        body = {
          generated_at: "",
          database_reachable: true,
          counts: {},
          items: [],
        };
      } else if (url.includes("/strategy-templates")) {
        body = [];
      } else if (url.includes("/user-strategies")) {
        body = { items: [], page: 1, page_size: 100, total: 0 };
      } else if (url.includes("/instruments?")) {
        body = {
          items: [
            {
              id: "11111111-1111-4111-8111-111111111111",
              symbol: "300088",
              exchange: "SZSE",
              market: "CN_A",
              name: "长信科技",
              asset_type: "STOCK",
              currency: "CNY",
              lot_size: "100",
              price_tick: "0.01",
              timezone: "Asia/Shanghai",
              is_active: true,
              listed_at: null,
              delisted_at: null,
              lifecycle_status: "ACTIVE",
              updated_at: "",
            },
          ],
          page: 1,
          page_size: 50,
          total: 1,
        };
      } else if (url.endsWith("/strategy-specs/parse")) {
        body = {
          status: "COMPLETE",
          parser_source: "LOCAL_RULES",
          spec,
          preview: ["买入规则", "卖出规则"],
          warnings: [],
          missing_fields: [],
          ai_assistance: "DISABLED",
        };
      } else if (url.endsWith("/strategy-specs/validate")) {
        body = {
          valid: true,
          spec,
          preview: ["买入规则", "卖出规则"],
          compiled_strategy_key: "user_spec_test",
        };
      } else if (url.endsWith("/research/quick-backtests")) {
        submitted = JSON.parse(
          typeof init?.body === "string" ? init.body : "{}",
        ) as Record<string, unknown>;
        body = {
          id: "22222222-2222-4222-8222-222222222222",
          status: "COMPLETED",
        };
      }
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );

  renderRoute("/research/backtest");
  await userEvent.click(
    await screen.findByRole("button", { name: /解析策略$/ }),
  );
  await userEvent.click(
    await screen.findByRole("button", { name: "确认并使用" }),
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: /开始回测$/ })).toBeEnabled(),
  );
  await userEvent.click(screen.getByRole("combobox", { name: "回测股票" }));
  await userEvent.click(await screen.findByText("长信科技（300088.SZ）"));
  await userEvent.click(screen.getByRole("button", { name: /开始回测$/ }));

  await waitFor(() => expect(submitted).not.toBeNull());
  expect(submitted).toMatchObject({
    instrument_id: "11111111-1111-4111-8111-111111111111",
    initial_cash: "100000",
    price_adjustment_mode: "QFQ",
    spec,
  });
  expect(submitted).not.toHaveProperty("user_strategy_id");
}, 90_000);
