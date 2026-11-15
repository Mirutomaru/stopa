import { Link, useParams } from "react-router-dom";
import type { FileRow } from "../lib/api";
import { api } from "../lib/api";
import { useCurrentCase, useFetch } from "../lib/case";
import { useI18n } from "../i18n";

/** Artifact detail (AK F4.1) — podrobnosti souboru + export link. */
export default function ArtifactDetailPage() {
  const { t } = useI18n();
  const { file_id: fileId } = useParams<{ file_id: string }>();
  const { current } = useCurrentCase();

  if (!current || !fileId) {
    return (
      <>
        <h1>Artifact detail</h1>
        <div className="muted">← <Link to="/files">{t("nav_files")}</Link></div>
      </>
    );
  }

  const file = useFetch(() => api.files(current!.id, { limit: 500 }), [current.id]);
  const row: FileRow | undefined = (file.data ?? []).find((f) => f.id === fileId);

  return (
    <>
      <h1>Artifact detail — {row ? String(row.rel_path) : fileId}</h1>
      <div className="muted" style={{ marginBottom: 12 }}>
        ← <Link to="/files">{t("nav_files")}</Link> ·{" "}
        <a href={`/api/cases/${encodeURIComponent(current.id)}/files/${encodeURIComponent(fileId)}/export`}>↓ export</a>
      </div>
      {file.loading && <div className="muted">{t("loading")}</div>}
      {file.error && <div className="error">{t("error_prefix")} {file.error}</div>}
      {row && (
        <div className="card">
          <table className="grid">
            <tbody>
              {Object.entries(row)
                .filter(([, v]) => typeof v !== "object")
                .map(([k, v]) => (
                  <tr key={k}>
                    <th style={{ width: 200 }}>{k}</th>
                    <td>{String(v ?? "")}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
