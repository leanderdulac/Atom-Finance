"""Equal-weight B3 study. Synthetic tapes only. No network."""

from __future__ import annotations

import inspect
import json
import zipfile
from datetime import date

import numpy as np
import pytest

from app.models.equal_weight import (
    ELIGIBLE_FOR_LIVE_TRADING,
    LIQUID_MIN_NAMES,
    Target,
    build_signal_book,
    choose_specification,
    event_arrays,
    jump_census,
    plausible_cash,
    production_grid,
    render_report,
    run_study,
    simulate_book,
)
from app.models.equal_weight_io import (
    CashEvent,
    Listing,
    listings_from_tapes,
    load_cash_events,
    load_listings,
    load_strategy_tapes,
    parse_cotahist_print,
    parse_fca_equity,
    parse_yahoo_events,
    share_events_from_companies,
    yahoo_nominal_amount,
)
from app.models.net_net import Company, SharePoint, Tape
from app.models.rejected_net_net import rejected_ledger_count


def _ord(year: int, month: int, day: int) -> int:
    return date(year, month, day).toordinal()


def _company(cnpj: str, shares: float = 1_000.0, setor: str = "Têxtil") -> Company:
    point = SharePoint(_ord(2014, 12, 31), _ord(2015, 1, 2), shares, 0.0, shares, 0.0)
    return Company(cnpj, cnpj, setor, "ATIVO", [], [], [point], [], [], [])


def _tape(start: int, n: int, price: float = 10.0, vol: float = 6_000_000.0, bid: float | None = None, ask: float | None = None) -> Tape:
    dates = np.arange(start, start + n, dtype=np.int64)
    close = np.full(n, price, dtype=np.float64)
    bid_px = price if bid is None else bid
    ask_px = price if ask is None else ask
    return Tape(
        dates,
        close,
        np.full(n, bid_px, dtype=np.float64),
        np.full(n, ask_px, dtype=np.float64),
        np.full(n, 1_000_000.0, dtype=np.float64),
        np.full(n, vol, dtype=np.float64),
        np.ones(n, dtype=np.float64),
    )


def test_grid_is_fixed_and_only_one_million_can_be_chosen():
    grid = production_grid()
    assert len(grid) == 24
    chosen = [row for row in grid if row["selection_candidate"]]
    assert len(chosen) == 8
    assert {row["aum"] for row in grid} == {100_000.0, 1_000_000.0, 10_000_000.0}
    assert {row["universe"] for row in chosen} == {"liquid", "small"}
    assert ELIGIBLE_FOR_LIVE_TRADING is False


def test_selection_ignores_out_of_sample_fields():
    weak = {
        "selection_candidate": True,
        "design_sharpe": 0.2,
        "design_cagr": 0.01,
        "design_turnover": 0.2,
        "n_design": 40,
        "frequency": "monthly",
        "adv_floor": 1_000_000.0,
        "universe": "liquid",
        "oos_cagr_net": 0.9,
        "oos_sharpe": 3.0,
    }
    strong = {
        "selection_candidate": True,
        "design_sharpe": 0.8,
        "design_cagr": 0.05,
        "design_turnover": 0.4,
        "n_design": 40,
        "frequency": "quarterly",
        "adv_floor": 50_000.0,
        "universe": "small",
        "oos_cagr_net": -0.4,
    }
    picked = choose_specification([weak, strong])
    assert picked is not None
    assert picked["universe"] == "small"
    assert picked["design_sharpe"] == 0.8
    short = dict(strong, n_design=12)
    assert choose_specification([short]) is None


def test_unlabeled_cash_is_withheld_and_a_labeled_dividend_is_not():
    events = {
        "AAA3": [
            CashEvent(_ord(2018, 6, 1), 1.0, "unknown"),
            CashEvent(_ord(2018, 7, 1), 2.0, "dividendo"),
            CashEvent(_ord(2018, 8, 1), 4.0, "jcp"),
        ]
    }
    taxed = event_arrays(events, 0.15)
    exempt = event_arrays(events, 0.0)
    assert taxed["AAA3"][1].tolist() == pytest.approx([0.85, 2.0, 3.4])
    assert exempt["AAA3"][1].tolist() == pytest.approx([1.0, 2.0, 3.4])


def test_a_cash_figure_above_the_previous_close_is_not_a_dividend():
    start = _ord(2011, 4, 1)
    tape = _tape(start, 40, price=10.0)
    events = {
        "PDGR3": [
            CashEvent(start + 10, 190_916_912.0, "unknown"),
            CashEvent(start + 12, 0.4, "dividendo"),
        ],
        "ORPH3": [CashEvent(start + 3, 20_000.0, "unknown")],
    }
    kept, summary = plausible_cash(events, {"PDGR3": tape})
    assert summary["dropped"] == 2
    assert [event.amount for event in kept["PDGR3"]] == [0.4]
    assert "ORPH3" not in kept
    taxed = event_arrays(kept, 0.15)
    assert taxed["PDGR3"][1].tolist() == pytest.approx([0.4])


def test_yahoo_nominal_undoes_a_later_split_only():
    ex = _ord(2018, 1, 2)
    assert yahoo_nominal_amount(0.5, ex, [(ex + 10, 2.0)]) == pytest.approx(1.0)
    assert yahoo_nominal_amount(0.5, ex, [(ex, 2.0)]) == pytest.approx(0.5)


def test_resize_does_not_round_trip_a_name_that_stays():
    start = _ord(2018, 1, 2)
    tape = _tape(start, 40, price=10.0, bid=9.0, ask=11.0, vol=5_000_000.0)
    sessions = list(range(start, start + 40))
    book = {
        sessions[5]: [Target("1", "AAA3", 5_000_000.0, 100_000.0)],
        sessions[20]: [Target("1", "AAA3", 5_000_000.0, 100_000.0)],
    }
    tapes = {"AAA3": tape}
    resize = simulate_book(sessions, tapes, book, 100_000.0, None, round_trip=False, exit_when_stale=False)
    bug = simulate_book(sessions, tapes, book, 100_000.0, None, round_trip=True, exit_when_stale=False)
    assert resize["net"][-1] > bug["net"][-1]
    assert resize["stats"].n < bug["stats"].n
    assert resize["eligible_for_live_trading"] is False


def test_split_scales_shares_and_a_dividend_is_cash():
    start = _ord(2018, 1, 2)
    tape = _tape(start, 15, price=10.0)
    tape.split[5] = 2.0
    tape.close[5:] = 5.0
    sessions = list(range(start, start + 15))
    book = {sessions[1]: [Target("1", "AAA3", 1_000_000.0, 100_000.0)]}
    events = event_arrays({"AAA3": [CashEvent(sessions[6], 1.0, "dividendo")]}, 0.15)
    run = simulate_book(sessions, {"AAA3": tape}, book, 100_000.0, events, exit_when_stale=False)
    assert run["dividend_cash"] > 0
    assert run["dividend_events"] == 1
    # Bought before the split, so the cash credit uses the post-split share count.
    assert run["net"][-1] > 100_000.0 - 1.0


def test_worthless_stale_exit_drops_the_position():
    start = _ord(2018, 1, 2)
    tape = _tape(start, 8, price=10.0)
    sessions = list(range(start, start + 30))
    book = {sessions[1]: [Target("1", "AAA3", 1_000_000.0, 100_000.0)]}
    tapes = {"AAA3": tape}
    last = simulate_book(sessions, tapes, book, 50_000.0, None, haircut=0.0, exit_when_stale=True)
    dead = simulate_book(sessions, tapes, book, 50_000.0, None, haircut=1.0, exit_when_stale=True)
    assert dead["worthless_exits"] >= 1
    assert dead["net"][-1] < last["net"][-1]


def test_a_delisted_name_missing_from_the_form_stays_in_the_liquid_book():
    start = _ord(2016, 3, 1)
    tape = _tape(start, 40, price=8.0, vol=2_000_000.0)
    tapes = {"ZZZZ3": tape}
    listings = listings_from_tapes(tapes, [], start + 80)
    assert listings[0].cnpj == "ROOT:ZZZZ"
    assert listings[0].end == start + 39
    signal = start + 30
    book = build_signal_book([], listings, tapes, [signal], "liquid", 50_000.0, min_names=1)
    assert [row.ticker for row in book[signal]] == ["ZZZZ3"]
    small = build_signal_book([], listings, tapes, [signal], "small", 50_000.0, min_names=1)
    assert small[signal] == []


def test_small_book_is_the_bottom_of_the_point_in_time_cap():
    start = _ord(2018, 6, 1)
    sessions = list(range(start, start + 40))
    signal = sessions[25]
    companies = [_company("1", shares=100.0), _company("2", shares=10_000.0)]
    listings = [
        Listing("1", "AAA3", start, None, "on"),
        Listing("2", "BBB3", start, None, "on"),
    ]
    tapes = {"AAA3": _tape(start, 40, price=10.0, vol=1_000_000.0), "BBB3": _tape(start, 40, price=10.0, vol=1_000_000.0)}
    book = build_signal_book(companies, listings, tapes, [signal], "small", 50_000.0, min_names=1)
    assert [row.ticker for row in book[signal]] == ["AAA3"]
    liquid = build_signal_book(companies, listings, tapes, [signal], "liquid", 50_000.0, min_names=LIQUID_MIN_NAMES)
    assert liquid[signal] == []


def test_run_study_chooses_on_the_design_window_and_counts_rejected_trials(tmp_path):
    start = _ord(2015, 1, 5)
    n = _ord(2019, 3, 29) - start
    companies = [_company("1", 1_000.0), _company("2", 1_000.0)]
    listings = [
        Listing("1", "AAA3", start, None, "on"),
        Listing("2", "BBB3", start, None, "on"),
    ]
    rising = _tape(start, n, price=10.0, vol=6_000_000.0)
    rising.close = 10.0 * np.cumprod(np.full(n, 1.0002))
    rising.bid = rising.close.copy()
    rising.ask = rising.close.copy()
    tapes = {"AAA3": rising, "BBB3": Tape(rising.dates, rising.close.copy(), rising.bid.copy(), rising.ask.copy(), rising.qty.copy(), rising.vol.copy(), rising.split.copy())}
    sessions = list(range(start, start + n))
    events = None
    report = run_study(
        companies,
        tapes,
        sessions,
        events,
        np.asarray([], dtype=np.int64),
        np.asarray([], dtype=np.float64),
        np.asarray([], dtype=np.int64),
        np.asarray([], dtype=np.float64),
        str(tmp_path / "trials.sqlite"),
        listings,
        min_names=1,
    )
    assert report["eligible_for_live_trading"] is False
    assert report["verdict"] in ("aprovado", "reprovado")
    assert report["n_rejected_net_net"] == rejected_ledger_count() == 32
    assert report["n_trials_decision"] == report["n_trials"] + 32
    assert report["n_trials_with_factor_trials"] == report["n_trials_decision"] + 24
    selected = report["oos_split"]["selected"]
    assert selected["universe"] == "liquid"
    assert selected["frequency"] == "monthly"
    assert selected["adv_floor"] == 5_000_000.0
    text = render_report(report)
    assert "eligible_for_live_trading" in text
    assert report["verdict"] in text
    assert "17,5%" in text


def test_parsers_keep_preferred_shares_and_the_trade_count():
    text = (
        "CNPJ_Companhia;Codigo_Negociacao;Valor_Mobiliario;Mercado;Data_Inicio_Negociacao;Data_Fim_Negociacao\n"
        "00.000.000/0001-91;PETR3;Ações Ordinárias;Bolsa;2001-01-02;\n"
        "00.000.000/0001-91;PETR4;Ações Preferenciais;Bolsa;2001-01-02;2020-01-02\n"
        "00.000.000/0001-91;PETR11;Units;Bolsa;2010-01-04;\n"
        "00.000.000/0001-91;PETR19;Debêntures;Bolsa;2010-01-04;\n"
    )
    rows = parse_fca_equity(text)
    assert [row[1] for row in rows] == ["PETR3", "PETR4", "PETR11"]
    assert rows[1][4] == "pn"
    assert rows[1][3] == _ord(2020, 1, 2)
    raw = [" "] * 245

    def put(start: int, value: str) -> None:
        for i, ch in enumerate(value):
            raw[start + i] = ch

    put(0, "01")
    put(2, "20120102")
    put(10, "02")
    put(12, f"{'ABCB4':<12}")
    put(24, "010")
    put(108, f"{1487:013d}")
    put(121, f"{1480:013d}")
    put(134, f"{1490:013d}")
    put(147, f"{226:05d}")
    put(152, f"{213300:018d}")
    put(170, f"{1000000:018d}")
    parsed = parse_cotahist_print("".join(raw))
    assert parsed is not None
    assert parsed["ticker"] == "ABCB4"
    assert parsed["close"] == pytest.approx(14.87)
    assert parsed["trades"] == 226


def _cotahist_line(day: str, ticker: str, close_cents: int, qty: int = 1000) -> str:
    raw = [" "] * 245

    def put(start: int, value: str) -> None:
        for i, ch in enumerate(value):
            raw[start + i] = ch

    put(0, "01")
    put(2, day)
    put(10, "02")
    put(12, f"{ticker:<12}")
    put(24, "010")
    put(108, f"{close_cents:013d}")
    put(121, f"{close_cents:013d}")
    put(134, f"{close_cents:013d}")
    put(147, f"{3:05d}")
    put(152, f"{qty:018d}")
    put(170, f"{close_cents * qty:018d}")
    return "".join(raw)


def test_cache_readers_gross_up_events_and_confirm_a_split(tmp_path):
    text = (
        "CNPJ_Companhia;Codigo_Negociacao;Valor_Mobiliario;Mercado;Data_Inicio_Negociacao;Data_Fim_Negociacao\n"
        "00.000.000/0001-91;ABC3;Acoes Ordinarias;Bolsa;2018-01-02;\n"
    )
    fca = tmp_path / "fca"
    fca.mkdir()
    with zipfile.ZipFile(fca / "fca_2018.zip", "w") as archive:
        archive.writestr("fca_cia_aberta_valor_mobiliario_2018.csv", text)
    listings = load_listings(tmp_path)
    assert [item.ticker for item in listings] == ["ABC3"]
    company = _company("00.000.000/0001-91", shares=100.0)
    company.shares.append(SharePoint(_ord(2018, 6, 30), _ord(2018, 6, 10), 200.0, 0.0, 200.0, 0.0))
    events = share_events_from_companies([company], listings)
    assert events["ABC3"][1] == [100.0, 200.0]
    cota = tmp_path / "cotahist"
    cota.mkdir()
    # Price halves and share volume doubles. The FRE receipt on 2018-06-10 is
    # after the print, so it is not the confirmation. The heuristic is.
    body = (
        _cotahist_line("20180601", "ABC3", 2000, qty=1000)
        + "\n"
        + _cotahist_line("20180604", "ABC3", 1000, qty=2000)
        + "\n"
    )
    with zipfile.ZipFile(cota / "COTAHIST_A2018.ZIP", "w") as archive:
        archive.writestr("COTAHIST_A2018.TXT", body)
    tapes, trades, n_splits = load_strategy_tapes(tmp_path, listings, events)
    assert n_splits == 1
    assert float(tapes["ABC3"].split[1]) == pytest.approx(2.0)
    assert trades["ABC3"][0] == 3
    payload = {
        "chart": {
            "result": [
                {
                    "events": {
                        "dividends": {"0": {"date": 1530662400, "amount": 0.5}},
                        "splits": {"0": {"date": 1530748800, "numerator": 2, "denominator": 1}},
                    }
                }
            ]
        }
    }
    parsed = parse_yahoo_events(payload, "ABC3")
    assert parsed[0].kind == "unknown"
    assert parsed[0].amount == pytest.approx(1.0)
    folder = tmp_path / "yahoo"
    folder.mkdir()
    (folder / "ABC3.json").write_text(
        json.dumps({"ticker": "ABC3", "events": [{"ordinal": parsed[0].ordinal, "amount": parsed[0].amount, "kind": "unknown"}]}),
        encoding="utf-8",
    )
    (folder / "_manifest.json").write_text("{}", encoding="utf-8")
    loaded = load_cash_events(folder)
    assert loaded["ABC3"][0].amount == pytest.approx(1.0)
    census = jump_census({"ABC3": tapes["ABC3"]}, ["ABC3"])
    assert census["confirmed_split_prints"] == 1
    assert census["unconfirmed_gaps"] == 0


def test_model_modules_do_not_open_the_network():
    import app.models.equal_weight as study
    import app.models.equal_weight_io as io

    source = inspect.getsource(study) + inspect.getsource(io)
    for banned in ("urllib", "requests", "httpx", "socket", "urlopen"):
        assert banned not in source
