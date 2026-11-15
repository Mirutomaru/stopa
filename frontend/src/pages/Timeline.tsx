import { useMemo, useRef, useState } from "react";
import { api, ApiError } from "../lib/api";
import type { TimelineRow } from "../lib/api";
import { useCurrentCase } from "../lib/case";
import { useLiveEvent } from "../lib/live-react";
import { useI18n } from "../i18n";

const PAGE = 300;

/** Timeline (AK F4.1): zoom = časové okno, lanes = seskupení podle typu události. */
export default function TimelinePage() {
  const { t } = useI18n();
  const { current } = useCurrentCase();
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [rows, setRows] = useState<TimelineRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  function load() {
    if (!current) return;
    api.timeline(current.id, { limit: PAGE, from_ts: from || undefined, to_ts: to || undefined })
      .then(setRows)
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : String(e)));
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useState(() => load());

  // F4.2 — live (WS): nový timeline event / hotový ingest → auto-refresh.
  const loadRef = useRef<() => void>(() => undefined);
  loadRef.current = load;
  useLiveEvent("timeline.event", () => loadRef.current(), Boolean(current));
  useLiveEvent(
    "ingest.progress",
    (ev) => {
      if (ev.status === "done" || ev.status === "error") loadRef.current();
    },
    Boolean(current),
  );

  const lanes = useMemo(() => {
    if (!rows) return [];
    const byType = new Map<string, TimelineRow[]>();
    for (const r of rows) {
      const key = String(r.event_type ?? r.artifact_type ?? "other");
      const list = byType.get(key);
      if (list) list.push(r);
      else byType.set(key, [r]);
    }
    return [...byType.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [rows]);

  if (!current) {
    return (<><h1>{t("timeline_heading")}</h1><div className="muted">← {t("cases_heading")}.</div></>);
  }

  return (
    <>
      <h1>{t("timeline_heading")} — {current.name}</h1>
      {error && <div className="error">{t("error_prefix")} {error} <button onClick={load}>{t("retry")}</button></div>}
      <div className="row" style={{ marginBottom: 12 }}>
        <label>{t("case_created")} od <input type="datetime-local" value={from} onChange={(e) => setFrom(e.target.value)} aria-label="od" /></label>
        <label>do <input type="datetime-local" value={to} onChange={(e) => setTo(e.target.value)} aria-label="do" /></label>
        <button className="primary" onClick={load}>Zoom</button>
      </div>
      {lanes.map(([type, items]) => (
        <section key={type} className="card">
          <h2>{type} ({items.length})</h2>
          <table className="grid">
            <thead><tr><th>UTC</th><th>lokálně</th><th>událost</th></tr></thead>
            <tbody>
              {items.map((r, i) => (
                <tr key={`${type}-${i}`}>
                  <td>{String(r.ts_utc ?? "—")}</td>
                  <td>{String(r.ts_local ?? "")}</td>
                  <td>
                    {Array.isArray(r.anomaly_flags) && r.anomaly_flags.length > 0 && (
                      <span className="pill warn" style={{ marginRight: 6 }}>{r.anomaly_flags.join(",")}</span>
                    )}
                    {String(r.title ?? "")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
    </>
  );
}
