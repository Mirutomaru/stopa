/* ════════════════════════════════════════════════════════════
   STOPA Forensic — AI ASSISTANT (E11): LM Studio chat panel.
   Režimy: nl_search (přirozená řeč → FTS query), summary, explain.
   Citace = klikací chipy → File Inspector / detail artifactu.
   ════════════════════════════════════════════════════════════ */
"use strict";

let _aiBusy = false;

/* ── status LM Studio ─────────────────────────────────────── */
async function renderAiModule(cid) {
  const statusEl = document.getElementById("ai-status");
  if (!statusEl) return;
  statusEl.innerHTML = '<span class="muted">Kontroluji dostupnost AI…</span>';
  try {
    const st = await api("/api/ai/status");
    Store.set("aiStatus", st);
    if (st.available) {
      statusEl.innerHTML =
        `<span class="dot ok"></span> <b>AI připravena</b>` +
        ` <span class="muted">LM Studio · model ${esc(st.model || "—")}</span>`;
    } else {
      statusEl.innerHTML =
        `<span class="dot warn"></span> <b>AI nedostupná</b>` +
        ` <span class="muted">spusťte LM Studio (localhost:1234) a načtěte model —` +
        ` dotazy se pak budou odpovídat automaticky</span>`;
    }
  } catch (e) {
    Store.set("aiStatus", { available: false });
    statusEl.innerHTML = `<span class="dot bad"></span> <b>AI nedostupná</b> <span class="muted">${esc(e.message)}</span>`;
  }

  // přepínač režimů — show/hide inputů
  const modeSel = document.getElementById("ai-mode");
  const qInput = document.getElementById("ai-question");
  const explainPick = document.getElementById("ai-explain-pick");
  const syncModeUi = () => {
    const m = modeSel.value;
    qInput.classList.toggle("hidden", m === "summary" || m === "explain");
    explainPick.classList.toggle("hidden", m !== "explain");
  };
  modeSel.onchange = syncModeUi;
  syncModeUi();

  document.getElementById("btn-ai-send").onclick = () => sendAiQuery(cid);
  qInput.addEventListener("keydown", (e) => { if (e.key === "Enter") sendAiQuery(cid); });

  renderAiChat();
}

/* ── odeslání dotazu ──────────────────────────────────────── */
async function sendAiQuery(cid) {
  if (_aiBusy || !cid) return;
  const mode = document.getElementById("ai-mode").value;
  const question = document.getElementById("ai-question").value.trim();
  const artifactId = document.getElementById("ai-artifact-id").value.trim() || null;

  let userLabel;
  if (mode === "nl_search") {
    if (!question) return toast("⚠ napište otázku");
    userLabel = `🔎 ${question}`;
  } else if (mode === "summary") {
    userLabel = "📋 Shrň tento případ";
  } else {
    if (!artifactId) return toast("⚠ vložte ID artifactu");
    userLabel = `💡 Vysvětli artifact ${artifactId}`;
  }

  _aiBusy = true;
  const btn = document.getElementById("btn-ai-send");
  btn.disabled = true;
  setTaskLabel("AI přemýšlí… (lokální inference může trvat)");
  pushAiMsg({ role: "user", text: userLabel });

  try {
    const r = await api(`/api/cases/${cid}/ai/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode, question, artifact_id: artifactId }),
    });
    pushAiMsg({ role: "assistant", data: r });
  } catch (e) {
    pushAiMsg({ role: "error", text: e.message });
  } finally {
    _aiBusy = false;
    btn.disabled = false;
    renderAiChat();
  }
}

/* ── chat historie + render ───────────────────────────────── */
function pushAiMsg(msg) {
  const hist = Store.get("aiMessages") || [];
  hist.push({ ...msg, ts: Date.now() });
  Store.set("aiMessages", hist);
}

function citationChipsHtml(citations) {
  if (!citations?.length) return "";
  return `<div class="ai-cites">${citations.map((c) => {
    const isFile = !!c.file_id;
    const label = c.rel_path || c.name || c.title || c.artifact_id || c.file_id;
    const cls = isFile ? "file" : "artifact";
    return `<button class="ai-cite ${cls}" data-fid="${esc(c.file_id || "")}" ` +
      `data-title="${esc(label)}" title="${esc(label)}">` +
      `${isFile ? "📄" : "◈"} <span>${esc(shortLabel(label))}</span></button>`;
  }).join("")}</div>`;
}

function renderAiChat() {
  const el = document.getElementById("ai-chat");
  if (!el) return;
  const hist = Store.get("aiMessages") || [];
  if (!hist.length) {
    el.innerHTML = '<p class="muted small">Zatím žádné dotazy — zeptejte se AI na cokoliv o tomto případě.</p>';
    return;
  }
  el.innerHTML = hist.map((m, i) => {
    if (m.role === "user") {
      return `<div class="ai-msg user"><span class="who">VY</span><div class="body">${esc(m.text)}</div></div>`;
    }
    if (m.role === "error") {
      return `<div class="ai-msg error"><span class="who">⚠</span><div class="body mono small">${esc(m.text)}</div></div>`;
    }
    const d = m.data || {};
    let extra = "";
    if (d.mode === "nl_search" && d.query) {
      extra += `<div class="ai-query">použitý dotaz: <code>${esc(d.query)}</code></div>`;
    }
    if (typeof d.confidence === "number") {
      extra += ` <span class="conf-badge ${d.confidence >= 0.8 ? "verified" : "inferred"}">confidence ${d.confidence.toFixed(2)}</span>`;
    }
    const cites = citationChipsHtml(d.citations);
    return `<div class="ai-msg assistant"><span class="who">AI</span>
      <div class="body">${esc(d.answer || "—")}${extra}</div>${cites}</div>`;
  }).join("");

  // klikací citace → File Inspector (soubor) / toast (artifact bez file_id)
  el.querySelectorAll(".ai-cite").forEach((b) => {
    b.addEventListener("click", () => {
      const fid = b.dataset.fid;
      if (fid && Store.get("caseId")) openInspector(fid);
      else toast(`◈ ${b.dataset.title || "artifact"}`);
    });
  });

  el.scrollTop = el.scrollHeight;
}
