"""Vestavěné FTK-style processing profily.

FTK Central má Forensic Processing / eDiscovery Processing — my máme 3 profily:
- forensic   : plný průchod (MD5+SHA-256, signatury, bad ext, dedupe, hash sets)
- ediscovery : lehký (MD5 jen pro deduplikaci, bez SHA-256 — FTK eDiscovery profil)
- quick      : minimální (jen SHA-256 + signatury; pro triage / AXIOM-style Quick scan)

Profily jsou data (ProcessingProfile), ne kód → snadno rozšířit z UI.
"""

from __future__ import annotations

from stopa.models import ProcessingProfile

FORENSIC = ProcessingProfile(
    name="forensic",
    compute_md5=True,
    compute_sha1=False,
    compute_sha256=True,
    signature_analysis=True,
    flag_bad_extensions=True,
    deduplicate=True,
    match_hash_sets=True,
)

EDISCOVERY = ProcessingProfile(
    name="ediscovery",
    compute_md5=True,  # FTK eDiscovery: MD5 pro deduplikaci napříč custodians
    compute_sha1=False,
    compute_sha256=False,
    signature_analysis=True,
    flag_bad_extensions=True,
    deduplicate=True,
    match_hash_sets=True,
)

QUICK = ProcessingProfile(
    name="quick",
    compute_md5=False,
    compute_sha1=False,
    compute_sha256=True,  # SHA-256 jako primární identifikátor (AXIOM-style triage)
    signature_analysis=True,
    flag_bad_extensions=False,
    deduplicate=False,
    match_hash_sets=False,
)

PROFILES: dict[str, ProcessingProfile] = {p.name: p for p in (FORENSIC, EDISCOVERY, QUICK)}


def get_profile(name: str) -> ProcessingProfile:
    """Vrátí profil podle jména; neznámý → KeyError s přehledem dostupných."""
    try:
        return PROFILES[name]
    except KeyError:
        available = ", ".join(sorted(PROFILES))
        raise KeyError(f"Neznámý processing profil '{name}' (dostupné: {available})") from None
