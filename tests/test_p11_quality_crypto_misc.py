"""STOPA — P1-1 quality sada vlna 13 (crypto extract + ddg current tabs + msn messenger).

Kontrakty doložené per parser:

``crypto_extract`` — file-based IO extraktor (řád: Electrum JSON → MetaMask vault →
exchange CSV → Bitcoin Core BDB → K1 text scan), všechny chyby = graceful ``[]``:
- exchange CSV (Binance deposits hlavička) → 1 artefakt na záznam
  (``crypto_exchange_record``), strop CRYPTO_MAX_RECORDS=20_000 s flagem ``truncated``
  + ``total_records`` v detailu prvního artefaktu;
- časová ekvivalence: ISO Z == ISO offset +02:00 == epoch s == epoch ms (≥1e12 → /1000)
  na stejný aware UTC datetime (``_parse_ts``);
- binárka s NUL v prvních 4096 B → decode None → ``[]``; oříznuté JSON bez komat →
  graceful fallthrough na ``[]``; CSV jen hlavička bez řádků → ``[]``;
- nestrukturovaný text do 4 MiB → K1 scan: adresy/txid/seedy, PII guard (citlivé
  materiály = počet); latin-1 fallback decode (neutf8 znaky) s roundtripem adres;
- locale: česká diakritika v Coinbase CSV Counterparty sloupci → raw detail verbatim.

``ddg_current_tabs`` — JSON pole záložek (nebo text, jeden URL na řádek):
- BOM prefix / binární smetí / oříznuté pole → ValueError „Neplatné JSON" (čte utf-8
  s errors=replace, ne utf-8-sig); kořen ≠ pole → TypeError „Očekáváno JSON pole záložek";
- items bez url = skip; MAX_TABS_PER_FILE=2000 (truncation payload[:MAX]);
- text varianta: dedup URL + strop 2000, žádné platné URL → ValueError
  „Žádný platný URL nenalezen"; extract dispatch podle head byte ([ = JSON),
  ValueError/TypeError → graceful [];
- snapshot bez času → artifact.timestamp is None; title truncation [:100].

``msn_messenger`` — textový MSN chat log parser:
- nadpis s verzí (regex ``messenger \\d[\\d.]*`` na konci řádku v prvních 4096 B)
  chybí → ValueError „Nadpis MSN/Messenger verze nenalezen"; extract = graceful [];
- zprávy až za „Chat started on ..."; format ``sender: text`` (volitelné
  ``(display name)``); sender >40 znaků bez tečky ani @ = šum (skip);
- MAX_MESSAGES_PER_FILE=5000 (truncation); decode utf-8 s errors=replace;
- chat log nemá per-message čas → artifact.timestamp is None (dokumentovaný kontrakt).
"""

# quality: positive negative boundary corrupted tz encoding locale size

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from stopa.artifacts.crypto_extract import CRYPTO_MAX_RECORDS, extract_crypto_artifacts
from stopa.artifacts.ddg_current_tabs import (
    MAX_TABS_PER_FILE,
    build_tab_artifacts,
    extract_current_tabs_artifacts,
    parse_current_tabs_json,
    parse_current_tabs_text,
)
from stopa.artifacts.msn_messenger import (
    MAX_MESSAGES_PER_FILE,
    build_msn_artifacts,
    extract_msn_artifacts,
    parse_msn_chat_log,
)

# ── společné konstanty ───────────────────────────────────────────────────

EPOCH = 1464955479  # = 2016-06-03T12:04:39Z (Binance vzorový export)
UTC_DT = datetime.fromtimestamp(EPOCH, tz=timezone.utc)

BINANCE_HDR = "Time,Asset,Amount,Address,TxHash"
COINBASE_HDR = "Type,Date/Time,Currency,Amount,Counterparty,Transaction ID"

ETH_ADDR = "0x639b7687c794dd23a8b2f3e1ceab31ddf435e5a2"
MSN_HDR = "Microsoft Messenger 8.5\n"
MSN_START = "Chat started on 2/14/2010 at 10:23 AM\n"


def _binance_csv(times: list[str]) -> bytes:
    rows = [BINANCE_HDR]
    for t in times:
        rows.append(f"{t},BTC,1.5,BTCaddrX,{'a' * 64}")
    return "\n".join(rows).encode("utf-8")


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    p = tmp_path / name
    p.write_bytes(data)
    return p


# ── crypto_extract ───────────────────────────────────────────────────────


class TestCryptoExtractQuality:
    def test_positive_exchange_csv(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "binance.csv", _binance_csv(["2016-06-03T12:04:39Z"]))
        arts = extract_crypto_artifacts(p)
        assert len(arts) == 1
        a = arts[0]
        assert a.artifact_type == "crypto_exchange_record"
        assert a.details["exchange"] == "binance"
        assert a.details["record_type"] == "deposit"
        assert a.timestamp == UTC_DT
        assert a.title.startswith("[binance] deposit")

    def test_negative_plain_text_no_match(self, tmp_path: Path) -> None:
        # žádné adresní tokeny (≥8 znaků), žádná txid, žádné klíče/seedy → []
        p = _write(tmp_path, "memo.txt", "Dobrý den\nprosím ověřte údaje\n".encode())
        assert extract_crypto_artifacts(p) == []

    def test_negative_truncated_json_fallthrough(self, tmp_path: Path) -> None:
        # JSON-looking start, nedekodovatelné, bez komat → CSV check přeskočen → []
        p = _write(tmp_path, "trunc.json", b'{"x": 1')
        assert extract_crypto_artifacts(p) == []

    def test_corrupted_binary_nul_header(self, tmp_path: Path) -> None:
        # NUL v prvních 4096 B → decode None → žádná textová cesta → [] graceful
        p = _write(tmp_path, "garbage.bin", b"\x00\x01\xff\xfePK?binarni-smeti\n")
        assert extract_crypto_artifacts(p) == []

    def test_corrupted_csv_header_only(self, tmp_path: Path) -> None:
        # platná hlavička bez datových řádků → prázdné records → [] (K1 nic nenajde)
        p = _write(tmp_path, "hdr.csv", BINANCE_HDR.encode("utf-8"))
        assert extract_crypto_artifacts(p) == []

    @pytest.mark.parametrize(
        "time_value",
        [
            "2016-06-03T12:04:39Z",  # ISO Z
            "2016-06-03T14:04:39+02:00",  # ISO offset → stejný UTC okamžik
            "1464955479",  # epoch sekundy
            "1464955479000",  # epoch ms (≥1e12 → /1000)
        ],
    )
    def test_tz_time_format_equivalence(self, tmp_path: Path, time_value: str) -> None:
        p = _write(tmp_path, "tz.csv", _binance_csv([time_value]))
        arts = extract_crypto_artifacts(p)
        assert len(arts) == 1
        assert arts[0].timestamp == UTC_DT

    def test_encoding_latin1_fallback_cz(self, tmp_path: Path) -> None:
        # „ú" = 0xFA v latin-1 → neplatné UTF-8 → fallback decode; adresa roundtrip
        text = f"poznamka ú a á: {ETH_ADDR}\n"
        p = _write(tmp_path, "note.txt", text.encode("latin-1"))
        arts = extract_crypto_artifacts(p)
        assert len(arts) == 1
        addrs = [a.get("raw_value") for a in arts[0].details["addresses"]]
        assert ETH_ADDR in addrs

    def test_locale_coinbase_cz_roundtrip(self, tmp_path: Path) -> None:
        # česká diakritika v Counterparty → raw detail verbatim
        row = 'Buy,2016-06-03T12:04:39Z,EUR,1.5,"Účetní kancelář Šmíd",txid123'
        p = _write(tmp_path, "cb.csv", (COINBASE_HDR + "\n" + row).encode("utf-8"))
        arts = extract_crypto_artifacts(p)
        assert len(arts) == 1
        assert arts[0].details["raw"]["Counterparty"] == "Účetní kancelář Šmíd"
        assert arts[0].timestamp == UTC_DT

    def test_size_max_records_truncation(self, tmp_path: Path) -> None:
        times = ["2016-06-03T12:04:39Z"] * (CRYPTO_MAX_RECORDS + 1)
        p = _write(tmp_path, "big.csv", _binance_csv(times))
        arts = extract_crypto_artifacts(p)
        assert len(arts) == CRYPTO_MAX_RECORDS
        # flag truncation v detailu prvního artefaktu
        assert arts[0].details["truncated"] is True
        assert arts[0].details["total_records"] == CRYPTO_MAX_RECORDS + 1

    def test_boundary_empty_file(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "empty.csv", b"")
        assert extract_crypto_artifacts(p) == []

    def test_boundary_single_record(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "one.csv", _binance_csv(["2016-06-03T12:04:39Z"]))
        arts = extract_crypto_artifacts(p)
        assert len(arts) == 1
        assert arts[0].confidence == 0.9  # s analyzovatelným časem


# ── ddg_current_tabs ─────────────────────────────────────────────────────


class TestDdgCurrentTabsQuality:
    def _tabs_json(self, n: int) -> bytes:
        return json.dumps(
            [{"title": f"Záložka {i}", "url": f"https://priklad.cz/{i}"} for i in range(n)]
        ).encode("utf-8")

    def test_positive_json_tabs(self, tmp_path: Path) -> None:
        tabs = parse_current_tabs_json(self._tabs_json(2))
        assert len(tabs) == 2
        arts = build_tab_artifacts(tabs)
        assert len(arts) == 2
        assert arts[0].artifact_type == "browser_tab"
        assert arts[0].details["title"] == "Záložka 0"
        assert arts[0].details["url"] == "https://priklad.cz/0"

    def test_negative_root_not_list(self) -> None:
        with pytest.raises(TypeError, match="Očekáváno JSON pole záložek"):
            parse_current_tabs_json(b'{"title": "x", "url": "https://y.cz"}')

    def test_boundary_empty_and_skips(self) -> None:
        assert parse_current_tabs_json(b"[]") == []
        # item bez url = skip, ne-dict = skip
        data = b'[{"title": "bez url"}, 42, {"url": "https://ok.cz"}]'
        tabs = parse_current_tabs_json(data)
        assert len(tabs) == 1
        assert tabs[0].url == "https://ok.cz"

    def test_boundary_text_variant(self) -> None:
        tabs = parse_current_tabs_text(b"https://jedna.cz\nhttp://dva.cz\nne-url radek\n")
        assert [t.url for t in tabs] == ["https://jedna.cz", "http://dva.cz"]
        with pytest.raises(ValueError, match="Žádný platný URL nenalezen"):
            parse_current_tabs_text(b"hello\nworld\n")

    @pytest.mark.parametrize(
        "payload",
        [
            b"\xef\xbb\xbf" + b'[]',  # BOM prefix (nečte se utf-8-sig)
            b"\x00\x01\xff\xfePK?binarni-smeti\n",  # binární smetí
            b'[{"url": "https://priklad.cz/',  # oříznuté pole
        ],
    )
    def test_corrupted_json_payloads(self, payload: bytes) -> None:
        with pytest.raises(ValueError, match="Neplatné JSON"):
            parse_current_tabs_json(payload)

    @pytest.mark.parametrize(
        "payload",
        [
            b"\x00\x01\xff\xfePK?binarni-smeti\n",  # head ≠ "[" → text cesta → []
            b'[{"url": "https://priklad.cz/',  # head = "[" → JSON cesta → ValueError → []
        ],
    )
    def test_corrupted_extract_graceful(self, tmp_path: Path, payload: bytes) -> None:
        p = _write(tmp_path, "tabs.json", payload)
        assert extract_current_tabs_artifacts(p) == []

    def test_encoding_invalid_utf8_replaced(self) -> None:
        # errors="replace" — neplatné bajty → U+FFFD, crash ne, url nepoškozená
        data = b'[{"title": "\xff\xfe", "url": "https://x.cz"}]'
        tabs = parse_current_tabs_json(data)
        assert len(tabs) == 1
        assert tabs[0].url == "https://x.cz"
        assert tabs[0].title == "\ufffd\ufffd"

    def test_locale_cz_content_roundtrip(self, tmp_path: Path) -> None:
        data = json.dumps(
            [{"title": "Česká záložka s diakritikou", "url": "https://cs.wikipedia.org/"}]
        ).encode("utf-8")
        tabs = parse_current_tabs_json(data)
        assert tabs[0].title == "Česká záložka s diakritikou"
        p = _write(tmp_path, "tabs.json", data)
        arts = extract_current_tabs_artifacts(p)
        assert len(arts) == 1
        assert "diakritikou" in arts[0].title

    def test_size_max_tabs_truncation(self) -> None:
        tabs = parse_current_tabs_json(self._tabs_json(MAX_TABS_PER_FILE + 1))
        assert len(tabs) == MAX_TABS_PER_FILE

    def test_size_text_dedup_and_cap(self) -> None:
        # dedup: stejný URL jednou; strop: MAX unikátních
        dup = b"https://x.cz\nhttps://x.cz\n"
        assert len(parse_current_tabs_text(dup)) == 1
        many = "\n".join(f"https://{i}.example.com" for i in range(MAX_TABS_PER_FILE + 50)).encode()
        assert len(parse_current_tabs_text(many)) == MAX_TABS_PER_FILE

    def test_tz_snapshot_no_time(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "tabs.json", self._tabs_json(3))
        arts = extract_current_tabs_artifacts(p)
        assert len(arts) == 3
        # snapshot otevřených záložek nemá čas (dokumentovaný kontrakt)
        assert all(a.timestamp is None for a in arts)


# ── msn_messenger ────────────────────────────────────────────────────────


class TestMsnMessengerQuality:
    def test_positive_chat_log(self, tmp_path: Path) -> None:
        data = (
            MSN_HDR
            + MSN_START
            + "----------------------------------------\n"
            + "jan@example.com (Jan Novák): Ahoj, jak se máš?\n"
            + "petra@seznam.cz: Dobrý den!\n"
        ).encode("utf-8")
        msgs = parse_msn_chat_log(data)
        assert len(msgs) == 2
        assert msgs[0].sender == "jan@example.com"
        assert msgs[0].display_name == "Jan Novák"
        assert msgs[0].text == "Ahoj, jak se máš?"
        arts = build_msn_artifacts(msgs)
        assert len(arts) == 2
        assert arts[0].artifact_type == "messenger_message"
        assert arts[0].confidence == 0.8
        assert "Jan Novák" in arts[0].title

    def test_negative_no_header(self, tmp_path: Path) -> None:
        data = b"random text bez nadpisu\nfoo: bar\n"
        with pytest.raises(ValueError, match="Nadpis MSN/Messenger verze nenalezen"):
            parse_msn_chat_log(data)
        p = _write(tmp_path, "chat.log", data)
        assert extract_msn_artifacts(p) == []  # graceful

    def test_boundary_empty_and_header_only(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "empty.log", b"")
        assert extract_msn_artifacts(p) == []
        # jen nadpis bez „Chat started on" a bez zpráv → 0 zpráv
        msgs = parse_msn_chat_log((MSN_HDR + "----------------------------------------\n").encode())
        assert msgs == []

    def test_corrupted_binary_and_truncated(self, tmp_path: Path) -> None:
        # binární smetí bez nadpisu → ValueError (parse) / [] (extract)
        garbage = b"\x00\x01\xff\xfePK?binarni-smeti\n"
        with pytest.raises(ValueError):
            parse_msn_chat_log(garbage)
        p = _write(tmp_path, "garbage.log", garbage)
        assert extract_msn_artifacts(p) == []
        # oříznutý log: kompletní řádky zůstávají, poslední neúplný je stále validní
        truncated = (MSN_HDR + MSN_START + "jan@example.com: Ahoj").encode("utf-8")
        msgs = parse_msn_chat_log(truncated)
        assert len(msgs) == 1
        assert msgs[0].text == "Ahoj"

    def test_encoding_invalid_utf8_and_diacritics(self, tmp_path: Path) -> None:
        # neplatné UTF-8 bajty → errors=replace (crash ne); diakritika roundtrip
        raw = (MSN_HDR + MSN_START + "x@y.cz: Ahoj ").encode("utf-8") + b"\xff\xfe"
        msgs = parse_msn_chat_log(raw)
        assert len(msgs) == 1
        assert msgs[0].text == "Ahoj \ufffd\ufffd"
        cz = (MSN_HDR + MSN_START + "a@b.cz: Příjděte prosím na schůzku\n").encode("utf-8")
        msgs_cz = parse_msn_chat_log(cz)
        assert msgs_cz[0].text == "Příjděte prosím na schůzku"

    def test_locale_cz_chat_roundtrip(self, tmp_path: Path) -> None:
        data = (
            MSN_HDR
            + MSN_START
            + "ondrej.novak@post.cz (Ondřej Novák): Dobrý večer, co povíte?\n"
            + "hana.svobodova@post.cz (Hana Svobodová): Skvělé počasí!\n"
        ).encode("utf-8")
        msgs = parse_msn_chat_log(data)
        assert len(msgs) == 2
        assert msgs[0].sender == "ondrej.novak@post.cz"
        assert msgs[0].display_name == "Ondřej Novák"
        arts = build_msn_artifacts(msgs)
        # title obsahuje text verbatim ([:80]) — diakritika bez ztráty
        assert "co povíte?" in arts[0].title

    def test_size_max_messages_truncation(self) -> None:
        lines = [MSN_HDR, MSN_START] + [f"u{i}@x.cz: zprava {i}" for i in range(MAX_MESSAGES_PER_FILE + 1)]
        msgs = parse_msn_chat_log("\n".join(lines).encode("utf-8"))
        assert len(msgs) == MAX_MESSAGES_PER_FILE

    def test_tz_no_per_message_time(self, tmp_path: Path) -> None:
        data = (MSN_HDR + MSN_START + "a@b.cz: zpráva bez času\n").encode("utf-8")
        arts = build_msn_artifacts(parse_msn_chat_log(data))
        assert len(arts) == 1
        # chat log nemá per-message čas (jen start v hlavičce) — dokumentovaný kontrakt
        assert arts[0].timestamp is None
        assert "zpráva bez času" in arts[0].title
