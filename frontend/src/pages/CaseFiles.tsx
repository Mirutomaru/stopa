import { useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { useCurrentCase, fmtBytes } from "../lib/case";
import { useI18n } from "../i18n";

const PAGE = 200;

export default function CaseFilesPage() {
  const { t } = useI18n();
  const { current } = useCurrentCase();
  const [rows, setRows] = useState<Awaited<ReturnType<typeof api.files>> | null>(null);
  const [offset, setOffset] = useState(0);
  const [family, setFamily] = useState("");
  const [error, setError] = useState<string | null>(null);

  function load(off: number) {
    if (!current) return;
    api.files(current.id, { limit: PAGE + 1, offset: off, family: family || undefined })
      .then(setRows)
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : String(e)));
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useState(() => load(offset));

  if (!current) {
    return (
      <>
        <h1>{t("files_heading")}</h1>
        <div className="muted">← {t("cases_heading")}: {t("case_open")}.</div>
      </>
    );
  }

  const more = rows !== null && rows.length > PAGE;
  const shown = rows ? rows.slice(0, PAGE) : [];

  return (
    <>
      <h1>{t("files_heading")} — {current.name}</h1>
      {error && <div className="error">{t("error_prefix")} {error} <button onClick={() => load(offset)}>{t("retry")}</button></div>}
      <div className="row" style={{ marginBottom: 12 }}>
        <input value={family} onChange={(e) => setFamily(e.target.value)} placeholder="signature family…" aria-label="family filter" />
        <button onClick={() => { setOffset(0); load(0); }}>{t("retry")}</button>
        <span className="muted">{rows ? `${shown.length} z ${rows.length}${more ? "+" : ""}` : "…"}</span>
      </div>
      <div className="card" style={{ padding: 0 }}>
        <table className="grid">
          <thead>
            <tr><th>rel_path</th><th>size</th><th>family</th></tr>
          </thead>
          <tbody>
            {shown.map((f) => (
              <tr key={f.id}>
                <td><Link to={`/artifacts/${encodeURIComponent(f.id)}`}>{String(f.rel_path)}</Link></td>
                <td>{typeof f.size_bytes === "number" ? fmtBytes(Number(f.size_bytes)) : "—"}</td>
                <td>{String(f.signature_type ?? "") || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {more && (
        <button onClick={() => { const n = offset + PAGE; setOffset(n); load(n); }}>↓ {PAGE} další</button>
      )}
    </>
  );
}
