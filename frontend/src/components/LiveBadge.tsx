import { useEffect, useState } from "react";
import { live } from "../lib/live";
import { useI18n } from "../i18n";
import { useCurrentCase } from "../lib/case";

/** F4.2 — Live indikátor + životní cyklus WS spojení pro vybraný případ.
 *
 * - zelená tečka = WS online (real-time push);
 * - šedá = OFFLINE → aplikace zůstává funkční přes REST polling (graceful degradation).
 */
export default function LiveBadge() {
  const [online, setOnline] = useState(false);
  const { t } = useI18n();
  const { current } = useCurrentCase();

  useEffect(() => live.onStatus(setOnline), []);

  // (re)připojení při změně vybraného případu; odpojení bez případu.
  useEffect(() => {
    if (!current) return;
    live.connect(current.id);
  }, [current?.id]);

  if (!current) return null;
  const label = t(online ? "live_online" : "live_offline");
  return (
    <span className={"live-badge" + (online ? " live-online" : "")} title={label}>
      {label}
    </span>
  );
}
