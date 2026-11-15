import { useState } from "react";
import type { ReactNode } from "react";
import { api, ApiError } from "../lib/api";
import type { HypoGraphPayload, HypoNode } from "../lib/api";
import { useCurrentCase, useFetch } from "../lib/case";
import { useI18n } from "./../i18n";

function HypoTree({ nodes }: { nodes: HypoNode[] }) {
  const byParent = new Map<string | null, HypoNode[]>();
  for (const n of nodes) {
    const k = n.parent_id ?? null;
    const list = byParent.get(k);
    if (list) list.push(n);
    else byParent.set(k, [n]);
  }

  function render(parentId: string | null, depth: number): ReactNode {
    return (byParent.get(parentId) ?? []).map((n) => (
      <div key={n.id} style={{ marginLeft: depth * 18 }}>
        <HypoNodeView node={n} />
        <div>{render(n.id, depth + 1)}</div>
      </div>
    ));
  }

  return <div>{render(null, 0)}</div>;
}

function HypoNodeView({ node }: { node: HypoNode }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const caseId = localStorage.getItem("stopa.case") ?? "";

  async function setStatus(status: "confirmed" | "refuted" | "pending") {
    setBusy(true);
    setErr(null);
    try {
      await api.setHypoStatus(caseId, node.id, status);
      window.dispatchEvent(new Event("hypo-changed"));
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={`hypo-node ${node.status}`}>
      <strong>{node.claim}</strong>{" "}
      <span className="pill">{node.confidence.toFixed(2)}</span>
      <span className={`pill ${node.status === "confirmed" ? "ok" : node.status === "refuted" ? "bad" : ""}`} style={{ marginLeft: 6 }}>
        {node.status}
      </span>{" "}
      {!busy && (
        <>
          <button onClick={() => setStatus("confirmed")} aria-label="potvrdit">✓</button>
          <button onClick={() => setStatus("refuted")} aria-label="vyvrátit">✗</button>
        </>
      )}
      {err && <div className="error">{err}</div>}
    </div>
  );
}

export default function HypothesesPage() {
  const { t } = useI18n();
  const { current } = useCurrentCase();
  const [useAi, setUseAi] = useState(false);
  const [busy, setBusy] = useState(false);
  const [genErr, setGenErr] = useState<string | null>(null);

  if (!current) {
    return (<><h1>{t("hypotheses_heading")}</h1><div className="muted">← {t("cases_heading")}.</div></>);
  }

  const { data, reload } = useFetch(() => api.hypotheses(current.id), [current.id]);

  // F3.5 — po změně stavu uzlu překreslit payload (lineage se nemění).
  useState(() => {
    const h = () => reload();
    window.addEventListener("hypo-changed", h);
    return () => window.removeEventListener("hypo-changed", h);
  });

  async function generate() {
    setBusy(true);
    setGenErr(null);
    try {
      await api.generateHypotheses(current!.id, useAi);
      reload();
    } catch (e) {
      setGenErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const payload: HypoGraphPayload | null = data;

  return (
    <>
      <h1>{t("hypotheses_heading")} — {current.name}</h1>
      {genErr && <div className="error" style={{ marginBottom: 8 }}>{t("error_prefix")} {genErr}</div>}
      <div className="row" style={{ marginBottom: 12 }}>
        <button className="primary" onClick={generate} disabled={busy}>
          {busy ? "…" : useAi ? "Generovat (AI)" : "Generovat (fallback)"}
        </button>
        <label><input type="checkbox" checked={useAi} onChange={(e) => setUseAi(e.target.checked)} /> LM Studio</label>
        <a href={api.hypothesisExportUrl(current.id, "json")}>↓ JSON</a>
        <a href={api.hypothesisExportUrl(current.id, "pdf")}>↓ PDF</a>
      </div>
      {payload && payload.nodes.length > 0 ? (
        <HypoTree nodes={payload.nodes} />
      ) : (
        <div className="muted">{t("loading")}</div>
      )}
    </>
  );
}
