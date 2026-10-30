/* ════════════════════════════════════════════════════════════
   STOPA Forensic — API helpery + formátování (sdílené všemi moduly)
   Sleduje počet letajících requestů → status bar "Analyzing…"
   ════════════════════════════════════════════════════════════ */
"use strict";

let _inflight = 0;

async function api(path, opts = {}) {
  _inflight++;
  Store.set("busy", true);
  try {
    const r = await fetch(path, opts);
    if (!r.ok) throw new Error(`${path} → ${r.status}: ${(await r.text()).slice(0, 200)}`);
    return r.json();
  } finally {
    _inflight--;
    Store.set("busy", _inflight > 0);
  }
}

function setTaskLabel(label) {
  Store.set("taskLabel", label || "");
}

/* ── formátování ─────────────────────────────────────────── */
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function fmtBytes(n) {
  if (!n && n !== 0) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${i === 0 ? n : n.toFixed(2)} ${units[i]}`;
}

function fmtDT(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d)) return esc(iso);
  const p = (x) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

function splitDT(iso) {
  if (!iso) return ["—", "—"];
  const d = new Date(iso);
  if (isNaN(d)) return [esc(iso), "—"];
  const p = (x) => String(x).padStart(2, "0");
  return [`${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`,
          `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`];
}

function toast(msg, ms = 3500) {
  const t = document.getElementById("toast");
  if (!t) return;
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.add("hidden"), ms);
}
