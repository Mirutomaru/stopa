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

function makeEnv({ pushResponse, pushError, statusResponse, statusError, plasoResponse, plasoError, previewResponse, previewError, exportPreviewResponse, exportPreviewError, auditResponse } = {}) {
  const dom = new JSDOM(`<!DOCTYPE html><body>
    <select id="ix-what"><option value="artifacts">Artifacty</option></select>
    <select id="ix-format"><option value="l2tcsv">l2tcsv</option></select>
    <button id="btn-interop-export"></button>
    <div class="card" id="l2tcsv-preview-card">
      <button id="btn-l2t-preview"></button>
      <div id="l2t-preview-status"></div>
      <div id="l2t-preview-table"></div>
    </div>
    <div class="card" id="export-preview-card">
      <select id="export-preview-format"><option value="csv">csv</option><option value="uco">uco</option></select>
      <button id="btn-export-preview"></button>
      <div id="export-preview-status"></div>
      <div id="export-preview-table"></div>
    </div>
    <div class="card" id="ts-push-card">
      <button id="btn-ts-push"></button>
      <input type="number" id="ts-push-limit" min="1" step="1" placeholder="vše">
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
  const opened = []; // zaznamenaná window.open() URL (download / re-download)
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
    window: { open(url) { opened.push(String(url)); return null; } },
    api: async (url, opts = {}) => {
      calls.push({ url: String(url), opts });
      const u = String(url);
      if (u.includes("/plaso-import")) {
        if (plasoError) throw new Error(plasoError);
        return plasoResponse ?? { events_total: 12, artifacts_imported: 3, timeline_events: 9 };
      }
      if (u.includes("/export-preview")) {
        if (exportPreviewError) throw new Error(exportPreviewError);
        return exportPreviewResponse ?? { case_id: "c1", dataset: "artifacts", format: "csv", columns: ["name", "sha256"], total_records: 7, limit: 50, rows: [{ name: "poznamky.txt", sha256: "ab" }] };
      }
      if (u.includes("/l2tcsv-preview")) {
        if (previewError) throw new Error(previewError);
        return previewResponse ?? { case_id: "c1", dataset: "artifacts", columns: ["date", "time", "source"], total_records: 7, limit: 50, rows: [{ date: "01/01/2026", time: "03:04:05", source: "STOPA" }] };
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
      if (u.includes("/audit")) return auditResponse ?? AUDIT;
      return CASE_DETAIL; // case detail
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(interopSrc, sandbox); // definuje renderInteropExports + IX_DATASETS
  return { sandbox, window, calls, toasts, opened };
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

await test("klik na push s limit: POST /timesketch-push body {what, limit}", async () => {
  const env = makeEnv();
  await env.sandbox.renderInteropExports("c1");
  const lim = env.window.document.getElementById("ts-push-limit");
  lim.value = "3";
  const btn = env.window.document.getElementById("btn-ts-push");
  btn.dispatchEvent(new env.window.MouseEvent("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 0));
  const pushCall = env.calls.find((c) => c.url.includes("/timesketch-push"));
  assert.ok(pushCall, "api bylo voláno pro timesketch-push");
  const body = JSON.parse(pushCall.opts.body);
  assert.deepEqual(body, { what: "artifacts", limit: 3 }, "body nese limit z inputu");
});

await test("klik na push bez limit (prázdný input): POST body jen {what}", async () => {
  const env = makeEnv();
  await env.sandbox.renderInteropExports("c1");
  const lim = env.window.document.getElementById("ts-push-limit");
  lim.value = ""; // prázdné = vše
  const btn = env.window.document.getElementById("btn-ts-push");
  btn.dispatchEvent(new env.window.MouseEvent("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 0));
  const pushCall = env.calls.find((c) => c.url.includes("/timesketch-push"));
  assert.ok(pushCall, "api bylo voláno pro timesketch-push");
  const body = JSON.parse(pushCall.opts.body);
  assert.deepEqual(body, { what: "artifacts" }, "bez limitu → body jen {what}");
});

await test("klik na push s invalidním limit (0): ✗ + žádné api volání", async () => {
  const env = makeEnv();
  await env.sandbox.renderInteropExports("c1");
  const lim = env.window.document.getElementById("ts-push-limit");
  lim.value = "0"; // < 1 → invalidní
  const btn = env.window.document.getElementById("btn-ts-push");
  btn.dispatchEvent(new env.window.MouseEvent("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 0));
  const status = env.window.document.getElementById("ts-status").textContent;
  assert.match(status, /✗ Limit musí být celé číslo ≥ 1/, "chybová zpráva pro limit < 1");
  assert.equal(env.calls.filter((c) => c.url.includes("/timesketch-push")).length, 0, "api nebylo voláno");
});

await test("úspěšný push s limit: ts-status ukazuje „z celkem N“", async () => {
  const env = makeEnv({ pushResponse: { sketch_id: 42, timeline_id: 7, task_id: "t-1", records: 3, total_records: 9 } });
  await env.sandbox.renderInteropExports("c1");
  const lim = env.window.document.getElementById("ts-push-limit");
  lim.value = "3";
  const btn = env.window.document.getElementById("btn-ts-push");
  btn.dispatchEvent(new env.window.MouseEvent("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 0));
  const status = env.window.document.getElementById("ts-status").textContent;
  assert.match(status, /✓ Push hotovo/, "úspěšná zpráva");
  assert.match(status, /záznamů 3 \(z celkem 9\)/, "počet pushnutých + celkový počet");
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

await test("l2t preview: po renderu má btn-l2t-preview navázaný onclick", async () => {
  const env = makeEnv();
  await env.sandbox.renderInteropExports("c1");
  const btn = env.window.document.getElementById("btn-l2t-preview");
  assert.ok(btn, "tlačítko btn-l2t-preview existuje");
  assert.equal(typeof btn.onclick, "function", "onclick handler je navázaný");
});

await test("l2t preview: GET /l2tcsv-preview?what=&limit=50 + tabulka se sloupci a řádky", async () => {
  const env = makeEnv({ previewResponse: { case_id: "c1", dataset: "artifacts", columns: ["date", "time", "source"], total_records: 7, limit: 50, rows: [{ date: "01/01/2026", time: "03:04:05", source: "STOPA" }] } });
  await env.sandbox.renderInteropExports("c1");
  const btn = env.window.document.getElementById("btn-l2t-preview");
  btn.dispatchEvent(new env.window.MouseEvent("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 0));
  const call = env.calls.find((c) => c.url.includes("/l2tcsv-preview"));
  assert.ok(call, "api bylo voláno pro l2tcsv-preview");
  assert.match(call.url, /\/api\/cases\/c1\/l2tcsv-preview\?what=artifacts&limit=50$/, "správný endpoint s what + limit");
  const status = env.window.document.getElementById("l2t-preview-status").textContent;
  assert.match(status, /✓ Náhled hotovo/, "úspěšná zpráva");
  assert.match(status, /záznamů celkem 7/, "total_records");
  const table = env.window.document.getElementById("l2t-preview-table").innerHTML;
  assert.match(table, /<th>date<\/th>/, "sloupec date v hlavičce");
  assert.match(table, /01\/01\/2026/, "hodnota z řádku");
});

await test("l2t preview prázdný dataset: ✓ + „je prázdný (záznamů 0)“ + tabulka bez obsahu", async () => {
  const env = makeEnv({ previewResponse: { case_id: "c1", dataset: "timeline", columns: ["date"], total_records: 0, limit: 50, rows: [] } });
  await env.sandbox.renderInteropExports("c1");
  const btn = env.window.document.getElementById("btn-l2t-preview");
  btn.dispatchEvent(new env.window.MouseEvent("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 0));
  const status = env.window.document.getElementById("l2t-preview-status").textContent;
  assert.match(status, /je prázdný \(záznamů 0\)/, "informativní zpráva pro prázdný dataset");
  assert.equal(env.window.document.getElementById("l2t-preview-table").innerHTML, "", "tabulka bez obsahu");
});

await test("l2t preview selhání: l2t-preview-status ukazuje ✗ + tlačítko se znovu aktivuje", async () => {
  const env = makeEnv({ previewError: "400: neplatný dataset" });
  await env.sandbox.renderInteropExports("c1");
  const btn = env.window.document.getElementById("btn-l2t-preview");
  btn.dispatchEvent(new env.window.MouseEvent("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 0));
  const status = env.window.document.getElementById("l2t-preview-status").textContent;
  assert.match(status, /✗ Náhled selhal/, "chybová zpráva");
  assert.equal(btn.disabled, false, "tlačítko po chybě znovu aktivní (finally)");
});

await test("export preview: po renderu má btn-export-preview navázaný onclick", async () => {
  const env = makeEnv();
  await env.sandbox.renderInteropExports("c1");
  const btn = env.window.document.getElementById("btn-export-preview");
  assert.ok(btn, "tlačítko btn-export-preview existuje");
  assert.equal(typeof btn.onclick, "function", "onclick handler je navázaný");
});

await test("export preview: GET /export-preview?what=&format=csv&limit=50 + tabulka se sloupci a řádky", async () => {
  const env = makeEnv({ exportPreviewResponse: { case_id: "c1", dataset: "artifacts", format: "csv", columns: ["name", "sha256"], total_records: 7, limit: 50, rows: [{ name: "poznamky.txt", sha256: "ab" }] } });
  await env.sandbox.renderInteropExports("c1");
  const btn = env.window.document.getElementById("btn-export-preview");
  btn.dispatchEvent(new env.window.MouseEvent("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 0));
  const call = env.calls.find((c) => c.url.includes("/export-preview"));
  assert.ok(call, "api bylo voláno pro export-preview");
  assert.match(call.url, /\/api\/cases\/c1\/export-preview\?what=artifacts&format=csv&limit=50$/, "správný endpoint s what + format + limit");
  const status = env.window.document.getElementById("export-preview-status").textContent;
  assert.match(status, /✓ Náhled hotovo \(csv\)/, "úspěšná zpráva s formátem");
  assert.match(status, /záznamů celkem 7/, "total_records");
  const table = env.window.document.getElementById("export-preview-table").innerHTML;
  assert.match(table, /<th>name<\/th>/, "sloupec name v hlavičce");
  assert.match(table, /poznamky\.txt/, "hodnota z řádku");
});

await test("export preview UCO: složené hodnoty se renderují jako JSON", async () => {
  const env = makeEnv({ exportPreviewResponse: { case_id: "c1", dataset: "artifacts", format: "uco", columns: ["type", "x-stopa"], total_records: 2, limit: 50, rows: [{ type: "file", "x-stopa": { category: "document" } }] } });
  await env.sandbox.renderInteropExports("c1");
  const sel = env.window.document.getElementById("export-preview-format");
  sel.value = "uco";
  const btn = env.window.document.getElementById("btn-export-preview");
  btn.dispatchEvent(new env.window.MouseEvent("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 0));
  const call = env.calls.find((c) => c.url.includes("/export-preview"));
  assert.match(call.url, /format=uco/, "formát uco v URL");
  const table = env.window.document.getElementById("export-preview-table").innerHTML;
  assert.match(table, /\{"category":"document"\}/, "složená hodnota jako JSON");
});

await test("export preview selhání: export-preview-status ukazuje ✗ + tlačítko se znovu aktivuje", async () => {
  const env = makeEnv({ exportPreviewError: "400: neplatný formát" });
  await env.sandbox.renderInteropExports("c1");
  const btn = env.window.document.getElementById("btn-export-preview");
  btn.dispatchEvent(new env.window.MouseEvent("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 0));
  const status = env.window.document.getElementById("export-preview-status").textContent;
  assert.match(status, /✗ Náhled selhal/, "chybová zpráva");
  assert.equal(btn.disabled, false, "tlačítko po chybě znovu aktivní (finally)");
});

/* ── STP-067 — re-download posledního exportu z historie (⬇ v řádcích) ── */

await test("re-download: každý řádek historie má ⬇ tlačítko s data-what/data-format z audit details", async () => {
  const env = makeEnv();
  await env.sandbox.renderInteropExports("c1");
  const btns = [...env.window.document.querySelectorAll("#ix-recent .ix-redl")];
  assert.equal(btns.length, 1, "jeden řádek → jedno ⬇ tlačítko");
  assert.equal(typeof btns[0].onclick, "function", "onclick handler je navázaný");
  assert.equal(btns[0].dataset.what, "artifacts", "data-what z audit details");
  assert.equal(btns[0].dataset.format, "l2tcsv", "data-format z audit details");
});

await test("re-download: klik na ⬇ → window.open /last-export?what=artifacts&format=l2tcsv (nové okno)", async () => {
  const env = makeEnv();
  await env.sandbox.renderInteropExports("c1");
  const btn = env.window.document.querySelector("#ix-recent .ix-redl");
  btn.onclick();
  assert.equal(env.opened.length, 1, "window.open voláno jednou");
  assert.match(env.opened[0], /^\/api\/cases\/c1\/last-export\?what=artifacts&format=l2tcsv$/, "správný endpoint s what + format z řádku");
});

await test("re-download: audit entry bez details → prázdné data-attribute a URL s prázdnými parametry", async () => {
  const env = makeEnv({ auditResponse: { entries: [{ action: "interop_exported", ts: "2026-11-07T11:00:00Z" }] } });
  await env.sandbox.renderInteropExports("c1");
  const btn = env.window.document.querySelector("#ix-recent .ix-redl");
  assert.ok(btn, "tlačítko existuje i bez details");
  assert.equal(btn.dataset.what, "", "data-what prázdné");
  assert.equal(btn.dataset.format, "", "data-format prázdné");
  btn.onclick();
  assert.match(env.opened[0], /^\/api\/cases\/c1\/last-export\?what=&format=$/, "URL s prázdnými parametry");
});

await test("re-download: prázdný audit (žádné interop_exported) → žádné ⬇ tlačítko", async () => {
  const env = makeEnv({ auditResponse: { entries: [{ action: "case_created", ts: "2026-11-07T09:00:00Z" }] } });
  await env.sandbox.renderInteropExports("c1");
  assert.equal(env.window.document.querySelectorAll("#ix-recent .ix-redl").length, 0, "žádné ⬇ tlačítko bez exportů v auditu");
});

console.log(`\ninterop.js DOM testy (Timesketch push + live status + Plaso import + L2T preview + export náhled + re-download): ${passed}/31 passed`);
