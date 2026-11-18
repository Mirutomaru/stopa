"""STOPA — P1-1 quality sada vlna 14 (bebo chat + chatroulette + net connections + limewire p2p + wifi wlan).

Kontrakty doložené per parser:

``bebo_chat`` / ``chatroulette`` — textový chat log (``[ts] user said: text`` /
``user: text``) nebo JSON pole záznamů (``user|from`` + ``message|text`` +
volitelný ``timestamp|time``):
- neplatné uzavřené JSON (trailing comma) → ValueError „Neplatné JSON";
  objektový kořen → TypeError „Očekáváno JSON pole záznamů";
- časová ekvivalence: epoch s == ISO řetězec == textový formát
  ``%Y-%m-%d %H:%M:%S`` (i ``%d.%m.%Y %H:%M``) → stejný aware UTC datetime;
- encoding = dokumentovaný lossy fallback ``utf-8/errors=replace`` — osamelé
  latin-1 bajty (ú=0xFA, á=0xE1) → U+FFFD, ASCII část verbatim;
- locale = česká diakritika v zprávě/odesílateli verbatim (UTF-8 vstup);
- MAX_MESSAGES_PER_FILE=5000 (truncation přesně na limit);
- binárka s NUL / prázdný soubor → extract graceful ``[]``;
- confidence 0.7 s odesílatelem, 0.5 bez; details text truncation [:500],
  title [:80].

``net_connections`` — netstat/ss snapshot parser:
- hlavička (proto/local address/foreign address/netid) v prvních 2048 B →
  jinak ValueError „Hlavička netstat/ss tabulky nenalezena", extract ``[]``;
- PID z ``pid=N`` (ss) nebo posledního číselného tokenu (Windows, jen když
  řádek má >=4 tokeny); stav z _KNOWN_STATES (Windows i Unix zkratky);
- dokumentovaný snapshot kontrakt: artifact.timestamp is None vždy;
- confidence 0.85 se stavem / 0.7 bez; MAX_CONNECTIONS_PER_FILE=5000;
- encoding = lossy utf-8/replace (šumový řádek s neutf8 bajtem = skip);
  locale = diakritické hostname verbatim (``serverů.cz``, regex ``[\\w.-]+``).

``limewire_p2p`` — P2P shared files (LimeWire/Limerunner/Luckywire):
- JSON pole záznamů i pipe řádky ``name|size|path|hash[|modified][|accessed]``;
  neplatné uzavřené JSON → ValueError „Neplatné JSON", objektový kořen →
  TypeError „Očekáváno JSON pole záznamů";
- rodina podle prvního markeru: Limerunner > Limewire > Luckywire (priorita);
  extract bez detekované rodiny (námě + head) → ``[]``;
- timestamp = date_modified or date_accessed, naive formáty → aware UTC;
- MAX_FILES_PER_FILE=20_000 (truncation přesně na limit);
- transfer metadata (downloaded_/uploaded_* by/from/to/on) jen pokud ve vstupu;
  confidence 0.7 s hash / 0.5 bez; binárka s NUL → graceful ``[]``.

``wifi_wlan`` — Windows WLAN profile XML:
- neplatné XML → ValueError „Neplatné WLAN profile XML"; extract graceful ``[]``;
- namespace-agnostický parsing (xmlns i obálkový kořen s více profily);
  cizí elementy v obálce = skip, profil bez SSID i name = skip;
- MAX_PROFILES_PER_FILE=50 (truncation přesně na limit);
- encryption = auth+enc text lowercased a spojený mezerou; has_key/key_length
  z sharedKey keyPassphrase/keyMaterial; MAC adresy regex + upper + dedup, max 10;
- dokumentovaný snapshot kontrakt: artifact.timestamp is None (XML nemá čas);
- encoding = deklarovaná XML charset (iso-8859-1) respektována — latin-1 znaky
  roundtrip bez ztráty; locale = plná česká diakritika verbatim (UTF-8).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from stopa.artifacts.bebo_chat import build_bebo_artifacts, extract_bebo_artifacts, parse_bebo_chat
from stopa.artifacts.chatroulette import (
    build_chatroulette_artifacts,
    extract_chatroulette_artifacts,
    parse_chatroulette,
)
from stopa.artifacts.limewire_p2p import (
    build_shared_file_artifacts,
    detect_family,
    extract_shared_files_artifacts,
    is_limewire_family_file,
    parse_shared_files,
)
from stopa.artifacts.net_connections import (
    build_netstat_artifacts,
    extract_netstat_artifacts,
    parse_netstat_text,
)
from stopa.artifacts.win_wlan import (
    build_wifi_artifacts,
    extract_wifi_artifacts,
    parse_wlan_profile_xml,
)

# Tato sada pokrývá všechny 8 kategorií pro všech 5 parserů vlny 14.
# quality: positive negative boundary corrupted tz encoding locale size

UTC = timezone.utc


# ── bebo_chat ────────────────────────────────────────────────────────────────


def test_bebo_positive_text_log_and_artifacts():
    data = (
        "[2019-03-04 12:00:01] jan.čapek said: ahoj\n"
        "petr: jak se máš?\n"
    ).encode()
    msgs = parse_bebo_chat(data)
    assert [m.user for m in msgs] == ["jan.čapek", "petr"]
    assert msgs[0].timestamp is not None and msgs[0].message == "ahoj"
    arts = build_bebo_artifacts(msgs)
    assert all(a.artifact_type == "messenger_message" for a in arts)
    assert arts[0].details["engine"] == "bebo_chat"
    assert arts[0].details["type"] == "live_chat"
    assert arts[0].confidence == 0.7


def test_bebo_positive_json_records_and_fallback_keys():
    payload = json.dumps(
        [
            {"user": "u1", "message": "prvni", "timestamp": 1551700801},
            {"from": "u2", "text": "drugi"},
            "ne-dict-item-skip",
        ]
    ).encode()
    msgs = parse_bebo_chat(payload)
    assert len(msgs) == 2
    assert (msgs[0].user, msgs[1].user) == ("u1", "u2")
    assert msgs[0].timestamp is not None and msgs[1].timestamp is None


def test_bebo_negative_invalid_json_and_nonlist():
    # uzavřené JSON s trailing comma → looks_json True → json.loads fail
    try:
        parse_bebo_chat(b'[{"user": "a",}]')
        raise AssertionError("očekáváno ValueError")
    except ValueError as e:
        assert str(e).startswith("Neplatné JSON")
    # objektový kořen (uzavřený) → TypeError
    try:
        parse_bebo_chat(b'{"user": "a", "message": "b"}')
        raise AssertionError("očekáváno TypeError")
    except TypeError as e:
        assert str(e) == "Očekáváno JSON pole záznamů"


def test_bebo_boundary_max_messages_truncation():
    lines = "".join(f"[2019-01-01 00:00:{i % 60:02d}] u{i} said: x\n" for i in range(5_001))
    assert len(parse_bebo_chat(lines.encode())) == 5_000
    payload = json.dumps([{"user": f"u{i}", "message": "x"} for i in range(5_001)]).encode()
    assert len(parse_bebo_chat(payload)) == 5_000


def test_bebo_corrupted_binary_and_empty(tmp_path: Path):
    f = tmp_path / "bebo_log.txt"
    f.write_bytes(b"\x00\x01\x02\xfe\xff" * 64)
    assert extract_bebo_artifacts(f) == []
    empty = tmp_path / "empty.txt"
    empty.write_bytes(b"")
    assert extract_bebo_artifacts(empty) == []


def test_bebo_tz_equivalence_epoch_iso_text():
    expected = datetime(2019, 3, 4, 12, 0, 1, tzinfo=UTC)
    epoch_msg = parse_bebo_chat(json.dumps([{"user": "u", "message": "m", "timestamp": 1551700801}]).encode())[0]
    iso_msg = parse_bebo_chat(b'[2019-03-04T12:00:01] u said: m\n')[0]
    text_msg = parse_bebo_chat(b"[2019-03-04 12:00:01] u said: m\n")[0]
    assert epoch_msg.timestamp == expected
    assert iso_msg.timestamp == expected
    assert text_msg.timestamp == expected
    # formát %d.%m.%Y %H:%M (minutová přesnost) → také aware UTC
    dot = parse_bebo_chat(b"[04.03.2019 12:00] u said: m\n")[0]
    assert dot.timestamp == datetime(2019, 3, 4, 12, 0, 0, tzinfo=UTC)


def test_bebo_encoding_latin1_lossy_replace():
    # ú = 0xFA a á = 0xE1 v latin-1 — osamelé neutf8 bajty → U+FFFD (lossy fallback)
    data = b"u1: ahoj \xfa svete \xe1\n"
    msgs = parse_bebo_chat(data)
    assert len(msgs) == 1
    assert msgs[0].message == "ahoj \ufffd svete \ufffd"


def test_bebo_locale_czech_diacritics_verbatim():
    data = "[2019-03-04 12:00:01] jan.čapek said: Dobrý den, jak se máš? Šéf řídí.\n".encode()
    msgs = parse_bebo_chat(data)
    assert msgs[0].user == "jan.čapek"
    arts = build_bebo_artifacts(msgs)
    assert arts[0].details["text"] == "Dobrý den, jak se máš? Šéf řídí."
    assert arts[0].title is not None and "jan.čapek" in arts[0].title


# ── chatroulette ─────────────────────────────────────────────────────────────


def test_cr_positive_text_and_json():
    data = (
        b"[2018-05-06 09:30:00] partner_abc said: hi there\n"
        b"me: hello!\n"
    )
    msgs = parse_chatroulette(data)
    assert [m.partner for m in msgs] == ["partner_abc", "me"]
    payload = json.dumps([{"partner": "p1", "message": "a"}, {"user": "p2", "text": "b"}]).encode()
    msgs2 = parse_chatroulette(payload)
    assert [m.partner for m in msgs2] == ["p1", "p2"]


def test_cr_negative_invalid_json_and_nonlist():
    try:
        parse_chatroulette(b'[{"partner": "a",}]')
        raise AssertionError("očekáváno ValueError")
    except ValueError as e:
        assert str(e).startswith("Neplatné JSON")
    try:
        parse_chatroulette(b'{"partner": "a"}')
        raise AssertionError("očekáváno TypeError")
    except TypeError as e:
        assert str(e) == "Očekáváno JSON pole záznamů"


def test_cr_boundary_max_messages_truncation():
    lines = "".join(f"[2018-01-01 00:00:{i % 60:02d}] u{i} said: x\n" for i in range(5_001))
    assert len(parse_chatroulette(lines.encode())) == 5_000


def test_cr_corrupted_binary_and_empty(tmp_path: Path):
    f = tmp_path / "cr_chat.txt"
    f.write_bytes(b"\x00\x7f\xfe\x89PNG\r\n" * 48)
    assert extract_chatroulette_artifacts(f) == []
    empty = tmp_path / "empty.txt"
    empty.write_bytes(b"")
    assert extract_chatroulette_artifacts(empty) == []


def test_cr_tz_equivalence_epoch_iso_text():
    expected = datetime(2018, 5, 6, 9, 30, 0, tzinfo=UTC)
    epoch_msg = parse_chatroulette(json.dumps([{"partner": "p", "message": "m", "timestamp": 1525599000}]).encode())[0]
    text_msg = parse_chatroulette(b"[2018-05-06 09:30:00] p said: m\n")[0]
    assert epoch_msg.timestamp == expected
    assert text_msg.timestamp == expected


def test_cr_encoding_latin1_lossy_replace():
    data = b"me: pozdrav \xfa a \xe1 konec\n"
    msgs = parse_chatroulette(data)
    assert len(msgs) == 1
    assert "\ufffd" in msgs[0].message and "pozdrav" in msgs[0].message


def test_cr_locale_czech_diacritics_verbatim():
    data = "[2018-05-06 09:30:00] partner said: Dobré ráno, krásný den!\n".encode()
    msgs = parse_chatroulette(data)
    assert msgs[0].message == "Dobré ráno, krásný den!"


def test_cr_confidence_and_truncation():
    long_msg = "x" * 600
    payload = json.dumps([{"message": long_msg}, {"partner": "p", "message": "krátké"}]).encode()
    msgs = parse_chatroulette(payload)
    arts = build_chatroulette_artifacts(msgs)
    assert arts[0].confidence == 0.5
    assert arts[1].confidence == 0.7
    assert len(arts[0].details["text"]) == 500
    # title kontrakt: prefix + message[:80] (celý title se nekratí)
    title = arts[0].title
    assert title is not None and title.startswith("Chatroulette") and title.endswith("x" * 80)


# ── net_connections ──────────────────────────────────────────────────────────

NET_HEADER = b"Proto  Local Address  Foreign Address  State\n"


def test_net_positive_windows_and_ss():
    data = (
        NET_HEADER
        + b"TCP   0.0.0.0:445            192.168.1.10:51234     ESTABLISHED       123\n"
        + b'tcp   0      0 0.0.0.0:22    [::]:*                 LISTEN      users:(("sshd",pid=999,fd=3))\n'
    )
    conns = parse_netstat_text(data)
    assert len(conns) == 2
    win = conns[0]
    assert (win.proto, win.local_addr, win.local_port) == ("TCP", "0.0.0.0", 445)
    assert (win.remote_addr, win.remote_port, win.state, win.pid) == ("192.168.1.10", 51234, "ESTABLISHED", 123)
    ss = conns[1]
    assert ss.state == "LISTEN" and ss.pid == 999
    arts = build_netstat_artifacts(conns)
    assert all(a.artifact_type == "network_connection" for a in arts)
    assert arts[0].details["local"] == "0.0.0.0:445"
    assert arts[0].details["remote"] == "192.168.1.10:51234"
    assert arts[0].confidence == 0.85


def test_net_negative_missing_header_and_bad_lines():
    try:
        parse_netstat_text(b"random text bez hlavicky\nTCP a:b c:d\n")
        raise AssertionError("očekáváno ValueError")
    except ValueError as e:
        assert str(e) == "Hlavička netstat/ss tabulky nenalezena"
    # řádky bez dvou addr tokenu / s nepodporovaným protokolem = skip
    data = NET_HEADER + b"UDP 0.0.0.0:68\nICMP 1.1.1.1:1 2.2.2.2:2\nTCP x y z\n"
    assert parse_netstat_text(data) == []


def test_net_boundary_max_connections_truncation():
    lines = "".join(f"TCP 10.0.0.{i % 250}:80 10.0.1.1:{i} ESTABLISHED {i}\n" for i in range(5_001))
    assert len(parse_netstat_text(NET_HEADER + lines.encode())) == 5_000


def test_net_corrupted_binary_with_header_graceful(tmp_path: Path):
    f = tmp_path / "netstat.txt"
    payload = b"\x00\x01proto\n" + b"\x00\xff" * 80 + b"\nTCP 127.0.0.1:80 127.0.0.1:99 ESTABLISHED 42\n"
    f.write_bytes(payload)
    arts = extract_netstat_artifacts(f)
    assert len(arts) == 1
    assert arts[0].details["pid"] == 42
    empty = tmp_path / "empty.txt"
    empty.write_bytes(b"")
    assert extract_netstat_artifacts(empty) == []


def test_net_tz_snapshot_none_contract():
    data = NET_HEADER + b"TCP   0.0.0.0:135        [::]:*                 LISTENING       7\n"
    arts = build_netstat_artifacts(parse_netstat_text(data))
    assert arts and all(a.timestamp is None for a in arts)


def test_net_encoding_latin1_lossy_replace():
    # šumový řádek s osamělým neutf8 bajtem (0xE9) → decode replace, skip bez crashu
    data = NET_HEADER + b"UDP \xe9.0.0.0:67 *:* NONE\nTCP 1.2.3.4:53 5.6.7.8:1234 ESTABLISHED 7\n"
    conns = parse_netstat_text(data)
    assert len(conns) == 1
    assert (conns[0].local_addr, conns[0].state) == ("1.2.3.4", "ESTABLISHED")


def test_net_locale_diacritic_hostname_verbatim():
    data = NET_HEADER + "TCP   serverů.cz:443         1.2.3.4:55551        ESTABLISHED      876\n".encode()
    conns = parse_netstat_text(data)
    assert len(conns) == 1
    assert conns[0].local_addr == "serverů.cz"
    arts = build_netstat_artifacts(conns)
    assert arts[0].details["local"] == "serverů.cz:443"


def test_net_boundary_pid_and_state_edge_cases():
    # bez stavu → confidence 0.7, detail state/pid chybí; krátký řádek (3 tokeny)
    # nebere poslední token jako PID
    data = NET_HEADER + b"TCP 127.0.0.1:80 127.0.0.1:99\n"
    conns = parse_netstat_text(data)
    assert len(conns) == 1
    assert conns[0].state == "" and conns[0].pid is None
    arts = build_netstat_artifacts(conns)
    assert arts[0].confidence == 0.7
    assert "state" not in arts[0].details and "pid" not in arts[0].details


# ── limewire_p2p ─────────────────────────────────────────────────────────────


def test_lw_positive_json_and_pipe():
    payload = json.dumps(
        [
            {
                "filename": "song.mp3",
                "size": 123456,
                "path": "/shared/music",
                "hash": "abc123",
                "date_modified": "2019-03-04 12:00:01",
                "downloaded_by": "user_a",
            }
        ]
    ).encode()
    recs = parse_shared_files(payload)
    assert len(recs) == 1
    r = recs[0]
    assert (r.filename, r.size, r.hash) == ("song.mp3", 123456, "abc123")
    assert r.transfer == {"downloaded_by": "user_a"}

    pipe = b"album.ogg|999|/share/album|def456\n"
    recs2 = parse_shared_files(pipe)
    assert len(recs2) == 1 and recs2[0].filename == "album.ogg"


def test_lw_negative_invalid_json_and_family_miss(tmp_path: Path):
    try:
        parse_shared_files(b'[{"filename": ')
        raise AssertionError("očekáváno ValueError")
    except ValueError as e:
        assert str(e).startswith("Neplatné JSON")
    try:
        parse_shared_files(b'{"filename": "a"}')
        raise AssertionError("očekáváno TypeError")
    except TypeError as e:
        assert str(e) == "Očekáváno JSON pole záznamů"
    # extract bez detekované rodiny (námě ani head neobsahuje marker) → []
    f = tmp_path / "notes.txt"
    f.write_bytes(b"a.mp3|1|/share|\n")
    assert extract_shared_files_artifacts(f) == []


def test_lw_boundary_max_files_truncation():
    lines = "".join(f"f{i}.mp3|1|/s|h\n" for i in range(20_001))
    assert len(parse_shared_files(lines.encode())) == 20_000
    payload = json.dumps([{"filename": f"f{i}"} for i in range(20_001)]).encode()
    assert len(parse_shared_files(payload)) == 20_000


def test_lw_corrupted_binary_and_empty(tmp_path: Path):
    f = tmp_path / "LimeWire.dat"
    f.write_bytes(b"\x00\x01\x02\xde\xad\xbe\xef" * 50)
    assert extract_shared_files_artifacts(f) == []
    empty = tmp_path / "empty.dat"
    empty.write_bytes(b"")
    assert extract_shared_files_artifacts(empty) == []


def test_lw_tz_naive_to_utc_and_accessed_fallback():
    pipe_mod = b"a.mp3|1|/s|h|2019-03-04 12:00:01\n"
    pipe_iso = b"a.mp3|1|/s|h|2019-03-04T12:00:01\n"
    r_mod = parse_shared_files(pipe_mod)[0]
    r_iso = parse_shared_files(pipe_iso)[0]
    assert r_mod.date_modified == datetime(2019, 3, 4, 12, 0, 1, tzinfo=UTC)
    assert r_mod.date_modified == r_iso.date_modified
    # bez modified → timestamp artifactu z date_accessed (fallback)
    pipe_acc = b"a.mp3|1|/s|h||2019-03-05 08:00:00\n"
    arts = build_shared_file_artifacts(parse_shared_files(pipe_acc), "limewire_shared_file")
    assert len(arts) == 1
    assert arts[0].timestamp == datetime(2019, 3, 5, 8, 0, 0, tzinfo=UTC)


def test_lw_encoding_latin1_lossy_replace():
    # é = 0xE9 v latin-1 → osamelý neutf8 bajt → U+FFFD (lossy fallback)
    recs = parse_shared_files(b"Caf\xe9.mp3|12|/share|\n")
    assert len(recs) == 1
    assert "\ufffd" in recs[0].filename and recs[0].filename.endswith(".mp3")


def test_lw_locale_czech_diacritics_verbatim():
    pipe = "písně/žádný.mp3|1234|C:\\share\\písně|abc123\n".encode()
    recs = parse_shared_files(pipe)
    assert len(recs) == 1
    assert recs[0].filename == "písně/žádný.mp3"
    assert recs[0].path == "C:\\share\\písně"
    arts = build_shared_file_artifacts(recs, "limewire_shared_file")
    assert arts[0].details["filename"] == "písně/žádný.mp3"
    assert arts[0].title is not None and "písně/žádný.mp3" in arts[0].title


def test_lw_family_priority_and_detection():
    # Limerunner má prioritu před Limewire (specifický marker první)
    assert detect_family(name="limerunner_limewire.dat") == "limerunner_shared_file"
    assert detect_family(name="limewire_export.txt") == "limewire_shared_file"
    assert detect_family(name="Luckywire.db") == "luckywire_shared_file"
    # head-based detekce vyžaduje marker + filename/pipe signál
    assert detect_family(head=b"LimeWire shared files\na.mp3|1|/|\n") == "limewire_shared_file"
    assert is_limewire_family_file(name="x.xml", head=b"<root/>") is False


# ── wifi_wlan ────────────────────────────────────────────────────────────────

WLAN_FULL_XML = (
    b'<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v3">'
    b"<name>Office</name>"
    b"<SSIDConfig><SSID><name>OfficeNet</name></SSID></SSIDConfig>"
    b"<smcSecurity><authEncryption>"
    b"<authentication>WPA2</authentication><encryption>AES</encryption>"
    b"</authEncryption></smcSecurity>"
    b"<sharedKey><keyType>passphrase</keyType>"
    b"<keyPassphrase>heslo12345</keyPassphrase></sharedKey>"
    b'<stationList itemID="0">'
    b"<macAddress>aa:bb:cc:dd:ee:ff</macAddress>"
    b"<macAddress>AA:BB:CC:DD:EE:FF</macAddress>"
    b"<macAddress>not-a-mac</macAddress>"
    b"</stationList>"
    b"</WLANProfile>"
)


def test_wifi_positive_full_profile():
    profs = parse_wlan_profile_xml(WLAN_FULL_XML)
    assert len(profs) == 1
    p = profs[0]
    assert (p.name, p.ssid) == ("Office", "OfficeNet")
    assert p.encryption == "wpa2 aes"
    assert p.has_key is True and p.key_length == 10
    assert p.mac_addresses == ["AA:BB:CC:DD:EE:FF"]  # upper + dedup, neplatná vynechána
    arts = build_wifi_artifacts(profs)
    assert len(arts) == 1
    a = arts[0]
    assert a.artifact_type == "wifi_profile" and a.confidence == 0.85
    assert a.details["ssid"] == "OfficeNet"
    assert a.details["known_ap_mac"] == ["AA:BB:CC:DD:EE:FF"]


def test_wifi_positive_wrapper_and_ssid_text_fallback():
    wrap = (
        "<root><other/><WLANProfile>"
        "<SSIDConfig><SSID>Kavárna</SSID></SSIDConfig>"
        "</WLANProfile></root>"
    ).encode()
    profs = parse_wlan_profile_xml(wrap)
    assert len(profs) == 1  # cizí element <other/> = skip
    assert profs[0].ssid == "Kavárna"  # fallback na textový obsah <SSID>
    assert build_wifi_artifacts(profs)[0].confidence == 0.85


def test_wifi_negative_invalid_xml_and_empty_profile(tmp_path: Path):
    try:
        parse_wlan_profile_xml(b"<WLANProfile><broken>")
        raise AssertionError("očekáváno ValueError")
    except ValueError as e:
        assert str(e).startswith("Neplatné WLAN profile XML")
    # profil bez SSID i name = skip (None)
    assert parse_wlan_profile_xml(b"<WLANProfile></WLANProfile>") == []
    f = tmp_path / "profile.xml"
    f.write_bytes(b"<WLANProfile><broken>")
    assert extract_wifi_artifacts(f) == []


def test_wifi_boundary_max_profiles_truncation():
    body = "".join(
        f'<WLANProfile><name>p{i}</name><SSIDConfig><SSID><name>s{i}</name></SSID></SSIDConfig></WLANProfile>'
        for i in range(51)
    )
    assert len(parse_wlan_profile_xml(f"<root>{body}</root>".encode())) == 50


def test_wifi_corrupted_binary_and_empty(tmp_path: Path):
    f = tmp_path / "wifi.xml"
    f.write_bytes(b"\x00\x01\xfe\xff" * 64)
    assert extract_wifi_artifacts(f) == []
    empty = tmp_path / "empty.xml"
    empty.write_bytes(b"")
    assert extract_wifi_artifacts(empty) == []


def test_wifi_tz_snapshot_none_contract():
    arts = build_wifi_artifacts(parse_wlan_profile_xml(WLAN_FULL_XML))
    assert arts and all(a.timestamp is None for a in arts)


def test_wifi_encoding_iso88591_declaration_roundtrip():
    # deklarovaný XML charset iso-8859-1 — ET ho respektuje, znaky bez ztráty
    xml_l1 = (
        '<?xml version="1.0" encoding="iso-8859-1"?><WLANProfile>'
        "<name>Káva</name>"
        "<SSIDConfig><SSID><name>Café Kávy á ú</name></SSID></SSIDConfig>"
        "</WLANProfile>"
    ).encode("latin-1")
    p = parse_wlan_profile_xml(xml_l1)[0]
    assert p.name == "Káva"
    assert p.ssid == "Café Kávy á ú"


def test_wifi_locale_czech_diacritics_verbatim():
    xml = (
        "<WLANProfile><name>Síť kavárny</name>"
        "<SSIDConfig><SSID><name>Kavárna šéfa – řetězec</name></SSID></SSIDConfig>"
        "</WLANProfile>"
    ).encode()
    p = parse_wlan_profile_xml(xml)[0]
    assert p.name == "Síť kavárny"
    assert p.ssid == "Kavárna šéfa – řetězec"
    arts = build_wifi_artifacts([p])
    assert arts[0].title is not None and "Kavárna šéfa – řetězec" in arts[0].title
