export type WsMessage = { type: string; [key: string]: any };
type Listener = (msg: WsMessage) => void;

const RETRY_BASE_MS = 2000;
const RETRY_MAX_MS = 30000;

class AgentSocket {
  private ws: WebSocket | null = null;
  private listeners = new Set<Listener>();
  private statusListeners = new Set<(connected: boolean) => void>();
  private retryTimer: number | null = null;
  private retries = 0;

  connect() {
    if (this.ws) return;
    // Same VITE_API_BASE_URL used by intel-api.ts for REST calls — when unset (same-origin
    // deploy), falls back to the page's own host, matching prior behavior.
    // VITE_WS_URL wins: a host whose /api is a rewrite (Vercel) cannot proxy a WebSocket, so it connects to
    // the backend directly.
    const apiOrigin = import.meta.env.VITE_API_BASE_URL as string | undefined;
    const direct = import.meta.env.VITE_WS_URL as string | undefined;
    let wsUrl: string;
    if (direct) {
      wsUrl = direct;
    } else if (apiOrigin) {
      wsUrl = apiOrigin.replace(/^http/, "ws") + "/ws";
    } else {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      wsUrl = `${proto}://${location.host}/ws`;
    }
    this.ws = new WebSocket(wsUrl);
    this.ws.onopen = () => {
      this.retries = 0;
      this.statusListeners.forEach((fn) => fn(true));
    };
    this.ws.onclose = () => {
      this.ws = null;
      this.statusListeners.forEach((fn) => fn(false));
      // back off while the server is down or restarting: a fixed 2s retry gets the browser rate-limited (429)
      const delay = Math.min(RETRY_MAX_MS, RETRY_BASE_MS * 2 ** this.retries++);
      this.retryTimer = window.setTimeout(() => this.connect(), delay);
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
