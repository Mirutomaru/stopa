"""P3-5 Wave 1 — čistá doména YARA/Sigma matching (offline, deterministické).

Pokrytí:
- YARA: parsing názvů/bloků pravidel, TLP z meta, kompilace + matching
  (volitelný yara-python přes importorskip), explicitní RuntimeError bez balíku
  (AK1), determinismus pořadí výstupu (AK2).
- Sigma: validace šablon (pydantic = ValueError dle konvence), JSON/YAML
  parsing, sémantika podmínek (AND přes klíče / OR uvnitř), ts meze včetně,
  determinismus pořadí.
- threat_intel: pravidlové druhy IOC_KINDS + STIX export je nese jen indikátory.
"""

from __future__ import annotations

import json
import sys

import pytest

from stopa.domain.threat_intel import (
    RULE_KINDS,
    IoC,
    canonical_value,
    export_bundle,
)
from stopa.domain.yara_sigma import (
    EventTarget,
    SigmaTemplate,
    YaraTarget,
    match_yara_files,
    parse_sigma_templates,
    parse_yara_rule_names,
    rule_blocks,
    rule_tlp_level,
    sigma_matches,
    yara_available,
)

YARA_SRC = '''
private global rule Malware_Sample {
    meta:
        tlp = "AMBER"
        author = "stopa-test"
    strings:
        $a = "MALWAREMARKER"
    condition:
        $a
}

rule Benign_Check {
    strings:
        $b = "BENIGNTEXT"
    condition:
        $b
}
'''


def _ev(i: int, ts: str, etype: str, title: str, path: str, flags: str = "") -> EventTarget:
    return EventTarget(id=f"ev-{i}", ts_utc=ts, event_type=etype, title=title, rel_path=path, anomaly_flags=flags)


EV_ALL = [
    _ev(1, "2024-12-09T14:00:00+00:00", "chat_message", "Hovor s Davidem", "sms/1.txt"),
    _ev(2, "2024-12-09T15:30:00+00:00", "browser_history", "Visit example.com", "DCIM/img.jpg", "mace_inconsistent"),
    _ev(3, "2024-12-10T08:00:00+00:00", "chat_message", "SMS od Mamky", "sms/2.txt", "gap, mace_inconsistent"),
]


# ── YARA parsing (bez kompilátoru) ──────────────────────────────────────


class TestYaraParsing:
    def test_parse_names_order_and_modifiers(self):
        assert parse_yara_rule_names(YARA_SRC) == ["Malware_Sample", "Benign_Check"]

    def test_parse_names_no_rules_empty(self):
        assert parse_yara_rule_names("strings: $a = 'x'") == []

    def test_parse_names_type_error(self):
        with pytest.raises(TypeError, match="string"):
            parse_yara_rule_names(b"rule X { }")  # type: ignore[arg-type]

    def test_rule_blocks_split_and_tlp(self):
        blocks = rule_blocks(YARA_SRC)
        assert [name for name, _ in blocks] == ["Malware_Sample", "Benign_Check"]
        assert rule_tlp_level(blocks[0][1]) == "AMBER"  # uvozovky + meta blok
        assert rule_tlp_level(blocks[1][1]) is None

    def test_rule_tlp_case_and_bare(self):
        assert rule_tlp_level('meta:\n tlp = red\n') == "RED"
        assert rule_tlp_level("rule X { strings: $s = 'tlp' }") is None

    def test_blocks_type_error(self):
        with pytest.raises(TypeError, match="string"):
            rule_blocks(42)  # type: ignore[arg-type]

    def test_yara_available_flag_consistent(self):
        assert isinstance(yara_available(), bool)


class TestYaraMatching:
    @pytest.fixture()
    def targets(self):
        return [
            YaraTarget("src-a", "DCIM/img.jpg", b"prefix MALWAREMARKER suffix"),
            YaraTarget("src-b", "data.bin", b"BENIGNTEXT only"),
            YaraTarget("src-a", "empty.txt", b""),
            YaraTarget("src-b", "gone.bin", None),  # chybějící na disku
        ]

    def test_match_hits_sorted_and_deterministic(self, targets):
        pytest.importorskip("yara")
        hits = match_yara_files(YARA_SRC, targets)
        assert [(h.rule, h.rel_path) for h in hits] == [
            ("Benign_Check", "data.bin"),
            ("Malware_Sample", "DCIM/img.jpg"),
        ]
        # shodný vstup (jiné pořadí targetů) = shodný výstup — AK2
        shuffled = list(reversed(targets))
        assert match_yara_files(YARA_SRC, shuffled) == hits

    def test_missing_data_skipped(self, targets):
        pytest.importorskip("yara")
        only_gone = [YaraTarget("src-b", "gone.bin", None)]
        assert match_yara_files(YARA_SRC, only_gone) == []

    def test_no_rules_value_error_without_library(self, targets):
        # kontrola jmen jde PŘED importem yara → ValueError funguje i bez balíku
        with pytest.raises(ValueError, match="neobsahuje žádné pravidlo"):
            match_yara_files("strings: $a = 'x'", targets)

    def test_invalid_source_value_error(self, targets):
        pytest.importorskip("yara")
        with pytest.raises(ValueError, match="Neplatný YARA zdroj"):
            match_yara_files("rule X { condition: 1 } strings:", targets)

    def test_missing_library_explicit_runtime_error(self, targets, monkeypatch):
        # AK1: bez yara-python explicitní stav (ne tiché 0 / silent skip)
        monkeypatch.setitem(sys.modules, "yara", None)
        with pytest.raises(RuntimeError, match="yara-python"):
            match_yara_files(YARA_SRC, targets)

    def test_type_error_targets(self):
        pytest.importorskip("yara")
        with pytest.raises(TypeError, match="YaraTarget"):
            match_yara_files(YARA_SRC, ["not-a-target"])  # type: ignore[list-item]


# ── Sigma šablony + matching ────────────────────────────────────────────

SIGMA_JSON = json.dumps(
    [
        {
            "name": "david-chats",
            "description": "chat zprávy s Davidem",
            "tlp": "AMBER",
            "detection": {"event_type": ["chat_message"], "title_contains": ["David"]},
        },
        {
            "name": "mace-window",
            "detection": {
                "anomaly_flag_any": ["mace_inconsistent"],
                "ts_start": "2024-12-09T15:00:00+00:00",
                "ts_end": "2024-12-09T16:00:00+00:00",
            },
        },
    ]
)


class TestSigmaTemplates:
    def test_parse_json_list(self):
        tpls = parse_sigma_templates(SIGMA_JSON)
        assert [t.name for t in tpls] == ["david-chats", "mace-window"]
        assert tpls[0].tlp == "AMBER"
        assert tpls[1].tlp == "GREEN"  # default

    def test_parse_single_dict_accepted(self):
        tpls = parse_sigma_templates('{"name": "x", "detection": {"event_type": ["a"]}}')
        assert [t.name for t in tpls] == ["x"]

    def test_empty_document_value_error(self):
        with pytest.raises(ValueError, match="Žádné šablony"):
            parse_sigma_templates("[]")

    def test_non_dict_item_type_error(self):
        with pytest.raises(TypeError, match="objekt"):
            parse_sigma_templates('[1, 2]')

    def test_doc_type_error(self):
        with pytest.raises(TypeError, match="string"):
            parse_sigma_templates(42)  # type: ignore[arg-type]

    def test_empty_name_value_error(self):
        with pytest.raises(ValueError, match="Název šablony"):
            SigmaTemplate.model_validate({"name": "  ", "detection": {"event_type": ["a"]}})

    def test_bad_tlp_value_error(self):
        with pytest.raises(ValueError, match="TLP"):
            SigmaTemplate.model_validate(
                {"name": "x", "tlp": "PURPLE", "detection": {"event_type": ["a"]}}
            )

    def test_empty_detection_value_error(self):
        with pytest.raises(ValueError, match="kritérium"):
            SigmaTemplate.model_validate({"name": "x", "detection": {}})


class TestSigmaYaml:
    YAML_DOC = (
        "---\n"
        'name: yaml-rule\n'
        'tlp: RED\n'
        "detection:\n"
        "  event_type:\n"
        "    - browser_history\n"
        "---\n"
        'name: second\n'
        "detection:\n"
        '  path_glob: ["*.jpg"]\n'
    )

    def test_parse_yaml_multidoc(self):
        pytest.importorskip("yaml")
        tpls = parse_sigma_templates(self.YAML_DOC)
        assert [t.name for t in tpls] == ["yaml-rule", "second"]
        assert tpls[0].tlp == "RED"

    def test_yaml_without_pyyaml_explicit_error(self, monkeypatch):
        pytest.importorskip("yaml")  # jen pokud YAML vůbec umíme číst
        monkeypatch.setitem(sys.modules, "yaml", None)
        with pytest.raises(ValueError, match="PyYAML|JSON"):
            parse_sigma_templates(self.YAML_DOC)

    def test_yaml_syntax_error_value_error(self):
        pytest.importorskip("yaml")
        with pytest.raises(ValueError, match="Neplatný YAML dokument"):
            parse_sigma_templates("name: [unclosed\n  bad:::")


class TestSigmaMatching:
    def test_event_type_or_within_key(self):
        tpl = SigmaTemplate.model_validate(
            {"name": "x", "detection": {"event_type": ["chat_message", "browser_history"]}}
        )
        assert sigma_matches(tpl, EV_ALL) == ["ev-1", "ev-2", "ev-3"]

    def test_title_contains_case_insensitive_or(self):
        tpl = SigmaTemplate.model_validate(
            {"name": "x", "detection": {"title_contains": ["DAVID", "mAMkY"]}}
        )
        assert sigma_matches(tpl, EV_ALL) == ["ev-1", "ev-3"]

    def test_path_glob(self):
        tpl = SigmaTemplate.model_validate(
            {"name": "x", "detection": {"path_glob": ["sms/*", "*.jpg"]}}
        )
        assert sigma_matches(tpl, EV_ALL) == ["ev-1", "ev-2", "ev-3"]

    def test_anomaly_flag_any_with_spaces(self):
        tpl = SigmaTemplate.model_validate(
            {"name": "x", "detection": {"anomaly_flag_any": ["mace_inconsistent"]}}
        )
        # ev-2 i ev-3 (flag s mezerou po čárce se stripuje)
        assert sigma_matches(tpl, EV_ALL) == ["ev-2", "ev-3"]

    def test_ts_bounds_inclusive_and(self):
        tpl = SigmaTemplate.model_validate(
            {
                "name": "x",
                "detection": {
                    "event_type": ["chat_message"],
                    "ts_start": "2024-12-09T14:00:00+00:00",
                    "ts_end": "2024-12-10T08:00:00+00:00",
                },
            }
        )
        # AND přes klíče: typ + oboje meze včetně → všechny 3 chat události v rozsahu
        assert sigma_matches(tpl, EV_ALL) == ["ev-1", "ev-3"]

    def test_ts_bounds_exclusive_outside(self):
        tpl = SigmaTemplate.model_validate(
            {"name": "x", "detection": {"ts_start": "2024-12-10T08:00:01+00:00"}}
        )
        assert sigma_matches(tpl, EV_ALL) == []

    def test_bad_ts_value_error(self):
        tpl = SigmaTemplate.model_validate(
            {"name": "x", "detection": {"ts_start": "not-a-date"}}
        )
        with pytest.raises(ValueError, match="ISO datum"):
            sigma_matches(tpl, EV_ALL)

    def test_output_sorted_by_ts_then_id_deterministic(self):
        tpl = SigmaTemplate.model_validate(
            {"name": "x", "detection": {"event_type": ["chat_message"]}}
        )
        out = sigma_matches(tpl, list(reversed(EV_ALL)))
        assert out == ["ev-1", "ev-3"]  # ts pořadí nezávislé na vstupu

    def test_type_errors(self):
        tpl = SigmaTemplate.model_validate(
            {"name": "x", "detection": {"event_type": ["a"]}}
        )
        with pytest.raises(TypeError, match="SigmaTemplate"):
            sigma_matches("tpl", EV_ALL)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="EventTarget"):
            sigma_matches(tpl, [1])  # type: ignore[list-item]


# ── threat_intel: pravidlové druhy + STIX export ────────────────────────


class TestRuleKindsInThreatIntel:
    def test_rule_kinds_accepted(self):
        for kind in RULE_KINDS:
            ioc = IoC(kind=kind, value="My_Rule")
            assert ioc.value == "My_Rule"  # kanonika = identita pro názvy

    def test_rule_name_canonical_strips(self):
        assert canonical_value("yara_rule", "  X1  ") == "X1"

    def test_rule_name_whitespace_only_rejected(self):
        with pytest.raises(ValueError, match="název pravidla"):
            IoC(kind="sigma_tpl", value="   ")

    def test_stix_export_excludes_rules(self):
        ip = IoC(kind="ip", value="10.20.30.40")
        yara = IoC(kind="yara_rule", value="Malware_Sample")
        doc = json.loads(export_bundle([ip, yara]))
        assert len(doc["objects"]) == 1  # jen indikátor, pravidlo je STOPA-lokální
        names = [o["name"] for o in doc["objects"]]
        assert all("Malware_Sample" not in n for n in names)
        # bundle ID deterministický — pravidlo se do něj nebere
        assert json.loads(export_bundle([ip]))["id"] == doc["id"]

    def test_stix_roundtrip_core_kinds_unaffected(self):
        from stopa.domain.threat_intel import import_bundle

        ioc = IoC(kind="domain", value="Example.com")
        yara = IoC(kind="yara_rule", value="R1")
        rt = import_bundle(export_bundle([ioc, yara]))
        assert [(r.kind, r.value) for r in rt] == [("domain", "example.com")]
