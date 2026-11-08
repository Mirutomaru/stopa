/* ════════════════════════════════════════════════════════════
   STOPA STP-060 — DOM testy interop.js (jsdom, vanilla Node)
   Timesketch push flow: wiring tlačítka + POST /timesketch-push
   + stavový výstup (úspěch i selhání). Spustí: node tests/js/interop.test.mjs
   ════════════════════════════════════════════════════════════ */
import { JSDOM } from "jsdom";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const INTEROP_JS = path.join(__dirname, "../../src/stopa/web/static/js/components/interop.js");
const interopSrc = fs.readFileSync(INTEROP_JS, "utf8");

/* fixture: case detail + correlations + audit (pro renderInteropExports) */
const CASE_DETAIL = { artifact_stats: { total: 7 } };
const CORRELATIONS = [
  { relation: "same_contact", confidence: "verified" },
];
const AUDIT = { entries: [{ action: "interop_exported", ts: "2026-11-07T10:00:00Z", details: { what: "artifacts", format: "l2tcsv", records: 7 } }] };

function makeEnv({ pushResponse, pushError, statusResponse, statusError, plasoResponse, plasoError } = {}) {
  const dom = new JSDOM(`<!DOCTYPE html><body>
    <select id="ix-what"><option value="artifacts">Artifacty</option></select>
    <select id="ix-format"><option value="l2tcsv">l2tcsv</option></select>
    <button id="btn-interop-export"></button>
    <div class="card" id="ts-push-card">
      <button id="btn-ts-push"></button>
      <button id="btn-ts-status"></button>
      <input type="file" id="plaso-file">
      <button id="btn-plaso-import"></button>
      <div id="ts-status"></div>
      <div id="ts-index-status"></div>
      <div id="plaso-status"></div>
    </div>
    <table id="ix-datasets"><tbody></tbody></table>
    <div id="ix-recent"></div>
  </body>`);
  const { window } = dom;

  const calls = []; // zaznamenané api volání (url, opts)
  let toasts = [];
  const sandbox = {
    document: window.document,
    console,
    Store: { set() {}, get(k) { return k === "caseId" ? "c1" : null; } },
    esc: (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])),
    fmtDT: (iso) => iso || "—",
    toast: (msg) => { toasts.push(msg); },
    // host Node timery — polling v interop.js běží ve vm sandboxu
    setTimeout, clearTimeout, setInterval, clearInterval,
    FormData: window.FormData,
    File: window.File,
    api: async (url, opts = {}) => {
      calls.push({ url: String(url), opts });
      const u = String(url);
      if (u.includes("/plaso-import")) {
        if (plasoError) throw new Error(plasoError);
        return plasoResponse ?? { events_total: 12, artifacts_imported: 3, timeline_events: 9 };
      }
      if (u.includes("/timesketch-push")) {
        if (pushError) throw new Error(pushError);
        return pushResponse ?? { sketch_id: 42, timeline_id: 7, task_id: "t-1", records: 7 };
      }
      if (u.includes("/timesketch-status")) {
        if (statusError) throw new Error(statusError);
        return statusResponse ?? { sketch_id: 42, timeline_id: 7, status: "processing", updated_at: "2026-11-08T10:00:00Z" };
      }
      if (u.endsWith("/correlations")) return CORRELATIONS;
      if (u.includes("/audit")) return AUDIT;
      return CASE_DETAIL; // case detail
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(interopSrc, sandbox); // definuje renderInteropExports + IX_DATASETS
  return { sandbox, window, calls, toasts };
}

let passed = 0;
async function test(name, fn) {
  try { await fn(); console.log(`  ✓ ${name}`); passed++; }
  catch (e) { console.error(`  ✗ ${name}\n    ${e.message}`); process.exitCode = 1; }
}

await test("renderInteropExports: po renderu má btn-ts-push navázaný onclick", async () => {
  const env = makeEnv();
  await env.sandbox.renderInteropExports("c1");
  const btn = env.window.document.getElementById("btn-ts-push");
  assert.ok(btn, "tlačítko btn-ts-push existuje");
  assert.equal(typeof btn.onclick, "function", "onclick handler je navázaný");
});

await test("klik na push: POST /timesketch-push s body {what} (zvolený dataset)", async () => {
  const env = makeEnv();
  await env.sandbox.renderInteropExports("c1");
  const btn = env.window.document.getElementById("btn-ts-push");
  btn.dispatchEvent(new env.window.MouseEvent("click", { bubbles: true }));
  // onclick je async — počkej na vyřízení promise
  await new Promise((r) => setTimeout(r, 0));
  const pushCall = env.calls.find((c) => c.url.includes("/timesketch-push"));
  assert.ok(pushCall, "api bylo voláno pro timesketch-push");
  assert.equal(pushCall.opts.method, "POST", "metoda POST");
  assert.match(pushCall.url, /\/api\/cases\/c1\/timesketch-push$/, "správný endpoint s caseId");
  const body = JSON.parse(pushCall.opts.body);
  assert.deepEqual(body, { what: "artifacts" }, "body {what} z ix-what selectu");
});

await test("úspěšný push: ts-status ukazuje ✓ + sketch/timeline/records", async () => {
  const env = makeEnv({ pushResponse: { sketch_id: 42, timeline_id: 7, task_id: "t-1", records: 7 } });
  await env.sandbox.renderInteropExports("c1");
  const btn = env.window.document.getElementById("btn-ts-push");
  btn.dispatchEvent(new env.window.MouseEvent("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 0));
  const status = env.window.document.getElementById("ts-status").textContent;
  assert.match(status, /✓ Push hotovo/, "úspěšná zpráva");
  assert.match(status, /sketch 42/, "obsahuje sketch_id");
  assert.match(status, /timeline 7/, "obsahuje timeline_id");
  assert.match(status, /záznamů 7/, "obsahuje počet záznamů");
});

await test("selhání push (503): ts-status ukazuje ✗ + tlačítko se znovu aktivuje", async () => {
  const env = makeEnv({ pushError: "Timesketch nedostupná — spusťte ji" });
  await env.sandbox.renderInteropExports("c1");
  const btn = env.window.document.getElementById("btn-ts-push");
  btn.dispatchEvent(new env.window.MouseEvent("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 0));
  const status = env.window.document.getElementById("ts-status").textContent;
  assert.match(status, /✗ Push selhal/, "chybová zpráva");
  assert.equal(btn.disabled, false, "tlačítko po chybě znovu aktivní (finally)");
});

await test("během pushu je tlačítko disabled (busy stav)", async () => {
  let resolvePush;
  const env = makeEnv();
  // nahraď api tak, aby push visel dokud neresolvujeme
  const origApi = env.sandbox.api;
  env.sandbox.api = async (url, opts) => {
    if (String(url).includes("/timesketch-push")) return new Promise((res) => { resolvePush = res; });
    return origApi(url, opts);
  };
  await env.sandbox.renderInteropExports("c1");
  const btn = env.window.document.getElementById("btn-ts-push");
  btn.dispatchEvent(new env.window.MouseEvent("click", { bubbles: true }));
  // onclick je async — po prvním ticku by měl být disabled nastavený synchronně před await
  assert.equal(btn.disabled, true, "tlačítko během pushu disabled");
  resolvePush({ sketch_id: 1, timeline_id: 2, task_id: "x", records: 3 });
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(btn.disabled, false, "po dokončení znovu aktivní");
});

await test("renderInteropExports: po renderu má btn-ts-status navázaný onclick", async () => {
  const env = makeEnv();
  await env.sandbox.renderInteropExports("c1");
  const btn = env.window.document.getElementById("btn-ts-status");
  assert.ok(btn, "tlačítko btn-ts-status existuje");
  assert.equal(typeof btn.onclick, "function", "onclick handler je navázaný");
});

await test("klik na stav: GET /timesketch-status + řádek ukazuje processing… a sketch/timeline", async () => {
  const env = makeEnv({ statusResponse: { sketch_id: 42, timeline_id: 7, status: "processing", updated_at: "2026-11-08T10:00:00Z" } });
  await env.sandbox.renderInteropExports("c1");
  const btn = env.window.document.getElementById("btn-ts-status");
  btn.dispatchEvent(new env.window.MouseEvent("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 0)); // první tick (async) se vyřídí
  const call = env.calls.find((c) => c.url.includes("/timesketch-status"));
  assert.ok(call, "api bylo voláno pro timesketch-status");
  assert.match(call.url, /\/api\/cases\/c1\/timesketch-status$/, "správný endpoint s caseId");
  const row = env.window.document.getElementById("ts-index-status").textContent;
  assert.match(row, /Indexace: processing…/, "stav processing zobrazen");
  assert.match(row, /sketch 42/, "obsahuje sketch_id");
  assert.match(row, /timeline 7/, "obsahuje timeline_id");
  assert.equal(btn.textContent, "⏹ Zastavit stav", "label přepnutý na stop");
  env.sandbox.stopTsStatusPolling(); // uklidit timer před koncem testu
});

await test("terminální stav ready: polling se zastaví (label obnoveno, žádné další dotazy)", async () => {
  const env = makeEnv({ statusResponse: { sketch_id: 1, timeline_id: 2, status: "ready", updated_at: "2026-11-08T10:05:00Z" } });
  await env.sandbox.renderInteropExports("c1");
  env.sandbox.startTsStatusPolling("c1", 30); // krátký interval pro test
  await new Promise((r) => setTimeout(r, 5)); // první tick hotov → ready → stop
  const btn = env.window.document.getElementById("btn-ts-status");
  assert.equal(btn.textContent, "📡 Stav indexace", "label obnoveno po terminálním stavu");
  const row = env.window.document.getElementById("ts-index-status").textContent;
  assert.match(row, /ready ✓/, "terminální stav zobrazen");
  const n1 = env.calls.filter((c) => c.url.includes("/timesketch-status")).length;
  await new Promise((r) => setTimeout(r, 80)); // >2 intervaly — kdyby běžel, přibyly by dotazy
  const n2 = env.calls.filter((c) => c.url.includes("/timesketch-status")).length;
  assert.equal(n2, n1, "žádné další dotazy po zastavení");
});

await test("terminální stav fail: polling se zastaví", async () => {
  const env = makeEnv({ statusResponse: { sketch_id: 3, timeline_id: 4, status: "fail", updated_at: "2026-11-08T10:06:00Z" } });
  await env.sandbox.renderInteropExports("c1");
  env.sandbox.startTsStatusPolling("c1", 30);
  await new Promise((r) => setTimeout(r, 5));
  const btn = env.window.document.getElementById("btn-ts-status");
  assert.equal(btn.textContent, "📡 Stav indexace", "label obnoveno po fail stavu");
  const row = env.window.document.getElementById("ts-index-status").textContent;
  assert.match(row, /fail ✗/, "fail stav zobrazen");
  const n1 = env.calls.filter((c) => c.url.includes("/timesketch-status")).length;
  await new Promise((r) => setTimeout(r, 80));
  const n2 = env.calls.filter((c) => c.url.includes("/timesketch-status")).length;
  assert.equal(n2, n1, "žádné další dotazy po zastavení");
});

await test("404 (žádný push): řádek „Zatím žádný Timesketch push.“ + polling se zastaví", async () => {
  const env = makeEnv({ statusError: "/api/cases/c1/timesketch-status → 404: zatím žádný Timesketch push v audit logu" });
  await env.sandbox.renderInteropExports("c1");
  env.sandbox.startTsStatusPolling("c1", 30);
  await new Promise((r) => setTimeout(r, 5));
  const row = env.window.document.getElementById("ts-index-status").textContent;
  assert.match(row, /Zatím žádný Timesketch push/, "informativní zpráva místo hlášení chyby");
  const btn = env.window.document.getElementById("btn-ts-status");
  assert.equal(btn.textContent, "📡 Stav indexace", "label obnoveno po 404");
  const n1 = env.calls.filter((c) => c.url.includes("/timesketch-status")).length;
  await new Promise((r) => setTimeout(r, 80));
  const n2 = env.calls.filter((c) => c.url.includes("/timesketch-status")).length;
  assert.equal(n2, n1, "žádné další dotazy po zastavení");
});

await test("503 (Timesketch mimo): řádek ✗ Stav nedotázán + polling pokračuje", async () => {
  const env = makeEnv({ statusError: "/api/cases/c1/timesketch-status → 503: Timesketch nedostupná" });
  await env.sandbox.renderInteropExports("c1");
  env.sandbox.startTsStatusPolling("c1", 20); // krátký interval — polling má pokračovat
  await new Promise((r) => setTimeout(r, 70)); // >3 intervaly
  const row = env.window.document.getElementById("ts-index-status").textContent;
  assert.match(row, /✗ Stav nedotázán/, "chybová zpráva zobrazena");
  const n = env.calls.filter((c) => c.url.includes("/timesketch-status")).length;
  assert.ok(n >= 2, `polling pokračoval přes dočasnou chybu (${n} dotazů)`);
  env.sandbox.stopTsStatusPolling(); // uklidit timer před koncem testu
});

await test("plaso import: po renderu má btn-plaso-import navázaný onclick", async () => {
  const env = makeEnv();
  await env.sandbox.renderInteropExports("c1");
  const btn = env.window.document.getElementById("btn-plaso-import");
  assert.ok(btn, "tlačítko btn-plaso-import existuje");
  assert.equal(typeof btn.onclick, "function", "onclick handler je navázaný");
});

await test("plaso import bez souboru: plaso-status ukazuje ✗ + žádné api volání", async () => {
  const env = makeEnv();
  await env.sandbox.renderInteropExports("c1");
  const btn = env.window.document.getElementById("btn-plaso-import");
  btn.dispatchEvent(new env.window.MouseEvent("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 0));
  const status = env.window.document.getElementById("plaso-status").textContent;
  assert.match(status, /✗ Nejprve vyberte l2tcsv soubor/, "chybová zpráva bez souboru");
  assert.equal(env.calls.filter((c) => c.url.includes("/plaso-import")).length, 0, "api nebylo voláno");
});

await test("plaso import: POST /plaso-import multipart + stav ✓ s počty", async () => {
  const env = makeEnv({ plasoResponse: { events_total: 12, artifacts_imported: 3, timeline_events: 9 } });
  await env.sandbox.renderInteropExports("c1");
  const input = env.window.document.getElementById("plaso-file");
  Object.defineProperty(input, "files", { value: [new env.window.File(["a,b,c"], "plaso.l2tcsv")], configurable: true });
  const btn = env.window.document.getElementById("btn-plaso-import");
  btn.dispatchEvent(new env.window.MouseEvent("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 0));
  const call = env.calls.find((c) => c.url.includes("/plaso-import"));
  assert.ok(call, "api bylo voláno pro plaso-import");
  assert.equal(call.opts.method, "POST", "metoda POST");
  assert.match(call.url, /\/api\/cases\/c1\/plaso-import$/, "správný endpoint s caseId");
  assert.ok(call.opts.body instanceof env.sandbox.FormData, "body je FormData (multipart)");
  const status = env.window.document.getElementById("plaso-status").textContent;
  assert.match(status, /✓ Import hotovo/, "úspěšná zpráva");
  assert.match(status, /záznamů 12/, "events_total");
  assert.match(status, /artifactů 3/, "artifacts_imported");
  assert.match(status, /timeline eventů 9/, "timeline_events");
});

await test("plaso import selhání: plaso-status ukazuje ✗ + tlačítko se znovu aktivuje", async () => {
  const env = makeEnv({ plasoError: "400: soubor neobsahuje l2tcsv" });
  await env.sandbox.renderInteropExports("c1");
  const input = env.window.document.getElementById("plaso-file");
  Object.defineProperty(input, "files", { value: [new env.window.File(["x"], "bad.l2tcsv")], configurable: true });
  const btn = env.window.document.getElementById("btn-plaso-import");
  btn.dispatchEvent(new env.window.MouseEvent("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 0));
  const status = env.window.document.getElementById("plaso-status").textContent;
  assert.match(status, /✗ Import selhal/, "chybová zpráva");
  assert.equal(btn.disabled, false, "tlačítko po chybě znovu aktivní (finally)");
});

console.log(`\ninterop.js DOM testy (Timesketch push + live status + Plaso import): ${passed}/15 passed`);
