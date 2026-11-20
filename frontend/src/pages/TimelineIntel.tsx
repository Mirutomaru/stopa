import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../lib/api";
import type { TimelineIntelData } from "../lib/api";
import { useCurrentCase } from "../lib/case";
import { useLiveEvent } from "../lib/live-react";
import { useI18n } from "../i18n";

/** Trvání gapu lidě čitelně (h/min/s). */
function fmtDur(s: number): string {
  if (!Number.isFinite(s) || s <= 0) return "0 s";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h > 0) return `${h} h ${m} min`;
  if (m > 0) return `${m} min ${Math.round(s % 60)} s`;
  return `${Math.round(s)} s`;
}

/** P3-6 — SPA view pokročilé timeline intelligence (P2-3 API).
 *
 *  Sekce: gapy, outliery, cross-source korelace, vysvětlení nejistoty + summary.
 *  Live auto-refresh na `timeline.event` / hotový ingest (stejně jako Timeline). */
export default function TimelineIntelPage() {
  const { t } = useI18n();
  const { current } = useCurrentCase();
  const [data, setData] = useState<TimelineIntelData | null>(null);
  const [error, setError] = useState<string | null>(null);

  function load() {
    if (!current) return;
    api.timelineIntel(current.id)
      .then(setData)
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : String(e)));
  }

  // načtení až po vyřešení listCases (useCurrentCase je asynchronní) + při přepnutí případu.
  const caseId = current?.id ?? null;
  useEffect(() => {
    if (caseId) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseId]);

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

  if (!current) {
    return (<><h1>{t("timeline_intel_heading")}</h1><div className="muted">← {t("cases_heading")}.</div></>);
  }

  return (
    <>
      <h1>{t("timeline_intel_heading")} — {current.name}</h1>
      {error && <div className="error">{t("error_prefix")} {error} <button onClick={load}>{t("retry")}</button></div>}
      {data && (
        <>
          <p className="muted">
            {data.events_analyzed} {t("ti_events_analyzed")} —{" "}
            {t("ti_gaps")}: {data.gaps.length}, outliers: {data.outliers.length},{" "}
            {t("ti_correlations")}: {data.correlations.length}
          </p>

          <section className="card">
            <h2>{t("ti_gaps")} ({data.gaps.length})</h2>
            <table className="grid">
              <thead><tr><th>{t("ti_col_ts")}</th><th>{t("ti_col_event")}</th><th>{t("ti_col_duration")}</th></tr></thead>
              <tbody>
                {data.gaps.map((g, i) => (
                  <tr key={i}>
                    <td>{g.start_ts} → {g.end_ts}</td>
                    <td>{g.start_event_id} / {g.end_event_id}</td>
                    <td>{fmtDur(g.duration_seconds)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section className="card">
            <h2>{t("ti_outliers")} ({data.outliers.length})</h2>
            <table className="grid">
              <thead><tr><th>{t("ti_col_event")}</th><th>{t("ti_col_ts")}</th><th>{t("ti_col_prev_gap")}</th><th>{t("ti_col_next_gap")}</th></tr></thead>
              <tbody>
                {data.outliers.map((o, i) => (
                  <tr key={i}>
                    <td>{o.event_id}</td>
                    <td>{o.ts_utc}</td>
                    <td>{fmtDur(o.prev_gap_seconds)}</td>
                    <td>{fmtDur(o.next_gap_seconds)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section className="card">
            <h2>{t("ti_correlations")} ({data.correlations.length})</h2>
            <table className="grid">
              <thead><tr><th>{t("ti_col_subject")}</th><th>{t("ti_col_confidence")}</th><th>{t("ti_col_sources")}</th><th>{t("ti_col_events")}</th></tr></thead>
              <tbody>
                {data.correlations.map((c) => (
                  <tr key={c.group_id}>
                    <td>{c.subject}</td>
                    <td><span className="pill">{c.confidence}</span></td>
                    <td>{c.source_ids.join(", ")}</td>
                    <td>{c.event_ids.length}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section className="card">
            <h2>{t("ti_uncertainty")} ({data.uncertainty.length})</h2>
            <table className="grid">
              <thead><tr><th>{t("ti_col_event")}</th><th>{t("ti_col_reasons")}</th><th>{t("ti_col_severity")}</th></tr></thead>
              <tbody>
                {data.uncertainty.map((u) => (
                  <tr key={u.event_id}>
                    <td>{u.event_id}</td>
                    <td>{u.reasons.join("; ")}</td>
                    <td><span className={`pill ${u.severity === "high" ? "warn" : ""}`}>{u.severity}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </>
      )}
    </>
  );
}
