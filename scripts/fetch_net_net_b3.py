"""Download the public files for the B3 net-net study.

Writes a cache directory (default ``data/net-net``). This script is the only
piece that opens a socket. Unit tests do not import it.

Sources, all without an API key:
- CVM DFP, ITR, FCA and FRE, including cancelled registrants
- CVM company registry
- B3 COTAHIST annual files (cash equities, delisted names included)
- Tesouro Transparente prefixado yields
- Yahoo Finance chart for the Ibovespa price index
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

CVM = "https://dados.cvm.gov.br/dados/CIA_ABERTA"
COTAHIST = "https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A{year}.ZIP"
TESOURO = (
    "https://www.tesourotransparente.gov.br/ckan/dataset/"
    "df56aa42-484a-4a59-8184-7676580c81e3/resource/"
    "796d2059-14e9-44e3-80c9-2d9e30b405c1/download/PrecoTaxaTesouroDireto.csv"
)
IBOV = "https://query1.finance.yahoo.com/v8/finance/chart/%5EBVSP?interval=1d&range=max"
UA = "atom-finance-research/net-net"


def _get(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        print(f"have {dest.name}")
        return
    print(f"get  {url}")
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=180) as response, dest.open("wb") as handle:
        while True:
            chunk = response.read(1 << 20)
            if not chunk:
                break
            handle.write(chunk)


def main() -> None:
    parser = argparse.ArgumentParser(description="Download CVM, COTAHIST, Tesouro and Ibovespa files.")
    parser.add_argument("--cache", type=Path, default=Path("data/net-net"))
    parser.add_argument("--start", type=int, default=2010)
    parser.add_argument("--end", type=int, default=2026)
    args = parser.parse_args()
    cache: Path = args.cache
    _get(f"{CVM}/CAD/DADOS/cad_cia_aberta.csv", cache / "cad_cia_aberta.csv")
    _get(TESOURO, cache / "tesouro.csv")
    _get(IBOV, cache / "ibov.json")
    for year in range(args.start, args.end + 1):
        for kind in ("dfp", "itr", "fca"):
            if kind == "itr" and year < 2011:
                continue
            url = f"{CVM}/DOC/{kind.upper()}/DADOS/{kind}_cia_aberta_{year}.zip"
            _get(url, cache / kind / f"{kind}_{year}.zip")
        if year >= 2011:
            _get(COTAHIST.format(year=year), cache / "cotahist" / f"COTAHIST_A{year}.ZIP")
        _get(
            f"{CVM}/DOC/FRE/DADOS/fre_cia_aberta_{year}.zip",
            cache / "fre" / f"fre_{year}.zip",
        )
    print(f"cache {cache.resolve()}")


if __name__ == "__main__":
    main()
