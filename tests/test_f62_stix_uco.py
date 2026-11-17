"""F6.2 — STIX 2.1 / UCO plná implementace (oblast Q Interop, Fáze 6).

AK dle ROADMAP V2:
- **100 % mapováno** — každý typ v KNOWN_ARTIFACT_TYPES má explicitní záznam
  v STIX mapě (nativní objekt nebo explicitní x-stopa-record) a v UCO mapě
  (mapped nebo explicitně unmapped);
- **stix2-validator** — validace bundle proti oficiálnímu schematu (volitelná
  závislost stix2, extras [stix]; bez ní graceful degradation);
- **round-trip test** — STIX bundle i UCO dokument se dají zpět převést na
  původní záznamy identicky (ne-None pole + id).

Domain testy = čistá logika bez I/O; CLI test = sdílený fixture ``e10_case``.
"""

from __future__ import annotations

import json
import sys

import pytest

# sdílený fixture — case DB s artifactem, timeline eventem a korelací
from test_e10 import e10_case  # noqa: F401

from stopa.domain.ai_grounding import KNOWN_ARTIFACT_TYPES
from stopa.domain.export import (
    _STIX_OBJ_MAP,
    from_stix_bundle,
    to_stix_bundle,
    validate_stix_bundle,
)
from stopa.domain.uco import UCO_ARTIFACT_MAP, UCO_UNMAPPED, from_uco_json, to_uco_json

# STIX 2.1 — povolené typy SDO (nativní cíle mapy); x-stopa-record = explicitní
# STOPA rozšíření (custom object), povoleno validátorem přes allow_custom=True.
_STIX_21_SDO_TYPES = frozenset(
    {
        "file", "directory", "process", "user-account", "group", "application",
        "software", "service", "autonomous-system", "port", "ipv4-addr",
        "ipv6-addr", "mac-addr", "domain-name", "url", "email-msg", "message",
        "note", "opinion", "indicator", "network-traffic", "mutex",
        "network-connection", "windows-registry-key", "certificate",
        "mobile-app", "payment-card", "bank-account", "crypto-wallet",
        "crypto-currency-transaction", "region", "location", "device",
    }
)

_LEGACY_ALIASES = frozenset({"audio", "document", "email", "image", "video"})


def _art_records() -> list[dict]:
    """Realistické záznamy v tvaru artifact_records() (ne-None + None pole)."""
    return [
        {
            "id": "art-1",
            "source_id": "src-1",
            "file_id": "file-1",
            "rel_path": "doc.pdf",
            "artifact_type": "browser_history",
            "timestamp_utc": "2026-10-30T12:00:00+00:00",
            "title": "Příliš žluťoučký kůň https://x.cz",
            "confidence": 0.9,
            "parser_version": "t-1.0",
            "extracted_at_utc": None,
            "anomaly_flags": None,
            "details_json": '{"k": "v"}',
        },
        {
            "id": "art-2",
            "source_id": "src-1",
            "file_id": "file-2",
            "rel_path": "wallet.dat",
            "artifact_type": "crypto_wallet",
            "timestamp_utc": None,
            "title": None,
            "confidence": 0.5,
            "parser_version": "t-1.0",
            "extracted_at_utc": "2026-11-01T08:00:00+00:00",
            "anomaly_flags": "future_date",
            "details_json": None,
        },
    ]


def _timeline_records() -> list[dict]:
    """Realistické záznamy v tvaru timeline_records()."""
    return [
        {
            "id": "ev-1",
            "case_id": "c1",
            "event_type": "browser_history",
            "ts_utc": "2026-10-30T12:00:00+00:00",
            "title": "navštívená stránka https://x.cz",
            "source_id": "src-1",
            "anomaly_flags": "gap_before",
            "details_json": None,
        },
    ]


def _non_none(rec: dict) -> dict:
    """Očekávaný tvar po round-tripu — jen ne-None pole v původním záznamu."""
    return {k: v for k, v in rec.items() if v is not None}


# ── AK 1: 100 % mapováno (STIX + UCO nad KNOWN_ARTIFACT_TYPES) ────────────


class TestFullMappingCoverage:
    def test_stix_map_covers_all_known_types(self):
        known = set(KNOWN_ARTIFACT_TYPES)
        missing = known - set(_STIX_OBJ_MAP)
        assert not missing, f"typy bez explicitní STIX mapy: {sorted(missing)}"

    def test_stix_map_size_and_no_drift(self):
        # 67 KNOWN typů + 5 legacy aliasů STP-023 = celá mapa; aliasy nesmí
        # kolidět s registrací (jinak by šlo o duplicitu, ne alias).
        assert len(_STIX_OBJ_MAP) == len(KNOWN_ARTIFACT_TYPES) + len(_LEGACY_ALIASES)
        assert _LEGACY_ALIASES.isdisjoint(set(KNOWN_ARTIFACT_TYPES))

    def test_stix_map_values_are_valid_stix_types(self):
        for atype, stype in _STIX_OBJ_MAP.items():
            allowed = _STIX_21_SDO_TYPES | {"x-stopa-record"}
            assert stype in allowed, f"{atype} → {stype!r} není validní STIX 2.1 typ"

    def test_stix_mapping_spot_checks(self):
        from stopa.domain.export import _stix_object_type

        # nativní objekty — podstatou artefaktu je ten observable
        assert _stix_object_type("browser_history") == "url"
        assert _stix_object_type("app_execution") == "process"
        assert _stix_object_type("mem_process") == "process"
        assert _stix_object_type("email_message") == "email-msg"
        assert _stix_object_type("google_mail_info") == "email-msg"
        assert _stix_object_type("registry_hive") == "windows-registry-key"
        assert _stix_object_type("google_account") == "user-account"
        assert _stix_object_type("user_sid") == "user-account"
        assert _stix_object_type("network_connection") == "network-connection"
        assert _stix_object_type("location") == "location"
        assert _stix_object_type("google_device") == "device"
        # konzervativní explicitní rozšíření (žádný fiktivní nativní objekt)
        assert _stix_object_type("autofill_entry") == "x-stopa-record"
        assert _stix_object_type("win_prefetch") == "x-stopa-record"
        # legacy aliasy STP-023 + neznámý typ → default file (zpětná kompatibilita)
        assert _stix_object_type("email") == "message"
        assert _stix_object_type("neznamy_typ") == "file"
        assert _stix_object_type(None) == "file"

    def test_uco_coverage_complement(self):
        # STP-055 invariant (součást F6.2 AK): mapped ∪ explicitně unmapped
        # pokrývá přesně KNOWN_ARTIFACT_TYPES — žádné tiché propadnutí.
        covered = set(UCO_ARTIFACT_MAP) | set(UCO_UNMAPPED)
        assert covered == set(KNOWN_ARTIFACT_TYPES)


# ── AK 1/2: povinné schémové vlastnosti z reálných dat (stix2-validní) ───


class TestStixRequiredProps:
    def test_url_gets_value_from_title(self):
        rec = {"id": "a1", "artifact_type": "browser_history",
               "title": "https://x.cz/stranka"}
        obj = json.loads(to_stix_bundle([rec]))["objects"][0]
        assert obj["type"] == "url"
        assert obj["value"] == "https://x.cz/stranka"

    def test_url_downgrade_when_title_not_url(self):
        # omnibox dotaz (browser_search) — title bez „://" → explicitní downgrade
        rec = {"id": "a2", "artifact_type": "browser_search", "title": "počasí Praha"}
        obj = json.loads(to_stix_bundle([rec]))["objects"][0]
        assert obj["type"] == "x-stopa-record"

    def test_location_gets_lat_lon_from_details(self):
        rec = {"id": "a3", "artifact_type": "google_location",
               "details_json": '{"latitude": 48.12, "longitude": 17.1}'}
        obj = json.loads(to_stix_bundle([rec]))["objects"][0]
        assert obj["type"] == "location"
        assert obj["latitude"] == 48.12 and obj["longitude"] == 17.1

    def test_location_downgrade_without_coords(self):
        rec = {"id": "a4", "artifact_type": "google_location"}
        obj = json.loads(to_stix_bundle([rec]))["objects"][0]
        assert obj["type"] == "x-stopa-record"

    def test_process_pid_from_details(self):
        rec = {"id": "a5", "artifact_type": "mem_process",
               "details_json": '{"pid": 1234}'}
        obj = json.loads(to_stix_bundle([rec]))["objects"][0]
        assert obj["type"] == "process" and obj["pid"] == 1234

    def test_process_cmdline_fallback(self):
        rec = {"id": "a6", "artifact_type": "mem_process",
               "details_json": '{"cmdline": "C:\\\\Windows\\\\explorer.exe"}'}
        obj = json.loads(to_stix_bundle([rec]))["objects"][0]
        assert obj["type"] == "process" and "command_line" in obj

    def test_process_downgrade_without_data(self):
        # app_execution bez pid/cmdline v details → explicitní downgrade (bez domýšlení)
        rec = {"id": "a7", "artifact_type": "app_execution"}
        obj = json.loads(to_stix_bundle([rec]))["objects"][0]
        assert obj["type"] == "x-stopa-record"

    def test_mixed_types_bundle_validates(self):
        pytest.importorskip("stix2")  # volitelná závislost — extras [stix]
        recs = [
            {"id": "b1", "artifact_type": "browser_history", "title": "https://a.cz"},
            {"id": "b2", "artifact_type": "google_location",
             "details_json": '{"latitude": 48.0, "longitude": 17.0}'},
            {"id": "b3", "artifact_type": "mem_process", "details_json": '{"pid": 7}'},
            {"id": "b4", "artifact_type": "app_execution"},  # downgrade cesta
        ]
        ok, detail = validate_stix_bundle(to_stix_bundle(recs))
        assert ok, detail


# ── AK 3 (STIX): round-trip bundle → záznamy identické ────────────────────


class TestStixRoundTrip:
    def test_artifacts_roundtrip_identity(self):
        recs = _art_records()
        imported = from_stix_bundle(to_stix_bundle(recs, dataset="artifacts"))
        assert len(imported) == 2
        for original, restored in zip(recs, imported, strict=True):
            assert restored == _non_none(original), (
                f"round-trip neshoduje se pro {original['id']!r}"
            )

    def test_timeline_roundtrip_identity(self):
        recs = _timeline_records()
        imported = from_stix_bundle(to_stix_bundle(recs, dataset="timeline"))
        assert len(imported) == 1
        assert imported[0] == _non_none(recs[0])

    def test_deterministic_bundle_text(self):
        recs = _art_records()
        # stejný vstup = stejný text (reprodukovatelnost C4 i po F6.2 mapě)
        assert to_stix_bundle(recs) == to_stix_bundle(list(recs))

    def test_foreign_object_without_x_stopa(self):
        bundle = json.dumps(
            {
                "type": "bundle",
                "id": "bundle--8b3e9f10-1234-5678-9abc-def012345678",
                "objects": [
                    {"type": "ipv4-addr", "spec_version": "2.1",
                     "id": "ipv4-addr--8b3e9f10-1234-5678-9abc-def012345678",
                     "name": "host"},
                ],
            }
        )
        recs = from_stix_bundle(bundle)
        assert len(recs) == 1
        # cizí objekt bez STOPA extenze — jen typ/název, žádné domýšlení polí
        assert recs[0]["stix_type"] == "ipv4-addr"
        assert recs[0]["name"] == "host"


class TestFromStixErrors:
    def test_invalid_json_raises(self):
        try:
            from_stix_bundle("{nejson")
        except ValueError as e:
            assert "nevalidní JSON" in str(e)
        else:  # pragma: no cover — obrana proti tichému propadnutí
            raise AssertionError("očekáván ValueError")

    def test_not_a_bundle_raises(self):
        try:
            from_stix_bundle('{"type": "note", "id": "n"}')
        except TypeError as e:
            assert "bundle" in str(e)
        else:  # pragma: no cover — obrana proti tichému propadnutí
            raise AssertionError("očekáván TypeError")


# ── AK 2: stix2-validator (volitelná závislost, graceful degradation) ─────


class TestValidateStixBundle:
    def test_real_bundle_passes(self):
        pytest.importorskip("stix2")  # volitelná závislost — extras [stix]
        ok, detail = validate_stix_bundle(to_stix_bundle(_art_records()))
        assert ok, detail
        # timeline dataset = custom typ x-stopa-record — allow_custom=True
        ok_tl, detail_tl = validate_stix_bundle(
            to_stix_bundle(_timeline_records(), dataset="timeline")
        )
        assert ok_tl, detail_tl

    def test_invalid_json_fails(self):
        ok, detail = validate_stix_bundle("{nejson")
        assert not ok
        assert "nevalidní JSON" in detail

    def test_malformed_stix_fails(self):
        pytest.importorskip("stix2")  # volitelná závislost — extras [stix]
        bad = json.dumps(
            {
                "type": "bundle",
                "id": "bundle--8b3e9f10-1234-5678-9abc-def012345678",
                "objects": [
                    {"type": "file", "spec_version": "2.1",
                     "id": "file--neni_uuid", "name": "x"},
                ],
            }
        )
        ok, detail = validate_stix_bundle(bad)
        assert not ok
        assert "InvalidValueError" in detail or "STIX identifier" in detail

    def test_graceful_degradation_without_stix2(self, monkeypatch):
        # sys.modules["stix2"] = None → import stix2 hájí ImportError
        monkeypatch.setitem(sys.modules, "stix2", None)
        ok, detail = validate_stix_bundle(to_stix_bundle(_art_records()))
        assert not ok
        assert detail.startswith("stix2 není nainstalován")


# ── AK 3 (UCO): round-trip dokument → záznamy identické ───────────────────


class TestUcoRoundTrip:
    def test_artifacts_roundtrip_identity(self):
        recs = _art_records()
        imported = from_uco_json(to_uco_json(recs, dataset="artifacts"))
        assert len(imported) == 2
        for original, restored in zip(recs, imported, strict=True):
            assert restored == _non_none(original), (
                f"round-trip neshoduje se pro {original['id']!r}"
            )

    def test_timeline_roundtrip_identity(self):
        recs = _timeline_records()
        imported = from_uco_json(to_uco_json(recs, dataset="timeline"))
        assert len(imported) == 1
        assert imported[0] == _non_none(recs[0])

    def test_foreign_object_without_x_stopa(self):
        doc = json.dumps(
            {
                "@context": "https://unifiedcyberontology.org/ontology/uco",
                "dataset": "artifacts",
                "count": 1,
                "objects": [{"@type": "observable:File", "name": "cizi_soubor"}],
            }
        )
        recs = from_uco_json(doc)
        assert len(recs) == 1
        assert recs[0]["uco_type"] == "observable:File"
        assert recs[0]["name"] == "cizi_soubor"


class TestFromUcoErrors:
    def test_invalid_json_raises(self):
        try:
            from_uco_json("{nejson")
        except ValueError as e:
            assert "nevalidní JSON" in str(e)
        else:  # pragma: no cover — obrana proti tichému propadnutí
            raise AssertionError("očekáván ValueError")

    def test_not_a_doc_raises(self):
        try:
            from_uco_json('{"type": "note"}')
        except TypeError as e:
            assert "UCO dokument" in str(e)
        else:  # pragma: no cover — obrana proti tichým propadnutím
            raise AssertionError("očekáván TypeError")


# ── CLI E2E — reálná case DB (fixture e10_case z test_e10) ────────────────


class TestCliF62:
    def test_cli_export_stix_with_validate(self, e10_case, capsys):  # noqa: F811
        pytest.importorskip("stix2")  # bez něj validace = přeskočena (jiný text)
        from stopa import cli

        db, case_id = e10_case
        db.close()
        assert (
            cli.main(
                [
                    "export", case_id, "--what", "artifacts",
                    "--format", "stix", "--validate-stix",
                ]
            )
            == 0
        )
        out = capsys.readouterr().out
        assert "STIX validace: validní STIX 2.1 bundle" in out

    def test_cli_export_uco_roundtrip(self, e10_case, tmp_path):  # noqa: F811
        from stopa import cli

        db, case_id = e10_case
        artifact = db.list_artifacts(limit=1)[0]
        db.close()
        out = tmp_path / "art.uco.json"
        assert (
            cli.main(
                [
                    "export", case_id, "--what", "artifacts",
                    "--format", "uco", "--out", str(out),
                ]
            )
            == 0
        )
        imported = from_uco_json(out.read_text(encoding="utf-8"))
        assert len(imported) == 1
        rec = imported[0]
        # traceability do case DB — id se shoduje s reálným artifactem
        assert rec["id"] == str(artifact.id)
        assert rec["artifact_type"] == "browser_history"
