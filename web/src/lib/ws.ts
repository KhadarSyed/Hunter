export type WsMessage = { type: string; [key: string]: any };
type Listener = (msg: WsMessage) => void;

class AgentSocket {
  private ws: WebSocket | null = null;
  private listeners = new Set<Listener>();
  private statusListeners = new Set<(connected: boolean) => void>();
  private retryTimer: number | null = null;

  connect() {
    if (this.ws) return;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    this.ws = new WebSocket(`${proto}://${location.host}/ws`);
    this.ws.onopen = () => this.statusListeners.forEach((fn) => fn(true));
    this.ws.onclose = () => {
      this.ws = null;
      this.statusListeners.forEach((fn) => fn(false));
      this.retryTimer = window.setTimeout(() => this.connect(), 2000);
    };
    this.ws.onerror = () => this.ws?.close();
    this.ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        this.listeners.forEach((fn) => fn(msg));
      } catch {
        /* ignore malformed message */
      }
    };
  }

  onMessage(fn: Listener) {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  onStatus(fn: (connected: boolean) => void) {
    this.statusListeners.add(fn);
    return () => this.statusListeners.delete(fn);
  }
}

export const agentSocket = new AgentSocket();
