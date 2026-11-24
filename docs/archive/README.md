# docs/archive/ — superseded dokumenty

Point-in-time audity, revize a reporty, jejichž nálezy jsou implementovány nebo je nahradily
novější verze. Živé dokumenty zůstávají v kořeni repa (ROADMAP, CHANGELOG, AI GOVERNANCE)
a v `docs/` (designs, strategie, modely). Historická záznamová vrstva navíc: `.stopa-dev/`.

| Soubor | Pořízeno | Proč archivní |
|--------|----------|---------------|
| `CHANGELOG.md` (z kořene) | do [2.0.0] | paralelní changelog, zastavil se při 2.0; autoritativní = `STOPA_CHANGELOG.md` |
| `STOPA_ARCHITECTURE.md` (z kořene) | 2026-11-03 @ e227929 (v0.1.0) | snapshot architektury v0.1.0; aktuální stav `.stopa-dev/PROJECT_STATE.md` |
| `STOPA_TECHNICAL_AUDIT_master_prompt.md` (z kořene) | 2026-11-03 @ e227929 (v0.1.0) | MASTER PROMPT auditní výstup; novější stav viz `.stopa-dev/PROJECT_STATE.md` § technický dluh |
| `STOPA_SECURITY_REPORT.md` (z kořene) | 2026-11-03 @ e227929 (v0.1.0) | T1–T10 snapshot; živý model = `docs/SECURITY_THREAT_MODEL.md` + `docs/STOPA_SECURITY_MODEL.md` |
| `STOPA_TEST_REPORT.md` (z kořene) | 2026-11-03 @ e227929 (v0.1.0) | tabulka testů v0.1.0; aktuální počty v release notes + `.stopa-dev/TEST_REGISTRY.md` |
| `STOPA_VALIDATION_REPORT.md` (z kořene) | 2026-11-03 @ e227929 (v0.1.0) | C3 registry snapshot; aktuální validace v release notes 2.x |
| `ARCHITECTURE_AUDIT.md` | stav k 2.1 | nálezy implementovány dle `ROADMAP_2_1.md` (2.1 hotové) |
| `AUDIT-2026-11.md` | 2026-11-02 @ 87398fa (627 testů) | plný audit v0.1.0 éry; nahrazen pozdějšími audity a hardening reporty |
| `EXECUTIVE_SUMMARY.md` | Release 2.0 GA / plán 2.1 | executive summary auditních výstupů k 2.1 |
| `PROJECT_AUDIT.md` | 2026-10-31 @ b01140d (v0.1.0) | projektový audit; nahrazen `AUDIT-2026-11.md` a pozdějšími |
| `review-2026-10-30.md` | 2026-10-30 @ f2cf27e (200 testů) | souhrn pro revizi; nahrazen `PROJECT_AUDIT.md` a pozdějšími |
| `improvement-plan.md` | 2026-10-30 @ 27d242e (318 testů) | plán vylepšení v0.1.0 éry; nahrazen ROADMAP_2_1 a `.stopa-dev/ROADMAP.md` |
| `STOPA_FINAL_VALIDATION_2026-11-10.md` | 2026-11-10 @ e37b328 (v0.1.0) | závěrečná validace v0.1.0; nahrazena release validacemi 2.x |

Pojmenování: soubory z kořene, které kolidily se jménem v `docs/`, dostaly příponu
`_master_prompt` (původní název = MASTER PROMPT kořenový výstup).
