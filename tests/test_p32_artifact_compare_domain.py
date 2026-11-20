"""P3-2 Artifact Version Comparison — Wave 1 čistá doména (docs/P3_DESIGNS.md §P3-2).

Pokrytí návrhu:
- ``artifact_key`` = ``(artifact_type, rel_path)`` bez source_id (verze napříč zachytími);
- path-based JSON diff: added/removed/changed s oběma hodnotami a cestou;
  deterministické pořadí → byte-přesný výstup pro stejné vstupy (AK2);
- metadata diff ve fixním pořadí METADATA_FIELDS (parser_version/source_id/…);
- AK1: identické hodnoty → prázdný diff; změněná hodnota → záznam s cestou + oběma hodnotami;
- AK3 provenance: výsledek nese parser_versions obou verzí;
- semantika chyb: typ = ``TypeError``, jiný artifact_key = ``ValueError``.

Offline a deterministické — bez DB, bez síti.
"""

from __future__ import annotations

import json

import pytest

from stopa.domain.artifact_compare import (
    METADATA_FIELDS,
    ArtifactComparison,
    ArtifactRecord,
    JsonDiffEntry,
    compare_artifacts,
    comparison_to_dict,
    diff_json,
)


def _rec(**kw) -> ArtifactRecord:
    base: dict = {"id": "art-x", "artifact_type": "browser_history", "rel_path": "DCIM/img.jpg"}
    base.update(kw)
    return ArtifactRecord(**base)


class TestArtifactKey:
    def test_key_is_type_and_relpath(self):
        a = _rec(rel_path="a/b.txt")
        assert a.artifact_key() == ("browser_history", "a/b.txt")

    def test_source_id_not_part_of_key(self):
        a = _rec(source_id="src-1")
        b = _rec(id="art-y", source_id="src-2")  # jiné zachytí téhož důkazu
        assert a.artifact_key() == b.artifact_key()

    def test_none_relpath_normalizes_to_empty(self):
        assert _rec(rel_path=None).artifact_key() == ("browser_history", "")


class TestDiffJson:
    def test_identical_objects_empty_diff(self):  # AK1
        d = {"a": 1, "b": {"c": [1, 2]}}
        assert diff_json(d, dict(reversed(list(d.items())))) == ()

    def test_changed_scalar_path_and_both_values(self):  # AK1
        diffs = diff_json({"exif": {"Make": "Canon"}}, {"exif": {"Make": "Nikon"}})
        assert diffs == (JsonDiffEntry("exif.Make", "changed", "Canon", "Nikon"),)

    def test_added_and_removed_nested_keys(self):
        old = {"a": 1, "gone": {"deep": True}}
        new = {"a": 1, "fresh": [3]}
        diffs = diff_json(old, new)
        by_path = {e.path: e for e in diffs}
        # nejvyšší bod odlišnosti: celý podstrom jako jeden záznam s hodnotou
        assert by_path["gone"].kind == "removed" and by_path["gone"].old == {"deep": True}
        assert by_path["fresh"].kind == "added" and by_path["fresh"].new == [3]

    def test_list_index_change_and_length_grow_shrink(self):
        diffs = diff_json({"items": [1, 2]}, {"items": [1, 9]})
        assert diffs == (JsonDiffEntry("items[1]", "changed", 2, 9),)
        more = diff_json({"items": [1]}, {"items": [1, 5]})
        assert more == (JsonDiffEntry("items[1]", "added", None, 5),)
        less = diff_json({"items": [1, 5]}, {"items": [1]})
        assert less == (JsonDiffEntry("items[1]", "removed", 5, None),)

    def test_structural_type_change_is_changed_entry(self):
        diffs = diff_json({"x": {"a": 1}}, {"x": [1]})
        assert diffs and diffs[0].path == "x" and diffs[0].kind == "changed"
        assert diffs[0].old == {"a": 1} and diffs[0].new == [1]

    def test_null_vs_missing_is_removed(self):
        diffs = diff_json({"k": None}, {})
        assert diffs == (JsonDiffEntry("k", "removed", None, None),)

    def test_deterministic_byte_identical_ordering(self):  # AK2
        old = {"zeta": 1, "alpha": {"m": [3, {"q": True}], "b": 2}, "mid": "x"}
        new = {"alpha": {"m": [4], "b": 9}, "zeta": 7}
        c1 = comparison_to_dict(compare_artifacts(
            _rec(details=old), _rec(id="art-y", details=new)))
        # vstupy s odlišným pořadím klíčů → byte-přesně stejný výstup
        old2 = {k: old[k] for k in sorted(old, reverse=True)}
        new2 = {k: new[k] for k in sorted(new, reverse=True)}
        c2 = comparison_to_dict(compare_artifacts(
            _rec(details=old2), _rec(id="art-y", details=new2)))
        assert json.dumps(c1, sort_keys=False) == json.dumps(c2, sort_keys=False)

    def test_non_mapping_input_typeerror(self):
        with pytest.raises(TypeError, match="JSON objekt"):
            diff_json([1], {})  # type: ignore[arg-type]


class TestCompareArtifacts:
    def test_identical_semantics_and_empty_diffs(self):  # AK1
        d = {"a": [1, {"b": None}]}
        r = compare_artifacts(_rec(details=d), _rec(id="art-y", details=dict(d)))
        assert isinstance(r, ArtifactComparison)
        assert r.identical and r.json_diffs == () and r.metadata_diffs == ()

    def test_changed_value_recorded_with_path_and_values(self):  # AK1
        r = compare_artifacts(
            _rec(details={"url": "http://old"}), _rec(id="art-y", details={"url": "http://new"})
        )
        assert not r.identical
        assert r.json_diffs[0].path == "url"
        assert r.json_diffs[0].old == "http://old" and r.json_diffs[0].new == "http://new"

    def test_metadata_only_change_is_not_identical(self):
        d = {"a": 1}
        r = compare_artifacts(
            _rec(details=d, parser_version="2.3"),
            _rec(id="art-y", details=dict(d), parser_version="2.4"),
        )
        assert not r.identical and r.json_diffs == ()
        assert ("parser_version", "2.3", "2.4") in r.metadata_diffs

    def test_metadata_diff_fixed_field_order(self):
        a = _rec(source_id="src-1", confidence=0.5, title="A", anomaly_flags=("f1",))
        b = _rec(id="art-y", source_id="src-2", confidence=0.9, title=None,
                 anomaly_flags=("f2",), details=dict(a.details))
        r = compare_artifacts(a, b)
        assert [m[0] for m in r.metadata_diffs] == [
            f for f in METADATA_FIELDS if f in ("source_id", "confidence", "anomaly_flags", "title")
        ]

    def test_different_key_valueerror(self):  # jiný artefakt = semantická chyba
        with pytest.raises(ValueError, match="jiný artefakt"):
            compare_artifacts(_rec(rel_path="a.txt"), _rec(id="art-y", rel_path="b.txt"))
        with pytest.raises(ValueError, match="jiný artefakt"):
            compare_artifacts(
                _rec(), _rec(id="art-y", artifact_type="chat_message")
            )

    def test_wrong_input_types_raise_typeerror(self):  # konvence projektu
        with pytest.raises(TypeError, match="ArtifactRecord"):
            compare_artifacts({"id": "x"}, _rec())  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="details"):
            compare_artifacts(_rec(details=[1]), _rec(id="art-y", details=[1]))

    def test_parser_versions_exposed(self):  # AK3 provenance
        r = compare_artifacts(
            _rec(parser_version="2.3"), _rec(id="art-y", parser_version="2.4")
        )
        assert r.parser_versions == ("2.3", "2.4")
        d = comparison_to_dict(r)
        assert d["parser_versions"] == {"a": "2.3", "b": "2.4"}

    def test_comparison_to_dict_shape(self):
        r = compare_artifacts(
            _rec(details={"x": 1}), _rec(id="art-y", details={"x": 2}, parser_version="9")
        )
        d = comparison_to_dict(r)
        assert d["identical"] is False
        assert d["key"] == ["browser_history", "DCIM/img.jpg"]
        assert d["json_diffs"][0] == {"path": "x", "kind": "changed", "old": 1, "new": 2}
        assert json.dumps(d)  # plně serializovatelné
