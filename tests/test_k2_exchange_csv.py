"""STOPA — K2 testy: exchange CSV parsery (Binance/Coinbase/Kraken).

Pokrytí: normalizace časových formátů (ISO Z/offset/naive, epoch s/ms),
normalizace částek, detekce typu exportu podle hlavičky (vč. aliasů a
exchange hintu), end-to-end parsery všech 7 typů, TSV fallback, gaps v
timeline (spec AK).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from stopa.domain.crypto.exchanges import (
    ExchangeParse,
    ExchangeRecord,
    _parse_amount,
    _parse_ts,
    detect_exchange_csv,
    find_timeline_gaps,
    parse_exchange_csv,
)

# ── časová normalizace ───────────────────────────────────────────────────

EPOCH = 1464955479  # = 2016-06-03T12:04:39Z (Binance vzorový export)


class TestParseTs:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("2016-06-03T12:04:39Z", datetime.fromtimestamp(EPOCH, tz=timezone.utc)),
            (
                "2016-06-03T14:04:39+02:00",  # offset → UTC instant
                datetime.fromtimestamp(EPOCH, tz=timezone.utc),
            ),
            ("2016-06-03T12:04:39", None),  # naive — viz test níže (tz se doplní)
        ],
    )
    def test_iso(self, value: str, expected: datetime | None) -> None:
        got = _parse_ts(value)
        assert got is not None
        if expected is not None:
            assert got == expected and got.tzinfo is not None
        else:  # naive ISO — tz se doplní jako UTC
            assert got.utcoffset() == timedelta(0)

    @pytest.mark.parametrize(
        "value",
        [
            "2016-06-03T12:04:39+00:00",
            "2016-06-03T07:04:39-05:00",
            "2016-06-03T12:04:39.123456Z",
        ],
    )
    def test_iso_offsets_and_micros(self, value: str) -> None:
        got = _parse_ts(value)
        assert got is not None and got.utcoffset() == timedelta(0)

    def test_naive_iso_assumed_utc(self) -> None:
        got = _parse_ts("2016-06-03T12:04:39")
        assert got == datetime.fromtimestamp(EPOCH, tz=timezone.utc)

    @pytest.mark.parametrize(
        "value",
        [
            str(EPOCH),  # epoch sekundy (int string)
            f"{EPOCH}.9",  # Kraken float epoch
            str(EPOCH * 1000),  # epoch milisekundy (int)
            f"{EPOCH * 1000}.5",  # epoch ms s desetinou
        ],
    )
    def test_epoch_seconds_and_millis(self, value: str) -> None:
        got = _parse_ts(value)
        assert got is not None and got.tzinfo == timezone.utc

    @pytest.mark.parametrize(
        "value",
        [None, "", "   ", "-5", "garbage-date", "2016-13-45T99:99:99"],
    )
    def test_invalid_returns_none(self, value: str | None) -> None:
        assert _parse_ts(value) is None


# ── normalizace částek ───────────────────────────────────────────────────

class TestParseAmount:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("$1,234.56", 1234.56),
            ("1,234.56", 1234.56),
            ("12 345", 12345.0),
            ("-12.5", -12.5),
            ("0.001", 0.001),
            ("7", 7.0),
        ],
    )
    def test_valid(self, value: str, expected: float) -> None:
        assert _parse_amount(value) == pytest.approx(expected)

    @pytest.mark.parametrize(
        "value", [None, "", "-", "abc", "$", "1.2.3"]
    )
    def test_invalid_returns_none(self, value: str | None) -> None:
        assert _parse_amount(value) is None


# ── detekce typu exportu ────────────────────────────────────────────────

BINANCE_DEPOSITS_HDR = "Time,Asset,Amount,Address,TxHash"
COINBASE_TX_HDR = "Type,Date/Time,Currency,Amount,Counterparty,Transaction ID"


class TestDetectExchangeCsv:
    @pytest.mark.parametrize(
        "text,expected",
        [
            (BINANCE_DEPOSITS_HDR + "\nrow\n", "binance_deposits"),
            ("Time,Asset,Amount,Fee\nrow\n", "binance_withdrawals"),  # fee → withdrawal
            ("Symbol,Side,Price,Quantity\nrow\n", "binance_trades"),
            (COINBASE_TX_HDR + "\nrow\n", "coinbase_transactions"),
            ("Balance Time,Balance\nrow\n", "coinbase_balance_history"),
            ("Balance Time,Balance,Currency\nrow\n", "coinbase_balance_history"),
            ("time,pair,side,volume,price\nrow\n", "kraken_trades"),
            ("Time,Type,Amount,Pair\nrow\n", "kraken_funds"),  # pair → auto detekce
        ],
    )
    def test_autodetect(self, text: str, expected: str) -> None:
        assert detect_exchange_csv(text) == expected

    @pytest.mark.parametrize(
        "header,hint,expected",
        [
            ("Time,Asset,Amount,Fee", "binance", "binance_withdrawals"),
            ("Time,Asset,Amount", "binance", "binance_deposits"),
            ("Type,Date/Time,Amount", "coinbase", "coinbase_transactions"),
            ("Time,Type,Amount", "kraken", "kraken_funds"),
        ],
    )
    def test_exchange_hint(self, header: str, hint: str, expected: str) -> None:
        assert detect_exchange_csv(header + "\nrow\n", exchange_hint=hint) == expected

    @pytest.mark.parametrize(
        "header",
        [
            BINANCE_DEPOSITS_HDR.upper(),  # velká písmena — normalizace hlavičky
            COINBASE_TX_HDR.swapcase().lower() if False else COINBASE_TX_HDR,
        ],
    )
    def test_header_case_insensitive(self, header: str) -> None:
        assert detect_exchange_csv(header + "\nrow\n") is not None

    @pytest.mark.parametrize(
        "text",
        [
            "",  # prázdný soubor
            "foo\nbar",  # jeden sloupec, žádný alias
            "a,b,c\nd,e,f",  # komo, ale žádné známé hlavičky
            "Amount,Asset\n1,BTC",  # bez časového sloupce
        ],
    )
    def test_non_exchange_returns_none(self, text: str) -> None:
        assert detect_exchange_csv(text) is None


# ── end-to-end parsery ───────────────────────────────────────────────────

BINANCE_DEPOSITS_FILE = (
    BINANCE_DEPOSITS_HDR + "\n"
    "2016-06-03T12:04:39Z,BTC,0.5,1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa,"
    + "a" * 64
    + "\n"
    "2016-07-01T08:30:00Z,ETH,1.25,0xAbCdef0123456789abcdef0123456789ABCDEF01,"
    + "b" * 64
    + "\n"
)


class TestBinanceDeposits:
    @pytest.fixture()
    def parsed(self) -> ExchangeParse:
        result = parse_exchange_csv(BINANCE_DEPOSITS_FILE)
        assert isinstance(result, ExchangeParse)
        return result

    def test_kind_and_records(self, parsed: ExchangeParse) -> None:
        assert parsed.exchange == "binance"
        assert parsed.kind == "binance_deposits"
        assert len(parsed.records) == 2
        assert all(r.record_type == "deposit" for r in parsed.records)

    def test_fields_parsed(self, parsed: ExchangeParse) -> None:
        rec = parsed.records[0]
        assert rec.asset == "BTC"
        assert rec.amount == pytest.approx(0.5)
        assert rec.address_or_counterparty == "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
        assert rec.txid_reference == "a" * 64
        assert rec.timestamp is not None and rec.timestamp.tzinfo == timezone.utc

    def test_aware_utc_timestamp(self, parsed: ExchangeParse) -> None:
        expected = datetime.fromtimestamp(EPOCH, tz=timezone.utc)
        assert parsed.records[0].timestamp == expected


class TestBinanceWithdrawals:
    FILE = "Time,Asset,Amount,Fee\n2016-06-03T12:04:39Z,BTC,-0.5,0.002\n"

    def test_fee_column_switches_to_withdrawal(self) -> None:
        parsed = parse_exchange_csv(self.FILE)
        assert isinstance(parsed, ExchangeParse) and parsed.kind == "binance_withdrawals"
        rec = parsed.records[0]
        assert rec.record_type == "withdrawal"
        assert rec.fee == pytest.approx(0.002)
        assert rec.amount == pytest.approx(-0.5)


class TestBinanceTrades:
    FILE = (
        "Symbol,Side,Price,Quantity,Fee,Time\n"
        "BTCUSDT,BUY,30000.5,0.01,0.03,2016-06-03T12:04:39Z\n"
    )

    def test_trade_fields(self) -> None:
        parsed = parse_exchange_csv(self.FILE)
        assert isinstance(parsed, ExchangeParse) and parsed.kind == "binance_trades"
        rec = parsed.records[0]
        assert rec.record_type == "trade"
        assert rec.asset == "BTCUSDT"
        assert rec.side == "BUY"  # raw hodnota bez normalizace
        assert rec.price == pytest.approx(30000.5)
        assert rec.amount == pytest.approx(0.01)


class TestCoinbaseTransactions:
    @pytest.mark.parametrize(
        "type_value,record_type,side",
        [
            ("Buy", "trade", "buy"),
            ("Sell", "trade", "sell"),
            ("Send money to friend", "transfer", "out"),
            ("Received from exchange", "transfer", "in"),
            ("Deposit", "deposit", None),
            ("Withdrawal", "withdrawal", None),
            ("Fee", "other", None),
        ],
    )
    def test_type_mapping(self, type_value: str, record_type: str, side: str | None) -> None:
        text = COINBASE_TX_HDR + "\n" f"{type_value},2016-06-03T12:04:39Z,USD,10.5,cpt\n"
        parsed = parse_exchange_csv(text)
        assert isinstance(parsed, ExchangeParse) and parsed.kind == "coinbase_transactions"
        rec = parsed.records[0]
        assert rec.record_type == record_type
        if side is not None:
            assert rec.side == side

    def test_counterparty_and_amount(self) -> None:
        # částka s tisíční oddělovačem musí být v CSV uvozovkách (jiné by se
        # rozparcelovala na dva sloupce)
        text = COINBASE_TX_HDR + '\nBuy,2016-06-03T12:04:39Z,USD,"$1,234.56",alice\n'
        parsed = parse_exchange_csv(text)
        assert isinstance(parsed, ExchangeParse)
        rec = parsed.records[0]
        assert rec.amount == pytest.approx(1234.56)
        assert rec.address_or_counterparty == "alice"

    def test_without_currency_column_hint_fallback(self) -> None:
        text = "Type,Date/Time,Amount\nBuy,2016-06-03T12:04:39Z,10.5\n"
        assert detect_exchange_csv(text) is None  # bez currency ani hintu
        parsed = parse_exchange_csv(text, exchange_hint="coinbase")
        assert isinstance(parsed, ExchangeParse) and len(parsed.records) == 1


class TestCoinbaseBalanceHistory:
    FILE = "Balance Time,Balance,Currency\n2016-06-03T12:04:39Z,152.75,USD\n"

    def test_balance_record(self) -> None:
        parsed = parse_exchange_csv(self.FILE)
        assert isinstance(parsed, ExchangeParse) and parsed.kind == "coinbase_balance_history"
        rec = parsed.records[0]
        assert rec.record_type == "balance"
        assert rec.amount == pytest.approx(152.75)
        assert rec.asset == "USD"


class TestKrakenTrades:
    FILE = (
        "time,pair,side,volume,price\n"
        f"{EPOCH}.9,XBTUSD,buy,0.001,30000.5\n"
    )

    def test_float_epoch_and_fields(self) -> None:
        parsed = parse_exchange_csv(self.FILE)
        assert isinstance(parsed, ExchangeParse) and parsed.kind == "kraken_trades"
        rec = parsed.records[0]
        assert rec.record_type == "trade"
        assert rec.asset == "XBTUSD"
        assert rec.side == "buy"
        assert rec.amount == pytest.approx(0.001)
        assert rec.price == pytest.approx(30000.5)
        expected = datetime.fromtimestamp(EPOCH + 0.9, tz=timezone.utc)
        assert rec.timestamp == expected


class TestKrakenFunds:
    FILE_WITH_PAIR = (
        "Time,Type,Amount,Pair\n"
        "2016-06-03T12:04:39Z,Deposit,0.5,XBT\n"
        "2016-07-01T08:30:00Z,Withdrawal,-0.5,XBT\n"
    )

    def test_deposit_withdrawal_mapping(self) -> None:
        parsed = parse_exchange_csv(self.FILE_WITH_PAIR)
        assert isinstance(parsed, ExchangeParse) and parsed.kind == "kraken_funds"
        types = [r.record_type for r in parsed.records]
        assert types == ["deposit", "withdrawal"]

    def test_without_pair_needs_hint(self) -> None:
        text = "Time,Type,Amount\n2016-06-03T12:04:39Z,Deposit,0.5\n"
        assert detect_exchange_csv(text) is None
        parsed = parse_exchange_csv(text, exchange_hint="kraken")
        assert isinstance(parsed, ExchangeParse) and len(parsed.records) == 1


class TestCsvEdges:
    def test_tsv_delimiter(self) -> None:
        text = "Time\tAsset\tAmount\n2016-06-03T12:04:39Z\tBTC\t0.5\n"
        parsed = parse_exchange_csv(text)
        assert isinstance(parsed, ExchangeParse) and parsed.kind == "binance_deposits"
        rec = parsed.records[0]
        assert rec.asset == "BTC" and rec.amount == pytest.approx(0.5)

    def test_header_only_no_rows(self) -> None:
        parsed = parse_exchange_csv(BINANCE_DEPOSITS_HDR + "\n")
        assert isinstance(parsed, ExchangeParse)
        assert parsed.records == [] and parsed.skipped_rows == 0

    def test_empty_text_returns_none(self) -> None:
        assert parse_exchange_csv("") is None

    def test_unusable_row_skipped(self) -> None:
        # Type bez rozpoznání + prázdný čas i částka → řádek nepoužitelný
        text = COINBASE_TX_HDR + "\nXyz,,,\n"
        parsed = parse_exchange_csv(text)
        assert isinstance(parsed, ExchangeParse)
        assert parsed.skipped_rows == 1 and not parsed.records

    def test_raw_row_preserved_for_audit(self) -> None:
        text = BINANCE_DEPOSITS_HDR + ",Note\n2016-06-03T12:04:39Z,BTC,0.5,addr," + "c" * 64 + ",hlavni depozit\n"
        parsed = parse_exchange_csv(text)
        assert isinstance(parsed, ExchangeParse)
        raw = parsed.records[0].raw
        assert raw.get("Note") == "hlavni depozit"
        assert raw.get(BINANCE_DEPOSITS_HDR.split(",")[0]) == "2016-06-03T12:04:39Z"


# ── gaps v timeline (spec AK) ───────────────────────────────────────────

def _rec(ts: datetime | None, amount: float = 1.0) -> ExchangeRecord:
    return ExchangeRecord(
        exchange="binance",
        kind="binance_deposits",
        record_type="deposit",
        timestamp=ts,
        amount=amount,
    )


T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


class TestFindTimelineGaps:
    def test_empty_and_single(self) -> None:
        assert find_timeline_gaps([]) == []
        assert find_timeline_gaps([_rec(T0)]) == []

    def test_no_gap_within_threshold(self) -> None:
        recs = [_rec(T0), _rec(T0 + timedelta(days=13, hours=23))]
        assert find_timeline_gaps(recs) == []

    def test_exact_threshold_not_a_gap(self) -> None:
        # přesně 14 dní — podmínka je striktní „> min"
        recs = [_rec(T0), _rec(T0 + timedelta(days=14))]
        assert find_timeline_gaps(recs, min_gap_days=14.0) == []

    def test_single_gap(self) -> None:
        start, end = T0, T0 + timedelta(days=30)
        recs = [_rec(start), _rec(end)]
        gaps = find_timeline_gaps(recs)
        assert len(gaps) == 1
        gap = gaps[0]
        assert gap["from"] == start.isoformat()
        assert gap["to"] == end.isoformat()
        assert gap["gap_days"] == pytest.approx(30.0)

    def test_unsorted_input_still_detected(self) -> None:
        recs = [_rec(T0 + timedelta(days=20)), _rec(T0)]
        gaps = find_timeline_gaps(recs, min_gap_days=14.0)
        assert len(gaps) == 1 and gaps[0]["gap_days"] == pytest.approx(20.0)

    def test_multiple_gaps_sorted(self) -> None:
        recs = [
            _rec(T0),
            _rec(T0 + timedelta(days=15)),
            _rec(T0 + timedelta(days=40)),  # druhá mezera 25 dní
        ]
        gaps = find_timeline_gaps(recs)
        assert len(gaps) == 2
        assert [g["gap_days"] for g in gaps] == [pytest.approx(15.0), pytest.approx(25.0)]

    def test_none_timestamp_ignored(self) -> None:
        recs = [_rec(None), _rec(T0 + timedelta(days=99)), _rec(T0)]
        gaps = find_timeline_gaps(recs)
        assert len(gaps) == 1 and gaps[0]["gap_days"] == pytest.approx(99.0)

    def test_custom_min_gap(self) -> None:
        recs = [_rec(T0), _rec(T0 + timedelta(days=8))]
        assert find_timeline_gaps(recs, min_gap_days=7.0) != []
        assert find_timeline_gaps(recs, min_gap_days=9.0) == []

    def test_rounding_two_decimals(self) -> None:
        recs = [_rec(T0), _rec(T0 + timedelta(days=1, hours=1))]
        gaps = find_timeline_gaps(recs, min_gap_days=0.5)
        assert len(gaps) == 1 and gaps[0]["gap_days"] == pytest.approx(1.04)
