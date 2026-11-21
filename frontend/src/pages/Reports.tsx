import { api } from "../lib/api";
import { useCurrentCase } from "../lib/case";
import { useI18n } from "../i18n";

/** P4-4 W2 — minimální reporting view (parita s legacy F5.5: Daubert pack).
 *
 *  S3 rozšíří /reports o compliance PDF/JSON, interop exporty a tabulku
 *  ručně označených souborů (legacy mod-reporting). */
export default function ReportsPage() {
  const { t } = useI18n();
  const { current } = useCurrentCase();

  if (!current) {
    return (<><h1>{t("reports_heading")}</h1><div className="muted">← {t("cases_heading")}.</div></>);
  }

  return (
    <>
      <h1>{t("reports_heading")} — {current.name}</h1>
      <section className="card">
        <h2>{t("daubert_section")}</h2>
        <p className="muted">{t("daubert_desc")}</p>
        <button onClick={() => window.open(api.daubertPackUrl(current.id))}>⬇ {t("btn_daubert_pack")}</button>
      </section>
    </>
  );
}
