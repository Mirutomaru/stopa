"""P1-1 quality framework — vlna 16: **locale sweep** (27 parserů, +27 párů).

Kategorie ``locale`` = česká diakritika prochází vstupem → záznamem/artefaktem
**verbatim**, bez transliterace, normalizace ani truncationu. Každý parser má
samostatný test s reálným obsahem v doménovém kontextu (jména procesů a modulů,
předměty mail, nadpisy stránek, bucket názvy, kontaktní jména apod.).

Kontrakty empiricky ověřeny probe skriptem před psaním testů: 27/27 parserů
vrací diakritiku verbatim v poli záznamu. Poznámky ze source analýzy:
- ``amazon_ec2_s3`` — EC2 record nedrží tagy (jen instance_id/state/IP),
  locale se dokládá přes S3 bucket/key (sdílený JSON loader).
- ``skype_warrant`` — text zprávy → title s truncationem na 60 znaků; test
  používá krátkou zprávu, aby verbatim porovnání nebylo oříznuto.
- ``sharepoint_wr`` — auto-detekce sekcí: dokumenty (name) i stránky
  (title→name + content), oba tvary pokryty v jednom testu.
"""

from __future__ import annotations

import json

from stopa.artifacts.amazon_cloudtrail import parse_cloudtrail
from stopa.artifacts.amazon_ec2_s3 import parse_s3_objects
from stopa.artifacts.facebook_wr import parse_facebook_friends
from stopa.artifacts.google_chrome_autofill import parse_chrome_autofill
from stopa.artifacts.google_chrome_bookmarks import parse_chrome_bookmarks
from stopa.artifacts.google_chrome_history_wr import parse_chrome_history_wr
from stopa.artifacts.google_contacts_wr import parse_contacts_wr
from stopa.artifacts.instagram_account import parse_instagram_account
from stopa.artifacts.instagram_messages import parse_instagram_messages
from stopa.artifacts.instagram_posts import parse_instagram_posts
from stopa.artifacts.mem_handles import parse_mem_handles
from stopa.artifacts.mem_hooks import parse_mem_hooks
from stopa.artifacts.mem_modules import parse_mem_modules
from stopa.artifacts.mem_network import parse_mem_connections
from stopa.artifacts.mem_processes import parse_mem_processes
from stopa.artifacts.mem_scan import (
    parse_cmdscan_text,
    parse_filescan_text,
)
from stopa.artifacts.ms_contacts import parse_ms_contacts
from stopa.artifacts.ms_mail_pst import parse_ms_mail_pst
from stopa.artifacts.ms_outlook_calendar import parse_outlook_calendar
from stopa.artifacts.ms_teams_conversations import parse_teams_conversations
from stopa.artifacts.ms_teams_teams import build_team_artifacts
from stopa.artifacts.sharepoint_wr import parse_sharepoint
from stopa.artifacts.skype_warrant_return import parse_skype_warrant
from stopa.artifacts.snapchat_wr import parse_snapchat_contacts
from stopa.artifacts.twitter_messages import parse_twitter_messages
from stopa.artifacts.twitter_posts import parse_twitter_posts
from stopa.artifacts.twitter_users import parse_twitter_users

# ── memory forensics (vlna 8) ────────────────────────────────────────────────

def _j(obj: object) -> bytes:
    return json.dumps(obj).encode()


def test_locale_mem_handles():
    """Diakritika v názvu handle verbatim."""
    # quality: locale
    recs = parse_mem_handles(_j([{"handleValue": "0x14", "name": "\\Device\\Soubor-dohledná"}]))
    assert recs[0].name == r"\Device\Soubor-dohledná"


def test_locale_mem_hooks():
    """Diakritika v názvu modulu hooku verbatim."""
    # quality: locale
    recs = parse_mem_hooks(_j([{"apiFunction": "NtReadFile", "module": "modul-žluťoučký.dll"}]))
    assert recs[0].module == "modul-žluťoučký.dll"


def test_locale_mem_modules():
    """Diakritika v názvu modulu verbatim."""
    # quality: locale
    recs = parse_mem_modules(_j([{"name": "modul-účetnictví.dll"}]))
    assert recs[0].name == "modul-účetnictví.dll"


def test_locale_mem_network():
    """Diakritika v názvu procesu na spojení verbatim."""
    # quality: locale
    net = parse_mem_connections(
        _j([{"localAddress": "1.2.3.4:80", "remoteAddress": "5.6.7.8:1234",
            "processName": "sítě-sdílení.exe"}])
    )
    assert net[0].process_name == "sítě-sdílení.exe"


def test_locale_mem_processes():
    """Diakritika v uživateli a cmdline procesu verbatim."""
    # quality: locale
    recs = parse_mem_processes(
        _j([{"name": "proc.exe", "pid": 7, "user": "Uživatel\\Domény",
            "cmdline": r"C:\Plocha\překlad.docx --řešit diakritiku"}])
    )
    assert recs[0].user == "Uživatel\\Domény"
    assert recs[0].cmdline == r"C:\Plocha\překlad.docx --řešit diakritiku"


def test_locale_mem_scan():
    """Diakritika v cestách filescan i cmdline cmdscan verbatim."""
    # quality: locale
    fs = parse_filescan_text(
        ("InMemory File Name\n/účet/smlouva-česká.txt").encode()
    )
    assert [e.path for e in fs] == ["/účet/smlouva-česká.txt"]

    cmd = parse_cmdscan_text(
        ("Offset(V)\tProcess Name\tCommandLine\n"
         "0x1c8a2b4e000 svchost.exe C:\\Windows\\sítě\\služba.exe -k sítě").encode()
    )
    assert cmd[0].command_line == r"C:\Windows\sítě\služba.exe -k sítě"


# ── Microsoft exporty (vlna 12) ──────────────────────────────────────────────

def test_locale_ms_contacts():
    """Diakritika v displayName kontaktu verbatim."""
    # quality: locale
    recs = parse_ms_contacts(_j([{"displayName": "Příliš žluťoučký Kůň",
                                  "emailAddresses": ["a@x.cz"]}]))
    dn = recs[0].display_name
    assert dn is not None and dn == "Příliš žluťoučký Kůň"


def test_locale_ms_mail_pst():
    """Diakritika v předmětu e-mailu verbatim."""
    # quality: locale
    recs = parse_ms_mail_pst(_j([{"subject": "Připomenutí schůzky",
                                  "dateReceived": "2026-01-05T10:00:00Z"}]))
    subj = recs[0].subject
    assert subj is not None and subj == "Připomenutí schůzky"


def test_locale_ms_outlook_calendar():
    """Diakritika v předmětu a místě kalendářního události verbatim."""
    # quality: locale
    recs = parse_outlook_calendar(
        _j([{"subject": "Schůzka na radnici", "location": "Městská knihovna, čtenárna",
             "startDateTime": "2026-01-05T10:00:00Z"}])
    )
    subj = recs[0].subject
    loc = recs[0].location
    assert subj is not None and subj == "Schůzka na radnici"
    assert loc is not None and loc == "Městská knihovna, čtenárna"


def test_locale_ms_teams_conversations():
    """Diakritika v těle Teams zprávy verbatim."""
    # quality: locale
    recs = parse_teams_conversations(
        _j([{"from": "J. Novák", "body": "Ahoj, jak se máš? Schůzka je přesunutá.",
             "messageId": "m1"}])
    )
    text = recs[0].text
    assert text is not None and text == "Ahoj, jak se máš? Schůzka je přesunutá."


def test_locale_ms_teams_teams():
    """Diakritika v názvu týmu (title + details) a jménech členů verbatim."""
    # quality: locale
    arts = build_team_artifacts(
        [{"displayName": "Tým překlady a lokalizace", "ownerId": "own-1",
          "members": ["Jan Novák", "Petr Dvořák"]}]
    )
    assert len(arts) == 1
    art = arts[0]
    title = art.title
    assert title is not None and title.startswith("Microsoft Teams: Tým překlady a lokalizace")
    assert art.details.get("team_name") == "Tým překlady a lokalizace"
    assert art.details.get("members") == ["Jan Novák", "Petr Dvořák"]


# ── Chrome / Skype / kontakty warrant (vlna 7) ───────────────────────────────

def test_locale_chrome_autofill():
    """Diakritika v jméně a adrese autofill záznamu verbatim."""
    # quality: locale
    recs = parse_chrome_autofill(_j([{"name": "Petr Dvořák", "city": "Hlavní 547"}]))
    assert recs[0].name == "Petr Dvořák"
    assert recs[0].city == "Hlavní 547"


def test_locale_chrome_bookmarks():
    """Diakritika v názvu URL záložky verbatim.

    Parser emituje jen URL záznamy (složky se neemitují jako samostatné
    recordy — doloženo existujícím kontraktem vlny 7).
    """
    # quality: locale
    bm = json.dumps({
        "roots": {"bookmark_bar": {
            "children": [{
                "date_added": "13000000000000000", "id": "1",
                "name": "Žluťoučký kůň", "type": "url", "url": "https://k.cz",
            }],
            "date_added": "13000000000000000", "id": "0",
            "name": "Složka s diakritikou", "type": "folder",
        }}
    }).encode()
    recs = parse_chrome_bookmarks(bm)
    assert len(recs) == 1
    assert recs[0].name == "Žluťoučký kůň"


def test_locale_chrome_history_wr():
    """Diakritika v titulu historie verbatim."""
    # quality: locale
    recs = parse_chrome_history_wr(_j([{"url": "https://x.cz", "title": "Příliš žluťoučký kůň"}]))
    assert recs[0].title == "Příliš žluťoučký kůň"


def test_locale_contacts_wr():
    """Diakritika v zobrazeném jménu kontaktu verbatim."""
    # quality: locale
    recs = parse_contacts_wr(_j([{"name": ["Míra Šmída"], "givenName": ["Míra"],
                                  "familyName": ["Šmíd"]}]))
    assert recs[0].display_name == "Míra Šmída"


def test_locale_skype_warrant():
    """Diakritika v textu zprávy (→ title) verbatim, bez truncationu."""
    # quality: locale
    recs = parse_skype_warrant(
        _j([{"conversationId": "c", "from": "8:a", "to": "8:b",
             "message": "Ahoj, jak se máš?", "composetime": "2016-01-01T00:00:00Z"}])
    )
    assert recs[0].sub_type == "chat"
    assert recs[0].title == "Ahoj, jak se máš?"


# ── Instagram / Snapchat (vlna 7/10) ─────────────────────────────────────────

def test_locale_instagram_account():
    """Diakritika v full_name followerů verbatim."""
    # quality: locale
    _, users = parse_instagram_account(_j({
        "followers": [{"username": "f1", "full_name": "Karel Dvořák"}],
    }))
    assert users[0].full_name == "Karel Dvořák"


def test_locale_instagram_messages():
    """Diakritika v těle Direct zprávy verbatim."""
    # quality: locale
    recs = parse_instagram_messages(_j([{"from": "a", "body": "Víkend u jezera s přáteli"}]))
    assert recs[0].text == "Víkend u jezera s přáteli"


def test_locale_instagram_posts():
    """Diakritika v caption příspěvku verbatim."""
    # quality: locale
    posts, _ = parse_instagram_posts(_j([{"id": "p", "caption": "Příliš žluťoučký kůň"}]))
    assert posts[0].caption == "Příliš žluťoučký kůň"


def test_locale_snapchat_wr():
    """Diakritika v full_name kamaráda verbatim."""
    # quality: locale
    recs = parse_snapchat_contacts(_j({"friends": [
        {"username": "f1", "full_name": "Tomáš Hájek"}]}))
    assert recs[0].full_name == "Tomáš Hájek"


# ── Twitter / Facebook (vlna 7/11) ───────────────────────────────────────────

def test_locale_twitter_messages():
    """Diakritika v textu DM zprávy verbatim."""
    # quality: locale
    recs = parse_twitter_messages(_j([{"sender": "a", "recipient": "b",
                                       "text": "Ahoj, jak se máš?"}]))
    assert recs[0].text == "Ahoj, jak se máš?"


def test_locale_twitter_posts():
    """Diakritika v textu tweetu verbatim."""
    # quality: locale
    recs = parse_twitter_posts(_j([{"author": "uživatel", "text": "Příliš žluťoučký kůň"}]))
    assert recs[0].text == "Příliš žluťoučký kůň"


def test_locale_twitter_users():
    """Diakritika v plném jménu uživatele verbatim."""
    # quality: locale
    recs = parse_twitter_users(_j([{"screen_name": "u", "name": "Jan Novák"}]))
    assert recs[0].full_name == "Jan Novák"


def test_locale_facebook_wr():
    """Diakritika v jméně přítele verbatim."""
    # quality: locale
    recs = parse_facebook_friends(_j({"friends": [
        {"name": "Martin Čermák", "username": "mc"}]}))
    assert recs[0].full_name == "Martin Čermák"


# ── Amazon cloud exporty (vlna 12) ───────────────────────────────────────────

def test_locale_amazon_cloudtrail():
    """Diakritika v názvu události CloudTrail verbatim."""
    # quality: locale
    recs = parse_cloudtrail(_j([{"eventName": "Lookup-dohledná-smlouva",
                                 "userIdentity": {"type": "AssumedRole"}}]))
    en = recs[0].event_name
    assert en is not None and en == "Lookup-dohledná-smlouva"


def test_locale_amazon_ec2_s3():
    """Diakritika v názvu S3 bucketu a klíči objektu verbatim.

    EC2 record nedrží tagy (jen instance_id/state/IP) — locale se dokládá
    přes S3 vstupní cestu, sdílí s EC2 stejný JSON loader.
    """
    # quality: locale
    recs = parse_s3_objects(_j({"buckets": [
        {"name": "b-česká",
         "objects": [{"key": "smlouvy/příliš-žluťoučký.pdf"}]}]}))
    assert recs[0].bucket == "b-česká"
    assert recs[0].key == "smlouvy/příliš-žluťoučký.pdf"


# ── SharePoint (vlna 12) ─────────────────────────────────────────────────────

def test_locale_sharepoint_wr():
    """Diakritika v názvu dokumentu i obsahu stránky verbatim."""
    # quality: locale
    docs = parse_sharepoint(_j([{"name": "smlouva-Příliš žluťoučký kůň.pdf",
                                 "size": 1024,
                                 "url": "https://corp.sharepoint.com/x"}]))
    assert len(docs) == 1
    dn = docs[0].name
    assert dn is not None and dn == "smlouva-Příliš žluťoučký kůň.pdf"

    pages = parse_sharepoint(_j({"pages": [
        {"title": "Domů", "content": "Vítejte, milí čtenáři!",
         "url": "https://corp.sharepoint.com/sites/x"}]}))
    assert len(pages) == 1
    pn = pages[0].name
    pc = pages[0].content
    assert pn is not None and pn == "Domů"
    assert pc is not None and pc == "Vítejte, milí čtenáři!"
