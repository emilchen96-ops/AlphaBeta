import { marketDataWebSocket } from "../src/api/marketDataWebSocket";
import type { MarketQuote } from "../src/types/market";

class FakeWebSocket {
  static readonly OPEN = 1;
  static instances: FakeWebSocket[] = [];
  readyState = 0;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;

  constructor(readonly url: string) {
    FakeWebSocket.instances.push(this);
  }

  send(value: string) {
    this.sent.push(value);
  }

  close() {
    this.readyState = 3;
    this.onclose?.();
  }

  open() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }

  receive(payload: object) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }
}

afterEach(() => {
  vi.unstubAllGlobals();
  FakeWebSocket.instances = [];
});

test("集中式行情客户端发送 hello 并丢弃重复 revision", () => {
  vi.stubGlobal("WebSocket", FakeWebSocket);
  const instrumentId = "11111111-1111-4111-8111-111111111111";
  const received: MarketQuote[] = [];
  const unsubscribe = marketDataWebSocket.subscribe([instrumentId], (quote) =>
    received.push(quote),
  );
  const socket = FakeWebSocket.instances[0];
  socket.open();
  expect(JSON.parse(socket.sent[0])).toMatchObject({
    schema_version: 1,
    type: "hello",
    instrument_ids: [instrumentId],
  });
  const quote = {
    type: "quote_update",
    instrument_id: instrumentId,
    source_code: "AKSHARE_EASTMONEY",
    symbol: "600000",
    quote_time: null,
    received_at: "2026-07-15T00:00:00Z",
    last_price: "10.25",
    quality_status: "INCOMPLETE",
    revision: 1,
  };
  socket.receive(quote);
  socket.receive(quote);
  socket.receive({ ...quote, last_price: "10.26", revision: 2 });
  expect(received.map((item) => item.revision)).toEqual([1, 2]);
  unsubscribe();
});
