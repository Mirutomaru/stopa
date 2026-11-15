import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import DashboardPage from "./pages/Dashboard";
import CaseFilesPage from "./pages/CaseFiles";
import TimelinePage from "./pages/Timeline";
import EntitiesPage from "./pages/Entities";
import AiPanelPage from "./pages/AiPanel";
import HypothesesPage from "./pages/Hypotheses";
import ArtifactDetailPage from "./pages/ArtifactDetail";
import { useI18n } from "./i18n";

export default function App() {
  const { t, lang, setLang } = useI18n();
  return (
    <div className="layout">
      <nav className="sidebar" aria-label={t("app_title")}>
        <div className="brand">{t("app_title").split("—")[0].trim()}</div>
        <NavLink to="/" end className={({ isActive }) => "nav-link" + (isActive ? " active" : "")}>
          {t("nav_dashboard")}
        </NavLink>
        <NavLink to="/files" className={({ isActive }) => "nav-link" + (isActive ? " active" : "")}>
          {t("nav_files")}
        </NavLink>
        <NavLink to="/timeline" className={({ isActive }) => "nav-link" + (isActive ? " active" : "")}>
          {t("nav_timeline")}
        </NavLink>
        <NavLink to="/entities" className={({ isActive }) => "nav-link" + (isActive ? " active" : "")}>
          {t("nav_entities")}
        </NavLink>
        <NavLink to="/ai" className={({ isActive }) => "nav-link" + (isActive ? " active" : "")}>
          {t("nav_ai")}
        </NavLink>
        <NavLink to="/hypotheses" className={({ isActive }) => "nav-link" + (isActive ? " active" : "")}>
          {t("nav_hypotheses")}
        </NavLink>
        <div style={{ marginTop: "auto" }}>
          <button onClick={() => setLang(lang === "cs" ? "en" : "cs")} aria-label="Jazyk / Language">
            🌐 {t("lang_toggle")}
          </button>
        </div>
      </nav>
      <main className="main">
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/files" element={<CaseFilesPage />} />
          <Route path="/artifacts/:file_id" element={<ArtifactDetailPage />} />
          <Route path="/timeline" element={<TimelinePage />} />
          <Route path="/entities" element={<EntitiesPage />} />
          <Route path="/ai" element={<AiPanelPage />} />
          <Route path="/hypotheses" element={<HypothesesPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
