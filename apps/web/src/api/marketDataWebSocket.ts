import type { MarketQuote } from "../types/market";
import type { WebSocketState } from "../types/system";

type Listener = (quote: MarketQuote) => void;
type StateListener = (state: WebSocketState) => void;

function websocketUrl() {
  const explicit = import.meta.env.VITE_WS_BASE_URL?.replace(/\/$/, "");
  if (explicit) return `${explicit}/ws/v1/market-data`;
  const api = (
    import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000"
  ).replace(/\/$/, "");
  return `${api.replace(/^http/, "ws")}/ws/v1/market-data`;
}

class MarketDataWebSocketClient {
  private socket: WebSocket | null = null;
  private listeners = new Map<string, Set<Listener>>();
  private stateListeners = new Set<StateListener>();
  private revisions = new Map<string, number>();
  private quotes = new Map<string, MarketQuote>();
  private attempt = 0;
  private reconnectTimer: number | null = null;
  private pingTimer: number | null = null;
  private state: WebSocketState = "disconnected";

  subscribe(instrumentIds: string[], listener: Listener) {
    for (const id of instrumentIds) {
      const listeners = this.listeners.get(id) ?? new Set<Listener>();
      listeners.add(listener);
      this.listeners.set(id, listeners);
      const cached = this.quotes.get(id);
      if (cached) listener(cached);
    }
    this.ensureConnected();
    this.sendSubscriptions("subscribe", instrumentIds);
    return () => {
      const removed: string[] = [];
      for (const id of instrumentIds) {
        const listeners = this.listeners.get(id);
        listeners?.delete(listener);
        if (listeners?.size === 0) {
          this.listeners.delete(id);
          removed.push(id);
        }
      }
      this.sendSubscriptions("unsubscribe", removed);
      if (this.listeners.size === 0) this.disconnect();
    };
  }

  onState(listener: StateListener) {
    this.stateListeners.add(listener);
    listener(this.state);
    return () => {
      this.stateListeners.delete(listener);
    };
  }

  private setState(state: WebSocketState) {
    this.state = state;
    for (const listener of this.stateListeners) listener(state);
  }

  private ensureConnected() {
    if (typeof WebSocket === "undefined" || this.socket) return;
    this.setState("connecting");
    const socket = new WebSocket(websocketUrl());
    this.socket = socket;
    socket.onopen = () => {
      this.attempt = 0;
      this.setState("connected");
      this.sendSubscriptions("hello", [...this.listeners.keys()]);
      this.pingTimer = window.setInterval(
        () => this.send({ schema_version: 1, type: "ping" }),
        15_000,
      );
    };
    socket.onmessage = (message) => this.onMessage(String(message.data));
    socket.onerror = () => socket.close();
    socket.onclose = () => {
      this.socket = null;
      if (this.pingTimer !== null) window.clearInterval(this.pingTimer);
      this.pingTimer = null;
      this.setState("disconnected");
      if (this.listeners.size > 0) {
        const delay = Math.min(1_000 * 2 ** this.attempt++, 30_000);
        this.reconnectTimer = window.setTimeout(
          () => this.ensureConnected(),
          delay,
        );
      }
    };
  }

  private disconnect() {
    if (this.reconnectTimer !== null) window.clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    this.socket?.close();
  }

  private sendSubscriptions(
    type: "hello" | "subscribe" | "unsubscribe",
    ids: string[],
  ) {
    if (ids.length > 0 || type === "hello") {
      this.send({ schema_version: 1, type, instrument_ids: ids });
    }
  }

  private send(payload: object) {
    if (this.socket?.readyState === WebSocket.OPEN)
      this.socket.send(JSON.stringify(payload));
  }

  private onMessage(raw: string) {
    let event: Record<string, unknown>;
    try {
      event = JSON.parse(raw) as Record<string, unknown>;
    } catch {
      return;
    }
    if (event.type === "quote_snapshot" && Array.isArray(event.items)) {
      for (const item of event.items) this.dispatch(item as MarketQuote);
    } else if (event.type === "quote_update") {
      this.dispatch(event as unknown as MarketQuote);
    }
  }

  private dispatch(quote: MarketQuote) {
    const current = this.revisions.get(quote.instrument_id) ?? 0;
    if (quote.revision <= current) return;
    this.revisions.set(quote.instrument_id, quote.revision);
    this.quotes.set(quote.instrument_id, quote);
    for (const listener of this.listeners.get(quote.instrument_id) ?? [])
      listener(quote);
  }
}

export const marketDataWebSocket = new MarketDataWebSocketClient();
