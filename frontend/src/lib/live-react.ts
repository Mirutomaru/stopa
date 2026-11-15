import { useEffect, useRef } from "react";
import { live } from "./live";
import type { LiveEvent } from "./live";

/** Připojí/odpojí WS k případu podle `caseId` (idempotentní). */
export function useLiveConnection(caseId: string | null): void {
  useEffect(() => {
    if (!caseId) return;
    live.connect(caseId);
  }, [caseId]);
}

/** Globální stav spojení pro indikátor LIVE/OFFLINE. */
export function useLiveOnline(): boolean {
  const ref = useRef(false);
  useEffect(() => live.onStatus((online) => (ref.current = online)), []);
  // re-render na změnu stavu řeší LiveBadge vlastním state; tady jen čtení
  return ref.current;
}

/** Přihlásí handler pro události daného typu (volitelně filtr). */
export function useLiveEvent(
  type: string,
  handler: (ev: LiveEvent) => void,
  enabled = true,
): void {
  const ref = useRef(handler);
  ref.current = handler;
  useEffect(() => {
    if (!enabled) return;
    return live.onEvent((ev) => {
      if (ev.type === type) ref.current(ev);
    });
  }, [type, enabled]);
}
