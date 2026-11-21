import { useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import type { AttackHeatmapData, AttackTechnique } from "../lib/api";
import { useCurrentCase } from "../lib/case";
import { useI18n } from "../i18n";

/** P4-4 W2 — MITRE ATT&CK heat-mapa (parita s legacy F6.3: taktiky×techniky).
 *
 *  Řádky = taktiky, buňky = techniky; intenzita barvy ∝ počet artefaktů na
 *  technice; tooltip = vzorky artefaktů (title/rel_path) — stejně jako legacy.
 *  Taktika bez hitů se nevykresluje (parita s renderAttackMap v modules.js). */
export default function AttackMapPage() {
  const { t } = useI18n();
  const { current } = useCurrentCase();
  const [data, setData] = useState<AttackHeatmapData | null>(null);
  const [error, setError] = useState<string | null>(null);

  function load() {
    if (!current) return;
    api.attackMap(current.id)
      .then(setData)
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : String(e)));
  }

  const caseId = current?.id ?? null;
  useEffect(() => {
    if (caseId) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseId]);

  if (!current) {
    return (<><h1>{t("attack_heading")}</h1><div className="muted">← {t("cases_heading")}.</div></>);
  }

  const techs: AttackTechnique[] = data?.techniques ?? [];
  const maxCount = Math.max(1, ...techs.map((x) => x.count));
  const byTactic: Record<string, AttackTechnique[]> = {};
  for (const x of techs) (byTactic[x.tactic] ||= []).push(x);

  return (
    <>
      <h1>{t("attack_heading")} — {current.name}</h1>
      {error && (
        <div className="error">{t("error_prefix")} {error} <button onClick={load}>{t("retry")}</button></div>
      )}
      {data && (
        <>
          <p className="muted">
            {t("attack_artifacts")}: {data.summary.artifacts_total}{" "}
            ({t("attack_mapped")}: {data.summary.mapped_artifacts},{" "}
            {t("attack_unmapped")}: {data.summary.unmapped_artifacts}) ·{" "}
            {t("attack_techniques_hit")}: {data.summary.techniques_hit} ·{" "}
            {t("attack_coverage")}: {data.summary.coverage_pct}%
          </p>
          <a className="muted" href={api.attackMapStixUrl(current.id)}>⬇ {t("attack_stix_export")}</a>
          <hr />
          {techs.length === 0 && <div className="muted">{t("attack_empty")}</div>}
          {(data.tactics ?? []).map((tac) => {
            const rows = byTactic[tac.id];
            if (!rows || rows.length === 0) return null; // taktika bez hitů — se nevykresluje (parita F6.3)
            return (
              <div className="attack-tactic" key={tac.id}>
                <strong>{tac.name}</strong> <span className="muted">({tac.id})</span>{" "}
                {[...rows]
                  .sort((a, b) => a.id.localeCompare(b.id))
                  .map((x) => {
                    const alpha = 0.15 + 0.75 * (x.count / maxCount);
                    const samples = ((data.cells ?? {})[x.id] ?? [])
                      .map((s) => s.title || s.rel_path || "")
                      .join("; ");
                    return (
                      <span
                        key={x.id}
                        className="attack-cell"
                        style={{ background: `rgba(239,68,68,${alpha.toFixed(2)})` }}
                        title={samples}
                      >
                        {x.name} <b>{x.count}</b>
                      </span>
                    );
                  })}
              </div>
            );
          })}
        </>
      )}
    </>
  );
}
