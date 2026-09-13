"""Form 4 parser + mocked EDGAR fetch. No live sec.gov calls."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.edgar import fetch_form4_events, parse_form4_xml

FORM4 = """<?xml version="1.0"?>
<ownershipDocument>
  <issuer><issuerTradingSymbol>AAA</issuerTradingSymbol></issuer>
  <reportingOwner><reportingOwnerId>
    <rptOwnerCik>0000123456</rptOwnerCik>
    <rptOwnerName>DOE JANE</rptOwnerName>
  </reportingOwnerId></reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>2024-03-01</value></transactionDate>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>500</value></transactionShares>
        <transactionPricePerShare><value>10.5</value></transactionPricePerShare>
      </transactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <transactionDate><value>2024-03-02</value></transactionDate>
      <transactionCoding><transactionCode>A</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>999</value></transactionShares>
        <transactionPricePerShare><value>0</value></transactionPricePerShare>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>
"""


def test_parse_keeps_open_market_buy_drops_award():
    events = parse_form4_xml(FORM4)
    assert len(events) == 1
    assert events[0]["side"] == "buy"
    assert events[0]["ticker"] == "AAA"
    assert events[0]["insider_id"] == "0000123456"
    assert events[0]["shares"] == 500
    assert events[0]["notional"] == 5250.0


@pytest.mark.asyncio
async def test_fetch_requires_user_agent():
    with pytest.raises(ValueError, match="ATOM_SEC_USER_AGENT"):
        await fetch_form4_events("AAA", client=AsyncMock(), user_agent="no-email")


@pytest.mark.asyncio
async def test_fetch_parses_mocked_filings():
    async def _get(url, headers=None, timeout=None):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        if "company_tickers" in url:
            resp.json.return_value = {"0": {"ticker": "AAA", "cik_str": 123}}
            resp.text = ""
        elif "submissions" in url:
            resp.json.return_value = {
                "filings": {
                    "recent": {
                        "form": ["4", "10-K"],
                        "accessionNumber": ["0001-00", "0002"],
                        "primaryDocument": ["own.xml", "10k.htm"],
                    }
                }
            }
            resp.text = ""
        else:
            resp.text = FORM4
            resp.json.return_value = {}
        return resp

    client = MagicMock()
    client.get = _get
    out = await fetch_form4_events(
        "AAA", client=client, user_agent="ATOM Research desk@example.com", limit=4,
    )
    assert out["cik"] == "0000000123"
    assert out["n_filings"] == 1
    assert out["n_events"] == 1
    assert out["events"][0]["insider_id"] == "0000123456"
