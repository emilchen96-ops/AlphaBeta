import { useEffect, useState } from "react";

import { getLatestQuotes } from "../api/market";
import { marketDataWebSocket } from "../api/marketDataWebSocket";
import type { MarketQuote } from "../types/market";
import type { WebSocketState } from "../types/system";

export function useMarketQuotes(instrumentIds: string[]) {
  const subscriptionKey = [...new Set(instrumentIds)].sort().join(",");
  const [quotes, setQuotes] = useState<Record<string, MarketQuote>>({});
  const [status, setStatus] = useState<WebSocketState>("disconnected");

  useEffect(() => marketDataWebSocket.onState(setStatus), []);
  useEffect(() => {
    const stableIds = subscriptionKey ? subscriptionKey.split(",") : [];
    if (stableIds.length === 0) return undefined;
    let active = true;
    const update = (quote: MarketQuote) => {
      if (!active) return;
      setQuotes((current) => {
        if ((current[quote.instrument_id]?.revision ?? 0) >= quote.revision)
          return current;
        return { ...current, [quote.instrument_id]: quote };
      });
    };
    void getLatestQuotes(stableIds)
      .then((response) => response.items.forEach(update))
      .catch(() => undefined);
    const unsubscribe = marketDataWebSocket.subscribe(stableIds, update);
    return () => {
      active = false;
      unsubscribe();
    };
  }, [subscriptionKey]);

  return { quotes, status };
}
