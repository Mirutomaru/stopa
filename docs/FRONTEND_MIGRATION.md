# P0-6 — Frontend sjednocení: parity mapa a migrační plán

**Stav:** ✅ dokument hotový (parity mapa 19/19 modulů + pořadí + AK per krok).
Implementační kroky S1–S10 se sledují v `ROADMAP_2_1.md` §D; každý = samostatný
releasovatelný celek (nová SPA stránka/krok + testy + build bundle do
`src/stopa/web/static/spa/`).

## 1. Cíl a AK

- **Cíl:** jedna UI místo dvou — legacy static UI (`src/stopa/web/static/`, ~2 500 řádků JS)
  a React SPA (`frontend/`) čtou totéž case DB, takže migrace = přesun funkcí do SPA,
  nikoli dat. Legacy se po dosažení parity zamrzne (feature-frozen) a deprecuje.
- **AK:**
  - parity mapa pokrývá **100 % legacy funkcí** — každý z 19 modulů má řádek (§3);
  - každý migrační krok = samostatný releasovatelný celek s vlastním AK a testy;
  - po S1–S10: legacy UI za flagem `?ui=legacy` + deprecation banner.

## 2. Inventář

### Legacy static UI (soubory → rozsah)

| Komponenta | Řádků | Obsah |
|---|---|---|
| `index.html` | 557 | 19 sekcí `#mod-*`, bootstrap |
| `js/components/modules.js` | 630 | render logika všech modulů (disk image, FS TSK, partice, registry, SQLite, chaty, dedup, reporting, ATT&CK/Daubert…) |
| `js/components/ai.js` | 327 | AI Assistant (LM Studio) |
| `js/components/interop.js` | 283 | Interop exporty l2tcsv/UCO/CSV/JSON/XML/STIX + Timesketch push |
| `js/components/graph.js` | 252 | Entity Graph (force-directed) |
| `js/components/inspector.js` | 235 | Artifact inspector |
| `js/components/files.js` | 215 | Case Files (zdroje, soubory, bad-ext/duplikáty) |
| `js/components/validation.js` | 114 | Validation Center (+ sloupce Stav/Testy z P0-4) |
| `js/components/audit.js`, `role.js`, `search.js`, `sidebar.js`, `api.js`, `state.js` | ~325 | Audit Center, role, hledání, navigace (registry 19 modulů), API/state |

### React SPA (`frontend/src`) — 7 route / stránek

| Route | Stránka | Pokrytí |
|---|---|---|
| `/` | `Dashboard.tsx` | seznam případů + počty (files/bytes/bad_ext/dups/artifacts) |
| `/files` | `CaseFiles.tsx` | zdroje + soubory případu |
| `/artifacts/:file_id` | `ArtifactDetail.tsx` | detail artefaktu + per-file export link |
| `/timeline` | `Timeline.tsx` | timeline událostí |
| `/entities` | `Entities.tsx` | graf entit (SVG `EntityGraph`) |
| `/ai` | `AiPanel.tsx` | AI panel (LM Studio) |
| `/hypotheses` | `HypothesesPage` | hypotézy |

## 3. Parity mapa — 100 % legacy modulů (19/19)

Stav: ✅ pokryto · 🟡 částečně · ❌ nepokryto

| # | Legacy modul | Funkce | SPA stav | Poznámka / cíl |
|---|---|---|---|---|
| 1 | Dashboard | přehled případu — statistiky, zdroje, artifacty | 🟡 | `/` + `/files` existují; sjednocený per-case stats view chybí → **S8** |
| 2 | Cases | případy v workspace, zařízení, poslední aktivita | ✅ | `/` Dashboard (case list, examiner, auto-export toggle) |
| 3 | Artifacts | kompletní timeline extrahovaných artefaktů | 🟡 | `/timeline` + `/artifacts/:file_id`; filtry per typ/typologii chybí → **S5/S6** |
| 4 | File System (TSK) | soubory z filesystemu + carving signatury | ❌ | jen obecný `/files` listing → **S4** |
| 5 | Disk Image | detekované typy obrazů a obsah | ❌ | → **S4** |
| 6 | Partition Map | partice, offsety, velikosti | ❌ | → **S4** |
| 7 | System Registry | registry hive klíče + iOS plist datumy | ❌ | typově specializované renderery → **S6** |
| 8 | SQLite Recovery | DB + smazané řádky (WAL & freelist) | ❌ | → **S6** |
| 9 | Messaging Chats | SMS/iMessage/WhatsApp/hovory chronologicky | ❌ | specializace timeline → **S5** |
| 10 | Deduplication | bad-ext, duplikáty, smazané zázny | 🟡 | počty bad_ext/dups na `/`; dedikovaný view chybí → **S4** |
| 11 | Entity Graph | force-directed graf entit (E5) | ✅ | `/entities` (`EntityGraph` SVG) |
| 12 | Correlation | propojení entit + přechod na důkaz (E5) | 🟡 | graf existuje; „evidence → proof“ přechod chybí → **S5** |
| 13 | Reporting | court-ready reporty + označené soubory | ❌ | compliance PDF/JSON jen v legacy → **S3** |
| 14 | AI Assistant | LM Studio — NL hledání, shrnutí (E11) | ✅ | `/ai` AiPanel |
| 15 | Validation Center | registry + validační reporty C3/C6 (+P0-4) | 🟡 | sloupce Stav/Testy jen v legacy `validation.js` → **S2** |
| 16 | Audit Center | hash chain + Ed25519 body (C4), pečetě F5.1, klíče P0-2 | ❌ | → **S10** |
| 17 | Interop Exporty | l2tcsv/UCO/CSV/JSON/XML/STIX, Timesketch push | ❌ | SPA má jen per-file export link → **S3** |
| 18 | Diagnostics | verze knihoven + TSK/EWF/FDE dostupnost (E12) | ❌ | → **S10** |
| 19 | Settings | časové pásmo, AI URL, role, bind address (E12) | 🟡 | auto-export toggle na `/`; ostatní nastavení chybí → **S10** |

**Součet: ✅ 3 · 🟡 6 · ❌ 10 = 19/19 modulů zařazeno do kroků S1–S10.**
Pozn.: ATT&CK (F6.3) a Daubert pack (F5.5) mají hotové API endpoínty
(`/api/cases/{id}/attack-map`, `/api/cases/{id}/daubert-pack`) — v SPA zatím bez
stránky → S1/S2 (master prompt je řadí na začátek).

## 4. Migrační pořadí (dle master promptu) + AK per krok

Každý krok: nová/rozšířená SPA stránka, testy (TestClient/render), **rebuild bundle**
(`frontend` → `src/stopa/web/static/spa/`) a commit jako samostatný releasovatelný celek.

| Krok | Cíl (SPA) | API podklad (existuje) | AK — releasovatelný celek |
|---|---|---|---|
| **S1** ATT&CK + threat intel | nová `/attack` | `GET /api/cases/{id}/attack-map` (+STIX varianta) | heatmap techniky per případ; JSON kontrakt identický s CLI `stopa attack-map`; test: render ≥20 technik z fixture |
| **S2** Daubert + validation lab | nová `/validation` | `GET /api/parser-status`, `GET /api/validation/registry`, `daubert-pack` | sloupce Stav (P0-4)/Testy + souhrnný řádek — stejný kontrakt jako legacy; regrese: oba UI vrací identický validated count |
| **S3** Reports & Exporty | nová `/reports` | `compliance-report?format=json\|pdf`, interop export endpoínty, Timesketch push | court-ready report (JSON+PDF) a STIX/UCO/l2tcsv export ze SPA; AK: digest PDF odpovídá CLI `stopa compliance` |
| **S4** Evidence management | rozšíření `/files` | sources/files API + bad-ext/duplikáty/deletion data | TSK/disk-image/partition-map/system-recovery/sql-recovery/dedup jako taby & filtry v CaseFiles; AK: počty řádků odpovídají legacy modulům |
| **S5** Timeline | rozšíření `/timeline` | timeline + correlation API | chronologický messaging view (SMS/WhatsApp/hovory) + „evidence → proof“ přechod; AK: počet událostí odpovídá legacy correlation |
| **S6** Artifact viewer | rozšíření `/artifacts/:file_id` | detail endpoínt | typově specializované renderery (registry hive, SQLite řádky) v ArtifactDetail; AK: parita polí s `inspector.js` |
| **S7** Plugins | nová `/plugins` | `/api/plugins`, plugin-run endpoínty | seznam + spuštění pluginů ze SPA se stavem sandboxu (P0-3); AK: výstup runu odpovídá CLI `stopa plugin-run` |
| **S8** Case management | rozšíření `/` | cases API | sjednocený per-case dashboard (statistiky + zdroje + artifact summary — parita s legacy Dashboard) |
| **S9** AI workspace | rozšíření `/ai` | AI endpoínty (LM Studio) | NL hledání + vysvětlení artefaktů ze SPA; AK: query roundtrip odpovídá chování `ai.js` |
| **S10** Admin screens | nová `/admin` | settings/diagnostics/integrity-keys/rotate-key endpoínty | Settings (timezóna, AI URL, role, bind) + Diagnostics (verze TSK/EWF/FDE) + Audit Center (hash chain, kontrolní body, generace klíčů P0-2); AK: ověření hash-chain audit logu ze SPA |

## 5. Deprecace legacy UI

1. Po S1–S10: legacy = **feature-frozen** (žádné nové funkce jen do legacy).
2. Oba frontendy se servírují vedle sebe (`/spa` vs. `/`) — čtou totéž case DB,
   žádná migrace dat.
3. Legacy za flagem `?ui=legacy` + deprecation banner; odstranění až po 1 release bez regresí.
