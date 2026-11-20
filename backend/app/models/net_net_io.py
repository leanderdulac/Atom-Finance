"""Parsers for the B3 net-net study. No network calls.

CVM open-data files are latin-1, semicolon-separated. COTAHIST is the B3
fixed-width daily file (record type 01). Tesouro Transparente uses a comma
decimal. Callers pass paths or text; nothing here downloads.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np

from app.models.net_net import (
    BsPoint,
    Company,
    EarnRow,
    SharePoint,
    Tape,
    confirmed_split_factors,
)

ACCOUNTS = frozenset({"1.01", "2.01", "2.02", "2.03.01", "3.09", "3.11"})


def _norm_header(header: list[str]) -> list[str]:
    return [cell.strip().lstrip("\ufeff").lower() for cell in header]


def _idx(header: list[str], *names: str) -> int | None:
    normalized = _norm_header(header)
    for name in names:
        key = name.lower()
        if key in normalized:
            return normalized.index(key)
    return None


def _date_ord(value: str) -> int | None:
    text = (value or "").strip()
    if len(text) < 10:
        return None
    chunk = text[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(chunk, fmt).date().toordinal()
        except ValueError:
            continue
    return None


def _float_dot(value: str) -> float | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _float_comma(value: str) -> float | None:
    text = (value or "").strip().replace(".", "").replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _scale(token: str) -> float:
    text = (token or "").strip().upper()
    if "MIL" in text:
        return 1_000.0
    return 1.0


def _rows(text: str):
    reader = csv.reader(io.StringIO(text), delimiter=";")
    try:
        header = next(reader)
    except StopIteration:
        return
    for row in reader:
        if row:
            yield header, row


def parse_document_header(text: str) -> dict[tuple[str, int, int], int]:
    """``(cnpj, dt_refer, versao) -> DT_RECEB`` ordinal."""
    out: dict[tuple[str, int, int], int] = {}
    for header, row in _rows(text):
        i_cnpj = _idx(header, "cnpj_cia", "cnpj_companhia")
        i_ref = _idx(header, "dt_refer", "data_referencia")
        i_ver = _idx(header, "versao", "versão")
        i_rec = _idx(header, "dt_receb", "data_recebimento")
        if None in (i_cnpj, i_ref, i_ver, i_rec):
            break
        if max(i_cnpj, i_ref, i_ver, i_rec) >= len(row):
            continue
        refer = _date_ord(row[i_ref])
        received = _date_ord(row[i_rec])
        if refer is None or received is None:
            continue
        try:
            version = int(float(row[i_ver]))
        except ValueError:
            continue
        out[(row[i_cnpj].strip(), refer, version)] = received
    return out


def parse_capital(text: str, receipts: dict[tuple[str, int, int], int]) -> list[tuple]:
    """Rows of ``(cnpj, received, period_end, on_out, pn_sub, total_sub, pn_out)``."""
    out = []
    for header, row in _rows(text):
        i_cnpj = _idx(header, "cnpj_cia")
        i_ref = _idx(header, "dt_refer")
        i_ver = _idx(header, "versao")
        i_on = _idx(header, "qt_acao_ordin_cap_integr")
        i_pn = _idx(header, "qt_acao_pref_cap_integr")
        i_tot = _idx(header, "qt_acao_total_cap_integr")
        i_on_t = _idx(header, "qt_acao_ordin_tesouro")
        i_pn_t = _idx(header, "qt_acao_pref_tesouro")
        if None in (i_cnpj, i_ref, i_ver, i_on, i_pn, i_tot, i_on_t, i_pn_t):
            break
        needed = (i_cnpj, i_ref, i_ver, i_on, i_pn, i_tot, i_on_t, i_pn_t)
        if max(needed) >= len(row):
            continue
        refer = _date_ord(row[i_ref])
        if refer is None:
            continue
        try:
            version = int(float(row[i_ver]))
        except ValueError:
            continue
        received = receipts.get((row[i_cnpj].strip(), refer, version))
        if received is None:
            continue
        on_i = _float_dot(row[i_on]) or 0.0
        pn_i = _float_dot(row[i_pn]) or 0.0
        tot_i = _float_dot(row[i_tot]) or 0.0
        on_t = _float_dot(row[i_on_t]) or 0.0
        pn_t = _float_dot(row[i_pn_t]) or 0.0
        on_out = on_i - on_t
        pn_out = pn_i - pn_t
        if on_out <= 0 or tot_i <= 0:
            continue
        out.append((row[i_cnpj].strip(), received, refer, on_out, pn_i, tot_i, max(pn_out, 0.0)))
    return out


_FRE_CAPITAL_RANK = {
    "capital integralizado": 0,
    "capital subscrito": 1,
    "capital emitido": 2,
}


def parse_fre_shares(header_text: str, capital_text: str, treasury_text: str | None = None) -> list[tuple]:
    """Share counts from the Formulário de Referência.

    DFP zips have no ``composicao_capital`` before 2020. The FRE reports
    integrated (else subscribed, else issued) shares and is public only on
    ``DT_RECEB``. Authorized capital is the ceiling, not the shares outstanding.
    Treasury is the latest exercise-end balance in the FRE movement schedule
    when that balance is smaller than the class it belongs to.
    """
    receipts = parse_document_header(header_text)
    best: dict[tuple[str, int, int], tuple[int, float, float, float]] = {}
    for header, row in _rows(capital_text):
        i_cnpj = _idx(header, "cnpj_companhia", "cnpj_cia")
        i_ref = _idx(header, "data_referencia", "dt_refer")
        i_ver = _idx(header, "versao")
        i_tipo = _idx(header, "tipo_capital")
        i_on = _idx(header, "quantidade_acoes_ordinarias")
        i_pn = _idx(header, "quantidade_acoes_preferenciais")
        i_tot = _idx(header, "quantidade_total_acoes")
        if None in (i_cnpj, i_ref, i_ver, i_tipo, i_on, i_pn, i_tot):
            break
        if max(i_cnpj, i_ref, i_ver, i_tipo, i_on, i_pn, i_tot) >= len(row):
            continue
        refer = _date_ord(row[i_ref])
        if refer is None:
            continue
        try:
            version = int(float(row[i_ver]))
        except ValueError:
            continue
        rank = _FRE_CAPITAL_RANK.get(row[i_tipo].strip().lower())
        if rank is None:
            continue
        on_i = _float_dot(row[i_on]) or 0.0
        pn_i = _float_dot(row[i_pn]) or 0.0
        tot_i = _float_dot(row[i_tot]) or 0.0
        if tot_i <= 0 or on_i <= 0:
            continue
        key = (row[i_cnpj].strip(), refer, version)
        prev = best.get(key)
        if prev is None or rank < prev[0]:
            best[key] = (rank, on_i, pn_i, tot_i)
    treasury = _fre_treasury(treasury_text) if treasury_text else {}
    out = []
    for (cnpj, refer, version), (_rank, on_i, pn_i, tot_i) in best.items():
        received = receipts.get((cnpj, refer, version))
        if received is None:
            continue
        on_t, pn_t = treasury.get((cnpj, refer, version), (0.0, 0.0))
        if on_t < 0 or on_t >= on_i:
            on_t = 0.0
        if pn_t < 0 or pn_t > pn_i:
            pn_t = 0.0
        on_out = on_i - on_t
        if on_out <= 0:
            continue
        out.append((cnpj, received, refer, on_out, pn_i, tot_i, max(pn_i - pn_t, 0.0)))
    return out


def _fre_treasury(text: str) -> dict[tuple[str, int, int], tuple[float, float]]:
    """Latest exercise-end treasury shares, ordinary and preferred, by filing version."""
    latest: dict[tuple[str, int, int, str], tuple[int, float]] = {}
    for header, row in _rows(text):
        i_cnpj = _idx(header, "cnpj_companhia", "cnpj_cia")
        i_ref = _idx(header, "data_referencia", "dt_refer")
        i_ver = _idx(header, "versao")
        i_fim = _idx(header, "data_fim_exercicio_social")
        i_kind = _idx(header, "valor_mobiliario")
        i_esp = _idx(header, "especie_acao")
        i_qty = _idx(header, "quantidade_final")
        if None in (i_cnpj, i_ref, i_ver, i_fim, i_esp, i_qty):
            break
        if max(i_cnpj, i_ref, i_ver, i_fim, i_esp, i_qty) >= len(row):
            continue
        if i_kind is not None and i_kind < len(row):
            security = row[i_kind].strip().lower()
            if security and "acao" not in security and "aç" not in security:
                continue
        refer = _date_ord(row[i_ref])
        end = _date_ord(row[i_fim])
        if refer is None or end is None:
            continue
        try:
            version = int(float(row[i_ver]))
        except ValueError:
            continue
        especie = row[i_esp].strip().lower()
        if "ordin" in especie:
            kind = "on"
        elif "preferen" in especie:
            kind = "pn"
        else:
            continue
        qty = _float_dot(row[i_qty]) or 0.0
        key = (row[i_cnpj].strip(), refer, version, kind)
        prev = latest.get(key)
        if prev is None or end > prev[0]:
            latest[key] = (end, qty)
        elif end == prev[0]:
            latest[key] = (end, prev[1] + qty)
    folded: dict[tuple[str, int, int], tuple[float, float]] = {}
    for (cnpj, refer, version, kind), (_end, qty) in latest.items():
        on_t, pn_t = folded.get((cnpj, refer, version), (0.0, 0.0))
        if kind == "on":
            on_t = qty
        else:
            pn_t = qty
        folded[(cnpj, refer, version)] = (on_t, pn_t)
    return folded


def parse_statement(text: str, consolidated: bool) -> list[tuple]:
    """Account rows. Balance-sheet rows have no start date (``start is None``)."""
    out = []
    cached: tuple | None = None
    for header, row in _rows(text):
        if cached is None:
            cached = (
                _idx(header, "cnpj_cia"),
                _idx(header, "dt_refer"),
                _idx(header, "versao"),
                _idx(header, "escala_moeda"),
                _idx(header, "ordem_exerc"),
                _idx(header, "dt_ini_exerc"),
                _idx(header, "dt_fim_exerc"),
                _idx(header, "cd_conta"),
                _idx(header, "vl_conta"),
            )
            if cached[0] is None or cached[7] is None or cached[8] is None:
                return out
        i_cnpj, i_ref, i_ver, i_esc, i_ord, i_ini, i_fim, i_cd, i_vl = cached
        if i_cd >= len(row) or i_vl >= len(row):
            continue
        code = row[i_cd].strip()
        # 3.99.01.* is basic earnings per share in reais, not in the statement's
        # MIL/UNIDADE scale. The parent 3.99.01 line is a heading and is ignored.
        is_eps = code.startswith("3.99.01.") and code.count(".") >= 3
        if code not in ACCOUNTS and not is_eps:
            continue
        if i_ord is not None and i_ord < len(row):
            ordem = row[i_ord].upper()
            if "LTIMO" not in ordem:
                continue
        refer = _date_ord(row[i_ref]) if i_ref is not None and i_ref < len(row) else None
        end = _date_ord(row[i_fim]) if i_fim is not None and i_fim < len(row) else refer
        start = _date_ord(row[i_ini]) if i_ini is not None and i_ini < len(row) else None
        if refer is None or end is None:
            continue
        try:
            version = int(float(row[i_ver])) if i_ver is not None and i_ver < len(row) else 1
        except ValueError:
            continue
        value = _float_dot(row[i_vl])
        if value is None:
            continue
        scale = _scale(row[i_esc]) if i_esc is not None and i_esc < len(row) else 1.0
        if not is_eps:
            value *= scale
        out.append(
            (row[i_cnpj].strip(), refer, version, start, end, code, value, consolidated)
        )
    return out


def parse_fca_tickers(text: str) -> list[tuple[str, str, int, int | None]]:
    """``(cnpj, ticker, start, end)`` for common shares listed on the exchange."""
    out = []
    cached = None
    for header, row in _rows(text):
        if cached is None:
            cached = (
                _idx(header, "cnpj_companhia", "cnpj_cia", "cnpj"),
                _idx(header, "codigo_negociacao", "cod_negociacao"),
                _idx(header, "valor_mobiliario"),
                _idx(header, "mercado"),
                _idx(header, "data_inicio_negociacao"),
                _idx(header, "data_fim_negociacao"),
            )
            if cached[0] is None or cached[1] is None or cached[2] is None:
                return out
        i_cnpj, i_tic, i_val, i_mkt, i_ini, i_fim = cached
        if i_tic >= len(row) or i_val >= len(row):
            continue
        kind = row[i_val].lower()
        if "ordin" not in kind:
            continue
        if i_mkt is not None and i_mkt < len(row) and row[i_mkt].strip() not in ("", "Bolsa"):
            continue
        ticker = row[i_tic].strip().upper()
        if not ticker or len(ticker) > 8:
            continue
        start = _date_ord(row[i_ini]) if i_ini is not None and i_ini < len(row) else None
        end = _date_ord(row[i_fim]) if i_fim is not None and i_fim < len(row) else None
        if start is None:
            start = date(1990, 1, 1).toordinal()
        out.append((row[i_cnpj].strip(), ticker, start, end))
    return out


def parse_cadastro(text: str) -> list[tuple[str, str, str, str]]:
    """``(cnpj, denom, setor, sit)``."""
    out = []
    for header, row in _rows(text):
        i_cnpj = _idx(header, "cnpj_cia")
        i_denom = _idx(header, "denom_social")
        i_setor = _idx(header, "setor_ativ")
        i_sit = _idx(header, "sit")
        if None in (i_cnpj, i_denom, i_setor, i_sit):
            break
        if i_sit >= len(row):
            continue
        out.append((row[i_cnpj].strip(), row[i_denom].strip(), row[i_setor].strip(), row[i_sit].strip()))
    return out


def parse_cotahist_line(line: str) -> dict | None:
    """One COTAHIST type-01 cash-equity print, or None.

    Layout is the B3 historical-quote record (positions documented in
    ``SeriesHistoricas_Layout``): type, date, BDI, ticker, market, prices in
    cents, share quantity, financial volume in cents. Only the standard lot
    (BDI 02) of the cash market (TPMERC 010) is a usable print.
    """
    raw = line.rstrip("\r\n")
    if len(raw) < 245 or raw[0:2] != "01":
        return None
    if raw[10:12] != "02" or raw[24:27] != "010":
        return None
    try:
        ordinal = datetime.strptime(raw[2:10], "%Y%m%d").date().toordinal()
        close = int(raw[108:121]) / 100.0
        bid = int(raw[121:134]) / 100.0
        ask = int(raw[134:147]) / 100.0
        qty = int(raw[152:170])
        vol = int(raw[170:188]) / 100.0
    except ValueError:
        return None
    ticker = raw[12:24].strip().upper()
    if not ticker or close <= 0:
        return None
    return {
        "date": ordinal,
        "ticker": ticker,
        "close": close,
        "bid": bid,
        "ask": ask,
        "qty": float(qty),
        "vol": vol,
    }


def iter_cotahist_zip(path: Path):
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if not name.endswith("/")]
        if not names:
            return
        with archive.open(names[0]) as handle:
            for raw in handle:
                line = raw.decode("latin-1", errors="replace")
                parsed = parse_cotahist_line(line)
                if parsed is not None:
                    yield parsed


def yields_from_tesouro(text: str) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Nominal Tesouro Prefixado yields, decimal per base date.

    ``pre_5y`` is the prefixado title (zero or semiannual) whose maturity is
    closest to five years, preferring the 3-to-8-year window. ``pre_long`` is
    the longest prefixado maturity that day. The yield is the mid of the
    Tesouro Direto morning buy and sell rates. IPCA+ titles are real yields
    and are not returned: a nominal P/E cap cannot use them raw.
    """
    by_day: dict[int, list[tuple[int, float]]] = defaultdict(list)
    reader = csv.reader(io.StringIO(text), delimiter=";")
    try:
        header = next(reader)
    except StopIteration:
        return _empty_yields()
    normalized = _norm_header(header)
    def col(*names: str) -> int:
        for name in names:
            if name in normalized:
                return normalized.index(name)
        raise ValueError(f"tesouro column missing: {names}")
    try:
        i_type = col("tipo titulo")
        i_mat = col("data vencimento")
        i_base = col("data base")
        i_buy = col("taxa compra manha")
        i_sell = col("taxa venda manha")
    except ValueError:
        return _empty_yields()
    for row in reader:
        if len(row) <= i_sell:
            continue
        title = row[i_type].strip().lower()
        if not title.startswith("tesouro prefixado"):
            continue
        base = _date_ord(row[i_base])
        maturity = _date_ord(row[i_mat])
        buy = _float_comma(row[i_buy])
        sell = _float_comma(row[i_sell])
        if None in (base, maturity, buy, sell):
            continue
        mid = (buy + sell) / 2.0 / 100.0
        if mid <= 0 or maturity <= base:
            continue
        by_day[base].append((maturity, mid))
    five_d, five_y, long_d, long_y = [], [], [], []
    for base in sorted(by_day):
        options = by_day[base]
        longest = max(options, key=lambda item: item[0])
        long_d.append(base)
        long_y.append(longest[1])
        target = base + int(365.25 * 5)
        window = [item for item in options if base + int(365.25 * 3) <= item[0] <= base + int(365.25 * 8)]
        pool = window or [item for item in options if item[0] - base >= int(365.25 * 2)] or options
        chosen = min(pool, key=lambda item: abs(item[0] - target))
        five_d.append(base)
        five_y.append(chosen[1])
    return {
        "pre_5y": (np.asarray(five_d, dtype=np.int64), np.asarray(five_y, dtype=np.float64)),
        "pre_long": (np.asarray(long_d, dtype=np.int64), np.asarray(long_y, dtype=np.float64)),
    }


def _empty_yields() -> dict[str, tuple[np.ndarray, np.ndarray]]:
    empty_i = np.asarray([], dtype=np.int64)
    empty_f = np.asarray([], dtype=np.float64)
    return {"pre_5y": (empty_i, empty_f), "pre_long": (empty_i.copy(), empty_f.copy())}


def parse_yahoo_chart(text: str) -> tuple[np.ndarray, np.ndarray]:
    payload = json.loads(text)
    result = payload["chart"]["result"][0]
    stamps = result.get("timestamp") or []
    quote = result["indicators"]["quote"][0]["close"]
    ords, closes = [], []
    for stamp, close in zip(stamps, quote, strict=False):
        if close is None:
            continue
        ordinal = datetime.fromtimestamp(int(stamp), UTC).date().toordinal()
        ords.append(ordinal)
        closes.append(float(close))
    return np.asarray(ords, dtype=np.int64), np.asarray(closes, dtype=np.float64)


def _zip_member(archive: zipfile.ZipFile, name: str) -> str:
    with archive.open(name) as handle:
        return handle.read().decode("latin-1")


def _fre_capital_rows(path: Path) -> list[tuple]:
    """Capital rows from one FRE zip. Empty when the vintage has no share schedule."""
    with zipfile.ZipFile(path) as archive:
        header_name = capital_name = treasury_name = None
        for name in archive.namelist():
            base = name.lower().split("/")[-1]
            if not base.endswith(".csv"):
                continue
            if base.startswith("fre_cia_aberta_") and base.count("_") == 3:
                header_name = name
            elif "capital_social_" in base and base.count("_") == 5:
                capital_name = name
            elif "tesouraria_movimentacao" in base:
                treasury_name = name
        if header_name is None or capital_name is None:
            return []
        treasury = _zip_member(archive, treasury_name) if treasury_name else None
        return parse_fre_shares(
            _zip_member(archive, header_name),
            _zip_member(archive, capital_name),
            treasury,
        )


def _ingest_filing_zip(path: Path, kind: str, receipts, capital_rows, bs, earn) -> None:
    """Read one DFP or ITR zip once. Header receipts are applied before the statements."""
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        header_names = []
        other = []
        for name in names:
            lower = name.lower()
            if not lower.endswith(".csv"):
                continue
            if any(token in lower for token in ("bpa", "bpp", "dre", "dfc", "dmpl", "dva", "dra", "parecer", "composicao", "capital")):
                other.append(name)
            elif f"{kind}_cia_aberta_" in lower:
                header_names.append(name)
        for name in header_names:
            receipts.update(parse_document_header(_zip_member(archive, name)))
        for name in other:
            lower = name.lower()
            text = _zip_member(archive, name)
            if "composicao_capital" in lower:
                capital_rows.extend(parse_capital(text, receipts))
            elif any(token in lower for token in ("bpa_", "bpp_", "dre_")):
                _accumulate_statements(text, "_con_" in lower, receipts, bs, earn)


def _accumulate_statements(text: str, consolidated: bool, receipts, bs, earn) -> None:
    for cnpj, refer, version, start, end, code, value, is_con in parse_statement(text, consolidated):
        received = receipts.get((cnpj, refer, version))
        if received is None:
            continue
        if code in ("1.01", "2.01", "2.02", "2.03.01"):
            slot = bs[is_con].setdefault((cnpj, received, end), {})
            slot[{"1.01": "ca", "2.01": "cl", "2.02": "ltl", "2.03.01": "capital"}[code]] = value
        elif code.startswith("3.99"):
            slot = earn[is_con].setdefault((cnpj, received, start or end, end), {})
            previous = slot.get("eps")
            if previous is None or abs(value) > abs(previous):
                slot["eps"] = value
        else:
            slot = earn[is_con].setdefault((cnpj, received, start or end, end), {})
            slot[code] = value


def assemble_companies(
    cadastro: list[tuple[str, str, str, str]],
    receipts: dict[tuple[str, int, int], int],
    capital_rows: list[tuple],
    bs_partial: dict[bool, dict],
    earn_partial: dict[bool, dict],
    ticker_rows: list[tuple[str, str, int, int | None]],
) -> list[Company]:
    by_cnpj: dict[str, Company] = {}
    for cnpj, denom, setor, sit in cadastro:
        by_cnpj[cnpj] = Company(
            cnpj=cnpj,
            denom=denom,
            setor=setor,
            sit=sit,
            bs_con=[],
            bs_ind=[],
            shares=[],
            er_con=[],
            er_ind=[],
            tickers=[],
        )
    for consolidated, table in bs_partial.items():
        for (cnpj, received, end), fields in table.items():
            if "ca" not in fields or "cl" not in fields or "ltl" not in fields:
                continue
            company = by_cnpj.get(cnpj)
            if company is None:
                continue
            point = BsPoint(
                period_end=end,
                received=received,
                ca=fields["ca"],
                cl=fields["cl"],
                ltl=fields["ltl"],
                capital=fields.get("capital"),
            )
            (company.bs_con if consolidated else company.bs_ind).append(point)
    for consolidated, table in earn_partial.items():
        for (cnpj, received, start, end), fields in table.items():
            ni = fields.get("3.11", fields.get("3.09"))
            if ni is None:
                continue
            company = by_cnpj.get(cnpj)
            if company is None:
                continue
            row = EarnRow(start, end, received, ni, fields.get("eps"))
            (company.er_con if consolidated else company.er_ind).append(row)
    # Latest receipt wins when two versions share a period end and a receipt day.
    share_best: dict[tuple[str, int, int], tuple] = {}
    for cnpj, received, end, on_out, pn_sub, total_sub, pn_out in capital_rows:
        key = (cnpj, received, end)
        share_best[key] = (on_out, pn_sub, total_sub, pn_out)
    for (cnpj, received, end), values in share_best.items():
        company = by_cnpj.get(cnpj)
        if company is None:
            continue
        company.shares.append(SharePoint(end, received, *values))
    # Ticker intervals: open-ended if any vintage left the end date blank.
    spans: dict[tuple[str, str], list[tuple[int, int | None]]] = defaultdict(list)
    for cnpj, ticker, start, end in ticker_rows:
        spans[(cnpj, ticker)].append((start, end))
    for (cnpj, ticker), intervals in spans.items():
        company = by_cnpj.get(cnpj)
        if company is None:
            continue
        start = min(item[0] for item in intervals)
        if any(item[1] is None for item in intervals):
            end = None
        else:
            end = max(item[1] for item in intervals if item[1] is not None)
        company.tickers.append((ticker, start, end))
    companies = list(by_cnpj.values())
    for company in companies:
        company.bs_con.sort(key=lambda point: (point.period_end, point.received))
        company.bs_ind.sort(key=lambda point: (point.period_end, point.received))
        company.shares.sort(key=lambda point: (point.period_end, point.received))
        company.er_con.sort(key=lambda row: (row.end, row.received))
        company.er_ind.sort(key=lambda row: (row.end, row.received))
    return companies


def rescale_share_counts(companies: list[Company]) -> int:
    """Some registrants file composicao_capital in thousands of shares and some in units.

    The file has no scale column. Earnings per share (3.99.01, reais per share) over
    net income distinguishes a factor of 1 from a factor of 1,000. When EPS is missing
    or the ratio is ambiguous, a par above R$2,000 (capital social / shares) is treated
    as the thousands scale. Over-scaling drops a name from the net-net screen; under-scaling
    would invent one, so the fallback only scales up.
    """
    n_scaled = 0
    for company in companies:
        earnings = list(company.er_con) + list(company.er_ind)
        scaled: list[SharePoint] = []
        for point in company.shares:
            factor = _share_factor(point, earnings, company.bs_con + company.bs_ind)
            if factor != 1.0:
                n_scaled += 1
                point = SharePoint(
                    point.period_end,
                    point.received,
                    point.on_out * factor,
                    point.pn_subscribed * factor,
                    point.total_subscribed * factor,
                    point.pn_out * factor,
                )
            scaled.append(point)
        company.shares = scaled
    return n_scaled


def _share_factor(point: SharePoint, earnings: list[EarnRow], balance: list[BsPoint]) -> float:
    if point.total_subscribed <= 0:
        return 1.0
    best: EarnRow | None = None
    for row in earnings:
        if row.eps is None or row.eps == 0 or row.ni == 0:
            continue
        if abs(row.end - point.period_end) > 20:
            continue
        if best is None or abs(row.end - point.period_end) < abs(best.end - point.period_end):
            best = row
    if best is not None and best.eps:
        ratio = abs(best.ni) / abs(best.eps) / point.total_subscribed
        if 400.0 <= ratio <= 2_500.0:
            return 1_000.0
        if 0.4 <= ratio <= 2.5:
            return 1.0
    capital = None
    for item in balance:
        if abs(item.period_end - point.period_end) > 20 or item.capital is None or item.capital <= 0:
            continue
        capital = item.capital
        break
    if capital is None:
        return 1.0
    par = capital / point.total_subscribed
    if par > 2_000.0:
        return 1_000.0
    return 1.0


def tapes_from_prints(
    prints: dict[str, dict[int, tuple[float, float, float, float, float]]],
    share_events: dict[str, tuple[list[int], list[float]]],
) -> tuple[dict[str, Tape], int]:
    """Build tapes and return how many prints were reclassified as splits."""
    tapes: dict[str, Tape] = {}
    n_splits = 0
    for ticker, by_day in prints.items():
        ords = sorted(by_day)
        if len(ords) < 2:
            continue
        close = np.array([by_day[day][0] for day in ords], dtype=np.float64)
        bid = np.array([by_day[day][1] for day in ords], dtype=np.float64)
        ask = np.array([by_day[day][2] for day in ords], dtype=np.float64)
        qty = np.array([by_day[day][3] for day in ords], dtype=np.float64)
        vol = np.array([by_day[day][4] for day in ords], dtype=np.float64)
        dates = np.array(ords, dtype=np.int64)
        events = share_events.get(ticker)
        if events is None:
            split = np.ones(len(dates), dtype=np.float64)
        else:
            split = confirmed_split_factors(dates, close, events[0], events[1])
        n_splits += int(np.sum(np.abs(split - 1.0) > 1e-8))
        tapes[ticker] = Tape(dates, close, bid, ask, qty, vol, split)
    return tapes, n_splits


def session_calendar(tapes: dict[str, Tape], min_names: int = 25) -> list[int]:
    counts: dict[int, int] = defaultdict(int)
    for tape in tapes.values():
        for ordinal in tape.dates:
            counts[int(ordinal)] += 1
    if not counts:
        return []
    floor = min(min_names, max(1, len(tapes) // 10))
    return sorted(day for day, count in counts.items() if count >= floor)


def load_bundle(cache: Path) -> dict:
    """Read a cache directory produced by ``scripts/fetch_net_net_b3.py``."""
    cache = Path(cache)
    cad_path = cache / "cad_cia_aberta.csv"
    cadastro = parse_cadastro(cad_path.read_text(encoding="latin-1"))
    receipts: dict[tuple[str, int, int], int] = {}
    capital_rows: list[tuple] = []
    bs: dict[bool, dict] = {True: {}, False: {}}
    earn: dict[bool, dict] = {True: {}, False: {}}
    tickers: list[tuple[str, str, int, int | None]] = []
    for kind in ("dfp", "itr"):
        folder = cache / kind
        if not folder.exists():
            continue
        for path in sorted(folder.glob("*.zip")):
            print(f"ingest {path.name}", flush=True)
            _ingest_filing_zip(path, kind, receipts, capital_rows, bs, earn)
    fre = cache / "fre"
    if fre.exists():
        for path in sorted(fre.glob("*.zip")):
            print(f"ingest {path.name}", flush=True)
            capital_rows.extend(_fre_capital_rows(path))
    fca = cache / "fca"
    if fca.exists():
        for path in sorted(fca.glob("*.zip")):
            with zipfile.ZipFile(path) as archive:
                for name in archive.namelist():
                    if "valor_mobiliario" in name.lower():
                        tickers.extend(parse_fca_tickers(_zip_member(archive, name)))
    companies = assemble_companies(cadastro, receipts, capital_rows, bs, earn, tickers)
    n_share_points_rescaled = rescale_share_counts(companies)
    wanted = {ticker for company in companies for ticker, _s, _e in company.tickers}
    prints: dict[str, dict[int, tuple]] = defaultdict(dict)
    cota = cache / "cotahist"
    if cota.exists():
        seen_paths: set[Path] = set()
        for path in sorted(cota.iterdir()):
            if path.suffix.lower() != ".zip" or path in seen_paths:
                continue
            seen_paths.add(path)
            print(f"prices {path.name}", flush=True)
            for parsed in iter_cotahist_zip(path):
                if parsed["ticker"] not in wanted:
                    continue
                prints[parsed["ticker"]][parsed["date"]] = (
                    parsed["close"],
                    parsed["bid"],
                    parsed["ask"],
                    parsed["qty"],
                    parsed["vol"],
                )
    ticker_owner: dict[str, str] = {}
    for company in companies:
        for ticker, _start, _end in company.tickers:
            ticker_owner.setdefault(ticker, company.cnpj)
    by_cnpj = {company.cnpj: company for company in companies}
    share_events: dict[str, tuple[list[int], list[float]]] = {}
    for ticker, cnpj in ticker_owner.items():
        collapsed: dict[int, SharePoint] = {}
        for point in by_cnpj[cnpj].shares:
            prev = collapsed.get(point.received)
            if prev is None or point.period_end > prev.period_end:
                collapsed[point.received] = point
        points = [collapsed[key] for key in sorted(collapsed)]
        if len(points) < 2:
            continue
        share_events[ticker] = (
            [point.received for point in points],
            [point.on_out for point in points],
        )
    tapes, n_splits = tapes_from_prints(prints, share_events)
    sessions = session_calendar(tapes)
    tesouro = cache / "tesouro.csv"
    if tesouro.exists():
        yields = yields_from_tesouro(tesouro.read_text(encoding="latin-1"))
    else:
        yields = _empty_yields()
    ibov_path = cache / "ibov.json"
    if ibov_path.exists():
        ibov_ords, ibov_close = parse_yahoo_chart(ibov_path.read_text(encoding="utf-8"))
    else:
        ibov_ords = np.asarray([], dtype=np.int64)
        ibov_close = np.asarray([], dtype=np.float64)
    return {
        "companies": companies,
        "tapes": tapes,
        "sessions": sessions,
        "yields": yields,
        "ibov_ords": ibov_ords,
        "ibov_close": ibov_close,
        "n_split_adjustments": n_splits,
        "n_priced_tickers": len(tapes),
        "n_share_points_rescaled": n_share_points_rescaled,
    }
