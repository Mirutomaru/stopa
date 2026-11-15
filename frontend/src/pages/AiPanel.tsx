import { useState } from "react";
import { api, ApiError } from "../lib/api";
import type { AiQueryResult } from "../lib/api";
import { useCurrentCase } from "../lib/case";
import { useLiveEvent } from "../lib/live-react";
import { useI18n } from "../i18n";

interface Msg {
  role: "user" | "assistant";
  text: string;
}

export default function AiPanelPage() {
  const { t } = useI18n();
  const { current } = useCurrentCase();
  const [mode, setMode] = useState<"nl_search" | "summary">("nl_search");
  const [question, setQuestion] = useState("");
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [liveActions, setLiveActions] = useState<string[]>([]);

  // F4.2 — live AI akce přes WS (posledních 5 z audit logu v reálném čase).
  useLiveEvent("ai.action", (ev) => {
    const ts = String(ev.ts ?? "").slice(11, 19);
    setLiveActions((a) => [`${ts} ${String(ev.action ?? "")}`, ...a].slice(0, 5));
  });

  if (!current) {
    return (<><h1>{t("ai_heading")}</h1><div className="muted">← {t("cases_heading")}.</div></>);
  }

  async function ask() {
    const q = question.trim();
    if (!q || busy) return;
    setBusy(true);
    setError(null);
    setMsgs((m) => [...m, { role: "user", text: q }]);
    try {
      const res: AiQueryResult = await api.aiQuery(current!.id, mode, { question: q });
      const answer = typeof res.answer === "string" ? res.answer : JSON.stringify(res, null, 2);
      setMsgs((m) => [...m, { role: "assistant", text: answer }]);
      setQuestion("");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1>{t("ai_heading")} — {current.name}</h1>
      <div className="card">
        {liveActions.length > 0 && (
          <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>
            AI akce (live): {liveActions.join(" · ")}
          </div>
        )}
        <div className="chat-log" aria-live="polite">
          {msgs.map((m, i) => (
            <div key={i} className={`chat-msg ${m.role}`}>{m.text}</div>
          ))}
          {msgs.length === 0 && <div className="muted">{t("loading")}</div>}
        </div>
        {error && <div className="error" style={{ marginBottom: 8 }}>{t("error_prefix")} {error}</div>}
        <div className="row">
          <select value={mode} onChange={(e) => setMode(e.target.value as "nl_search" | "summary")} aria-label="AI mode">
            <option value="nl_search">NL search</option>
            <option value="summary">Summary</option>
          </select>
          {mode === "nl_search" && (
            <input style={{ flex: 1 }} value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Např. Kdo se připojoval po půlnoci?" aria-label="dotaz" />
          )}
          <button className="primary" onClick={ask} disabled={busy || (mode === "nl_search" && !question.trim())}>
            {busy ? "…" : "AI →"}
          </button>
        </div>
      </div>
    </>
  );
}
