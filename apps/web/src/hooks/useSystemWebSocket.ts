import { useEffect, useState } from "react";

import type { WebSocketState } from "../types/system";

const MAX_BACKOFF_MS = 30_000;
const PING_INTERVAL_MS = 15_000;

function websocketUrl(): string {
  const explicit = import.meta.env.VITE_WS_BASE_URL?.replace(/\/$/, "");
  if (explicit) {
    return `${explicit}/ws/system`;
  }
  const apiUrl = (
    import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000"
  ).replace(/\/$/, "");
  return `${apiUrl.replace(/^http/, "ws")}/ws/system`;
}

export interface SystemWebSocketResult {
  status: WebSocketState;
  lastMessageAt: Date | null;
}

export function useSystemWebSocket(): SystemWebSocketResult {
  const [status, setStatus] = useState<WebSocketState>(() =>
    typeof WebSocket === "undefined" ? "disconnected" : "connecting",
  );
  const [lastMessageAt, setLastMessageAt] = useState<Date | null>(null);

  useEffect(() => {
    if (typeof WebSocket === "undefined") {
      return undefined;
    }

    let active = true;
    let attempt = 0;
    let socket: WebSocket | null = null;
    let reconnectTimer: number | null = null;
    let pingTimer: number | null = null;

    const clearPing = () => {
      if (pingTimer !== null) {
        window.clearInterval(pingTimer);
        pingTimer = null;
      }
    };

    const connect = () => {
      if (!active) return;
      setStatus("connecting");
      socket = new WebSocket(websocketUrl());

      socket.onopen = () => {
        if (!active) return;
        attempt = 0;
        setStatus("connected");
        clearPing();
        pingTimer = window.setInterval(() => {
          if (socket?.readyState === WebSocket.OPEN) {
            socket.send("ping");
          }
        }, PING_INTERVAL_MS);
      };

      socket.onmessage = () => {
        if (active) setLastMessageAt(new Date());
      };

      socket.onerror = () => {
        socket?.close();
      };

      socket.onclose = () => {
        clearPing();
        if (!active) return;
        setStatus("disconnected");
        const delay = Math.min(1_000 * 2 ** attempt, MAX_BACKOFF_MS);
        attempt += 1;
        reconnectTimer = window.setTimeout(connect, delay);
      };
    };

    connect();
    return () => {
      active = false;
      clearPing();
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, []);

  return { status, lastMessageAt };
}
