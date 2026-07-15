import {
  addWatchlistItem,
  createWatchlist,
  getBars,
  getInstruments,
  removeWatchlistItem,
  reorderWatchlist,
} from "../src/api/market";

function response(body: unknown, status = 200) {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => vi.unstubAllGlobals());

test("标的搜索会编码关键字和分页", async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValue(
      response({ items: [], page: 1, page_size: 50, total: 0 }),
    );
  vi.stubGlobal("fetch", fetchMock);
  await getInstruments("浦发 银行");
  expect(String(fetchMock.mock.calls[0][0])).toContain(
    "keyword=%E6%B5%A6%E5%8F%91+%E9%93%B6%E8%A1%8C",
  );
});

test("创建自选列表发送 JSON", async () => {
  const fetchMock = vi.fn().mockResolvedValue(response({ id: "w1" }, 201));
  vi.stubGlobal("fetch", fetchMock);
  await createWatchlist("核心", "说明");
  expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "POST" });
  expect(fetchMock.mock.calls[0][1]?.body).toBe(
    JSON.stringify({ name: "核心", description: "说明" }),
  );
});

test("添加自选股使用标的 ID", async () => {
  const fetchMock = vi.fn().mockResolvedValue(response({ id: "item-1" }, 201));
  vi.stubGlobal("fetch", fetchMock);
  await addWatchlistItem("w1", "i1");
  expect(String(fetchMock.mock.calls[0][0])).toContain("/watchlists/w1/items");
  expect(fetchMock.mock.calls[0][1]?.body).toContain('"instrument_id":"i1"');
});

test("移除自选股正确处理 204", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(null, 204)));
  await expect(removeWatchlistItem("w1", "x1")).resolves.toBeUndefined();
});

test("排序提交完整 ID 顺序", async () => {
  const fetchMock = vi.fn().mockResolvedValue(response(null, 204));
  vi.stubGlobal("fetch", fetchMock);
  await reorderWatchlist("w1", ["b", "a"]);
  expect(fetchMock.mock.calls[0][1]?.body).toBe(
    JSON.stringify({ item_ids: ["b", "a"] }),
  );
});

test("K线查询包含周期和复权参数", async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValue(
      response({ source_code: "DEMO", items: [], freshness: {} }),
    );
  vi.stubGlobal("fetch", fetchMock);
  await getBars("i1", "MINUTE_1", "FORWARD");
  const url = String(fetchMock.mock.calls[0][0]);
  expect(url).toContain("timeframe=MINUTE_1");
  expect(url).toContain("adjustment_type=FORWARD");
});
