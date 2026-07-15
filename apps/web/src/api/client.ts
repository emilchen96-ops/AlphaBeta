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
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(
    () => controller.abort(),
    DEFAULT_TIMEOUT_MS,
  );

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
      );
    }
    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError("请求超时，请稍后重试", 0, "REQUEST_TIMEOUT", null);
    }
    throw new ApiError("无法连接 AlphaDesk API", 0, "NETWORK_ERROR", null);
  } finally {
    window.clearTimeout(timeoutId);
  }
}
