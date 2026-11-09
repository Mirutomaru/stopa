/* ════════════════════════════════════════════════════════════
   STOPA STP-069 — DOM testy modules.js (jsdom, vanilla Node)
   Cases modul: checkbox auto-exportu per case → PATCH /api/cases/{id}
   + rollback UI při selhání. Spustí: node tests/js/modules.test.mjs
   ════════════════════════════════════════════════════════════ */
import { JSDOM } from "jsdom";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MODULES_JS = path.join(__dirname, "../../src/stopa/web/static/js/components/modules.js");
const modulesSrc = fs.readFileSync(MODULES_JS, "utf8");

/* fixture: dva případy — jeden s auto-exportem zapnutým */
const CASES = [
  { id: "case-aaa1", name: "Případ Alfa", examiner: "M. Matúš", created_at: "2026-11-09T08:00:00Z", files: 3, artifacts: 7, auto_export_enabled: false },
  { id: "case-bbb2", name: "Případ Beta", examiner: null, created_at: "2026-11-09T09:30:00Z", files: 1, artifacts: 2, auto_export_enabled: true },
];

function makeEnv({ patchError } = {}) {
  const dom = new JSDOM(`<!DOCTYPE html><body>
    <table id="cases-table"><thead></thead><tbody></tbody></table>
    <div id="env-dbdir"></div>
    <div id="env-cases-count"></div>
    <div id="env-last-activity"></div>
  </body>`);
  const { window } = dom;

  const calls = []; // zaznamenané api volání (url, opts)
  let toasts = [];
  const sandbox = {
    document: window.document,
    console,
    Store: { set() {}, get(k) { return k === "caseId" ? null : null; } },
    esc: (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])),
    fmtDT: (iso) => iso || "—",
    toast: (msg) => { toasts.push(msg); },
    setTimeout, clearTimeout, setInterval, clearInterval,
    confirm: () => true,
    openCase: async () => {}, // stub — testuje se jen wiring, ne navigace
    api: async (url, opts = {}) => {
      calls.push({ url: String(url), opts });
      const u = String(url);
      if (u === "/api/cases") return CASES;
      if (u === "/api/diagnostics") return { python: "3.11", libraries: {}, components: {} };
      if (/^\/api\/cases\/[^/]+$/.test(u) && opts.method === "PATCH") {
        if (patchError) throw new Error(patchError);
        return {}; // PATCH OK
      }
      return {};
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(modulesSrc, sandbox); // definuje renderCasesModule + ostatní renderery
  return { sandbox, window, calls, toasts };
}

let passed = 0;
async function test(name, fn) {
  try { await fn(); console.log(`  ✓ ${name}`); passed++; }
  catch (e) { console.error(`  ✗ ${name}\n    ${e.message}`); process.exitCode = 1; }
}

await test("renderCasesModule: checkbox .case-auto-export v každém řádku, stav z auto_export_enabled", async () => {
  const env = makeEnv();
  await env.sandbox.renderCasesModule();
  const cbs = [...env.window.document.querySelectorAll("#cases-table .case-auto-export")];
  assert.equal(cbs.length, 2, "checkbox v obou řádcích");
  assert.equal(cbs[0].checked, false, "Alfa: default off (auto_export_enabled=false)");
  assert.equal(cbs[1].checked, true, "Beta: checked (auto_export_enabled=true)");
});

await test("renderCasesModule: řádek nese data-cid s case ID", async () => {
  const env = makeEnv();
  await env.sandbox.renderCasesModule();
  const rows = [...env.window.document.querySelectorAll("#cases-table tbody tr")];
  assert.equal(rows[0].dataset.cid, "case-aaa1", "data-cid = case ID (ne jméno)");
  assert.equal(rows[1].dataset.cid, "case-bbb2", "druhý řádek");
});

await test("zapnutí checkboxu: PATCH /api/cases/{id} s body {auto_export_enabled:true}", async () => {
  const env = makeEnv();
  await env.sandbox.renderCasesModule();
  const cb = env.window.document.querySelector("#cases-table .case-auto-export"); // Alfa (off)
  cb.checked = true;
  cb.dispatchEvent(new env.window.Event("change", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 0));
  const patchCall = env.calls.find((c) => c.opts.method === "PATCH" && c.url.includes("/api/cases/"));
  assert.ok(patchCall, "PATCH bylo voláno");
  assert.equal(patchCall.url, "/api/cases/case-aaa1", "endpoint s case ID z data-cid");
  assert.deepEqual(JSON.parse(patchCall.opts.body), { auto_export_enabled: true }, "body jen auto_export_enabled:true");
});

await test("vypnutí checkboxu: PATCH s body {auto_export_enabled:false}", async () => {
  const env = makeEnv();
  await env.sandbox.renderCasesModule();
  const cbs = [...env.window.document.querySelectorAll("#cases-table .case-auto-export")];
  const cb = cbs[1]; // Beta (on)
  assert.equal(cb.checked, true);
  cb.checked = false;
  cb.dispatchEvent(new env.window.Event("change", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 0));
  const patchCall = env.calls.find((c) => c.opts.method === "PATCH" && c.url.includes("/api/cases/"));
  assert.ok(patchCall, "PATCH bylo voláno");
  assert.equal(patchCall.url, "/api/cases/case-bbb2", "endpoint s case ID Bety");
  assert.deepEqual(JSON.parse(patchCall.opts.body), { auto_export_enabled: false }, "body auto_export_enabled:false");
});

await test("selhání PATCH → rollback checkboxu + warning toast (UI se neschlape)", async () => {
  const env = makeEnv({ patchError: "403 Forbidden" });
  await env.sandbox.renderCasesModule();
  const cb = env.window.document.querySelector("#cases-table .case-auto-export"); // Alfa (off)
  cb.checked = true;
  cb.dispatchEvent(new env.window.Event("change", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(cb.checked, false, "checkbox se vrátil do původního stavu");
  assert.ok(env.toasts.some((t) => /403 Forbidden/.test(t)), "toast s chybovou zprávou z API");
});

console.log(`\nmodules.js DOM testy (STP-069 auto-export checkbox): ${passed}/5 passed`);
