"""STOPA pipeline — jediný analyze() entrypoint sdílený CLI i web GUI.

Postup (FTK-style processing):
1. walk zdroje → WalkedFile záznamy
2. pro každý soubor: hashy podle profilu + signatura (magic bytes)
3. bad extension check, dedupe napříč případem, known-bad hash sets
4. upsert do case DB + ProcessResult summary

Jeden kódový průchod pro CLI i web — jedna cesta k debugování.
"""


# P1-4 vlna D — god-file rozloženo do modulů ``registry``, ``matching``,
# ``extractors``, ``dispatch``, ``pool``, ``core``; facade re-exportuje celý povrch.

# Kompatibilitní povrch — jména, která konzumenti/testy importují ze ``stopa.pipeline``
# (v monolitu dostupná přes jeho top-level importy).
from stopa.domain.sandbox import SandboxConfig  # noqa: F401
from stopa.models import Artifact  # noqa: F401
from stopa.pipeline.core import (
    _case_id_for_source,
    _maybe_auto_export,
    load_hash_sets,
    parser_versions,
    process_source,
    replay_extract,
    run_timeline_intel,
    summarize_outputs,
)
from stopa.pipeline.dispatch import _extract_artifacts_for
from stopa.pipeline.extractors import (
    SANDBOX_CONFIG,
    SANDBOX_ENABLED,
    SIGNATURE_HEAD_BYTES,
    _extract_registry_all,
    _extract_sqlite_all,
    _parser_error_artifact,
    _read_head,
    _run_extractor,
)
from stopa.pipeline.matching import (
    _name_based_match,
    _sns_prepass,
)
from stopa.pipeline.pool import (
    _POOL_PROFILE,
    _POOL_SETS,
    _FileWork,
    _pool_init,
    _process_file_task,
    _process_file_worker,
)
from stopa.pipeline.registry import (
    ARTIFACT_EXTRACTORS,
    NAME_BASED_EXTRACTORS,
)

__all__ = [
    "ARTIFACT_EXTRACTORS",
    "NAME_BASED_EXTRACTORS",
    "SANDBOX_CONFIG",
    "SANDBOX_ENABLED",
    "SIGNATURE_HEAD_BYTES",
    "_POOL_PROFILE",
    "_POOL_SETS",
    "_FileWork",
    "_case_id_for_source",
    "_extract_artifacts_for",
    "_extract_registry_all",
    "_extract_sqlite_all",
    "_maybe_auto_export",
    "_name_based_match",
    "_parser_error_artifact",
    "_pool_init",
    "_process_file_task",
    "_process_file_worker",
    "_read_head",
    "_run_extractor",
    "_sns_prepass",
    "load_hash_sets",
    "parser_versions",
    "process_source",
    "replay_extract",
    "run_timeline_intel",
    "summarize_outputs",
]
