"""P1 security — omezené XML parsování (billion laughs / hloubková bomba).

Kryje:
- ``bounded_xml_parse`` (doménová vrstva): limity, stream, str/bytes, ParseError.
- Call sites v důkazových parserech: ODF content.xml, OOXML docProps, Windows
  Scheduled Task + WLAN profile XML, UFED report.xml — bomba nesmí padnout
  proces a musí skončit buď graceful degradací nebo dokumentovanou výjimkou.

Vše offline + deterministické (žádné I/O mimo tmp_path).
"""

from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from stopa.artifacts.openoffice_base import extract_openoffice_base_artifacts
from stopa.artifacts.win_schedtask import parse_scheduled_task_xml
from stopa.artifacts.win_wlan import parse_wlan_profile_xml
from stopa.domain.file_meta import extract_metadata
from stopa.domain.mobile_forensics import UfedParseError, parse_ufdr_xml
from stopa.domain.xml_bounded import (
    DEFAULT_MAX_DEPTH,
    XmlLimitError,
    bounded_xml_parse,
)


def _billion_laughs() -> bytes:
    """Klasická billion laughs — 5 úrovní samoreferenčních entit."""
    return b'<?xml version=\'1.0\'?>\n<!DOCTYPE lolz [\n<!ENTITY lol "lol">\n<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">\n<!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">\n<!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">\n<!ENTITY lol5 "&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;">\n]>\n<root>&lol5;</root>'


def _depth_bomb(depth: int) -> bytes:
    """Vnořených <a> prvků do zadané hloubky."""
    return b"<a>" * depth + b"</a>" * depth


# ── bounded_xml_parse — unit ───────────────────────────────────────────


class TestBoundedXmlParse:
    def test_normal_namespaced_xml_matches_plain_et(self):
        doc = (
            '<task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">'
            '  <RegInfo><Description>úloha</Description></RegInfo>'
            '</task>'
        ).encode()
        root = bounded_xml_parse(doc)
        plain = ET.fromstring(doc)
        assert root.tag == plain.tag
        ns = "{http://schemas.microsoft.com/windows/2004/02/mit/task}"
        assert root.find(".//" + ns + "Description").text == "úloha"

    def test_str_input(self):
        root = bounded_xml_parse("<r a=" + chr(39) + "1" + chr(39) + ">x&amp;y</r>")
        assert root.tag == "r"
        assert root.text == "x&y"  # předdefinovaná entity se rozbalí normálně

    def test_stream_input_matches_bytes(self):
        doc = b"<a><b c='2'>text</b></a>"
        from_stream = bounded_xml_parse(io.BytesIO(doc))
        from_bytes = bounded_xml_parse(doc)
        assert from_stream.tag == from_bytes.tag
        assert from_stream[0].attrib == from_bytes[0].attrib

    def test_billion_laughs_raises_fast(self):
        start = time.monotonic()
        with pytest.raises(XmlLimitError, match="billion laughs"):
            bounded_xml_parse(_billion_laughs())
        # entity se odhalí v DOCTYPE → O(1), bez expanze (celý run < 2 s)
        assert time.monotonic() - start < 2.0

    def test_single_entity_decl_rejected_even_if_unused(self):
        with pytest.raises(XmlLimitError, match="billion laughs"):
            bounded_xml_parse(b"<!DOCTYPE r [<!ENTITY x 'y'>]><r/>")

    def test_predefined_entities_pass_through(self):
        root = bounded_xml_parse(b"<r>a&amp;b&lt;c&gt;</r>")
        assert root.text == "a&b<c>"

    def test_depth_bomb_raises_at_limit(self):
        with pytest.raises(XmlLimitError, match="hloubka"):
            bounded_xml_parse(_depth_bomb(DEFAULT_MAX_DEPTH + 1))

    def test_exactly_max_depth_ok(self):
        root = bounded_xml_parse(_depth_bomb(DEFAULT_MAX_DEPTH))
        assert root.tag == "a"

    def test_custom_max_depth(self):
        with pytest.raises(XmlLimitError, match="hloubka"):
            bounded_xml_parse(b"<a><b/></a>", max_depth=1)
        assert bounded_xml_parse(b"<a/>", max_depth=1).tag == "a"

    def test_malformed_xml_propagates_parse_error(self):
        with pytest.raises(ET.ParseError):
            bounded_xml_parse(b"<a><b></a>")

    def test_empty_input_raises(self):
        # stejná sémantika jako ET.fromstring(b"") → ParseError "no element found"
        with pytest.raises(ET.ParseError, match="no element found"):
            bounded_xml_parse(b"")


# ── call sites — důkazové parsery ──────────────────────────────────────


class TestCallSites:
    def test_odb_content_xml_bomb_graceful(self, tmp_path: Path):
        """ODF kontejner s billion-laughs content.xml → [] (metadata chybí), ne crash."""
        odb = tmp_path / "bomb.odb"
        with zipfile.ZipFile(odb, "w") as zf:
            # Writer mimetype → bez potvrzení Base; prázdná metadata ⇒ []
            zf.writestr("mimetype", b"application/vnd.oasis.opendocument.text")
            zf.writestr("content.xml", _billion_laughs())
        assert extract_openoffice_base_artifacts(odb) == []

    def test_docx_docprops_bomb_graceful(self):
        """docx s billion-laughs docProps/core.xml → {} (bez crashu)."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("docProps/core.xml", _billion_laughs())
        assert extract_metadata(buf.getvalue(), "dokument.docx") == {}

    def test_docprops_oversized_member_skipped(self):
        """docProps/core.xml > 256 KiB → přeskočen (bez expanze)."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("docProps/core.xml", b"<x>" + b"a" * (300 * 1024) + b"</x>")
        assert extract_metadata(buf.getvalue(), "velky.docx") == {}

    def test_schedtask_bomb_value_error(self):
        with pytest.raises(ValueError, match="Scheduled Task XML"):
            parse_scheduled_task_xml(_billion_laughs())

    def test_wlan_depth_bomb_value_error(self):
        with pytest.raises(ValueError, match="WLAN profile XML"):
            parse_wlan_profile_xml(_depth_bomb(DEFAULT_MAX_DEPTH + 1))

    def test_ufdr_report_xml_bomb_parse_error(self):
        doc = (b'<!DOCTYPE r [<!ENTITY x "y">]>'
               b'<Extraction><Model type="SystemInfo"/></Extraction>')
        with pytest.raises(UfedParseError, match="nevalidní XML"):
            parse_ufdr_xml(doc)

    def test_normal_schedtask_still_parses(self):
        doc = (b'<?xml version="1.0"?>'
               b'<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">'
               b'  <Actions><Exec><Command>C:\\win\\system32\\cmd.exe</Command></Exec></Actions>'
               b'</Task>')
        tasks = parse_scheduled_task_xml(doc)
        assert len(tasks) == 1
