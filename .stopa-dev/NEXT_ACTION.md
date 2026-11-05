# STOPA — Nejbližší akce

**Po dokončení:** STP-044 (ETAPA D vlna 2) | **Datum:** 2026-11-04

## ✅ Co je hotové
- ETAPA D dokončena ★★: CI benchmark job (STP-043, ```0136e91```) + E2E testy a dokumentace (STP-044, ```ca93d58```)
- Full suite **1813 passed, 1 skipped**, ruff clean

## 🎯 Nejbližší úkol: **Volba ETAPY E**
Audit reálného stavu kandidátů (ne jen staré „Nedokončeno" v roadmapě):
- **M Security — sandbox izolace parserů** (P2, nejvyšší zbývající priorita)
- H AI Copilot — detekce rozporů citací (P2)
- I+O Validation/Audit Center UI (P2)
- G/J/K/Q = P3

Postup: audit kódu → rozhodnutí → synchronizace DEV OS + root roadmapy → TASKS/PROJECT_STATE/CHANGELOG/checkpoint/NEXT_ACTION.

## 📌 Kontext pro pokračování
- Benchmark engine: `domain/benchmark.py` (detect_regressions, threshold 20 %), `data/benchmark_engine.py` (run_benchmark suite=all / 77 položek)
- CI benchmark job: `.github/workflows/ci.yml` (job `benchmark`), `scripts/ci_benchmark.py`, baseline `benchmarks/baseline.json`
- Dokumentace: `docs/STOPA_BENCHMARKS.md`
