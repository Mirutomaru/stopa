/** F4.2 — Live události přes WebSocket s reconnection (exponenciální backoff + jitter)
 *  a stavem pro graceful degradation na REST polling.
 *
 * Kontrakt serveru (`/api/cases/{case_id}/ws`):
 * - `hello` při připojení, `heartbeat` při neaktivitě, pak stream:
 *   `ingest.progress`, `timeline.event`, `ai.action`.
 */
export type LiveEvent = {
  type: string; // hello | heartbeat | ingest.progress | timeline.event | ai.action
  case_id?: string;
  ts?: string;
} & Record<string, unknown>;

type EventListener = (ev: LiveEvent) => void;
type StatusListener = (online: boolean) => void;

const BACKOFF_BASE_MS = 500;
const BACKOFF_MAX_MS = 8000;

class LiveClient {
  private ws: WebSocket | null = null;
  private url: string | null = null;
  private listeners = new Set<EventListener>();
  private statusListeners = new Set<StatusListener>();
  private attempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | undefined;
  private manualClose = false;

  get online(): boolean {
    return this.ws !== null && this.ws.readyState === WebSocket.OPEN;
  }

  /** (Re)připojí k událostem případu. Idempotentní pro stejnou URL. */
  connect(caseId: string): void {
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const url = `${proto}://${window.location.host}/api/cases/${encodeURIComponent(
      caseId,
    )}/ws`;
    if (
      this.url === url &&
      this.ws !== null &&
      (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)
    ) {
      return; // stejné spojení už běží (více komponent sdílí singleton)
    }
    this.disconnect();
    this.url = url;
    this.manualClose = false;
    this.attempt = 0;
    this.open(url);
  }

  private open(url: string): void {
    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch {
      this.scheduleReconnect(); // např. jsdom bez WebSocket — fallback na REST
      return;
    }
    this.ws = ws;
    ws.onopen = () => {
      if (this.ws !== ws) return;
      this.attempt = 0;
      this.emitStatus(true);
    };
    ws.onmessage = (msg: MessageEvent) => {
      if (this.ws !== ws) return;
      try {
        const ev = JSON.parse(String(msg.data)) as LiveEvent;
        if (ev && typeof ev.type === "string") this.listeners.forEach((fn) => fn(ev));
      } catch {
        /* poškozený rámec — ignorovat */
      }
    };
    ws.onclose = () => {
      if (this.ws !== ws) return;
      this.emitStatus(false);
      if (!this.manualClose) this.scheduleReconnect();
    };
    ws.onerror = () => {
      try {
        ws.close();
      } catch {
        /* noop */
      }
    };
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer !== undefined || !this.url || this.manualClose) return;
    const delay = Math.min(BACKOFF_BASE_MS * 2 ** this.attempt, BACKOFF_MAX_MS);
    this.attempt += 1;
    // jitter ±20 % — ~100 klientů se nespojí do jednoho "thundering herd" (AK F4.2)
    const jittered = delay * (0.8 + Math.random() * 0.4);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = undefined;
      if (this.url !== null && !this.manualClose) this.open(this.url);
    }, jittered);
  }

  /** Ruční odpojení (výměna případu / pagehide). */
  disconnect(): void {
    this.manualClose = true;
    if (this.reconnectTimer !== undefined) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = undefined;
    }
    const ws = this.ws;
    this.ws = null;
    this.url = null;
    this.attempt = 0;
    if (ws !== null) {
      try {
        ws.onclose = null; // nepouštět scheduleReconnect po ručním close
        ws.close();
      } catch {
        /* noop */
      }
    }
    this.emitStatus(false);
  }

  /** Přihlásí listener událostí; vrací odhlašovací funkci. */
  onEvent(fn: EventListener): () => void {
    this.listeners.add(fn);
    return () => {
      this.listeners.delete(fn);
    };
  }

  /** Stav spojení (badge + REST fallback); aktuální hodnota se dodá okamžitě. */
  onStatus(fn: StatusListener): () => void {
    this.statusListeners.add(fn);
    fn(this.online);
    return () => {
      this.statusListeners.delete(fn);
    };
  }

  private emitStatus(online: boolean): void {
    this.statusListeners.forEach((fn) => fn(online));
  }
}

/** Sdílený singleton — jedno WS spojení na SPA. */
export const live = new LiveClient();
