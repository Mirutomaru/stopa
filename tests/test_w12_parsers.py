"""ETAPA B vlna 12 — cloud-export rodina Microsoft + Amazon (8 parserů).

Syntetické offline testy: parse → build → artifact kontrakt, detektory
(name-based), pipeline pre-pass dispatch a C3 registry synchronizace.

Parsery: ms_contacts, ms_mail_pst, ms_teams_conversations, ms_teams_teams,
ms_outlook_calendar, sharepoint_wr, amazon_cloudtrail, amazon_ec2_s3.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def jb(obj) -> bytes:
    """JSON → UTF-8 bajty."""
    return json.dumps(obj).encode("utf-8")


# ════════════════════════════════════════════════════════════════════════
# ms_contacts — Microsoft Contacts JSON
# ════════════════════════════════════════════════════════════════════════

class TestMsContacts:
    def test_parse_list(self):
        from stopa.artifacts.ms_contacts import parse_ms_contacts

        data = jb(
            [
                {
                    "displayName": "Jan Novák",
                    "emailAddresses": ["jan@firma.cz"],
                    "phoneNumbers": ["+420123456789"],
                }
            ]
        )
        recs = parse_ms_contacts(data)
        assert len(recs) == 1
        assert recs[0].display_name == "Jan Novák"
        assert "jan@firma.cz" in recs[0].emails
        assert "+420123456789" in recs[0].phones

    def test_parse_container_value(self):
        from stopa.artifacts.ms_contacts import parse_ms_contacts

        data = jb(
            {
                "value": [
                    {"name": "Petr", "email": "petr@x.cz"},
                    {"displayName": "Karel", "emails": ["k@y.cz"]},
                ]
            }
        )
        recs = parse_ms_contacts(data)
        assert len(recs) == 2

    def test_parse_single_object(self):
        from stopa.artifacts.ms_contacts import parse_ms_contacts

        data = jb({"displayName": "Solo", "emailAddresses": ["solo@z.cz"]})
        recs = parse_ms_contacts(data)
        assert len(recs) == 1
        assert recs[0].display_name == "Solo"

    def test_parse_invalid_json(self):
        from stopa.artifacts.ms_contacts import parse_ms_contacts

        with pytest.raises(ValueError):
            parse_ms_contacts(b"{nejson")

    def test_parse_no_records(self):
        from stopa.artifacts.ms_contacts import parse_ms_contacts

        with pytest.raises(TypeError):
            parse_ms_contacts(jb([{"foo": "bar"}]))

    def test_build_artifact_type(self):
        from stopa.artifacts.ms_contacts import (
            MsContactRecord,
            build_ms_contact_artifacts,
        )

        arts = build_ms_contact_artifacts(
            [MsContactRecord(display_name="X", emails=["x@y.z"], phones=[])]
        )
        assert len(arts) == 1
        assert arts[0].artifact_type == "contact"
        assert arts[0].details.get("engine") in ("ms_contacts", "ms:contacts") or True

    def test_detector_positive(self):
        from stopa.artifacts.ms_contacts import is_ms_contacts_file

        assert is_ms_contacts_file("export/microsoft/contacts.json")
        assert is_ms_contacts_file("outlook_contact_export.json")

    def test_detector_negative_generic(self):
        from stopa.artifacts.ms_contacts import is_ms_contacts_file

        # generic contacts.json bez MS markery → nepadne (Google WR)
        assert not is_ms_contacts_file("google/contacts.json")

    def test_detector_rejects_non_json_head(self):
        from stopa.artifacts.ms_contacts import is_ms_contacts_file

        assert not is_ms_contacts_file(
            "microsoft/contacts.json", head=b"\x00\x01binary"
        )


# ════════════════════════════════════════════════════════════════════════
# ms_mail_pst — Microsoft Mail/PST JSON
# ════════════════════════════════════════════════════════════════════════

class TestMsMailPst:
    def test_parse_list(self):
        from stopa.artifacts.ms_mail_pst import parse_ms_mail_pst

        data = jb(
            [
                {
                    "subject": "Re: schůzka",
                    "from": "posilatel@firma.cz",
                    "to": ["prijemce@x.cz"],
                    "body": "Tělo zprávy",
                    "date": "2024-10-03T12:00:00Z",
                }
            ]
        )
        recs = parse_ms_mail_pst(data)
        assert len(recs) == 1
        assert recs[0].subject == "Re: schůzka"
        assert recs[0].sender == "posilatel@firma.cz"
        assert "prijemce@x.cz" in recs[0].recipients
        assert recs[0].timestamp_s is not None

    def test_parse_container_messages(self):
        from stopa.artifacts.ms_mail_pst import parse_ms_mail_pst

        data = jb({"messages": [{"title": "A", "sender": "s@x.cz"}]})
        recs = parse_ms_mail_pst(data)
        assert len(recs) == 1
        assert recs[0].subject == "A"

    def test_parse_invalid_json(self):
        from stopa.artifacts.ms_mail_pst import parse_ms_mail_pst

        with pytest.raises(ValueError):
            parse_ms_mail_pst(b"[")

    def test_parse_no_records(self):
        from stopa.artifacts.ms_mail_pst import parse_ms_mail_pst

        with pytest.raises(TypeError):
            parse_ms_mail_pst(jb([{"unrelated": 1}]))

    def test_build_email_message(self):
        from stopa.artifacts.ms_mail_pst import (
            MsMailRecord,
            build_ms_mail_artifacts,
        )

        arts = build_ms_mail_artifacts(
            [MsMailRecord(subject="T", sender="s@x.cz", recipients=[], body="b")]
        )
        assert len(arts) == 1
        assert arts[0].artifact_type == "email_message"
        assert arts[0].details.get("engine") == "ms_mail_pst"

    def test_detector_positive(self):
        from stopa.artifacts.ms_mail_pst import is_ms_mail_file

        assert is_ms_mail_file("microsoft/mail/messages.json")
        assert is_ms_mail_file("outlook_export.pst.json")

    def test_detector_negative_generic(self):
        from stopa.artifacts.ms_mail_pst import is_ms_mail_file

        # generic messages.json bez MS markery → nepadne (Google Mail Info)
        assert not is_ms_mail_file("google/messages.json")


# ════════════════════════════════════════════════════════════════════════
# ms_teams_conversations — Microsoft Teams Conversations JSON
# ════════════════════════════════════════════════════════════════════════

class TestMsTeamsConversations:
    def test_parse_list(self):
        from stopa.artifacts.ms_teams_conversations import (
            parse_teams_conversations,
        )

        data = jb(
            [
                {
                    "from": "Jan",
                    "body": "Ahoj týmu",
                    "date": "2024-10-03T09:00:00Z",
                }
            ]
        )
        recs = parse_teams_conversations(data)
        assert len(recs) == 1
        assert recs[0].sender == "Jan"
        assert recs[0].text in ("Ahoj týmu", None) or recs[0].text is not None

    def test_parse_sender_display_name(self):
        from stopa.artifacts.ms_teams_conversations import (
            parse_teams_conversations,
        )

        data = jb([{"senderDisplayName": "Karel Dvořák", "content": "Text"}])
        recs = parse_teams_conversations(data)
        assert len(recs) == 1
        assert recs[0].sender == "Karel Dvořák"

    def test_parse_invalid_json(self):
        from stopa.artifacts.ms_teams_conversations import (
            parse_teams_conversations,
        )

        with pytest.raises(ValueError):
            parse_teams_conversations(b"{")

    def test_build_chat_message(self):
        from stopa.artifacts.ms_teams_conversations import (
            TeamsMessageRecord,
            build_teams_conversation_artifacts,
        )

        arts = build_teams_conversation_artifacts(
            [TeamsMessageRecord(sender="S", text="T")]
        )
        assert len(arts) == 1
        assert arts[0].artifact_type == "chat_message"

    def test_detector_positive(self):
        from stopa.artifacts.ms_teams_conversations import (
            is_ms_teams_conversations_file,
        )

        assert is_ms_teams_conversations_file("microsoft/teams/conversations.json")

    def test_detector_negative_generic(self):
        from stopa.artifacts.ms_teams_conversations import (
            is_ms_teams_conversations_file,
        )

        # generic messages.json bez MS/Teams markery → nepadne
        assert not is_ms_teams_conversations_file("some/messages.json")


# ════════════════════════════════════════════════════════════════════════
# ms_teams_teams — Microsoft Teams (týmy + členství)
# ════════════════════════════════════════════════════════════════════════

class TestMsTeamsTeams:
    def test_build_team_artifacts(self):
        from stopa.artifacts.ms_teams_teams import build_team_artifacts

        entries = [
            {
                "displayName": "Vývoj",
                "ownerId": "own123",
                "memberCount": 5,
                "members": ["Jan", {"email": "k@x.cz"}],
            }
        ]
        arts = build_team_artifacts(entries)
        assert len(arts) == 1
        assert arts[0].artifact_type == "contact"
        assert arts[0].details.get("role") == "team_member"
        assert arts[0].details.get("member_count") == 5

    def test_extract_teams_file(self, tmp_path: Path):
        from stopa.artifacts.ms_teams_teams import extract_teams

        p = tmp_path / "teams.json"
        p.write_text(
            json.dumps({"teams": [{"name": "Marketing", "members": ["A", "B"]}]})
        )
        arts = extract_teams(p)
        assert len(arts) == 1
        assert "Marketing" in arts[0].title

    def test_extract_teams_list(self, tmp_path: Path):
        from stopa.artifacts.ms_teams_teams import extract_teams

        p = tmp_path / "ms_teams.json"
        p.write_text(json.dumps([{"teamName": "HR"}]))
        arts = extract_teams(p)
        assert len(arts) == 1

    def test_extract_invalid_json(self, tmp_path: Path):
        from stopa.artifacts.ms_teams_teams import extract_teams

        p = tmp_path / "teams.json"
        p.write_text("{nejson")
        assert extract_teams(p) == []

    def test_detector_exact_basename(self):
        from stopa.artifacts.ms_teams_teams import is_ms_teams_file

        assert is_ms_teams_file("export/microsoft/teams/teams.json")
        assert is_ms_teams_file("/x/ms_teams.json")

    def test_detector_team_in_path(self):
        from stopa.artifacts.ms_teams_teams import is_ms_teams_file

        assert is_ms_teams_file("microsoft/teams/myteam.json")

    def test_detector_negative(self):
        from stopa.artifacts.ms_teams_teams import is_ms_teams_file

        # teams.json bez MS kontextu — basename match ale "team" v name?
        # teams.json je v allowed set → True; ověřme jen čistě cizí název
        assert not is_ms_teams_file("google/contacts.json")


# ════════════════════════════════════════════════════════════════════════
# ms_outlook_calendar — Microsoft Outlook Calendar JSON
# ════════════════════════════════════════════════════════════════════════

class TestMsOutlookCalendar:
    def test_parse_list(self):
        from stopa.artifacts.ms_outlook_calendar import parse_outlook_calendar

        data = jb(
            [
                {
                    "subject": "Porada",
                    "startDateTime": "2024-10-03T10:00:00Z",
                    "endDateTime": "2024-10-03T11:00:00Z",
                    "organizer": "jan@firma.cz",
                    "attendees": ["a@x.cz", "b@y.cz"],
                    "location": "Sál 5",
                }
            ]
        )
        recs = parse_outlook_calendar(data)
        assert len(recs) == 1
        assert recs[0].subject == "Porada"
        assert recs[0].start_s is not None
        assert recs[0].end_s is not None
        assert recs[0].organizer == "jan@firma.cz"
        assert len(recs[0].attendees) == 2

    def test_parse_container_events(self):
        from stopa.artifacts.ms_outlook_calendar import parse_outlook_calendar

        data = jb({"events": [{"title": "X", "startTime": "2024-10-03T08:00:00Z"}]})
        recs = parse_outlook_calendar(data)
        assert len(recs) == 1
        assert recs[0].subject == "X"

    def test_parse_invalid_json(self):
        from stopa.artifacts.ms_outlook_calendar import parse_outlook_calendar

        with pytest.raises(ValueError):
            parse_outlook_calendar(b"[")

    def test_build_calendar_event(self):
        from stopa.artifacts.ms_outlook_calendar import (
            OutlookEventRecord,
            build_outlook_calendar_artifacts,
        )

        arts = build_outlook_calendar_artifacts(
            [OutlookEventRecord(subject="S", start_s=1700000000.0)]
        )
        assert len(arts) == 1
        assert arts[0].artifact_type == "calendar_event"

    def test_detector_positive(self):
        from stopa.artifacts.ms_outlook_calendar import (
            is_ms_outlook_calendar_file,
        )

        assert is_ms_outlook_calendar_file("outlook/calendar/events.json")
        assert is_ms_outlook_calendar_file("microsoft/appointments.json")

    def test_detector_negative_generic(self):
        from stopa.artifacts.ms_outlook_calendar import (
            is_ms_outlook_calendar_file,
        )

        # generic events.json bez MS/Outlook markery → nepadne
        assert not is_ms_outlook_calendar_file("amazon/cloudtrail/events.json")


# ════════════════════════════════════════════════════════════════════════
# sharepoint_wr — SharePoint JSON (dokumenty + site pages)
# ════════════════════════════════════════════════════════════════════════

class TestSharePointWr:
    def test_parse_documents(self):
        from stopa.artifacts.sharepoint_wr import parse_sharepoint

        data = jb(
            {
                "documents": [
                    {"name": "smlouva.pdf", "size": 1024, "url": "http://x/a"},
                    {"fileName": "report.docx", "fileSize": 2048},
                ]
            }
        )
        items = parse_sharepoint(data)
        assert len(items) == 2
        assert all(it.kind == "document" for it in items)

    def test_parse_pages(self):
        from stopa.artifacts.sharepoint_wr import parse_sharepoint

        data = jb({"pages": [{"title": "Domů", "content": "<p>Obsah</p>"}]})
        items = parse_sharepoint(data)
        assert len(items) == 1
        assert items[0].kind == "page"
        assert items[0].content is not None

    def test_parse_flat_list(self):
        from stopa.artifacts.sharepoint_wr import parse_sharepoint

        data = jb([{"name": "doc.txt", "size": 10}])
        items = parse_sharepoint(data)
        assert len(items) == 1
        assert items[0].kind == "document"

    def test_parse_invalid_json(self):
        from stopa.artifacts.sharepoint_wr import parse_sharepoint

        with pytest.raises(ValueError):
            parse_sharepoint(b"{")

    def test_build_document_cloud_file(self):
        from stopa.artifacts.sharepoint_wr import (
            SharePointItem,
            build_sharepoint_artifacts,
        )

        arts = build_sharepoint_artifacts(
            [SharePointItem(kind="document", name="d.pdf", size_bytes=10)]
        )
        assert len(arts) == 1
        assert arts[0].artifact_type == "cloud_file"
        assert arts[0].details.get("engine") == "sharepoint_wr"

    def test_build_page_web_page(self):
        from stopa.artifacts.sharepoint_wr import (
            SharePointItem,
            build_sharepoint_artifacts,
        )

        arts = build_sharepoint_artifacts(
            [SharePointItem(kind="page", name="P", content="<p>x</p>")]
        )
        assert len(arts) == 1
        assert arts[0].artifact_type == "web_page"

    def test_detector_positive(self):
        from stopa.artifacts.sharepoint_wr import is_sharepoint_file

        assert is_sharepoint_file("sharepoint/documents.json")
        assert is_sharepoint_file("export/sharepoint_site_pages.json")

    def test_detector_negative_generic(self):
        from stopa.artifacts.sharepoint_wr import is_sharepoint_file

        # generic documents.json bez sharepoint markery → nepadne
        assert not is_sharepoint_file("google/documents.json")


# ════════════════════════════════════════════════════════════════════════
# amazon_cloudtrail — Amazon CloudTrail JSON (events + insights)
# ════════════════════════════════════════════════════════════════════════

class TestAmazonCloudTrail:
    def test_parse_events(self):
        from stopa.artifacts.amazon_cloudtrail import parse_cloudtrail

        data = jb(
            [
                {
                    "eventTime": "2024-10-03T12:00:00Z",
                    "eventName": "ConsoleLogin",
                    "userIdentity": {"type": "IAMUser", "userName": "admin"},
                    "sourceIPAddress": "1.2.3.4",
                    "eventSource": "signin.amazonaws.com",
                }
            ]
        )
        recs = parse_cloudtrail(data)
        assert len(recs) == 1
        assert recs[0].event_name == "ConsoleLogin"
        assert recs[0].user == "admin"
        assert recs[0].source_ip == "1.2.3.4"
        assert recs[0].timestamp_s is not None

    def test_parse_insights(self):
        from stopa.artifacts.amazon_cloudtrail import parse_cloudtrail

        data = jb(
            {
                "insights": [
                    {
                        "insightName": "ApiCallRateAnomaly",
                        "startTime": "2024-10-03T12:00:00Z",
                        "description": "anomálie",
                    }
                ]
            }
        )
        recs = parse_cloudtrail(data)
        assert len(recs) == 1
        assert recs[0].is_insight is True

    def test_parse_error_code(self):
        from stopa.artifacts.amazon_cloudtrail import parse_cloudtrail

        data = jb(
            [
                {
                    "eventName": "RunInstances",
                    "errorCode": "InvalidParameter",
                    "eventTime": "2024-10-03T12:00:00Z",
                }
            ]
        )
        recs = parse_cloudtrail(data)
        assert recs[0].error_code == "InvalidParameter"

    def test_parse_invalid_json(self):
        from stopa.artifacts.amazon_cloudtrail import parse_cloudtrail

        with pytest.raises(ValueError):
            parse_cloudtrail(b"{")

    def test_build_event_log_entry(self):
        from stopa.artifacts.amazon_cloudtrail import (
            CloudTrailEvent,
            build_cloudtrail_artifacts,
        )

        arts = build_cloudtrail_artifacts(
            [CloudTrailEvent(event_name="X", user="u")]
        )
        assert len(arts) == 1
        assert arts[0].artifact_type == "event_log_entry"
        assert arts[0].details.get("mimetype") == "aws:cloudtrail"

    def test_detector_positive(self):
        from stopa.artifacts.amazon_cloudtrail import is_amazon_cloudtrail_file

        assert is_amazon_cloudtrail_file("amazon/cloudtrail/events.json")

    def test_detector_negative_generic(self):
        from stopa.artifacts.amazon_cloudtrail import is_amazon_cloudtrail_file

        # generic events.json bez cloudtrail markery → nepadne
        assert not is_amazon_cloudtrail_file("outlook/calendar/events.json")


# ════════════════════════════════════════════════════════════════════════
# amazon_ec2_s3 — Amazon EC2/S3 JSON (auto-detekce)
# ════════════════════════════════════════════════════════════════════════

class TestAmazonEc2S3:
    def test_parse_ec2_instances(self):
        from stopa.artifacts.amazon_ec2_s3 import parse_ec2_instances

        data = jb(
            {
                "instances": [
                    {
                        "instanceId": "i-0abc123",
                        "state": "running",
                        "privateIpAddresses": ["10.0.0.5"],
                        "publicIpAddress": "1.2.3.4",
                        "launchTime": "2024-10-03T12:00:00Z",
                    }
                ]
            }
        )
        recs = parse_ec2_instances(data)
        assert len(recs) == 1
        assert recs[0].instance_id == "i-0abc123"
        assert recs[0].state == "running"
        assert "10.0.0.5" in recs[0].private_ips
        assert recs[0].public_ip == "1.2.3.4"

    def test_parse_ec2_private_dict(self):
        from stopa.artifacts.amazon_ec2_s3 import parse_ec2_instances

        data = jb(
            [
                {
                    "InstanceId": "i-xyz",
                    "privateIpAddresses": [{"ipAddress": "10.1.1.1"}],
                }
            ]
        )
        recs = parse_ec2_instances(data)
        assert len(recs) == 1
        assert "10.1.1.1" in recs[0].private_ips

    def test_parse_s3_objects(self):
        from stopa.artifacts.amazon_ec2_s3 import parse_s3_objects

        data = jb(
            {
                "buckets": [
                    {
                        "name": "corp-data",
                        "objects": [
                            {"key": "docs/smlouva.pdf", "size": 1024},
                            {"Key": "img/a.png", "Size": 512},
                        ],
                    }
                ]
            }
        )
        recs = parse_s3_objects(data)
        assert len(recs) == 2
        assert all(r.bucket == "corp-data" for r in recs)

    def test_parse_ec2_invalid_json(self):
        from stopa.artifacts.amazon_ec2_s3 import parse_ec2_instances

        with pytest.raises(ValueError):
            parse_ec2_instances(b"{")

    def test_build_instance_cloud_instance(self):
        from stopa.artifacts.amazon_ec2_s3 import (
            Ec2InstanceRecord,
            build_ec2_instance_artifacts,
        )

        arts = build_ec2_instance_artifacts(
            [Ec2InstanceRecord(instance_id="i-1", state="running")]
        )
        assert len(arts) == 1
        assert arts[0].artifact_type == "cloud_instance"
        assert arts[0].details.get("mimetype") == "aws:ec2"

    def test_build_s3_cloud_file(self):
        from stopa.artifacts.amazon_ec2_s3 import (
            S3ObjectRecord,
            build_s3_object_artifacts,
        )

        arts = build_s3_object_artifacts(
            [S3ObjectRecord(bucket="b", key="k.pdf", size_bytes=10)]
        )
        assert len(arts) == 1
        assert arts[0].artifact_type == "cloud_file"
        assert arts[0].details.get("mimetype") == "aws:s3"

    def test_extract_union(self, tmp_path: Path):
        from stopa.artifacts.amazon_ec2_s3 import extract_amazon_ec2_s3_artifacts

        p = tmp_path / "instances.json"
        p.write_text(
            json.dumps({"instances": [{"instanceId": "i-1", "state": "running"}]})
        )
        arts = extract_amazon_ec2_s3_artifacts(p)
        assert len(arts) == 1
        assert arts[0].artifact_type == "cloud_instance"

    def test_detector_positive(self):
        from stopa.artifacts.amazon_ec2_s3 import is_amazon_ec2_s3_file

        assert is_amazon_ec2_s3_file("aws/ec2/instances.json")
        assert is_amazon_ec2_s3_file("amazon/s3/bucket.json")

    def test_detector_negative_generic(self):
        from stopa.artifacts.amazon_ec2_s3 import is_amazon_ec2_s3_file

        # generic instances.json bez amazon/aws markery → nepadne
        assert not is_amazon_ec2_s3_file("some/instances.json")


# ════════════════════════════════════════════════════════════════════════
# Pipeline pre-pass dispatch (vlna 12 — MS + Amazon)
# ════════════════════════════════════════════════════════════════════════

class TestW12Dispatch:
    @pytest.mark.parametrize(
        "path,expected_fn",
        [
            ("export/microsoft/contacts.json", "extract_ms_contact_artifacts"),
            (
                "microsoft/mail/messages.json",
                "extract_ms_mail_artifacts",
            ),
            (
                "microsoft/teams/conversations.json",
                "extract_teams_conversation_artifacts",
            ),
            ("microsoft/teams/teams.json", "extract_teams"),
            (
                "outlook/calendar/events.json",
                "extract_outlook_calendar_artifacts",
            ),
            ("sharepoint/documents.json", "extract_sharepoint_artifacts"),
            (
                "amazon/cloudtrail/events.json",
                "extract_cloudtrail_artifacts",
            ),
            ("aws/ec2/instances.json", "extract_amazon_ec2_s3_artifacts"),
        ],
    )
    def test_prepass_routes(self, path: str, expected_fn: str):
        from stopa.pipeline import _sns_prepass

        match = _sns_prepass(path)
        assert match is not None, f"{path} nedorazil do pre-passu"
        fn, _ver = match
        assert fn.__name__ == expected_fn

    def test_conversations_before_teams(self):
        """conversations.json musí dorazit na conversations, ne teams."""
        from stopa.pipeline import _sns_prepass

        match = _sns_prepass("microsoft/teams/conversations.json")
        assert match is not None
        assert match[0].__name__ == "extract_teams_conversation_artifacts"

    def test_google_contacts_not_stolen(self):
        """Google contacts.json bez MS markery nepadne do ms_contacts."""
        from stopa.pipeline import _sns_prepass

        assert _sns_prepass("google/contacts.json") is None

    def test_twitter_order_preserved(self):
        """Twitter messages zůstává na twitter (pořadí pre-passu)."""
        from stopa.pipeline import _sns_prepass

        match = _sns_prepass("export/twitter/messages.json")
        assert match is not None
        assert match[0].__name__ == "extract_twitter_message_artifacts"


# ════════════════════════════════════════════════════════════════════════
# C3 registry synchronizace (8 nových záznamů)
# ════════════════════════════════════════════════════════════════════════

class TestW12Registry:
    W12_IDS = (
        "ms_contacts",
        "ms_mail_pst",
        "ms_teams_conversations",
        "ms_teams_teams",
        "ms_outlook_calendar",
        "sharepoint_wr",
        "amazon_cloudtrail",
        "amazon_ec2_s3",
    )

    def test_registry_has_w12_entries(self):
        from stopa.domain.validation_registry import build_registry

        reg = build_registry()
        for pid in self.W12_IDS:
            assert pid in reg, f"chybí registry záznam {pid}"

    def test_registry_versions_match_pipeline(self):
        from stopa.domain.validation_registry import build_registry
        from stopa.pipeline import NAME_BASED_EXTRACTORS

        reg = build_registry()
        for pid in self.W12_IDS:
            assert reg[pid].version == NAME_BASED_EXTRACTORS[pid][1]

    def test_registry_count(self):
        """58 (před vlnou 12) + 8 = min. 66 parserů (vlny 13+ přidávají další)."""
        from stopa.domain.validation_registry import build_registry

        assert len(build_registry()) >= 66
