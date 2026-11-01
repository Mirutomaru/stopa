/* ════════════════════════════════════════════════════════════
   STOPA E5 — DOM testy graph.js (jsdom, vanilla Node)
   Render grafu z fixture dat + klik→evidence flow + „→ Důkaz“.
   Spustí: node tests/js/graph.test.mjs  (exit 0 = OK)
   ════════════════════════════════════════════════════════════ */
import { JSDOM } from "jsdom";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const GRAPH_JS = path.join(__dirname, "../../src/stopa/web/static/js/components/graph.js");
const graphSrc = fs.readFileSync(GRAPH_JS, "utf8");

/* fixture: 3 entity (phone/email/hash) + 3 korelace (self-link + cross) */
const ENTITIES = [
  { kind: "phone", value: "+420777123456" },
  { kind: "email", value: "john@example.com" },
  { kind: "hash", value: "a".repeat(64) },
];
const CORRELATIONS = [
  { relation: "same_contact", confidence: "verified", entity_a: "+420777123456", entity_b: "+420777123456", evidence: [{ artifact_id: "w1", file_id: "file-1", rel_path: "/a/sms.db", detail: "phone=+420777123456" }] },
  { relation: "temporal_overlap", confidence: "inferred", entity_a: "+420777123456", entity_b: "john@example.com", evidence: [{ artifact_id: "w2", file_id: null, rel_path: "/b/mail.mbox", detail: "phone=+420777123456" }] },
  { relation: "hash_match", confidence: "verified", entity_a: "a".repeat(64), entity_b: "a".repeat(64), evidence: [{ artifact_id: "w3", file_id: "file-9", rel_path: "/c/doc.pdf", detail: "sha256=a…" }] },
];

function makeEnv() {
  const dom = new JSDOM(`<!DOCTYPE html><body>
    <svg id="graph-svg" viewBox="0 0 900 520"></svg>
    <div id="graph-evidence" class="hidden"></div>
  </body>`);
  const { window } = dom;
  const inspectorCalls = [];
  const sandbox = {
    document: window.document,
    console,
    api: async (url) => (String(url).includes("/entities") ? ENTITIES : CORRELATIONS),
    Store: { set() {}, get(k) { return k === "caseId" ? "c1" : null; } },
    esc: (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;"),
    openInspector: (fid) => inspectorCalls.push(fid),
    toast() {}, setTaskLabel() {},
  };
  vm.createContext(sandbox);
  vm.runInContext(graphSrc, sandbox); // definuje buildGraphData/forceLayout/renderEntityGraph/showEvidenceList/loadAndRenderGraph
  return { sandbox, window, inspectorCalls, dom };
}

let passed = 0;
async function test(name, fn) {
  try { await fn(); console.log(`  ✓ ${name}`); passed++; }
  catch (e) { console.error(`  ✗ ${name}\n    ${e.message}`); process.exitCode = 1; }
}

await test("buildGraphData: uzly z entit + hrany z korelací (self-link i cross)", () => {
  const { sandbox } = makeEnv();
  const g = sandbox.buildGraphData(ENTITIES, CORRELATIONS);
  assert.equal(g.nodes.length, 3, "3 unikátní entity");
  assert.equal(g.edges.length, 3, "3 hrany (2 self-link + 1 cross)");
  const kinds = new Set(g.nodes.map((n) => n.kind));
  assert.ok(kinds.has("phone") && kinds.has("email") && kinds.has("hash"), "barvy/kind zachovány");
});

await test("forceLayout: pozice ve viewportu + deterministický (2× stejný výsledek)", () => {
  const { sandbox } = makeEnv();
  const g = sandbox.buildGraphData(ENTITIES, CORRELATIONS);
  const p1 = sandbox.forceLayout(g.nodes, g.edges);
  const p2 = sandbox.forceLayout(g.nodes, g.edges);
  for (const n of g.nodes) {
    const p = p1.get(n.id);
    assert.ok(p.x >= 34 && p.x <= 866, `x=${p.x} v [34,866]`);
    assert.ok(p.y >= 34 && p.y <= 486, `y=${p.y} v [34,486]`);
    assert.equal(p1.get(n.id).x, p2.get(n.id).x, "deterministické x");
    assert.equal(p1.get(n.id).y, p2.get(n.id).y, "deterministické y");
  }
});

await test("renderEntityGraph: SVG obsahuje uzly (barva kind) + hrany", () => {
  const env = makeEnv();
  const svg = env.window.document.getElementById("graph-svg");
  env.sandbox.renderEntityGraph(svg, ENTITIES, CORRELATIONS);
  const circles = svg.querySelectorAll(".g-node circle");
  assert.equal(circles.length, 3, "3 uzly (kruhy)");
  assert.equal(svg.querySelectorAll(".g-edge").length, 3, "3 hrany");
  // barva podle kind — phone modrá
  const phoneNode = svg.querySelector('.g-node.phone circle');
  assert.ok(phoneNode && /#4da3ff/i.test(phoneNode.getAttribute("fill")), "phone uzel má modrou barvu");
});

await test("klik na hranu → evidence panel (click→evidence flow)", async () => {
  const env = makeEnv();
  await env.sandbox.loadAndRenderGraph("c1"); // fetch + render + wiring kliků
  const svg = env.window.document.getElementById("graph-svg");
  const edge = svg.querySelector(".g-edge");
  assert.ok(edge, "hrana existuje");
  edge.dispatchEvent(new env.window.MouseEvent("click", { bubbles: true }));
  const panel = env.window.document.getElementById("graph-evidence");
  assert.ok(!panel.classList.contains("hidden"), "evidence panel zobrazen");
  assert.match(panel.innerHTML, /same_contact|temporal_overlap|hash_match/, "obsahuje vztah");
});

await test("„→ Důkaz“: klik na evidence řádek volá openInspector(file_id)", () => {
  const env = makeEnv();
  const panel = env.window.document.getElementById("graph-evidence");
  // korelace s file_id v evidenci → button „→ Důkaz“
  env.sandbox.showEvidenceList(panel, CORRELATIONS[0], (fid) => env.inspectorCalls.push(fid));
  assert.ok(!panel.classList.contains("hidden"), "panel zobrazen");
  const btn = panel.querySelector(".ev-open");
  assert.ok(btn, "tlačítko „→ Důkaz“ existuje");
  btn.dispatchEvent(new env.window.MouseEvent("click", { bubbles: true }));
  assert.deepEqual(env.inspectorCalls, ["file-1"], "openInspector dostal file_id");
});

console.log(`\ngraph.js DOM testy: ${passed}/5 passed`);
