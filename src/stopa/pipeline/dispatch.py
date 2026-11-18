"""Dispečink extrakce — volba extraktoru podle signatury / názvu souboru.

P1-4 vlna D: vyčleněno z monolitu ``pipeline.py``; `_extract_artifacts_for`
spojí registry (signatury) a matching (název-souboru) do jedné cesty.
"""

from __future__ import annotations

from pathlib import Path

from stopa.artifacts.crypto_extract import CRYPTO_EXTRACT_VERSION, extract_crypto_artifacts
from stopa.models import Artifact

from .extractors import _run_extractor
from .matching import (
    _name_based_match,
    _sns_prepass,
)
from .registry import ARTIFACT_EXTRACTORS


def _extract_artifacts_for(
    path: Path, signature_type: str | None, crypto_scan: bool = True
) -> tuple[list[Artifact], str | None]:
    """Artifact extraktoři pro jeden soubor — signatura PŘED name-based fallbackem.

    AXIOM Hunter pattern: iCloud Messages export (`MessagesInICloud.csv`) nemá
    spolehlivou magic (XLSX je generic OOXML, delimited text žádnou), proto se
    detekuje podle názvu souboru — jen když signatura nic nenašla.

    Vrací ``(artifacts, parser_version)`` — verze se eviduje na každém artifactu
    (E2 provenience / reprodukovatelnost). Bez extraktoru → ``([], None)``.

    ETAPA E vlna 2 (STP-047): všechny cesty běží přes ``_run_extractor`` —
    sandbox subprocess s timeoutem; selhání parseru → ``parser_error`` artifact
    (pipeline nepadne). Fallback bez sandboxu = přímé volání.
    """
    if signature_type in ARTIFACT_EXTRACTORS:
        fn, ver = ARTIFACT_EXTRACTORS[signature_type]
        return _run_extractor(fn, path, ver), ver
    # ETAPA B vlna 10 — cloud SNS (Instagram/Snapchat): generic basenames kolidují
    # s Google detektory → pre-pass na celé cestě PŘED basename chainem.
    sns_match = _sns_prepass(str(path))
    if sns_match is not None:
        fn, ver = sns_match
        return _run_extractor(fn, path, ver), ver
    name_match = _name_based_match(path.name)  # name-based fallback (AXIOM Hunter)
    if name_match is None:
        # ETAPA B vlna 8 — Takeout soubory se generic názvy (Drive/Files.json, Voice/Texts.json):
        # klíčové slovo je v rodičovské složce → retry na celé cestě. Parsery jsou
        # defenzivní (ne-JSON → []), takže cizí soubory jen projdou bez artifactů.
        name_match = _name_based_match(str(path))
    if name_match is not None:
        fn, ver = name_match
        return _run_extractor(fn, path, ver), ver
    # K2 — crypto content scan (spec AK): soubor nesedl žádný známý extraktor →
    # sken textu na vestěné klíče/seedy/adresy. Defenzivní: binárka → [], velikost
    # omezená uvnitř extraktoru; PII guard (fingerprint místo raw hodnot).
    if crypto_scan:
        return _run_extractor(extract_crypto_artifacts, path, CRYPTO_EXTRACT_VERSION), CRYPTO_EXTRACT_VERSION
    return [], None
