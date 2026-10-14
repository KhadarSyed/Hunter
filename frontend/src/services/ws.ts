export type WsMessage = { type: string; [key: string]: any };
type Listener = (msg: WsMessage) => void;

const API_ORIGIN = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "";
const RETRY_BASE_MS = 2000;
const RETRY_MAX_MS = 30000;

class AgentSocket {
  private ws: WebSocket | null = null;
  private listeners = new Set<Listener>();
  private statusListeners = new Set<(connected: boolean) => void>();
  private retryTimer: number | null = null;
  private retries = 0;
  private connecting = false;

  connect() {
    if (this.ws || this.connecting) return;
    if (this.retryTimer !== null) {          // a direct connect() replaces any pending retry
      window.clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
    this.connecting = true;
    // The socket only opens with a short-lived ticket from the signed-in REST API (the session cookie lives on
    // the page's host, which the direct WebSocket never reaches)
    fetch(`${API_ORIGIN}/api/auth/ws-ticket`, { credentials: "include" })
      .then((r) => (r.ok ? r.json() : null))
      .then((body: { ticket?: string } | null) => {
        this.connecting = false;
        if (body?.ticket) this.open(body.ticket);
        else this.scheduleRetry();           // not signed in yet: try again later
      })
      .catch(() => {
        this.connecting = false;
        this.scheduleRetry();
      });
  }

  private open(ticket: string) {
    // VITE_WS_URL wins: a host whose /api is a rewrite (Vercel) cannot proxy a WebSocket, so it connects to
    // the backend directly. Otherwise the VITE_API_BASE_URL used for REST, else the page's own host.
    const direct = import.meta.env.VITE_WS_URL as string | undefined;
    let wsUrl: string;
    if (direct) {
      wsUrl = direct;
    } else if (API_ORIGIN) {
      wsUrl = API_ORIGIN.replace(/^http/, "ws") + "/ws";
    } else {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      wsUrl = `${proto}://${location.host}/ws`;
    }
    this.ws = new WebSocket(`${wsUrl}?ticket=${encodeURIComponent(ticket)}`);
    this.ws.onopen = () => {
      this.retries = 0;
      this.statusListeners.forEach((fn) => fn(true));
    };
    this.ws.onclose = () => {
      this.ws = null;
      this.statusListeners.forEach((fn) => fn(false));
      this.scheduleRetry();
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

  private scheduleRetry() {
    // back off while the server is down or restarting: a fixed 2s retry gets the browser rate-limited (429)
    if (this.retryTimer !== null) window.clearTimeout(this.retryTimer);
    const delay = Math.min(RETRY_MAX_MS, RETRY_BASE_MS * 2 ** this.retries++);
    this.retryTimer = window.setTimeout(() => {
      this.retryTimer = null;
      this.connect();
    }, delay);
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
