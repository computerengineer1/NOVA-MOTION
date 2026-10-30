/** Singleton WebSocket manager with auto-reconnect + REST-poll fallback flag.
 *
 * The UI never depends on the socket being up: `useJobProgress` also polls
 * the REST API, and this manager only accelerates updates when connected.
 */

import type { ProgressEvent } from "./types";

type Listener = (event: ProgressEvent) => void;

class ProgressSocket {
  private ws: WebSocket | null = null;
  private listeners = new Set<Listener>();
  private statusListeners = new Set<(connected: boolean) => void>();
  private retryDelay = 1000;
  private closedByUser = false;
  private url: string;

  constructor() {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    this.url = `${proto}//${window.location.host}/api/ws`;
  }

  get connected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    this.ensureConnected();
    return () => this.listeners.delete(listener);
  }

  onStatusChange(listener: (connected: boolean) => void): () => void {
    this.statusListeners.add(listener);
    listener(this.connected);
    return () => this.statusListeners.delete(listener);
  }

  private emitStatus() {
    const c = this.connected;
    this.statusListeners.forEach((l) => l(c));
  }

  private ensureConnected() {
    if (this.closedByUser) return;
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }
    try {
      this.ws = new WebSocket(this.url);
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.ws.onopen = () => {
      this.retryDelay = 1000;
      this.emitStatus();
    };
    this.ws.onmessage = (msg) => {
      try {
        const event = JSON.parse(String(msg.data)) as ProgressEvent;
        this.listeners.forEach((l) => l(event));
      } catch {
        /* ignore malformed frames */
      }
    };
    this.ws.onclose = () => {
      this.emitStatus();
      this.scheduleReconnect();
    };
    this.ws.onerror = () => {
      try { this.ws?.close(); } catch { /* noop */ }
    };
  }

  private scheduleReconnect() {
    if (this.closedByUser) return;
    window.setTimeout(() => this.ensureConnected(), this.retryDelay);
    this.retryDelay = Math.min(this.retryDelay * 1.7, 15000);
  }

  dispose() {
    this.closedByUser = true;
    try { this.ws?.close(); } catch { /* noop */ }
    this.ws = null;
  }
}

let instance: ProgressSocket | null = null;

export function getProgressSocket(): ProgressSocket {
  if (!instance) instance = new ProgressSocket();
  return instance;
}

/** Test hook: reset the singleton (used by vitest). */
export function __resetProgressSocket() {
  instance?.dispose();
  instance = null;
}
