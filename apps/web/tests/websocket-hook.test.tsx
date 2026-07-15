import { act, render, screen } from "@testing-library/react";

import { useSystemWebSocket } from "../src/hooks/useSystemWebSocket";

class FakeWebSocket {
  static readonly OPEN = 1;
  static instances: FakeWebSocket[] = [];
  readonly readyState = FakeWebSocket.OPEN;
  onopen: (() => void) | null = null;
  onmessage: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  close = vi.fn();
  send = vi.fn();

  constructor(public readonly url: string) {
    FakeWebSocket.instances.push(this);
  }
}

function HookProbe() {
  const { status } = useSystemWebSocket();
  return <span>{status}</span>;
}

afterEach(() => {
  FakeWebSocket.instances = [];
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

test("WebSocket Hook连接并在卸载时清理", () => {
  vi.stubGlobal("WebSocket", FakeWebSocket);
  const view = render(<HookProbe />);
  const socket = FakeWebSocket.instances[0];
  expect(socket.url).toContain("/ws/system");
  act(() => socket.onopen?.());
  expect(screen.getByText("connected")).toBeInTheDocument();
  view.unmount();
  expect(socket.close).toHaveBeenCalledOnce();
});

test("WebSocket断开后按退避间隔重连", async () => {
  vi.useFakeTimers();
  vi.stubGlobal("WebSocket", FakeWebSocket);
  const view = render(<HookProbe />);
  const first = FakeWebSocket.instances[0];
  act(() => first.onopen?.());
  act(() => first.onclose?.());
  expect(screen.getByText("disconnected")).toBeInTheDocument();
  await act(() => vi.advanceTimersByTimeAsync(1_000));
  expect(FakeWebSocket.instances).toHaveLength(2);
  view.unmount();
});
