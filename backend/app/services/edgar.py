"""
SEC EDGAR Form 4 parser and fetcher.

Open-market P/S transactions only — closer to Cohen, Malloy & Pomorski (2012)
than dumping every award and 10b5-1 sale. Live pulls require ATOM_SEC_USER_AGENT
(SEC fair-access rule). Tests parse fixtures; they never hit sec.gov.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from typing import Any

import httpx

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_ARCHIVES = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"

_OPEN_MARKET = {"P": "buy", "S": "sell"}


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1]


def _text(node: ET.Element | None) -> str:
    if node is None:
        return ""
    if node.text and node.text.strip():
        return node.text.strip()
    for child in node:
        if _local(child.tag) == "value" and child.text:
            return child.text.strip()
    return ""


def _find(node: ET.Element, name: str) -> ET.Element | None:
    for child in node.iter():
        if _local(child.tag) == name:
            return child
    return None


def parse_form4_xml(xml_text: str) -> list[dict]:
    """Extract open-market buy/sell lots from a Form 4 ownershipDocument."""
    root = ET.fromstring(xml_text)
    ticker_el = _find(root, "issuerTradingSymbol")
    ticker = _text(ticker_el).upper() or "UNKNOWN"
    # ElementTree elements with no children are falsy — never use `el or`.
    cik = _text(_find(root, "rptOwnerCik"))
    name = _text(_find(root, "rptOwnerName"))
    insider_id = cik or name or "unknown"
    events: list[dict] = []
    for txn in root.iter():
        if _local(txn.tag) != "nonDerivativeTransaction":
            continue
        code = _text(_find(txn, "transactionCode"))
        side = _OPEN_MARKET.get(code)
        if side is None:
            continue
        shares = float(_text(_find(txn, "transactionShares")) or 0)
        price = float(_text(_find(txn, "transactionPricePerShare")) or 0)
        date = _text(_find(txn, "transactionDate"))
        if shares <= 0 or not date:
            continue
        events.append({
            "ticker": ticker,
            "insider_id": insider_id,
            "side": side,
            "shares": shares,
            "date": date[:10],
            "notional": round(shares * price, 2) if price > 0 else shares,
            "transaction_code": code,
            "price": price,
        })
    return events


def _user_agent() -> str:
    return os.getenv("ATOM_SEC_USER_AGENT", "").strip()


def _headers(user_agent: str) -> dict[str, str]:
    return {
        "User-Agent": user_agent,
        "Accept-Encoding": "gzip, deflate",
    }


async def fetch_form4_events(
    ticker: str,
    *,
    client: httpx.AsyncClient,
    user_agent: str | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    """
    Look up CIK → recent Form 4 accessions → primary XML.

    `limit` is a filing cap, not an event cap. Amendments (4/A) are skipped.
    """
    ua = (user_agent or _user_agent()).strip()
    if not ua or "@" not in ua:
        raise ValueError(
            "Live EDGAR requires ATOM_SEC_USER_AGENT with a contact email "
            "(SEC fair-access User-Agent rule)."
        )
    ticker = ticker.upper().strip()
    if not re.fullmatch(r"[A-Z]{1,5}", ticker):
        raise ValueError("Ticker must be 1–5 letters")
    limit = max(1, min(int(limit), 15))

    tickers_resp = await client.get(
        SEC_TICKERS_URL,
        headers=_headers(ua),
        timeout=20.0,
    )
    tickers_resp.raise_for_status()
    mapping = tickers_resp.json()
    cik = None
    for row in mapping.values() if isinstance(mapping, dict) else mapping:
        if str(row.get("ticker", "")).upper() == ticker:
            cik = int(row["cik_str"])
            break
    if cik is None:
        raise ValueError(f"Ticker {ticker} not in SEC company_tickers.json")

    cik_pad = f"{cik:010d}"
    sub = await client.get(SEC_SUBMISSIONS_URL.format(cik=cik_pad), headers=_headers(ua), timeout=20.0)
    sub.raise_for_status()
    recent = sub.json().get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    documents = recent.get("primaryDocument", [])
    chosen: list[tuple[str, str]] = []
    for form, acc, doc in zip(forms, accessions, documents, strict=False):
        if form != "4":
            continue
        if not str(doc).lower().endswith(".xml"):
            continue
        chosen.append((acc.replace("-", ""), doc))
        if len(chosen) >= limit:
            break

    events: list[dict] = []
    filings_ok = 0
    parse_errors = 0
    for acc_nodash, doc in chosen:
        url = SEC_ARCHIVES.format(cik=cik, acc=acc_nodash, doc=doc)
        try:
            xml_resp = await client.get(url, headers=_headers(ua), timeout=20.0)
            xml_resp.raise_for_status()
            events.extend(parse_form4_xml(xml_resp.text))
            filings_ok += 1
        except (ET.ParseError, httpx.HTTPError, ValueError):
            parse_errors += 1

    return {
        "ticker": ticker,
        "cik": cik_pad,
        "n_filings": filings_ok,
        "n_parse_errors": parse_errors,
        "n_events": len(events),
        "events": events,
        "source": "sec_edgar_form4",
        "what_broke": [
            "Only non-derivative P/S lots; options exercises, gifts, and 10b5-1 (code A/M/F/G) are dropped.",
            "Amendments (4/A) skipped; late filings can rewrite the cluster after you already scored it.",
            "SEC rate limits and User-Agent are mandatory — this is not a scrape-the-world job.",
        ],
    }
