import { useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { useCurrentCase, fmtBytes } from "../lib/case";
import { useLiveEvent } from "../lib/live-react";
import { useI18n } from "../i18n";

export default function DashboardPage() {
  const { t } = useI18n();
  const { cases, error, current, select, reloadCases } = useCurrentCase();
  const [newName, setNewName] = useState("");
  const [busy, setBusy] = useState(false);
  const [createErr, setCreateErr] = useState<string | null>(null);

  // F4.2 — live (WS): ingest hotový/chyba → obnovit seznam případů (počty).
  useLiveEvent("ingest.progress", (ev) => {
    if (ev.status === "done" || ev.status === "error") reloadCases();
  });

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    if (!newName.trim()) return;
    setBusy(true);
    setCreateErr(null);
    try {
      const c = await api.createCase(newName.trim());
      select(c.id);
      setNewName("");
    } catch (err) {
      setCreateErr(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1>{t("cases_heading")}</h1>
      {error && <div className="error">{t("error_prefix")} {error}</div>}
      <form onSubmit={onCreate} className="card row">
        <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder={t("case_name")} aria-label={t("case_name")} />
        <button type="submit" className="primary" disabled={busy}>{t("case_new")}</button>
        {createErr && <span className="error">{createErr}</span>}
      </form>
      <div className="card">
        <table className="grid">
          <thead>
            <tr>
              <th>{t("case_name")}</th>
              <th>{t("case_examiner")}</th>
              <th>{t("case_created")}</th>
              <th>{t("case_files")}</th>
              <th>{t("case_artifacts")}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {cases.map((c) => (
              <tr key={c.id}>
                <td>
                  <strong>{c.name}</strong>
                  {current?.id === c.id && <span className="pill ok" style={{ marginLeft: 8 }}>{t("case_open")}</span>}
                </td>
                <td>{c.examiner ?? "—"}</td>
                <td>{new Date(c.created_at).toLocaleString()}</td>
                <td>{c.files} ({fmtBytes(c.bytes)})</td>
                <td>{c.artifacts}</td>
                <td className="row">
                  {current?.id !== c.id && (
                    <button onClick={() => select(c.id)} aria-label={`${t("case_open")} ${c.name}`}>→</button>
                  )}
                  <Link to="/files">{t("nav_files")}</Link>
                  <Link to="/timeline">⏱</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
