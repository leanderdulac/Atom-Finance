"""Graham net-net on B3. Fixtures only: these tests do not open a socket."""

from __future__ import annotations

import inspect
from datetime import date, timedelta

import numpy as np
import pytest

from app.models import net_net, net_net_io
from app.models.net_net import (
    FAMILY_ID,
    BsPoint,
    Company,
    EarnRow,
    Ledger,
    Position,
    SharePoint,
    Tape,
    fundamentals_asof,
    liquidation_per_share,
    monthly_simple_returns,
    passes_screen,
    pe_cap_from_yield,
    price_fill,
    production_grid,
    run_study,
    simulate,
)
from app.models.net_net_io import (
    parse_cadastro,
    parse_capital,
    parse_cotahist_line,
    parse_document_header,
    parse_fca_tickers,
    parse_fre_shares,
    parse_statement,
    rescale_share_counts,
    yields_from_tesouro,
)
from app.models.rejected_net_net import rejected_ledger_count
from app.models.trading_costs import BookTop


def _ord(year: int, month: int, day: int) -> int:
    return date(year, month, day).toordinal()


def test_pe_cap_is_the_1981_earnings_yield_rule():
    # Greenblatt, Pzena & Newberg: AAA at 8% -> maximum P/E about 6.25.
    assert pe_cap_from_yield(0.08) == pytest.approx(6.25)
    assert pe_cap_from_yield(0.10) == pytest.approx(5.0)


def test_preferred_is_book_capital_not_assumed_zero():
    lv = liquidation_per_share(100.0, 10.0, 5.0, 50.0, on_out=10, pn_integrated=10, total_integrated=20)
    # preferred claim = 50 * 10/20 = 25; (100 - 10 - 5 - 25) / 10 = 6
    assert lv == pytest.approx(6.0)
    no_pref = liquidation_per_share(100.0, 10.0, 5.0, None, on_out=10, pn_integrated=0, total_integrated=10)
    assert no_pref == pytest.approx(8.5)
    assert liquidation_per_share(100.0, 10.0, 5.0, None, 10, 10, 20) is None
    assert liquidation_per_share(100.0, -1.0, 5.0, 50.0, 10, 0, 10) is None


def test_screen_rejects_losses_negative_lv_and_rich_prices():
    assert passes_screen(6.0, 6.0, 2.0, 1.0, "pe5", None)
    assert not passes_screen(6.0, 6.0, 2.0, 0.85, "pe5", None)
    assert not passes_screen(10.0, -1.0, 2.0, 1.0, "pe5", None)
    assert not passes_screen(10.0, 20.0, -1.0, 1.0, "pe5", None)
    assert not passes_screen(10.0, 20.0, None, 1.0, "pe5", None)
    # P/E = 10 / 1 = 10, cap at 8% yield is 6.25.
    assert not passes_screen(10.0, 20.0, 1.0, 1.0, "ey", 0.08)
    assert passes_screen(5.0, 20.0, 1.0, 1.0, "ey", 0.08)
    assert not passes_screen(5.0, 20.0, 1.0, 1.0, "ey", None)


def test_point_in_time_hides_unreceived_filings_and_restatements():
    published = _ord(2021, 3, 20)
    restated = _ord(2021, 5, 2)
    period = _ord(2020, 12, 31)
    bs = [
        BsPoint(period, published, ca=100, cl=10, ltl=5, capital=50),
        BsPoint(period, restated, ca=200, cl=10, ltl=5, capital=50),
    ]
    shares = [SharePoint(period, published, on_out=10, pn_subscribed=10, total_subscribed=20, pn_out=10)]
    assert fundamentals_asof(bs, [], shares, [], [], published - 1) is None
    first = fundamentals_asof(bs, [], shares, [], [], published)
    assert first is not None and first.lv_per_share == pytest.approx(6.0)
    later = fundamentals_asof(bs, [], shares, [], [], restated)
    # Restated current assets 200 -> LV per share (200-10-5-25)/10 = 16.
    assert later is not None and later.lv_per_share == pytest.approx(16.0)
    # A filing that arrives next year cannot change the earlier snapshot.
    future = BsPoint(_ord(2021, 12, 31), _ord(2022, 3, 30), ca=1, cl=0, ltl=0, capital=1)
    again = fundamentals_asof([*bs, future], [], shares, [], [], published)
    assert again is not None and again.lv_per_share == pytest.approx(6.0)
    assert again.bs_received == published


def _quarter(year: int, quarter: int, ni: float, received: date) -> EarnRow:
    start_month = 1 + (quarter - 1) * 3
    start = date(year, start_month, 1)
    end = date(year, start_month + 3, 1) - timedelta(days=1) if start_month < 10 else date(year, 12, 31)
    return EarnRow(start.toordinal(), end.toordinal(), received.toordinal(), ni)


def test_ttm_needs_four_published_quarters_and_ignores_the_future():
    rows = [
        _quarter(2020, 1, 10, date(2020, 5, 15)),
        _quarter(2020, 2, 10, date(2020, 8, 15)),
        _quarter(2020, 3, 10, date(2020, 11, 15)),
        _quarter(2020, 4, -5, date(2021, 3, 30)),
        _quarter(2021, 1, 100, date(2021, 5, 15)),
    ]
    shares = [SharePoint(_ord(2019, 12, 31), _ord(2020, 1, 1), 10, 0, 10, 0)]
    bs = [BsPoint(_ord(2019, 12, 31), _ord(2020, 3, 1), 50, 5, 5, 10)]
    before_q4 = fundamentals_asof(bs, [], shares, rows, [], _ord(2021, 3, 1))
    assert before_q4 is not None and before_q4.ttm_source == "missing"
    after = fundamentals_asof(bs, [], shares, rows, [], _ord(2021, 3, 30))
    assert after is not None and after.ttm_source == "quarters"
    assert after.ttm_ni == pytest.approx(25.0)
    # The 2021 quarter is not part of the trailing sum on the day Q4 is published.
    assert after.earnings_received == _ord(2021, 3, 30)


def test_q4_is_annual_minus_nine_months_only_after_both_exist():
    y = 2020
    q1 = EarnRow(_ord(y, 1, 1), _ord(y, 3, 31), _ord(y, 5, 1), 10)
    q2 = EarnRow(_ord(y, 4, 1), _ord(y, 6, 30), _ord(y, 8, 1), 10)
    nine = EarnRow(_ord(y, 1, 1), _ord(y, 9, 30), _ord(y, 11, 1), 30)
    annual = EarnRow(_ord(y, 1, 1), _ord(y, 12, 31), _ord(y + 1, 3, 20), 50)
    bs_early = [BsPoint(_ord(y, 9, 30), _ord(y, 11, 1), 80, 10, 10, 20)]
    shares_early = [SharePoint(_ord(y, 9, 30), _ord(y, 11, 1), 10, 0, 10, 0)]
    early = fundamentals_asof(bs_early, [], shares_early, [q1, q2, nine], [], _ord(y, 11, 15))
    assert early is not None and early.ttm_ni is None
    mid = fundamentals_asof(bs_early, [], shares_early, [q1, q2, nine, annual], [], _ord(y + 1, 3, 1))
    assert mid is not None and mid.ttm_source != "quarters"
    done = fundamentals_asof(bs_early, [], shares_early, [q1, q2, nine, annual], [], _ord(y + 1, 3, 20))
    assert done is not None and done.ttm_source == "quarters"
    assert done.ttm_ni == pytest.approx(50.0)


def _tape(ords, close, bid=None, ask=None, qty=1_000_000.0, vol=None) -> Tape:
    close = np.asarray(close, dtype=np.float64)
    n = len(ords)
    bid_a = np.full(n, np.nan) if bid is None else np.asarray(bid, dtype=np.float64)
    ask_a = np.full(n, np.nan) if ask is None else np.asarray(ask, dtype=np.float64)
    vol_a = close * qty if vol is None else np.asarray(vol, dtype=np.float64)
    return Tape(
        dates=np.asarray(ords, dtype=np.int64),
        close=close,
        bid=bid_a,
        ask=ask_a,
        qty=np.full(n, qty),
        vol=vol_a,
        split=np.ones(n),
    )


def _sessions(start: date, n: int) -> list[int]:
    out = []
    day = start
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day.toordinal())
        day += timedelta(days=1)
    return out


def test_costs_use_the_desk_model_and_rise_with_participation():
    book = BookTop(bid=9.9, ask=10.1, bid_size=1_000, ask_size=1_000, mid=10.0, estimated=False)
    small, _ = price_fill("buy", 100, 10.0, book)
    large, capped = price_fill("buy", 1_000_000, 10.0, book)
    assert small.fee > 0 and small.half_spread > 0
    assert large.slippage_bps > small.slippage_bps
    assert capped
    assert small.venue == "b3"


def test_fallback_spread_is_wider_for_thin_names():
    assert net_net.fallback_full_spread_bps(100_000_000) < net_net.fallback_full_spread_bps(1_000_000)
    assert net_net.fallback_full_spread_bps(1_000) == net_net.SPREAD_CAP_BPS
    book, source = net_net.execution_book(10.0, 0.0, 0.0, adv_brl=1_000_000, adv_shares=100_000)
    assert source == "estimate" and book.estimated
    observed, source = net_net.execution_book(10.0, 9.95, 10.05, adv_brl=1_000_000, adv_shares=100_000)
    assert source == "book" and not observed.estimated


def test_double_exit_two_year_exit_and_net_lags_gross(tmp_path):
    sessions = _sessions(date(2020, 1, 2), 40)
    # Jump the close through a double after the first rebalance has filled.
    close = np.full(len(sessions), 10.0)
    close[15:] = 21.0
    bid = close * 0.99
    ask = close * 1.01
    tape = _tape(sessions, close, bid, ask)
    rows = {
        sessions[0]: [
            net_net.NameRow("c1", "AAA3", 10.0, 30.0, 5.0, 5_000_000.0, 500_000.0, 1_000_000.0, 0)
        ]
    }
    # Force this single date to be the only signal, whatever the calendar phase is.
    def selector(_sig, names, _pos):
        return list(names)

    run = simulate(sessions, {"AAA3": tape}, rows, selector, aum=1_000_000.0, hold_until_exit=True)
    assert run["double_exits"] >= 1
    assert run["net"][-1] < run["gross"][-1]
    assert run["stats"].fee > 0
    assert run["eligible_for_live_trading"] is False

    # Two-year exit. The fill is the session after the signal; the clock then
    # runs 800 days and the sale is the session after that close.
    early = _ord(2020, 1, 6)
    fill = early + 1
    late = fill + 800
    after = late + 1
    marks = [early, fill, late, after]
    tape2 = _tape(marks, [10.0, 10.0, 11.0, 11.0], [9.9, 9.9, 10.9, 10.9], [10.1, 10.1, 11.1, 11.1])
    rows2 = {early: [net_net.NameRow("c1", "AAA3", 10.0, 30.0, 5.0, 1e6, 1e5, 1e6, 0)]}
    aged = simulate(marks, {"AAA3": tape2}, rows2, selector, 100_000.0, True)
    assert aged["time_exits"] >= 1


def test_delisted_exit_count():
    sessions = _sessions(date(2020, 1, 2), 30)
    alive = sessions[:5]
    tape = _tape(alive, np.full(len(alive), 8.0), np.full(len(alive), 7.9), np.full(len(alive), 8.1))
    rows = {sessions[0]: [net_net.NameRow("dead", "ZZZ3", 8.0, 20.0, 2.0, 100_000.0, 10_000.0, 50_000.0, 0)]}

    def selector(_s, names, _p):
        return list(names)

    run = simulate(sessions, {"ZZZ3": tape}, rows, selector, 100_000.0, True)
    assert run["delist_exits"] >= 1
    assert run["net"][-1] > 0


def test_split_requires_a_confirming_share_count():
    dates = np.array([_ord(2020, 1, 2), _ord(2020, 1, 3), _ord(2020, 1, 6)], dtype=np.int64)
    # 10-for-1 grupamento: price jumps 10x.
    close = np.array([1.0, 10.0, 10.0])
    no = net_net.confirmed_split_factors(dates, close, [_ord(2019, 1, 1)], [1000.0])
    assert np.allclose(no, 1.0)
    yes = net_net.confirmed_split_factors(
        dates,
        close,
        [_ord(2019, 6, 1), _ord(2020, 4, 1)],
        [1000.0, 100.0],
    )
    assert yes[1] == pytest.approx(0.1)
    # A real crash of 50% with no share change is left alone.
    crash = np.array([10.0, 5.0, 5.0])
    kept = net_net.confirmed_split_factors(dates, crash, [_ord(2019, 6, 1), _ord(2020, 4, 1)], [1000.0, 1000.0])
    assert np.allclose(kept, 1.0)


def test_missing_prices_are_counted_not_filled_in():
    company = Company(
        cnpj="00",
        denom="FALIDA",
        setor="Têxtil e Vestuário",
        sit="CANCELADA",
        bs_con=[BsPoint(_ord(2020, 12, 31), _ord(2021, 3, 1), 10, 1, 1, 5)],
        bs_ind=[],
        shares=[SharePoint(_ord(2020, 12, 31), _ord(2021, 3, 1), 100, 0, 100, 0)],
        er_con=[],
        er_ind=[],
        tickers=[("FALI3", _ord(2000, 1, 1), _ord(2020, 6, 1))],
    )
    report = net_net.coverage_report([company], {})
    assert report["n_ticker_without_price"] == 1
    assert report["n_ticker_without_price_cancelada"] == 1
    assert report["n_with_on_ticker_and_price"] == 0
    bank = Company("01", "BANCO", "Bancos", "ATIVO", [], [], [], [], [], [("BANK3", 1, None)])
    assert net_net.coverage_report([bank], {"BANK3": _tape([1, 2], [1.0, 1.0])})["n_financial_excluded"] == 1


def test_parsers_and_cotahist_layout():
    header = parse_document_header(
        "CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;CATEG_DOC;ID_DOC;DT_RECEB;LINK_DOC\n"
        "00.000.000/0001-91;2023-12-31;1;BCO;001023;DFP;1;2024-02-08;http://example\n"
    )
    assert header[("00.000.000/0001-91", _ord(2023, 12, 31), 1)] == _ord(2024, 2, 8)
    capital = (
        "CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;QT_ACAO_ORDIN_CAP_INTEGR;QT_ACAO_PREF_CAP_INTEGR;"
        "QT_ACAO_TOTAL_CAP_INTEGR;QT_ACAO_ORDIN_TESOURO;QT_ACAO_PREF_TESOURO;QT_ACAO_TOTAL_TESOURO\n"
        "00.000.000/0001-91;2023-12-31;1;BCO;1000;400;1400;100;0;100\n"
    )
    rows = parse_capital(capital, header)
    assert rows[0][3] == pytest.approx(900)  # common outstanding
    assert rows[0][4] == pytest.approx(400)  # subscribed preferred, the claim
    bpa = (
        "CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;GRUPO_DFP;MOEDA;ESCALA_MOEDA;ORDEM_EXERC;"
        "DT_FIM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA\n"
        "00.000.000/0001-91;2023-12-31;1;BCO;1;DF;REAL;MIL;ÚLTIMO;2023-12-31;1.01;Ativo Circulante;10.5\n"
        "00.000.000/0001-91;2023-12-31;1;BCO;1;DF;REAL;MIL;PENÚLTIMO;2022-12-31;1.01;Ativo Circulante;9\n"
    )
    parsed = parse_statement(bpa, True)
    assert parsed[0][6] == pytest.approx(10_500)
    assert parsed[1][4] == _ord(2022, 12, 31)
    dre = (
        "CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;GRUPO_DFP;MOEDA;ESCALA_MOEDA;ORDEM_EXERC;"
        "DT_INI_EXERC;DT_FIM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA\n"
        "00.000.000/0001-91;2023-12-31;1;BCO;1;DF;REAL;MIL;ÚLTIMO;2023-01-01;2023-12-31;3.99.01.01;ON;9.15\n"
    )
    eps_rows = parse_statement(dre, True)
    assert eps_rows[0][6] == pytest.approx(9.15)
    fca = (
        "CNPJ_Companhia;Codigo_Negociacao;Valor_Mobiliario;Mercado;Data_Inicio_Negociacao;Data_Fim_Negociacao\n"
        "00.000.000/0001-91;FALI3;Ações Ordinárias;Bolsa;2001-01-02;2020-06-01\n"
        "00.000.000/0001-91;FALI4;Ações Preferenciais;Bolsa;2001-01-02;\n"
    )
    tickers = parse_fca_tickers(fca)
    assert tickers == [("00.000.000/0001-91", "FALI3", _ord(2001, 1, 2), _ord(2020, 6, 1))]
    cad = parse_cadastro(
        "CNPJ_CIA;DENOM_SOCIAL;SETOR_ATIV;SIT\n00.000.000/0001-91;FALIDA SA;Têxtil e Vestuário;CANCELADA\n"
    )
    assert cad[0][3] == "CANCELADA"
    line = _cotahist_line("20200102", "FALI3", close_cents=1234, bid_cents=1200, ask_cents=1300, qty=500, vol_cents=600000)
    parsed_line = parse_cotahist_line(line)
    assert parsed_line is not None
    assert parsed_line["ticker"] == "FALI3"
    assert parsed_line["close"] == pytest.approx(12.34)
    assert parsed_line["bid"] == pytest.approx(12.0)
    assert parsed_line["ask"] == pytest.approx(13.0)
    assert parsed_line["qty"] == 500
    assert parse_cotahist_line("00" + " " * 250) is None
    yields = yields_from_tesouro(
        "Tipo Titulo;Data Vencimento;Data Base;Taxa Compra Manha;Taxa Venda Manha\n"
        "Tesouro Prefixado;01/01/2027;02/01/2020;8,00;8,20\n"
        "Tesouro Prefixado;01/01/2045;02/01/2020;9,00;9,20\n"
        "Tesouro IPCA+;15/08/2045;02/01/2020;4,00;4,10\n"
        "Tesouro Prefixado;01/01/2032;03/01/2020;8,50;8,70\n"
    )
    # 5y target from 2020-01-02 is ~2025; 2027 is closer than 2045. IPCA+ is ignored.
    assert yields["pre_5y"][1][0] == pytest.approx(0.081)
    assert yields["pre_long"][1][0] == pytest.approx(0.091)


def _cotahist_line(day: str, ticker: str, close_cents: int, bid_cents: int, ask_cents: int, qty: int, vol_cents: int) -> str:
    raw = [" "] * 245
    def put(start, text):
        for i, ch in enumerate(text):
            raw[start + i] = ch
    put(0, "01")
    put(2, day)
    put(10, "02")
    put(12, f"{ticker:<12}")
    put(24, "010")
    put(108, f"{close_cents:013d}")
    put(121, f"{bid_cents:013d}")
    put(134, f"{ask_cents:013d}")
    put(152, f"{qty:018d}")
    put(170, f"{vol_cents:018d}")
    return "".join(raw)


def test_fre_share_counts_use_integrated_capital_and_the_receipt_date():
    header = (
        "CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;CATEG_DOC;ID_DOC;DT_RECEB;LINK_DOC\n"
        "33.000.167/0001-01;2012-01-01;3;PETR;1;FRE;1;2012-05-30;http://example\n"
    )
    capital = (
        "CNPJ_Companhia;Data_Referencia;Versao;ID_Documento;Nome_Companhia;ID_Capital_Social;"
        "Tipo_Capital;Data_Autorizacao_Aprovacao;Valor_Capital;Prazo_Integralizacao;"
        "Quantidade_Acoes_Ordinarias;Quantidade_Acoes_Preferenciais;Quantidade_Total_Acoes\n"
        "33.000.167/0001-01;2012-01-01;3;PETR;1;1;Capital Autorizado;2010-01-01;1;x;9000;1000;10000\n"
        "33.000.167/0001-01;2012-01-01;3;PETR;1;1;Capital Emitido;2010-01-01;1;x;8000;1000;9000\n"
        "33.000.167/0001-01;2012-01-01;3;PETR;1;1;Capital Integralizado;2010-01-01;1;x;7000;1000;8000\n"
        "33.000.167/0001-01;2012-01-01;9;PETR;1;1;Capital Integralizado;2010-01-01;1;x;1;0;1\n"
    )
    treasury = (
        "CNPJ_Companhia;Data_Referencia;Versao;ID_Documento;Nome_Companhia;Data_Inicio_Exercicio_Social;"
        "Data_Fim_Exercicio_Social;Valor_Mobiliario;Especie_Acao;Tipo_Classe_Acao_Preferencial;"
        "Descricao_Valor_Mobiliario;Escala_Cotacao;Quantidade_Inicial;Valor_Total_Inicial;"
        "Valor_Preco_Medio_Inicial;Quantidade_Adquirida;Valor_Total_Adquirido;Valor_Preco_Medio_Adquirido;"
        "Quantidade_Alienada;Valor_Total_Alienado;Valor_Preco_Medio_Alienado;Quantidade_Cancelada;"
        "Valor_Total_Cancelado;Valor_Preco_Medio_Cancelado;Quantidade_Final;Valor_Total_Final;"
        "Valor_Preco_Medio_Final;Percentual_Relacao_Valores_Mobiliarios_Circulacao\n"
        "33.000.167/0001-01;2012-01-01;3;1;PETR;2011-01-01;2011-12-31;Ações;Ordinária;;x;1;0;0;0;0;0;0;0;0;0;0;0;0;100;0;0;0\n"
        "33.000.167/0001-01;2012-01-01;3;1;PETR;2012-01-01;2012-12-31;Ações;Preferencial;A;;1;0;0;0;0;0;0;0;0;0;0;0;0;40;0;0;0\n"
        "33.000.167/0001-01;2012-01-01;3;1;PETR;2012-01-01;2012-12-31;Ações;Preferencial;B;;1;0;0;0;0;0;0;0;0;0;0;0;0;10;0;0;0\n"
    )
    rows = parse_fre_shares(header, capital, treasury)
    assert len(rows) == 1
    cnpj, received, end, on_out, pn_sub, total, pn_out = rows[0]
    assert cnpj == "33.000.167/0001-01"
    assert received == _ord(2012, 5, 30)
    assert end == _ord(2012, 1, 1)
    assert on_out == pytest.approx(6900)  # 7000 integrated minus 100 treasury
    assert pn_sub == pytest.approx(1000)  # claim is integrated preferred
    assert total == pytest.approx(8000)
    assert pn_out == pytest.approx(950)  # 1000 minus 40 + 10


def test_share_counts_filed_in_thousands_are_scaled_up():
    end = _ord(2023, 12, 31)
    received = _ord(2024, 2, 20)
    thousands = Company(
        cnpj="1",
        denom="VALE",
        setor="Mineração",
        sit="ATIVO",
        bs_con=[BsPoint(end, received, 1e11, 1e10, 1e10, 7.7e10)],
        bs_ind=[],
        shares=[SharePoint(end, received, 4_539_007, 0, 4_539_007, 0)],
        er_con=[EarnRow(end - 364, end, received, 40.554e9, 9.15)],
        er_ind=[],
        tickers=[],
    )
    units = Company(
        cnpj="2",
        denom="PETR",
        setor="Petróleo",
        sit="ATIVO",
        bs_con=[BsPoint(end, received, 1e11, 1e10, 1e10, 2.05e11)],
        bs_ind=[],
        shares=[SharePoint(end, received, 7.44e9, 5.6e9, 13.04e9, 5.6e9)],
        er_con=[EarnRow(end - 364, end, received, 125.166e9, 9.57)],
        er_ind=[],
        tickers=[],
    )
    par_only = Company(
        cnpj="3",
        denom="NOEPS",
        setor="Têxtil",
        sit="ATIVO",
        bs_con=[BsPoint(end, received, 1e9, 1e8, 1e8, 1.7e10)],
        bs_ind=[],
        shares=[SharePoint(end, received, 1_000_000, 0, 1_000_000, 0)],
        er_con=[EarnRow(end - 364, end, received, 50e6, None)],
        er_ind=[],
        tickers=[],
    )
    n = rescale_share_counts([thousands, units, par_only])
    assert n == 2
    assert thousands.shares[0].on_out == pytest.approx(4_539_007_000)
    assert units.shares[0].total_subscribed == pytest.approx(13.04e9)
    assert par_only.shares[0].on_out == pytest.approx(1_000_000_000)


def test_registered_dsr_uses_every_variation(tmp_path):
    sessions = _sessions(date(2020, 1, 2), 80)
    close = np.linspace(10, 12, len(sessions))
    tape = _tape(sessions, close, close * 0.995, close * 1.005, qty=2_000_000)
    company = Company(
        "c",
        "ALVO",
        "Têxtil e Vestuário",
        "ATIVO",
        [BsPoint(_ord(2019, 12, 31), _ord(2020, 1, 1), 500, 20, 20, 100)],
        [],
        [SharePoint(_ord(2019, 12, 31), _ord(2020, 1, 1), 10, 0, 10, 0)],
        [EarnRow(_ord(2019, 1, 1), _ord(2019, 12, 31), _ord(2020, 1, 1), 40)],
        [],
        [("ALVO3", _ord(2001, 1, 1), None)],
    )
    # Annual earnings make EPS = 4, price ~10, P/E ~2.5, LV per share = (500-20-20)/10 = 46.
    yields = {
        "pre_5y": (np.array([sessions[0]], dtype=np.int64), np.array([0.08])),
        "pre_long": (np.array([sessions[0]], dtype=np.int64), np.array([0.09])),
    }
    grid = [
        {"block": "primary", "filter": "plv1_pe5", "plv_max": 1.0, "pe_mode": "pe5", "yield": "pre_5y", "lag_days": 0, "phase": 0, "aum": 100_000.0},
        {"block": "yield", "filter": "plv1_ey", "plv_max": 1.0, "pe_mode": "ey", "yield": "pre_long", "lag_days": 0, "phase": 0, "aum": 100_000.0},
    ]
    # Pin phase 0 onto a month that this calendar actually signals. production uses
    # year*12+month % 4. January 2020 is phase 1, so shift the company into the grid's phase
    # by choosing phase from the first session's month.
    month_phase = (2020 * 12 + 1) % 4
    for spec in grid:
        spec["phase"] = month_phase
    report = run_study(
        [company],
        {"ALVO3": tape},
        sessions,
        yields,
        np.array(sessions, dtype=np.int64),
        close,
        registry_path=str(tmp_path / "trials.sqlite"),
        first_ord=sessions[0],
        grid=grid,
    )
    assert report["eligible_for_live_trading"] is False
    # The family already holds the rejected net-net ledger. Those rows count in N.
    expected_trials = 2 + rejected_ledger_count()
    assert report["n_trials"] == expected_trials
    assert report["verdict"]["eligible_for_live_trading"] is False
    assert {row["n_trials"] for row in report["trials"]} == {expected_trials}
    assert all(row["dsr"] is not None for row in report["trials"])
    assert report["family_id"] == FAMILY_ID
    # Both variations are in the deflator. A one-trial story would not be registered this way.
    assert report["trials"][0]["n_obs_months"] >= 3


def test_production_grid_is_fixed_and_covers_the_four_filters():
    grid = production_grid()
    filters = {row["filter"] for row in grid if row["block"] == "primary"}
    assert filters == {"plv1_ey", "plv085_ey", "plv1_pe5", "plv085_pe5"}
    assert {row["yield"] for row in grid} == {"pre_5y", "pre_long"}
    assert {row["lag_days"] for row in grid} >= {0, 63}
    assert {row["aum"] for row in grid} >= {1_000_000.0, 10_000_000.0, 50_000_000.0}
    assert len(grid) == len({(r["filter"], r["yield"], r["lag_days"], r["phase"], r["aum"]) for r in grid})


def test_modules_do_not_open_the_network():
    source = inspect.getsource(net_net) + inspect.getsource(net_net_io)
    for banned in ("urllib", "requests", "httpx", "socket", "urlopen"):
        assert banned not in source


def test_monthly_ibovespa_chart_is_not_used_as_the_benchmark():
    # range=max on this symbol comes back monthly. That series hides the
    # intra-month drawdown and must not be reported as the daily index.
    start = date(2018, 1, 1).toordinal()
    ords = np.array([start + 30 * i for i in range(8)], dtype=np.int64)
    close = np.array([100, 110, 90, 80, 95, 100, 105, 110], dtype=np.float64)
    block = net_net._ibov_stats(ords, close, [int(ords[0]), int(ords[-1])])
    assert block["available"] is False


def test_monthly_return_dates_are_the_month_that_closed():
    # Curve starts on a month-end. That mark is a level. The first return
    # ends at the next month-end, and the date must travel with it.
    start = date(2018, 12, 31).toordinal()
    mid = date(2019, 1, 15).toordinal()
    end = date(2019, 1, 31).toordinal()
    ords, rets = monthly_simple_returns([start, mid, end], [100.0, 110.0, 121.0])
    assert ords == [end]
    assert rets == pytest.approx([0.21])
    # Curve starts inside the month. The return to the first month-end is kept.
    early = date(2018, 12, 10).toordinal()
    ords, rets = monthly_simple_returns([early, start, end], [100.0, 110.0, 121.0])
    assert ords == [start, end]
    assert rets == pytest.approx([0.10, 0.10])


def test_full_replacement_does_not_round_trip_a_name_that_stays():
    """A name that remains in the book is resized, not sold and bought again.

    The previous replacement path liquidated every name and then bought the
    same book back, so each rebalance charged spread and slippage on the
    whole NAV. One round trip on this liquid tape costs well under 2%. Two
    would not.
    """
    sessions = _sessions(date(2020, 1, 2), 30)
    flat = np.full(len(sessions), 10.0)
    tape = _tape(sessions, flat, flat - 0.05, flat + 0.05, qty=5_000_000)
    held = net_net.NameRow("c", "AAA3", 10.0, None, None, 50_000_000.0, 5_000_000.0, None, 0)
    rows = {sessions[0]: [held], sessions[10]: [held]}

    def selector(_sig, names, _pos):
        return list(names)

    run = simulate(sessions, {"AAA3": tape}, rows, selector, 1_000_000.0, hold_until_exit=False)
    costs = run["stats"].fee + run["stats"].half_spread + run["stats"].slippage
    assert run["gross"][-1] - run["net"][-1] == pytest.approx(costs, abs=0.05)
    assert run["net"][-1] > 980_000
    assert run["stats"].n <= 3
    assert run["logs"][1]["n_new"] == 0
    assert run["logs"][1]["n_held"] == 1


def test_full_replacement_sells_a_name_that_leaves():
    sessions = _sessions(date(2020, 1, 6), 20)
    flat = np.full(len(sessions), 10.0)
    tapes = {
        "AAA3": _tape(sessions, flat, flat * 0.99, flat * 1.01, qty=2_000_000),
        "BBB3": _tape(sessions, flat, flat * 0.99, flat * 1.01, qty=2_000_000),
    }
    first = [
        net_net.NameRow("a", "AAA3", 10.0, None, None, 20_000_000.0, 2_000_000.0, None, 0),
        net_net.NameRow("b", "BBB3", 10.0, None, None, 20_000_000.0, 2_000_000.0, None, 0),
    ]
    second = [first[0]]
    rows = {sessions[0]: first, sessions[8]: second}

    def selector(_sig, names, _pos):
        return list(names)

    run = simulate(sessions, tapes, rows, selector, 1_000_000.0, False)
    assert run["logs"][0]["n_held"] == 2
    assert run["logs"][1]["n_held"] == 1
    assert run["logs"][1]["n_new"] == 0


def test_sparse_illiquid_drawdown_is_the_round_trip_not_a_cash_charge():
    """Flat price, one illiquid name, then cash. The hole is the capped fills.

    After the entry, a flat tape must not bleed NAV on the days the book just
    sits. The terminal gross-minus-net gap equals fee + half-spread + slippage.
    """
    sessions = _sessions(date(2020, 1, 2), 25)
    flat = np.full(len(sessions), 10.0)
    tape = _tape(sessions, flat, flat - 0.1, flat + 0.1, qty=200.0)
    rows = {sessions[0]: [net_net.NameRow("c", "ILLQ3", 10.0, 30.0, 5.0, 2_000.0, 200.0, 1.0, 0)]}

    def selector(_sig, names, _pos):
        return list(names)

    run = simulate(sessions, {"ILLQ3": tape}, rows, selector, 1_000_000.0, True)
    stats = run["stats"]
    costs = stats.fee + stats.half_spread + stats.slippage
    assert run["gross"][-1] - run["net"][-1] == pytest.approx(costs, abs=0.05)
    assert run["gross"][-1] == pytest.approx(1_000_000.0, rel=1e-6)
    assert stats.n_capped >= 1
    assert stats.slippage > stats.half_spread > stats.fee
    held = run["net"][2:-1]
    assert max(held) - min(held) < 1.0
    assert run["net"][-1] < run["net"][2]
    assert min(run["net"]) / run["net"][0] - 1.0 < -0.2


def test_small_cap_benchmark_is_the_bottom_of_the_same_universe():
    rows = [
        net_net.NameRow("a", "A", 1, None, None, 0, 0, 10.0, 0),
        net_net.NameRow("b", "B", 1, None, None, 0, 0, 20.0, 0),
        net_net.NameRow("c", "C", 1, None, None, 0, 0, 100.0, 0),
        net_net.NameRow("d", "D", 1, None, None, 0, 0, 200.0, 0),
    ]
    picked = {row.cnpj for row in net_net.small_cap_names(rows, 0.30)}
    assert picked == {"a"}
    # Same-share invariant used by the cost comparison.
    ledger = Ledger(100.0, {"A": Position("a", "A", 2.0, 5.0, 1)})
    gross = Ledger(100.0, {"A": Position("a", "A", 2.0, 5.0, 1)})
    assert ledger.positions["A"].shares == gross.positions["A"].shares
