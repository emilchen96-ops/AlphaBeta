import { ApiError, apiRequest } from "../src/api/client";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

test("统一客户端解析非200错误和Correlation ID", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          error: {
            code: "DEPENDENCY_UNAVAILABLE",
            message: "Service unavailable",
            details: null,
            correlation_id: "response-id",
            timestamp: "2026-07-15T00:00:00Z",
          },
        }),
        { status: 503, headers: { "Content-Type": "application/json" } },
      ),
    ),
  );

  await expect(apiRequest("/test")).rejects.toMatchObject({
    code: "DEPENDENCY_UNAVAILABLE",
    correlationId: "response-id",
    status: 503,
  } satisfies Partial<ApiError>);
});

test("统一客户端在超时后中止请求", async () => {
  vi.useFakeTimers();
  vi.stubGlobal(
    "fetch",
    vi.fn(
      (_input: RequestInfo | URL, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            reject(new DOMException("aborted", "AbortError"));
          });
        }),
    ),
  );

  const request = apiRequest("/slow");
  const assertion = expect(request).rejects.toMatchObject({
    code: "REQUEST_TIMEOUT",
  });
  await vi.advanceTimersByTimeAsync(5_000);
  await assertion;
});

test("统一客户端将服务端500与网络断开明确区分", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          error: {
            code: "INTERNAL_SERVER_ERROR",
            message: "An unexpected error occurred",
            details: null,
            correlation_id: "server-error-id",
            timestamp: "2026-07-25T00:00:00Z",
          },
        }),
        { status: 500, headers: { "Content-Type": "application/json" } },
      ),
    ),
  );

  await expect(apiRequest("/broken")).rejects.toMatchObject({
    message: "AlphaDesk 服务内部错误，请稍后重试",
    code: "INTERNAL_SERVER_ERROR",
    correlationId: "server-error-id",
    status: 500,
  } satisfies Partial<ApiError>);
});
