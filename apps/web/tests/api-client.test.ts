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
