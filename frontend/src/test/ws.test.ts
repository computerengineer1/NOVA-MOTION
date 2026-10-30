import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { __resetProgressSocket, getProgressSocket } from "../lib/ws";
import type { ProgressEvent } from "../lib/types";

/** Minimal WebSocket mock that records instances and lets tests drive events. */
class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static instances: MockWebSocket[] = [];

  url: string;
  readyState = MockWebSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onmessage: ((msg: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  close() { this.readyState = MockWebSocket.CLOSED; this.onclose?.(); }

  /* test drivers */
  open() { this.readyState = MockWebSocket.OPEN; this.onopen?.(); }
  send(data: unknown) { this.onmessage?.({ data: JSON.stringify(data) }); }
  sendRaw(data: string) { this.onmessage?.({ data }); }
  drop() { this.readyState = MockWebSocket.CLOSED; this.onclose?.(); }
}

beforeEach(() => {
  vi.useFakeTimers();
  MockWebSocket.instances = [];
  vi.stubGlobal("WebSocket", MockWebSocket);
  __resetProgressSocket();
});

afterEach(() => {
  __resetProgressSocket();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("ProgressSocket", () => {
  it("connects lazily on first subscribe and targets /api/ws", () => {
    const socket = getProgressSocket();
    expect(MockWebSocket.instances).toHaveLength(0);
    socket.subscribe(() => {});
    expect(MockWebSocket.instances).toHaveLength(1);
    expect(MockWebSocket.instances[0].url).toContain("/api/ws");
  });

  it("delivers parsed events to subscribers and ignores malformed frames", () => {
    const socket = getProgressSocket();
    const seen: ProgressEvent[] = [];
    socket.subscribe((e) => seen.push(e));
    const ws = MockWebSocket.instances[0];
    ws.open();
    ws.send({ type: "job_stage", job_id: "j1", status: "GENERATING" });
    ws.sendRaw("{not json!!");
    ws.send({ type: "job_progress", job_id: "j1", progress: 0.5, eta_seconds: 42 });
    expect(seen).toHaveLength(2);
    expect(seen[0].type).toBe("job_stage");
    expect(seen[1].eta_seconds).toBe(42);
  });

  it("does not spawn duplicate sockets while one is open", () => {
    const socket = getProgressSocket();
    socket.subscribe(() => {});
    MockWebSocket.instances[0].open();
    socket.subscribe(() => {});
    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it("reconnects with growing backoff after a drop", () => {
    const socket = getProgressSocket();
    socket.subscribe(() => {});
    const first = MockWebSocket.instances[0];
    first.open();
    first.drop();
    expect(MockWebSocket.instances).toHaveLength(1); // not yet
    vi.advanceTimersByTime(1000);
    expect(MockWebSocket.instances).toHaveLength(2); // reconnect #1
    MockWebSocket.instances[1].drop();
    vi.advanceTimersByTime(1600);
    expect(MockWebSocket.instances).toHaveLength(2); // backoff grew (~1.7s)
    vi.advanceTimersByTime(200);
    expect(MockWebSocket.instances).toHaveLength(3); // reconnect #2
  });

  it("reports connection status changes", () => {
    const socket = getProgressSocket();
    const states: boolean[] = [];
    socket.onStatusChange((c) => states.push(c));
    socket.subscribe(() => {});
    MockWebSocket.instances[0].open();
    MockWebSocket.instances[0].drop();
    expect(states[0]).toBe(false);       // initial
    expect(states).toContain(true);      // opened
    expect(states[states.length - 1]).toBe(false); // dropped
  });

  it("unsubscribe stops delivery", () => {
    const socket = getProgressSocket();
    const seen: ProgressEvent[] = [];
    const off = socket.subscribe((e) => seen.push(e));
    const ws = MockWebSocket.instances[0];
    ws.open();
    ws.send({ type: "hello" });
    off();
    ws.send({ type: "hello" });
    expect(seen).toHaveLength(1);
  });
});
