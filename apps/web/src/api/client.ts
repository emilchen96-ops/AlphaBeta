import type { ApiErrorEnvelope } from "../types/system";

const DEFAULT_TIMEOUT_MS = 5_000;
const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code: string,
    public readonly correlationId: string | null,
    public readonly details: unknown = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
  timeoutMs = DEFAULT_TIMEOUT_MS,
): Promise<T> {
  const controller = new AbortController();
  const externalSignal = init.signal;
  const cancelRequest = () => controller.abort();
  externalSignal?.addEventListener("abort", cancelRequest, { once: true });
  const timeoutId = window.setTimeout(cancelRequest, timeoutMs);

  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        ...init.headers,
      },
    });
    const correlationId = response.headers.get("X-Correlation-ID");
    if (!response.ok) {
      let envelope: ApiErrorEnvelope | null = null;
      try {
        envelope = (await response.json()) as ApiErrorEnvelope;
      } catch (error) {
        if (!(error instanceof SyntaxError)) {
          throw error;
        }
      }
      throw new ApiError(
        envelope?.error.message ?? "服务暂时不可用",
        response.status,
        envelope?.error.code ?? "HTTP_ERROR",
        envelope?.error.correlation_id ?? correlationId,
        envelope?.error.details ?? null,
      );
    }
    if (response.status === 204) {
      return undefined as T;
    }
    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    if (error instanceof DOMException && error.name === "AbortError") {
      if (externalSignal?.aborted) {
        throw new ApiError("请求已取消", 0, "REQUEST_CANCELLED", null);
      }
      throw new ApiError("请求超时，请稍后重试", 0, "REQUEST_TIMEOUT", null);
    }
    throw new ApiError("无法连接 AlphaDesk API", 0, "NETWORK_ERROR", null);
  } finally {
    window.clearTimeout(timeoutId);
    externalSignal?.removeEventListener("abort", cancelRequest);
  }
}
