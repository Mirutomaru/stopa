"""Testy forenzních časových konverzí — čistá doména, bez IO."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from stopa.domain.times import (
    from_chrome_micros,
    from_unix,
    to_chrome_micros,
)


class TestUnix:
    def test_epoch(self):
        assert from_unix(0.0) == datetime(1970, 1, 1, tzinfo=timezone.utc)

    def test_known_value(self):
        # 2024-03-15T12:34:56Z = 1710506096 s
        assert from_unix(1_710_506_096.0) == datetime(2024, 3, 15, 12, 34, 56, tzinfo=timezone.utc)

    def test_negative_raises(self):
        with pytest.raises(ValueError):
            from_unix(-1.0)


class TestChromeMicros:
    """Chrome/Edge visit_time = µs od Windows epochy (1601-01-01)."""

    def test_epoch_offset(self):
        # 1970-01-01 v Chrome čase = 11_644_473_600 s = 11_644_473_600_000_000 µs
        assert from_chrome_micros(11_644_473_600_000_000) == datetime(1970, 1, 1, tzinfo=timezone.utc)

    def test_roundtrip(self):
        dt = datetime(2025, 6, 1, 8, 30, 45, tzinfo=timezone.utc)
        assert from_chrome_micros(to_chrome_micros(dt)) == dt

    def test_known_value(self):
        # 2024-03-15T12:34:56Z = unix 1710506096 s → chrome µs od epochy 1601
        expected = (1_710_506_096 + 11_644_473_600) * 1_000_000
        assert from_chrome_micros(expected) == datetime(2024, 3, 15, 12, 34, 56, tzinfo=timezone.utc)

    def test_zero_raises(self):
        with pytest.raises(ValueError):
            from_chrome_micros(0)
