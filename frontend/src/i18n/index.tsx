import { createContext, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";

export type Lang = "cs" | "en";

const DICT: Record<Lang, Record<string, string>> = {
  cs: {
    app_title: "STOPA — Forenzní workbench",
    nav_dashboard: "Přehled",
    nav_files: "Soubory",
    nav_timeline: "Timeline",
    nav_entities: "Entity & graf",
    nav_ai: "AI Copilot",
    nav_hypotheses: "Graf hypotéz",
    cases_heading: "Případy",
    case_new: "Nový případ",
    case_name: "Název",
    case_examiner: "Pracovník",
    case_created: "Vytvořeno",
    case_files: "Soubory",
    case_artifacts: "Artefakty",
    case_open: "Otevřít",
    files_heading: "File System grid",
    timeline_heading: "Timeline",
    entities_heading: "Entity a vztahy",
    ai_heading: "AI Copilot",
    hypotheses_heading: "Graf hypotéz",
    lang_toggle: "EN",
    loading: "Načítám…",
    error_prefix: "Chyba:",
    retry: "Zkusit znovu",
    live_online: "LIVE",
    live_offline: "OFFLINE (REST)",
  },
  en: {
    app_title: "STOPA — Forensic workbench",
    nav_dashboard: "Dashboard",
    nav_files: "Files",
    nav_timeline: "Timeline",
    nav_entities: "Entities & graph",
    nav_ai: "AI Copilot",
    nav_hypotheses: "Hypothesis graph",
    cases_heading: "Cases",
    case_new: "New case",
    case_name: "Name",
    case_examiner: "Examiner",
    case_created: "Created",
    case_files: "Files",
    case_artifacts: "Artifacts",
    case_open: "Open",
    files_heading: "File System grid",
    timeline_heading: "Timeline",
    entities_heading: "Entities & relations",
    ai_heading: "AI Copilot",
    hypotheses_heading: "Hypothesis graph",
    lang_toggle: "CS",
    loading: "Loading…",
    error_prefix: "Error:",
    retry: "Retry",
    live_online: "LIVE",
    live_offline: "OFFLINE (REST)",
  },
};

interface I18nCtx {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: string) => string;
}

const Ctx = createContext<I18nCtx>({ lang: "cs", setLang: () => undefined, t: (k) => k });

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(() => {
    const saved = localStorage.getItem("stopa.lang");
    return saved === "en" ? "en" : "cs";
  });

  const value = useMemo<I18nCtx>(
    () => ({
      lang,
      setLang: (l) => {
        localStorage.setItem("stopa.lang", l);
        document.documentElement.lang = l;
        setLangState(l);
      },
      t: (key) => DICT[lang][key] ?? key,
    }),
    [lang],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useI18n() {
  return useContext(Ctx);
}
