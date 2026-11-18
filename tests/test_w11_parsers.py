"""ETAPA B vlna 11 — syntetické offline testy cloud SNS rodiny Twitter/X + Facebook.

Pokrývá: twitter_posts, twitter_messages, twitter_users, facebook_wr
(parse/build/IO entrypoint/detektoři) + SNS pre-pass dispatch (generic
basenames bez kolize s Google detektory).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stopa.artifacts.facebook_wr import (
    PARSER_VERSION as FACEBOOK_WR_VERSION,
)
from stopa.artifacts.facebook_wr import (
    build_facebook_contact_artifacts,
    build_facebook_message_artifacts,
    build_facebook_timeline_artifacts,
    extract_facebook_artifacts,
    is_facebook_file,
    parse_facebook_friends,
    parse_facebook_messages,
    parse_facebook_profile,
    parse_facebook_timeline,
)
from stopa.artifacts.twitter_messages import (
    PARSER_VERSION as TWITTER_MESSAGES_VERSION,
)
from stopa.artifacts.twitter_messages import (
    build_twitter_message_artifacts,
    extract_twitter_message_artifacts,
    is_twitter_messages_file,
    parse_twitter_messages,
)
from stopa.artifacts.twitter_posts import (
    PARSER_VERSION as TWITTER_POSTS_VERSION,
)
from stopa.artifacts.twitter_posts import (
    build_twitter_post_artifacts,
    extract_twitter_post_artifacts,
    is_twitter_posts_file,
    parse_twitter_posts,
)
from stopa.artifacts.twitter_users import (
    PARSER_VERSION as TWITTER_USERS_VERSION,
)
from stopa.artifacts.twitter_users import (
    build_twitter_user_artifacts,
    extract_twitter_user_artifacts,
    is_twitter_users_file,
    parse_twitter_users,
)

# ── twitter_posts ────────────────────────────────────────────────────────


class TestTwitterPostsParse:
    def test_flat_list(self):
        # quality: positive
        data = json.dumps(
            [
                {
                    "id": "1",
                    "author": "user_a",
                    "text": "Ahoj světe!",
                    "created_at": 1728000000,
                    "likes": 5,
                    "retweets": 2,
                }
            ]
        ).encode()
        records = parse_twitter_posts(data)
        assert len(records) == 1
        r = records[0]
        assert r.author == "user_a"
        assert r.text == "Ahoj světe!"
        assert r.timestamp == 1728000000
        assert r.likes == 5
        assert r.retweets == 2

    def test_warrant_return_keys(self):
        # quality: positive
        data = json.dumps(
            [
                {
                    "tweet_id": "t-1",
                    "from_user": "user_b",
                    "body": "Warrant text",
                    "date": "2024-10-03T12:00:00Z",
                }
            ]
        ).encode()
        records = parse_twitter_posts(data)
        assert len(records) == 1
        r = records[0]
        assert r.author == "user_b"
        assert r.text == "Warrant text"
        # ISO → epoch (2024-10-03T12:00:00Z)
        assert r.timestamp == 1727956800

    def test_milliseconds_heuristic(self):
        # quality: positive
        data = json.dumps(
            [{"author": "u", "text": "x", "created_at": 1728000000123}]
        ).encode()
        records = parse_twitter_posts(data)
        assert records[0].timestamp == 1728000000

    def test_retweet_and_reply_types(self):
        # quality: positive
        data = json.dumps(
            [
                {"author": "u", "text": "RT", "retweeted_status": {"id": "x"}},
                {
                    "author": "u",
                    "text": "reply",
                    "in_reply_to_status_id": "123",
                },
            ]
        ).encode()
        records = parse_twitter_posts(data)
        assert records[0].post_type == "retweet"
        assert records[1].post_type == "reply"

    def test_dict_wrapper(self):
        # quality: positive
        data = json.dumps(
            {"posts": [{"author": "u", "text": "wrapped"}]}
        ).encode()
        records = parse_twitter_posts(data)
        assert len(records) == 1
        assert records[0].text == "wrapped"

    def test_invalid_json(self):
        # quality: negative
        with pytest.raises(ValueError):
            parse_twitter_posts(b"{nejson")

    def test_empty_raises_typeerror(self):
        # quality: boundary
        with pytest.raises(TypeError):
            parse_twitter_posts(b"[{\"foo\": 1}]")


class TestTwitterPostsBuild:
    def test_artifact_fields(self):
        # quality: positive
        data = json.dumps(
            [
                {
                    "author": "user_a",
                    "text": "Ahoj!",
                    "created_at": 1728000000,
                    "url": "https://x.com/user_a/status/1",
                    "likes": 3,
                }
            ]
        ).encode()
        artifacts = build_twitter_post_artifacts(parse_twitter_posts(data))
        assert len(artifacts) == 1
        a = artifacts[0]
        assert a.artifact_type == "sns_post"
        assert a.parser_version == TWITTER_POSTS_VERSION
        assert a.details["engine"] == "twitter_posts"
        assert a.details["author"] == "user_a"
        assert a.details["timestamp_epoch"] == 1728000000
        assert a.details["likes"] == 3
        assert a.confidence == 0.7

    def test_low_confidence_without_author(self):
        # quality: positive
        data = json.dumps([{"text": "bez autora"}]).encode()
        artifacts = build_twitter_post_artifacts(parse_twitter_posts(data))
        assert artifacts[0].confidence == 0.5


class TestTwitterPostsIO:
    def test_entrypoint_roundtrip(self, tmp_path: Path):
        # quality: positive
        f = tmp_path / "posts.json"
        f.write_text(json.dumps([{"author": "u", "text": "t"}]))
        artifacts = extract_twitter_post_artifacts(f)
        assert len(artifacts) == 1
        assert artifacts[0].artifact_type == "sns_post"

    def test_entrypoint_bad_json(self, tmp_path: Path):
        # quality: positive
        f = tmp_path / "posts.json"
        f.write_text("{x")
        assert extract_twitter_post_artifacts(f) == []


class TestTwitterPostsDetector:
    @pytest.mark.parametrize(
        "name",
        [
            "twitter_posts.json",
            "Twitter/posts.json",
            "Twitter/Tweets.json",
            "Twitter/WarrantReturnPosts.json",  # jen s twitter markerem v ceste
        ],
    )
    def test_positive(self, name: str):
        # quality: positive
        assert is_twitter_posts_file(name)

    @pytest.mark.parametrize(
        "name",
        ["posts.json", "Twitter/messages.json", "twitter_users.json"],
    )
    def test_negative(self, name: str):
        # quality: positive
        assert not is_twitter_posts_file(name)


# ── twitter_messages ─────────────────────────────────────────────────────


class TestTwitterMessagesParse:
    def test_flat_list(self):
        # quality: positive
        data = json.dumps(
            [
                {
                    "sender": "user_a",
                    "recipient": "user_b",
                    "text": "Ahoj!",
                    "timestamp": 1728000000,
                }
            ]
        ).encode()
        records = parse_twitter_messages(data)
        assert len(records) == 1
        r = records[0]
        assert r.sender == "user_a"
        assert r.recipient == "user_b"
        assert r.text == "Ahoj!"
        assert r.timestamp == 1728000000

    def test_conversation_format(self):
        # quality: positive
        data = json.dumps(
            [
                {
                    "id": "c-1",
                    "participants": ["a", "b"],
                    "messages": [
                        {"sender": "a", "body": "Ahoj!", "time": 1728000000},
                        {"sender": "b", "body": "Nazdar", "time": 1728000060},
                    ],
                }
            ]
        ).encode()
        records = parse_twitter_messages(data)
        assert len(records) == 2
        assert all(r.conversation_id == "c-1" for r in records)
        assert all(r.participants == ("a", "b") for r in records)

    def test_dict_wrapper(self):
        # quality: positive
        data = json.dumps(
            {"direct_messages": [{"from": "x", "to": "y", "body": "hi"}]}
        ).encode()
        records = parse_twitter_messages(data)
        assert len(records) == 1
        assert records[0].sender == "x"

    def test_invalid_json(self):
        # quality: negative
        with pytest.raises(ValueError):
            parse_twitter_messages(b"[")

    def test_empty_raises_typeerror(self):
        # quality: boundary
        with pytest.raises(TypeError):
            parse_twitter_messages(b"[]")


class TestTwitterMessagesBuild:
    def test_artifact_fields(self):
        # quality: positive
        data = json.dumps(
            [
                {
                    "sender": "a",
                    "recipient": "b",
                    "text": "Ahoj!",
                    "timestamp": 1728000000,
                }
            ]
        ).encode()
        artifacts = build_twitter_message_artifacts(parse_twitter_messages(data))
        assert len(artifacts) == 1
        a = artifacts[0]
        assert a.artifact_type == "chat_message"
        assert a.parser_version == TWITTER_MESSAGES_VERSION
        assert a.details["engine"] == "twitter_messages"
        assert a.details["sender"] == "a"
        assert a.details["recipient"] == "b"
        assert a.details["timestamp_epoch"] == 1728000000
        assert a.confidence == 0.7


class TestTwitterMessagesIO:
    def test_entrypoint_roundtrip(self, tmp_path: Path):
        # quality: positive
        f = tmp_path / "DirectMessages.json"
        f.write_text(json.dumps([{"sender": "a", "text": "t"}]))
        artifacts = extract_twitter_message_artifacts(f)
        assert len(artifacts) == 1
        assert artifacts[0].artifact_type == "chat_message"


class TestTwitterMessagesDetector:
    @pytest.mark.parametrize(
        "name",
        ["twitter_messages.json", "Twitter/DirectMessages.json", "Twitter/messages.json"],
    )
    def test_positive(self, name: str):
        # quality: positive
        assert is_twitter_messages_file(name)

    @pytest.mark.parametrize("name", ["messages.json", "Twitter/posts.json"])
    def test_negative(self, name: str):
        # quality: positive
        assert not is_twitter_messages_file(name)


# ── twitter_users ────────────────────────────────────────────────────────


class TestTwitterUsersParse:
    def test_flat_list(self):
        # quality: positive
        data = json.dumps(
            [
                {
                    "screen_name": "user_a",
                    "name": "User A",
                    "followers_count": 42,
                    "friends_count": 7,
                }
            ]
        ).encode()
        records = parse_twitter_users(data)
        assert len(records) == 1
        r = records[0]
        assert r.username == "user_a"
        assert r.full_name == "User A"
        assert r.followers_count == 42
        assert r.friends_count == 7

    def test_own_account_dict(self):
        # quality: positive
        data = json.dumps(
            {"screen_name": "me", "name": "Me", "followers_count": 10}
        ).encode()
        records = parse_twitter_users(data)
        assert len(records) == 1
        assert records[0].relationship == "account"

    def test_followers_following_sections(self):
        # quality: positive
        data = json.dumps(
            {
                "screen_name": "me",
                "followers": [{"username": "fan_1"}],
                "following": [{"username": "idol_1"}],
            }
        ).encode()
        records = parse_twitter_users(data)
        rels = {r.username: r.relationship for r in records}
        assert rels["me"] == "account"
        assert rels["fan_1"] == "follower"
        assert rels["idol_1"] == "following"

    def test_invalid_json(self):
        # quality: negative
        with pytest.raises(ValueError):
            parse_twitter_users(b"{")

    def test_empty_raises_typeerror(self):
        # quality: boundary
        with pytest.raises(TypeError):
            parse_twitter_users(b"[{\"foo\": 1}]")


class TestTwitterUsersBuild:
    def test_contact_artifacts(self):
        # quality: positive
        data = json.dumps([{"screen_name": "user_a", "name": "User A"}]).encode()
        artifacts = build_twitter_user_artifacts(parse_twitter_users(data))
        assert len(artifacts) == 1
        a = artifacts[0]
        assert a.artifact_type == "contact"
        assert a.parser_version == TWITTER_USERS_VERSION
        assert a.details["engine"] == "twitter_users"
        assert a.details["mimetype"] == "sns:twitter"
        assert a.confidence == 0.6


class TestTwitterUsersIO:
    def test_entrypoint_roundtrip(self, tmp_path: Path):
        # quality: positive
        f = tmp_path / "Users.json"
        f.write_text(json.dumps([{"screen_name": "u"}]))
        artifacts = extract_twitter_user_artifacts(f)
        assert len(artifacts) == 1
        assert artifacts[0].artifact_type == "contact"


class TestTwitterUsersDetector:
    @pytest.mark.parametrize(
        "name",
        ["twitter_users.json", "Twitter/Users.json", "Twitter/FollowersAndFollowing.json"],
    )
    def test_positive(self, name: str):
        # quality: positive
        assert is_twitter_users_file(name)

    @pytest.mark.parametrize("name", ["users.json", "Twitter/posts.json"])
    def test_negative(self, name: str):
        # quality: positive
        assert not is_twitter_users_file(name)


# ── facebook_wr ──────────────────────────────────────────────────────────


class TestFacebookMessagesParse:
    def test_flat_list(self):
        # quality: positive
        data = json.dumps(
            [
                {
                    "sender": "a",
                    "recipient": "b",
                    "body": "Ahoj!",
                    "timestamp": 1728000000,
                }
            ]
        ).encode()
        records = parse_facebook_messages(data)
        assert len(records) == 1
        r = records[0]
        assert r.sender == "a"
        assert r.recipient == "b"
        assert r.text == "Ahoj!"
        assert r.timestamp == 1728000000

    def test_conversation_format(self):
        # quality: positive
        data = json.dumps(
            {
                "conversations": [
                    {
                        "id": "c-9",
                        "messages": [
                            {"from": "a", "to": "b", "message": "Hi", "time": 1728000000}
                        ],
                    }
                ]
            }
        ).encode()
        records = parse_facebook_messages(data)
        assert len(records) == 1
        assert records[0].conversation_id == "c-9"

    def test_invalid_json(self):
        # quality: negative
        with pytest.raises(ValueError):
            parse_facebook_messages(b"[")


class TestFacebookFriendsParse:
    def test_friends_list(self):
        # quality: positive
        data = json.dumps(
            {"friends": [{"name": "User B", "username": "user_b"}]}
        ).encode()
        records = parse_facebook_friends(data)
        assert len(records) == 1
        r = records[0]
        assert r.full_name == "User B"
        assert r.username == "user_b"
        assert r.relationship == "friend"

    def test_own_account(self):
        # quality: positive
        data = json.dumps({"name": "Me", "email": "me@example.com"}).encode()
        records = parse_facebook_friends(data)
        assert len(records) == 1
        assert records[0].relationship == "account"
        assert records[0].email == "me@example.com"

    def test_flat_list(self):
        # quality: positive
        data = json.dumps([{"name": "Friend C"}]).encode()
        records = parse_facebook_friends(data)
        assert len(records) == 1
        assert records[0].relationship == "friend"


class TestFacebookTimelineParse:
    def test_timeline_posts(self):
        # quality: positive
        data = json.dumps(
            {
                "timeline": [
                    {
                        "author": "a",
                        "text": "Post!",
                        "created_time": "2024-10-03T12:00:00Z",
                    }
                ]
            }
        ).encode()
        records = parse_facebook_timeline(data)
        assert len(records) == 1
        r = records[0]
        assert r.author == "a"
        assert r.text == "Post!"
        assert r.timestamp == 1727956800


class TestFacebookProfileParse:
    def test_profile_dict(self):
        # quality: positive
        data = json.dumps(
            {"name": "Me", "email": "me@example.com", "phone": "+420123"}
        ).encode()
        record = parse_facebook_profile(data)
        assert record is not None
        assert record.relationship == "account"
        assert record.full_name == "Me"

    def test_non_dict_returns_none(self):
        # quality: positive
        assert parse_facebook_profile(b"[1, 2]") is None


class TestFacebookBuild:
    def test_message_artifacts(self):
        # quality: positive
        data = json.dumps([{"sender": "a", "body": "Hi"}]).encode()
        artifacts = build_facebook_message_artifacts(parse_facebook_messages(data))
        assert len(artifacts) == 1
        a = artifacts[0]
        assert a.artifact_type == "chat_message"
        assert a.parser_version == FACEBOOK_WR_VERSION
        assert a.details["engine"] == "facebook_wr"

    def test_contact_artifacts(self):
        # quality: positive
        data = json.dumps({"friends": [{"name": "User B"}]}).encode()
        artifacts = build_facebook_contact_artifacts(parse_facebook_friends(data))
        assert len(artifacts) == 1
        a = artifacts[0]
        assert a.artifact_type == "contact"
        assert a.details["mimetype"] == "sns:facebook"

    def test_timeline_artifacts(self):
        # quality: positive
        data = json.dumps({"timeline": [{"author": "a", "text": "P"}]}).encode()
        artifacts = build_facebook_timeline_artifacts(parse_facebook_timeline(data))
        assert len(artifacts) == 1
        a = artifacts[0]
        assert a.artifact_type == "sns_post"
        assert a.details["post_type"] == "timeline"


class TestFacebookIO:
    def test_entrypoint_multi_section(self, tmp_path: Path):
        # quality: positive
        """Jeden WR soubor nese více sekcí — auto-detekce."""
        payload = {
            "messages": [{"sender": "a", "body": "Hi"}],
            "friends": [{"name": "User B"}],
            "timeline": [{"author": "a", "text": "Post"}],
        }
        f = tmp_path / "Facebook.json"
        f.write_text(json.dumps(payload))
        artifacts = extract_facebook_artifacts(f)
        types = {a.artifact_type for a in artifacts}
        assert types == {"chat_message", "contact", "sns_post"}

    def test_entrypoint_profile_only(self, tmp_path: Path):
        # quality: positive
        f = tmp_path / "ProfileInfo.json"
        f.write_text(json.dumps({"name": "Me", "email": "me@example.com"}))
        artifacts = extract_facebook_artifacts(f)
        assert len(artifacts) == 1
        assert artifacts[0].artifact_type == "contact"
        assert artifacts[0].details["relationship"] == "account"

    def test_entrypoint_bad_json(self, tmp_path: Path):
        # quality: positive
        f = tmp_path / "Facebook.json"
        f.write_text("{x")
        assert extract_facebook_artifacts(f) == []


class TestFacebookDetector:
    @pytest.mark.parametrize(
        "name",
        [
            "facebook_messenger.json",
            "Facebook/MessengerMessages.json",
            "Facebook/Friends.json",
            "Facebook/Timeline.json",
            "Facebook/ProfileInfo.json",
        ],
    )
    def test_positive(self, name: str):
        # quality: positive
        assert is_facebook_file(name)

    @pytest.mark.parametrize("name", ["Friends.json", "messenger_chat.txt"])
    def test_negative(self, name: str):
        # quality: positive
        assert not is_facebook_file(name)


# ── SNS pre-pass dispatch (vlna 10 + 11 regression) ─────────────────────


class TestSnsPrepassDispatch:
    """Pipeline pre-pass na celé cestě — generic basenames bez kolizí."""

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            # vlna 11 — Twitter/X
            ("Twitter/posts.json", "twitter_posts"),
            ("Twitter/Tweets.json", "twitter_posts"),
            ("Twitter/Statuses.json", "twitter_posts"),
            ("Twitter/WarrantReturnPosts.json", "twitter_posts"),
            ("Twitter/DirectMessages.json", "twitter_messages"),
            ("Twitter/messages.json", "twitter_messages"),
            ("Twitter/Users.json", "twitter_users"),
            ("Twitter/FollowersAndFollowing.json", "twitter_users"),
            # vlna 11 — Facebook
            ("Facebook/MessengerMessages.json", "facebook_wr"),
            ("Facebook/messages.json", "facebook_wr"),
            ("Facebook/Friends.json", "facebook_wr"),
            ("Facebook/Timeline.json", "facebook_wr"),
            ("Facebook/ProfileInfo.json", "facebook_wr"),
            # vlna 10 — regression Instagram/Snapchat
            ("Instagram/Messages.json", "instagram_messages"),
            ("Instagram/Stories.json", "instagram_posts"),
            ("Instagram/AccountHistory.json", "instagram_account"),
            ("Snapchat/MessagesWR.json", "snapchat_wr"),
        ],
    )
    def test_sns_paths(self, name: str, expected: str):
        # quality: positive
        from stopa.pipeline import NAME_BASED_EXTRACTORS, _sns_prepass

        match = _sns_prepass(name)
        assert match is not None, f"{name} nebyl chycen pre-pass"
        fn, _ver = match
        got = next(k for k, (f, _v) in NAME_BASED_EXTRACTORS.items() if f is fn)
        assert got == expected

    @pytest.mark.parametrize(
        "name",
        [
            # Google detektory — generic basenames bez SNS markery nepadnou
            "Google/Messages.json",
            "Drive/Files.json",
            "Voice/Texts.json",
            "random.txt",
        ],
    )
    def test_no_collision(self, name: str):
        # quality: positive
        from stopa.pipeline import _sns_prepass

        assert _sns_prepass(name) is None


# ── C3 registry — nové parsery registrovány ──────────────────────────────


class TestC3RegistryWave11:
    def test_new_parsers_registered(self):
        # quality: positive
        from stopa.domain.validation_registry import build_registry

        reg = build_registry()
        for pid in ("twitter_posts", "twitter_messages", "twitter_users", "facebook_wr"):
            assert pid in reg, f"{pid} chybí v C3 registry"
            assert reg[pid].version == "1.0"

    def test_registry_count_at_least_58(self):
        # quality: positive
        from stopa.domain.validation_registry import build_registry

        assert len(build_registry()) >= 58
