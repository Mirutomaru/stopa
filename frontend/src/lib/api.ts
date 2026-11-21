/**
 * F4.1 — typovaný API klient STOPA web backendu (FastAPI).
 * Same-origin fetch; v dev režimu Vite proxy /api → localhost:8042.
 */

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/** Přehled případu (GET /api/cases). */
export interface CaseSummary {
  id: string;
  name: string;
  examiner: string | null;
  created_at: string;
  files: number;
  bytes: number;
  bad_ext: number;
  dups: number;
  artifacts: number;
  auto_export_enabled: boolean;
  auto_export_interval_minutes: number | null;
}

/** FileRecord — defenzivní tvar (backend model_dump, superset). */
export interface FileRow {
  id: string;
  rel_path: string;
  name?: string;
  extension?: string;
  size_bytes?: number;
  source_id?: string;
  signature_type?: string | null;
  [key: string]: unknown;
}

/** Timeline událost (E2) — s backward-kompatibilními aliasy. */
export interface TimelineRow {
  ts_utc: string | null;
  ts_local?: string | null;
  event_type?: string | null;
  artifact_type?: string | null;
  title?: string | null;
  source_id?: string | null;
  anomaly_flags?: string[];
  [key: string]: unknown;
}

/** Kanonická entity (E4). */
export interface EntityRow {
  id: string;
  kind: string;
  value_normalized: string;
  occurrences?: number;
  [key: string]: unknown;
}

/** F3.5 — uzel grafu hypotéz v graph_payload(). */
export interface HypoNode {
  id: string;
  claim: string;
  confidence: number;
  status: "pending" | "confirmed" | "refuted";
  support: string[];
  against: string[];
  parent_id?: string | null;
}

/** P3-6 — pokročilá timeline intelligence (P2-3 API, GET .../timeline/advanced-intel). */
export interface TimelineIntelData {
  case_id: string;
  events_analyzed: number;
  gaps: Array<{
    start_event_id: string;
    end_event_id: string;
    start_ts: string;
    end_ts: string;
    duration_seconds: number;
  }>;
  outliers: Array<{
    event_id: string;
    ts_utc: string;
    prev_gap_seconds: number;
    next_gap_seconds: number;
  }>;
  correlations: Array<{
    group_id: string;
    subject: string;
    confidence: string;
    source_ids: string[];
    event_ids: string[];
  }>;
  uncertainty: Array<{
    event_id: string;
    reasons: string[];
    severity: "low" | "medium" | "high";
  }>;
  summary: Record<string, number>;
}

export interface HypoLineage {
  [artifactId: string]: { type?: string; title?: string } & Record<string, unknown>;
}

export interface HypoGraphPayload {
  nodes: HypoNode[];
  edges: Array<{ from: string; to: string; kind: "parent" | "support" | "against" }>;
  lineage: HypoLineage;
  stats?: Record<string, unknown>;
}

export interface AiQueryResult {
  answer?: string;
  citations?: string[];
  fts_query?: string;
  [key: string]: unknown;
}

interface PageOpts {
  limit?: number;
  offset?: number;
  [k: string]: string | number | boolean | undefined;
}

/** F6.3 — ATT&CK heat-mapa: technika s taktikou a počtem artefaktů (P4-4 W2). */
export interface AttackTechnique {
  id: string;
  name: string;
  tactic: string;
  count: number;
}

/** F6.3 — vzorek artefaktu v heat-mapa buňce (tooltip parity s legacy). */
export interface AttackCellSample {
  artifact_type?: string | null;
  title?: string | null;
  rel_path?: string | null;
  [key: string]: unknown;
}

/** F6.3 — payload GET /api/cases/{id}/attack-map (P4-4 W2). */
export interface AttackHeatmapData {
  tactics: { id: string; name: string }[];
  techniques: AttackTechnique[];
  cells: Record<string, AttackCellSample[]>;
  summary: {
    artifacts_total: number;
    mapped_artifacts: number;
    unmapped_artifacts: number;
    techniques_hit: number;
    tactics_hit: number;
    coverage_pct: number;
  };
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* ne-JSON tělo */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

function qs(opts?: PageOpts): string {
  if (!opts) return "";
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(opts)) {
    if (v !== undefined && v !== "") p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

export const api = {
  listCases(): Promise<CaseSummary[]> {
    return req("/api/cases");
  },
  createCase(name: string, examiner?: string): Promise<CaseSummary> {
    return req("/api/cases", {
      method: "POST",
      body: JSON.stringify({ name, examiner: examiner ?? null }),
    });
  },
  files(caseId: string, opts?: PageOpts & { family?: string }): Promise<FileRow[]> {
    return req(`/api/cases/${encodeURIComponent(caseId)}/files${qs(opts)}`);
  },
  timeline(caseId: string, opts?: PageOpts): Promise<TimelineRow[]> {
    return req(`/api/cases/${encodeURIComponent(caseId)}/timeline${qs(opts)}`);
  },
  // P3-6 — pokročilá timeline intelligence (P2-3 API; bez WS/limitu, full analýza případu)
  timelineIntel(caseId: string): Promise<TimelineIntelData> {
    return req(`/api/cases/${encodeURIComponent(caseId)}/timeline/advanced-intel`);
  },
  entities(caseId: string): Promise<EntityRow[]> {
    return req(`/api/cases/${encodeURIComponent(caseId)}/entities`);
  },
  aiStatus(): Promise<{ available: boolean; model?: string | null } & Record<string, unknown>> {
    return req("/api/ai/status");
  },
  aiQuery(
    caseId: string,
    mode: "nl_search" | "summary" | "explain",
    extra: { question?: string; artifact_id?: string } = {},
  ): Promise<AiQueryResult> {
    return req(`/api/cases/${encodeURIComponent(caseId)}/ai/query`, {
      method: "POST",
      body: JSON.stringify({ mode, ...extra }),
    });
  },
  // ── F3.5 — hypothesis graph ───────────────────────────────
  hypotheses(caseId: string): Promise<HypoGraphPayload> {
    return req(`/api/cases/${encodeURIComponent(caseId)}/hypotheses`);
  },
  generateHypotheses(caseId: string, useAi = false): Promise<Record<string, unknown>> {
    return req(
      `/api/cases/${encodeURIComponent(caseId)}/hypotheses/generate`,
      { method: "POST", body: JSON.stringify({ use_ai: useAi }) },
    );
  },
  setHypoStatus(caseId: string, hypId: string, status: "pending" | "confirmed" | "refuted") {
    return req(
      `/api/cases/${encodeURIComponent(caseId)}/hypotheses/${encodeURIComponent(hypId)}/status`,
      { method: "POST", body: JSON.stringify({ status }) },
    );
  },
  hypothesisExportUrl(caseId: string, format: "json" | "pdf"): string {
    return `/api/cases/${encodeURIComponent(caseId)}/hypotheses/export?format=${format}`;
  },
  /** P4-4 W2 — MITRE ATT&CK heat-mapa (F6.3 API). */
  attackMap(caseId: string): Promise<AttackHeatmapData> {
    return req(`/api/cases/${encodeURIComponent(caseId)}/attack-map`);
  },
  /** P4-4 W2 — STIX intrusion-set export URL heat-mapy (F6.3). */
  attackMapStixUrl(caseId: string): string {
    return `/api/cases/${encodeURIComponent(caseId)}/attack-map?format=stix`;
  },
  /** P4-4 W2 — Daubert challenge preparedness pack, JSON pro soud (F5.5 API). */
  daubertPackUrl(caseId: string): string {
    return `/api/cases/${encodeURIComponent(caseId)}/daubert-pack`;
  },
};
