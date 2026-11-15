import { useMemo } from "react";
import { api } from "../lib/api";
import type { EntityRow } from "../lib/api";
import { useCurrentCase, useFetch } from "../lib/case";
import { useLiveEvent } from "../lib/live-react";
import { useI18n } from "../i18n";

const KIND_COLORS: Record<string, string> = {
  user_account: "#4da3ff",
  url_host: "#3ecf8e",
  email: "#ffb454",
  ip_address: "#ff6b6b",
  path: "#b08cff",
  other: "#8b96ad",
};

/** Entity graph (Maltego-like): kruhové rozmístění uzlů, barva = kind. */
export function EntityGraph({ entities }: { entities: EntityRow[] }) {
  const W = 720;
  const H = 420;
  const CX = W / 2;
  const CY = H / 2;
  const R = Math.min(W, H) * 0.38;

  const nodes = useMemo(() => {
    return entities.map((e, i) => {
      const angle = (i / Math.max(entities.length, 1)) * Math.PI * 2 - Math.PI / 2;
      return { e, x: CX + R * Math.cos(angle), y: CY + R * Math.sin(angle) };
    });
  }, [entities]);

  const kinds = useMemo(() => [...new Set(entities.map((e) => e.kind))], [entities]);

  return (
    <div className="entity-graph">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={kinds.join(", ")}>
        {nodes.map(({ e, x, y }) => (
          <g key={e.id}>
            <circle cx={x} cy={y} r={12} fill={KIND_COLORS[e.kind] ?? KIND_COLORS.other} />
            <text x={x} y={y - 16} textAnchor="middle" fontSize={10} fill="#dce3f0">
              {e.value_normalized.length > 24 ? e.value_normalized.slice(0, 23) + "…" : e.value_normalized}
            </text>
          </g>
        ))}
      </svg>
      <div className="legend">
        {kinds.map((k) => (
          <span key={k}>
            <span className="dot" style={{ background: KIND_COLORS[k] ?? KIND_COLORS.other }} />
            {k}
          </span>
        ))}
      </div>
    </div>
  );
}

export default function EntitiesPage() {
  const { t } = useI18n();
  const { current } = useCurrentCase();

  if (!current) {
    return (<><h1>{t("entities_heading")}</h1><div className="muted">← {t("cases_heading")}.</div></>);
  }

  const { data, loading, error, reload } = useFetch(() => api.entities(current.id), [current.id]);

  // F4.2 — live (WS): hotový ingest → extrakce entity se obnoví.
  useLiveEvent("ingest.progress", (ev) => {
    if (ev.status === "done") reload();
  });

  if (loading) return (<><h1>{t("entities_heading")}</h1><div className="muted">{t("loading")}</div></>);
  if (error) return (<><h1>{t("entities_heading")}</h1><div className="error">{t("error_prefix")} {error}</div></>);

  const entities = data ?? [];
  return (
    <>
      <h1>{t("entities_heading")} — {current.name} ({entities.length})</h1>
      <EntityGraph entities={entities} />
      <div className="card" style={{ padding: 0, marginTop: 16 }}>
        <table className="grid">
          <thead><tr><th>kind</th><th>value</th></tr></thead>
          <tbody>
            {entities.map((e) => (
              <tr key={e.id}><td>{e.kind}</td><td>{e.value_normalized}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
