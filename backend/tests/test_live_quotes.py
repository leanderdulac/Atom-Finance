"""Tests for live_quotes — the health() staleness classifier is pure logic
worth testing directly; quote() is tested by mocking the Yahoo/Tradier
network boundary (yahoo_info, get_json)."""
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from app.services.live_quotes import health, quote
from app.services.market_sources import SourceError


def _iso(dt):
    return dt.isoformat()


class TestHealth:
    def test_recent_quote_with_full_book_is_recent(self):
        now = datetime.now(UTC)
        row = {
            'last_timestamp': _iso(now - timedelta(seconds=5)),
            'bid_timestamp': _iso(now - timedelta(seconds=5)),
            'ask_timestamp': _iso(now - timedelta(seconds=5)),
            'bid': 10.0, 'ask': 10.5,
        }
        result = health(row, now)
        assert result['last_status'] == 'recent'
        assert result['book_status'] == 'recent'

    def test_missing_last_timestamp_is_unknown_status(self):
        now = datetime.now(UTC)
        row = {'last_timestamp': None, 'bid_timestamp': None, 'ask_timestamp': None, 'bid': None, 'ask': None}
        result = health(row, now)
        assert result['last_status'] == 'unknown'

    def test_future_timestamp_is_flagged(self):
        now = datetime.now(UTC)
        row = {
            'last_timestamp': _iso(now + timedelta(minutes=5)),
            'bid_timestamp': None, 'ask_timestamp': None, 'bid': None, 'ask': None,
        }
        result = health(row, now)
        assert result['last_status'] == 'future'

    def test_old_timestamp_is_stale(self):
        now = datetime.now(UTC)
        row = {
            'last_timestamp': _iso(now - timedelta(minutes=10)),
            'bid_timestamp': None, 'ask_timestamp': None, 'bid': None, 'ask': None,
        }
        result = health(row, now)
        assert result['last_status'] == 'stale'

    def test_crossed_book_is_invalid(self):
        now = datetime.now(UTC)
        row = {
            'last_timestamp': _iso(now), 'bid_timestamp': _iso(now), 'ask_timestamp': _iso(now),
            'bid': 10.0, 'ask': 9.0,  # bid > ask — crossed/invalid book
        }
        result = health(row, now)
        assert result['book_status'] == 'invalid'

    def test_negative_bid_is_invalid(self):
        now = datetime.now(UTC)
        row = {
            'last_timestamp': _iso(now), 'bid_timestamp': _iso(now), 'ask_timestamp': _iso(now),
            'bid': -1.0, 'ask': 5.0,
        }
        result = health(row, now)
        assert result['book_status'] == 'invalid'

    def test_missing_bid_ask_timestamps_is_unknown_time(self):
        now = datetime.now(UTC)
        row = {
            'last_timestamp': _iso(now), 'bid_timestamp': None, 'ask_timestamp': None,
            'bid': 10.0, 'ask': 10.5,
        }
        result = health(row, now)
        assert result['book_status'] == 'unknown_time'

    def test_stale_bid_ask_timestamps_is_stale_or_future(self):
        now = datetime.now(UTC)
        row = {
            'last_timestamp': _iso(now), 'bid_timestamp': _iso(now - timedelta(minutes=5)),
            'ask_timestamp': _iso(now - timedelta(minutes=5)),
            'bid': 10.0, 'ask': 10.5,
        }
        result = health(row, now)
        assert result['book_status'] == 'stale_or_future'


@pytest.mark.asyncio
class TestQuoteYahoo:
    async def test_rejects_invalid_symbol_format(self):
        with pytest.raises(SourceError) as exc_info:
            await quote('yfinance', 'not a valid symbol!!', 'alice')
        assert exc_info.value.status == 422

    async def test_returns_quote_on_success(self):
        info = {
            'symbol': 'PETR4.SA', 'currency': 'BRL', 'exchange': 'SAO', 'quoteType': 'EQUITY',
            'regularMarketPrice': 38.5, 'bid': 38.4, 'ask': 38.6,
            'bidSize': 100, 'askSize': 200, 'regularMarketTime': 1700000000,
            'exchangeDataDelayedBy': 0,
        }
        with patch('app.services.live_quotes.yahoo_info', return_value=info):
            result = await quote('yfinance', 'PETR4.SA', 'alice')
        assert result['provider'] == 'yfinance'
        assert result['quote']['symbol'] == 'PETR4.SA'
        assert result['quote']['last'] == 38.5
        assert result['data_mode'] == 'unverified'

    async def test_raises_when_yahoo_call_fails(self):
        with patch('app.services.live_quotes.yahoo_info', side_effect=RuntimeError("rate limited")):
            with pytest.raises(SourceError) as exc_info:
                await quote('yfinance', 'PETR4.SA', 'alice')
        assert exc_info.value.status == 502

    async def test_raises_when_symbol_mismatch(self):
        with patch('app.services.live_quotes.yahoo_info', return_value={'symbol': 'OTHER'}):
            with pytest.raises(SourceError) as exc_info:
                await quote('yfinance', 'PETR4.SA', 'alice')
        assert exc_info.value.status == 502

    async def test_raises_when_no_usable_prices(self):
        info = {'symbol': 'PETR4.SA', 'regularMarketPrice': None, 'bid': None, 'ask': None}
        with patch('app.services.live_quotes.yahoo_info', return_value=info):
            with pytest.raises(SourceError) as exc_info:
                await quote('yfinance', 'PETR4.SA', 'alice')
        assert exc_info.value.status == 502


@pytest.mark.asyncio
class TestQuoteTradier:
    async def test_rejects_when_owner_not_authorized(self, monkeypatch):
        monkeypatch.setenv('TRADIER_OWNER', 'bob')
        with pytest.raises(SourceError) as exc_info:
            await quote('tradier', 'AAPL', 'alice')
        assert exc_info.value.status == 403

    async def test_rejects_when_token_missing(self, monkeypatch):
        monkeypatch.setenv('TRADIER_OWNER', 'alice')
        monkeypatch.setenv('TRADIER_ACCESS_TOKEN', '')
        with pytest.raises(SourceError) as exc_info:
            await quote('tradier', 'AAPL', 'alice')
        assert exc_info.value.status == 503

    async def test_returns_quote_on_success(self, monkeypatch):
        monkeypatch.setenv('TRADIER_OWNER', 'alice')
        monkeypatch.setenv('TRADIER_ACCESS_TOKEN', 'tok123')
        monkeypatch.setenv('TRADIER_ENV', 'sandbox')
        raw = {'quotes': {'quote': {
            'symbol': 'AAPL', 'exch': 'Q', 'type': 'stock',
            'last': 225.0, 'bid': 224.9, 'ask': 225.1, 'bidsize': 1, 'asksize': 2,
            'trade_date': 1700000000000, 'bid_date': 1700000000000, 'ask_date': 1700000000000,
        }}}
        with patch('app.services.live_quotes.get_json', return_value=raw):
            result = await quote('tradier', 'AAPL', 'alice')
        assert result['quote']['symbol'] == 'AAPL'
        assert result['quote']['last'] == 225.0
        assert result['data_mode'] == 'delayed'  # sandbox env

    async def test_raises_on_ambiguous_quote_list(self, monkeypatch):
        monkeypatch.setenv('TRADIER_OWNER', 'alice')
        monkeypatch.setenv('TRADIER_ACCESS_TOKEN', 'tok123')
        raw = {'quotes': {'quote': [{'symbol': 'AAPL'}, {'symbol': 'AAPL'}]}}
        with patch('app.services.live_quotes.get_json', return_value=raw):
            with pytest.raises(SourceError) as exc_info:
                await quote('tradier', 'AAPL', 'alice')
        assert exc_info.value.status == 502


@pytest.mark.asyncio
class TestQuoteUnsupportedProvider:
    async def test_raises_422(self):
        with pytest.raises(SourceError) as exc_info:
            await quote('unknown_provider', 'AAPL', 'alice')
        assert exc_info.value.status == 422
