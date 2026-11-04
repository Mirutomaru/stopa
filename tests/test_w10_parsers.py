"""ETAPA B vlna 10 — cloud SNS parsery (Instagram/Snapchat) — syntetické offline testy.

Pokrývá: instagram_messages, instagram_posts, instagram_account, snapchat_wr +
SNS pre-pass dispatch (generic basenames PŘED basename chainem).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stopa.artifacts.instagram_account import (
    PARSER_VERSION as IG_ACCT_VER,
)
from stopa.artifacts.instagram_account import (
    build_instagram_account_artifacts,
    extract_instagram_account_artifacts,
    is_instagram_account_file,
    parse_instagram_account,
)
from stopa.artifacts.instagram_messages import (
    PARSER_VERSION as IG_MSG_VER,
)
from stopa.artifacts.instagram_messages import (
    build_instagram_message_artifacts,
    extract_instagram_message_artifacts,
    is_instagram_messages_file,
    parse_instagram_messages,
)
from stopa.artifacts.instagram_posts import (
    PARSER_VERSION as IG_POSTS_VER,
)
from stopa.artifacts.instagram_posts import (
    build_instagram_post_artifacts,
    extract_instagram_post_artifacts,
    is_instagram_posts_file,
    parse_instagram_posts,
)
from stopa.artifacts.snapchat_wr import (
    PARSER_VERSION as SC_VER,
)
from stopa.artifacts.snapchat_wr import (
    build_snapchat_contact_artifacts,
    extract_snapchat_artifacts,
    is_snapchat_file,
    parse_snapchat_contacts,
    parse_snapchat_geolocation,
    parse_snapchat_ip_history,
    parse_snapchat_messages,
)


def _b(obj: object) -> bytes:
    return json.dumps(obj).encode("utf-8")


# ─────────────────────────── instagram_messages ───────────────────────────


class TestInstagramMessagesParse:
    def test_conversation_format(self):
        data = _b(
            [
                {
                    "id": "conv-1",
                    "participants": ["user_a", "user_b"],
                    "messages": [
                        {"sender": "user_a", "text": "Ahoj!", "timestamp": 1728000000},
                        {"sender": "user_b", "body": "Jsi to ty?", "time": 1728000600},
                    ],
                }
            ]
        )
        recs = parse_instagram_messages(data)
        assert len(recs) == 2
        assert recs[0].sender == "user_a"
        assert recs[0].text == "Ahoj!"
        assert recs[0].timestamp == 1728000000
        assert recs[0].conversation_id == "conv-1"
        assert recs[0].participants == ("user_a", "user_b")
        # tolerantní klíče — body/time fungují stejně jako text/timestamp
        assert recs[1].text == "Jsi to ty?"
        assert recs[1].timestamp == 1728000600

    def test_flat_format(self):
        data = _b(
            [
                {"from": "user_a", "to": "user_b", "body": "Přímá zpráva", "time": 1728000000},
                {"from": "user_c", "text": "Druhá"},
            ]
        )
        recs = parse_instagram_messages(data)
        assert len(recs) == 2
        assert recs[0].sender == "user_a"
        assert recs[0].recipient == "user_b"
        assert recs[0].text == "Přímá zpráva"

    def test_shared_media_url(self):
        data = _b(
            [
                {
                    "id": "conv-2",
                    "messages": [
                        {"sender": "user_a", "sharedMedia": {"url": "https://cdn.example.com/m1.jpg"}},
                    ],
                }
            ]
        )
        recs = parse_instagram_messages(data)
        assert len(recs) == 1
        assert recs[0].message_type == "share"
        assert recs[0].extra.get("media_url") == "https://cdn.example.com/m1.jpg"

    def test_invalid_json(self):
        with pytest.raises(ValueError):
            parse_instagram_messages(b"{nejson")

    def test_empty_payload(self):
        with pytest.raises(TypeError):
            parse_instagram_messages(_b({"foo": 1}))


class TestInstagramMessagesArtifacts:
    def test_build_artifacts(self):
        data = _b(
            [
                {
                    "id": "conv-1",
                    "participants": ["a", "b"],
                    "messages": [{"sender": "a", "text": "Zdravím", "timestamp": 1728000000}],
                }
            ]
        )
        arts = build_instagram_message_artifacts(parse_instagram_messages(data))
        assert len(arts) == 1
        a = arts[0]
        assert a.artifact_type == "chat_message"
        assert a.parser_version == IG_MSG_VER
        assert a.details["engine"] == "instagram_messages"
        assert a.details["sender"] == "a"
        assert a.details["conversation_id"] == "conv-1"
        assert a.details["participants"] == ["a", "b"]
        assert a.details["timestamp_epoch"] == 1728000000
        assert a.confidence >= 0.5

    def test_io_entrypoint(self, tmp_path: Path):
        p = tmp_path / "InstagramMessages.json"
        p.write_bytes(_b([{"from": "x", "to": "y", "body": "Hi"}]))
        arts = extract_instagram_message_artifacts(p)
        assert len(arts) == 1
        assert arts[0].artifact_type == "chat_message"

    def test_io_entrypoint_bad_json(self, tmp_path: Path):
        p = tmp_path / "x.json"
        p.write_bytes(b"not json")
        assert extract_instagram_message_artifacts(p) == []


class TestInstagramMessagesDetector:
    @pytest.mark.parametrize(
        "name",
        [
            "instagram_messages.json",
            "Instagram/Messages.json",
            "Instagram/DirectMessages.json",  # generic basename — marker v cestě
        ],
    )
    def test_positive(self, name: str):
        assert is_instagram_messages_file(name)

    @pytest.mark.parametrize(
        "name",
        [
            "messages.json",  # bez SNS markery — Google Mail
            "instagram_posts.json",  # posts, ne messages
            "snapchat_messages.json",
        ],
    )
    def test_negative(self, name: str):
        assert not is_instagram_messages_file(name)


# ─────────────────────────── instagram_posts ───────────────────────────


class TestInstagramPostsParse:
    def test_posts_with_comments(self):
        data = _b(
            [
                {
                    "id": "post-1",
                    "caption": "Víkend u jezera",
                    "timestamp": 1728000000,
                    "likes_count": 42,
                    "media_url": "https://cdn.example.com/p1.jpg",
                    "comments": [
                        {"user": "fan_1", "text": "Krásné!", "time": 1728000300},
                    ],
                }
            ]
        )
        posts, comments = parse_instagram_posts(data)
        assert len(posts) == 1
        p = posts[0]
        assert p.post_id == "post-1"
        assert p.caption == "Víkend u jezera"
        assert p.likes_count == 42
        assert p.media_url == "https://cdn.example.com/p1.jpg"
        assert len(comments) == 1
        assert comments[0].user == "fan_1"
        assert comments[0].text == "Krásné!"
        assert comments[0].post_id == "post-1"

    def test_story_detection(self):
        data = _b([{"id": "s-1", "story_id": "st-9", "type": "image"}])
        posts, _ = parse_instagram_posts(data)
        assert len(posts) == 1
        assert posts[0].is_story is True

    def test_media_list_format(self):
        data = _b(
            {
                "media": [
                    {"id": "m-1", "url": "https://cdn.example.com/m1.mp4", "type": "video"},
                    {"id": "m-2", "link": "https://cdn.example.com/m2.jpg"},
                ]
            }
        )
        posts, _ = parse_instagram_posts(data)
        assert len(posts) == 2
        assert posts[0].media_type == "video"
        assert posts[1].media_url == "https://cdn.example.com/m2.jpg"

    def test_invalid_json(self):
        with pytest.raises(ValueError):
            parse_instagram_posts(b"[")

    def test_empty_payload(self):
        with pytest.raises(TypeError):
            parse_instagram_posts(_b({"x": 1}))


class TestInstagramPostsArtifacts:
    def test_build_artifacts(self):
        data = _b(
            [
                {
                    "id": "post-1",
                    "caption": "Test",
                    "timestamp": 1728000000,
                    "likes_count": 7,
                    "comments": [{"user": "u1", "text": "ok"}],
                }
            ]
        )
        posts, comments = parse_instagram_posts(data)
        arts = build_instagram_post_artifacts(posts, comments)
        assert len(arts) == 2
        post_art, comment_art = arts
        assert post_art.artifact_type == "sns_post"
        assert post_art.parser_version == IG_POSTS_VER
        assert post_art.details["engine"] == "instagram_posts"
        assert post_art.details["post_id"] == "post-1"
        assert post_art.details["likes_count"] == 7
        assert comment_art.artifact_type == "sns_comment"
        assert comment_art.details["user"] == "u1"

    def test_io_entrypoint(self, tmp_path: Path):
        p = tmp_path / "InstagramPosts.json"
        p.write_bytes(_b([{"id": "p", "caption": "C"}]))
        arts = extract_instagram_post_artifacts(p)
        assert len(arts) == 1
        assert arts[0].artifact_type == "sns_post"


class TestInstagramPostsDetector:
    @pytest.mark.parametrize(
        "name",
        [
            "instagram_posts.json",
            "Instagram/Photos.json",
            "Instagram/Stories.json",
            "Instagram/Media.json",
            "Instagram/Comments.json",
        ],
    )
    def test_positive(self, name: str):
        assert is_instagram_posts_file(name)

    @pytest.mark.parametrize(
        "name",
        ["photos.json", "instagram_messages.json", "snapchat_media.json"],
    )
    def test_negative(self, name: str):
        assert not is_instagram_posts_file(name)


# ─────────────────────────── instagram_account ───────────────────────────


class TestInstagramAccountParse:
    def test_events_format(self):
        data = _b(
            [
                {"type": "login", "timestamp": 1728000000, "ip_address": "1.2.3.4"},
                {"action": "password_change", "time": 1728003600},
            ]
        )
        events, users = parse_instagram_account(data)
        assert len(events) == 2
        assert events[0].event_type == "login"
        assert events[0].ip_address == "1.2.3.4"
        assert events[1].event_type == "password_change"
        assert users == []

    def test_followers_format(self):
        data = _b(
            {
                "followers": [
                    {"username": "fan_1", "full_name": "Fan One"},
                    {"username": "fan_2"},
                ],
                "following": [{"username": "user_x"}],
            }
        )
        events, users = parse_instagram_account(data)
        assert events == []
        assert len(users) == 3
        assert users[0].relationship == "follower"
        assert users[0].full_name == "Fan One"
        assert users[2].relationship == "following"

    def test_invalid_json(self):
        with pytest.raises(ValueError):
            parse_instagram_account(b"{")

    def test_empty_payload(self):
        with pytest.raises(TypeError):
            parse_instagram_account(_b({"unrelated": True}))


class TestInstagramAccountArtifacts:
    def test_build_artifacts_events(self):
        data = _b([{"type": "login", "timestamp": 1728000000, "device": "Pixel 8"}])
        events, users = parse_instagram_account(data)
        arts = build_instagram_account_artifacts(events, users)
        assert len(arts) == 1
        a = arts[0]
        assert a.artifact_type == "event_log_entry"
        assert a.parser_version == IG_ACCT_VER
        assert a.details["engine"] == "instagram_account"
        assert a.details["event_type"] == "login"
        assert a.details["device"] == "Pixel 8"

    def test_build_artifacts_contacts(self):
        data = _b({"followers": [{"username": "fan_1"}]})
        events, users = parse_instagram_account(data)
        arts = build_instagram_account_artifacts(events, users)
        assert len(arts) == 1
        a = arts[0]
        assert a.artifact_type == "contact"
        assert a.details["mimetype"] == "sns:instagram"
        assert a.details["relationship"] == "follower"

    def test_io_entrypoint(self, tmp_path: Path):
        p = tmp_path / "InstagramAccountActions.json"
        p.write_bytes(_b([{"type": "login", "timestamp": 1728000000}]))
        arts = extract_instagram_account_artifacts(p)
        assert len(arts) == 1
        assert arts[0].artifact_type == "event_log_entry"


class TestInstagramAccountDetector:
    @pytest.mark.parametrize(
        "name",
        [
            "instagram_account_actions.json",
            "Instagram/AccountHistory.json",
            "Instagram/FollowersAndFollowing.json",
        ],
    )
    def test_positive(self, name: str):
        assert is_instagram_account_file(name)

    @pytest.mark.parametrize("name", ["account_info.json", "instagram_posts.json"])
    def test_negative(self, name: str):
        assert not is_instagram_account_file(name)


# ─────────────────────────── snapchat_wr ───────────────────────────


class TestSnapchatMessagesParse:
    def test_flat_messages(self):
        data = _b(
            [
                {"from": "user_a", "to": "user_b", "body": "Ahoj!", "time": 1728000000},
                {"sender": "user_c", "text": "Druhá"},
            ]
        )
        recs = parse_snapchat_messages(data)
        assert len(recs) == 2
        assert recs[0].sender == "user_a"
        assert recs[0].recipient == "user_b"
        assert recs[0].text == "Ahoj!"

    def test_conversation_format(self):
        data = _b(
            {
                "conversations": [
                    {
                        "group_id": "g-1",
                        "messages": [
                            {"from": "a", "body": "v skupině", "time": 1728000000},
                        ],
                    }
                ]
            }
        )
        recs = parse_snapchat_messages(data)
        assert len(recs) == 1
        assert recs[0].group_id == "g-1"

    def test_invalid_json(self):
        with pytest.raises(ValueError):
            parse_snapchat_messages(b"{")


class TestSnapchatContactsParse:
    def test_friends_list(self):
        data = _b({"friends": [{"username": "friend_1", "full_name": "Friend One"}]})
        recs = parse_snapchat_contacts(data)
        assert len(recs) == 1
        assert recs[0].relationship == "friend"
        assert recs[0].username == "friend_1"

    def test_account_info(self):
        data = _b(
            {"username": "me", "email": "me@example.com", "phone_number": "+420777123456"}
        )
        recs = parse_snapchat_contacts(data)
        assert len(recs) == 1
        assert recs[0].relationship == "account"
        assert recs[0].email == "me@example.com"


class TestSnapchatGeoIpParse:
    def test_geolocation(self):
        data = _b(
            [
                {"latitude": 50.09, "longitude": 14.43, "time": 1728000000},
                {"lat": 48.86, "lon": 2.35},
            ]
        )
        recs = parse_snapchat_geolocation(data)
        assert len(recs) == 2
        assert recs[0].latitude == 50.09
        assert recs[1].longitude == 2.35

    def test_ip_history(self):
        data = _b(
            {"ip_history": [{"ip_address": "1.2.3.4", "time": 1728000000, "event_type": "login"}]}
        )
        recs = parse_snapchat_ip_history(data)
        assert len(recs) == 1
        assert recs[0].ip_address == "1.2.3.4"
        assert recs[0].event_type == "login"


class TestSnapchatArtifacts:
    def test_contact_artifacts_email_phone(self):
        data = _b(
            {"username": "me", "email": "me@example.com", "phone_number": "+420777123456"}
        )
        recs = parse_snapchat_contacts(data)
        arts = build_snapchat_contact_artifacts(recs)
        # username + email + telefon = 3 kontakty pro E4 entity extrakci
        assert len(arts) == 3
        mimes = {a.details["mimetype"] for a in arts}
        assert mimes == {"sns:snapchat:user", "sns:snapchat:email", "sns:snapchat:phone"}
        assert all(a.artifact_type == "contact" for a in arts)
        assert all(a.parser_version == SC_VER for a in arts)

    def test_extract_auto_detect_messages(self, tmp_path: Path):
        p = tmp_path / "SnapchatMessagesWR.json"
        p.write_bytes(_b([{"from": "a", "to": "b", "body": "Hi", "time": 1728000000}]))
        arts = extract_snapchat_artifacts(p)
        assert len(arts) == 1
        assert arts[0].artifact_type == "chat_message"
        assert arts[0].details["engine"] == "snapchat_wr"

    def test_extract_auto_detect_geolocation(self, tmp_path: Path):
        p = tmp_path / "SnapchatGeolocation.json"
        p.write_bytes(_b([{"latitude": 50.09, "longitude": 14.43}]))
        arts = extract_snapchat_artifacts(p)
        assert len(arts) == 1
        assert arts[0].artifact_type == "location_data"
        assert arts[0].details["latitude"] == 50.09

    def test_extract_auto_detect_ip(self, tmp_path: Path):
        p = tmp_path / "SnapchatIpHistory.json"
        p.write_bytes(_b([{"ip_address": "1.2.3.4"}]))
        arts = extract_snapchat_artifacts(p)
        assert len(arts) == 1
        assert arts[0].artifact_type == "network_connection"

    def test_extract_bad_json(self, tmp_path: Path):
        p = tmp_path / "x.json"
        p.write_bytes(b"not json")
        assert extract_snapchat_artifacts(p) == []


class TestSnapchatDetector:
    @pytest.mark.parametrize(
        "name",
        ["snapchat_messages_wr.json", "Snapchat/Friends.json", "Snapchat/AccountInfo.json"],
    )
    def test_positive(self, name: str):
        assert is_snapchat_file(name)

    @pytest.mark.parametrize("name", ["friends.json", "instagram_friends.json"])
    def test_negative(self, name: str):
        assert not is_snapchat_file(name)


# ─────────────────────────── SNS pre-pass dispatch ───────────────────────────


class TestSnsPrepassDispatch:
    @pytest.fixture()
    def prepass(self):
        from stopa.pipeline import _sns_prepass

        return _sns_prepass

    @pytest.mark.parametrize(
        ("path", "expected_module"),
        [
            ("Instagram/Messages.json", "instagram_messages"),
            ("Instagram/DirectMessages.json", "instagram_messages"),
            ("FacebookInstagramMessages.json", "instagram_messages"),
            ("Instagram/Posts.json", "instagram_posts"),
            ("Instagram/Photos.json", "instagram_posts"),
            ("Instagram/Stories.json", "instagram_posts"),
            ("Instagram/ArchivedStories.json", "instagram_posts"),
            ("Instagram/DirectStories.json", "instagram_posts"),
            ("Instagram/Comments.json", "instagram_posts"),
            ("Instagram/Media.json", "instagram_posts"),
            # account PŘED posts — "AccountHistory" obsahuje substring "stor(y)"
            ("Instagram/AccountActions.json", "instagram_account"),
            ("Instagram/AccountHistory.json", "instagram_account"),
            ("Instagram/FollowersAndFollowing.json", "instagram_account"),
            ("Snapchat/MessagesWR.json", "snapchat_wr"),
            ("Snapchat/GroupChat.json", "snapchat_wr"),
            ("Snapchat/Friends.json", "snapchat_wr"),
            ("Snapchat/Geolocation.json", "snapchat_wr"),
            ("Snapchat/IpHistory.json", "snapchat_wr"),
            ("Snapchat/AccountInfo.json", "snapchat_wr"),
        ],
    )
    def test_sns_paths(self, prepass, path: str, expected_module: str):
        m = prepass(path)
        assert m is not None, f"{path} nebyl zachycen SNS pre-pass"
        assert expected_module in m[0].__module__

    @pytest.mark.parametrize(
        "path",
        [
            "netstat.txt",  # memory network / netstat — bez SNS markery
            "Google/Mail/Info.json",  # Google Mail export
            "Instagram/random_notes.txt",  # marker ale bez klíčových slov
            "Photos.json",  # generic basename bez cesty
        ],
    )
    def test_non_sns_paths(self, prepass, path: str):
        assert prepass(path) is None
