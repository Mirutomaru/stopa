/* ════════════════════════════════════════════════════════════
   STOPA Forensic — globální Store (ultralehký pub/sub, bez frameworku)
   Komponenty se přihlašují na klíče a re-renderují se při změně.
   ════════════════════════════════════════════════════════════ */
"use strict";

const Store = (() => {
  const data = {};
  const subs = new Map(); // key -> Set<fn>

  return {
    get(key) {
      return data[key];
    },
    set(key, value) {
      if (data[key] === value) return;
      data[key] = value;
      for (const fn of subs.get(key) || []) {
        try { fn(value); } catch (e) { console.error("Store subscriber", e); }
      }
    },
    subscribe(key, fn) {
      if (!subs.has(key)) subs.set(key, new Set());
      subs.get(key).add(fn);
      return () => subs.get(key).delete(fn);
    },
  };
})();

/* Počáteční stav — jednotlivé klíče:
   cases, caseId, caseDetail, module, selectedFile, busy, taskLabel */
Store.set("cases", []);
Store.set("caseId", null);
Store.set("caseDetail", null);
Store.set("module", "dashboard");
Store.set("selectedFile", null);
Store.set("busy", false);
Store.set("taskLabel", "");
