"""Long-horizon B3 factors. Research and paper simulation only.

Momentum 12-1, quality, low volatility, and an equal-rank composite.
Nothing here sends an order. ``eligible_for_live_trading`` is false on every
report this module builds.

The book is the same point-in-time panel as the net-net study (COTAHIST,
CVM filings visible at ``DT_RECEB``, delisted names kept). Fills go through
``trading_costs.quote_fill`` with the same spread and participation slippage.
A name that stays in the book is resized, not sold and bought again.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
from scipy.stats import rankdata

from app.models.afml.gate import gate
from app.models.afml.trials import TrialRegistry
from app.models.net_net import (
    ELIGIBLE_FOR_LIVE_TRADING,
    PRICE_STALE_SESSIONS,
    Company,
    EarnRow,
    NameRow,
    Tape,
    _earn_source,
    _ibov_stats,
    _latest,
    _source_pair,
    active_ticker,
    monthly_simple_returns,
    performance,
    simulate,
    trailing_adv,
    trailing_earnings,
)
from app.models.net_net_io import cdi_growth

FAMILY_ID = "b3_long_horizon_factors"
PERIODS_PER_YEAR = 12.0
LIQUIDITY_ADV_BRL = 1_000_000.0
ADV_WINDOW = 60
ADV_MIN_OBS = 20
VOL_WINDOW = 252
VOL_MIN_OBS = 120
VOL_GAP_DAYS = 5
QUINTILE = 0.20
MIN_ELIGIBLE = 25
MIN_QUALITY_COMPONENTS = 2
STATUTORY_TAX = 0.34
PARTICIPATION_CAP = 0.10
DESIGN_END = date(2018, 12, 31)
EVAL_START = date(2019, 1, 1)
SELECTION_AUM = 1_000_000.0
AUMS: tuple[float, ...] = (100_000.0, 1_000_000.0, 10_000_000.0)
FACTORS: tuple[str, ...] = ("momentum_12_1", "quality", "low_vol", "composite")
FREQUENCIES: tuple[str, ...] = ("monthly", "quarterly")
QUARTER_MONTHS = frozenset({3, 6, 9, 12})


def production_grid() -> list[dict[str, Any]]:
    """Every variation that will be registered. Fixed before any result is read."""
    specs = []
    for factor in FACTORS:
        for frequency in FREQUENCIES:
            for aum in AUMS:
                specs.append(
                    {
                        "factor": factor,
                        "frequency": frequency,
                        "aum": float(aum),
                        "selection": bool(frequency in FREQUENCIES and aum == SELECTION_AUM),
                    }
                )
    return specs


def adjusted_close(close: np.ndarray, split: np.ndarray) -> np.ndarray:
    """Price on the final share basis.

    ``split[i]`` is the share multiplier applied at print ``i`` (the close is
    already post-event). Earlier closes are divided by the product of every
    later multiplier, so a confirmed grupamento or split does not look like a
    return.
    """
    close = np.asarray(close, dtype=np.float64)
    split = np.asarray(split, dtype=np.float64)
    if len(close) == 0:
        return close
    future = np.cumprod(split[::-1])[::-1]
    denom = np.ones(len(close), dtype=np.float64)
    if len(close) > 1:
        denom[:-1] = future[1:]
    denom = np.where(denom > 0, denom, 1.0)
    return close / denom


def _add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def calendar_month_ends(sessions: Sequence[int]) -> dict[tuple[int, int], int]:
    last: dict[tuple[int, int], int] = {}
    for ordinal in sessions:
        day = date.fromordinal(int(ordinal))
        last[(day.year, day.month)] = int(ordinal)
    return last


def signal_ordinals(sessions: Sequence[int], frequency: str) -> list[int]:
    """Month-ends (or quarter-ends) that have a 12-month formation window and a later session to trade."""
    if frequency not in FREQUENCIES:
        raise ValueError("frequency must be monthly or quarterly")
    if len(sessions) < 2:
        return []
    ends = calendar_month_ends(sessions)
    last_session = int(sessions[-1])
    out = []
    for (year, month), ordinal in sorted(ends.items()):
        if ordinal >= last_session:
            continue
        if frequency == "quarterly" and month not in QUARTER_MONTHS:
            continue
        if _add_months(year, month, -1) not in ends or _add_months(year, month, -12) not in ends:
            continue
        out.append(int(ordinal))
    return out


def _ann_vol(dates: np.ndarray, adj: np.ndarray) -> np.ndarray:
    """Trailing std of close-to-close returns, annualized with sqrt(252).

    A return is kept only when the two prints are at most ``VOL_GAP_DAYS``
    calendar days apart, so a halt is not treated as a one-day move. The value
    at a print uses only that print and earlier ones.
    """
    n = len(adj)
    out = np.full(n, np.nan)
    if n < VOL_MIN_OBS + 1:
        return out
    gap = np.diff(dates.astype(np.int64))
    prev = adj[:-1]
    good = (prev > 0) & np.isfinite(adj[1:]) & (gap > 0) & (gap <= VOL_GAP_DAYS)
    ret = np.full(n, np.nan)
    ret[1:] = np.where(good, adj[1:] / prev - 1.0, np.nan)
    idx = np.flatnonzero(np.isfinite(ret))
    if len(idx) < VOL_MIN_OBS:
        return out
    vals = ret[idx]
    c1 = np.cumsum(vals)
    c2 = np.cumsum(vals * vals)
    for j in range(VOL_MIN_OBS - 1, len(vals)):
        j0 = j - VOL_WINDOW + 1
        if j0 < 0:
            j0 = 0
        nobs = j - j0 + 1
        if nobs < VOL_MIN_OBS:
            continue
        s1 = c1[j] - (c1[j0 - 1] if j0 else 0.0)
        s2 = c2[j] - (c2[j0 - 1] if j0 else 0.0)
        var = (s2 - (s1 * s1) / nobs) / (nobs - 1)
        if var >= 0:
            out[idx[j]] = math.sqrt(var) * math.sqrt(252.0)
    return out


@dataclass
class Prepared:
    tape: Tape
    adj: np.ndarray
    vol: np.ndarray


def prepare_tapes(tapes: dict[str, Tape]) -> dict[str, Prepared]:
    out = {}
    for ticker, tape in tapes.items():
        adj = adjusted_close(tape.close, tape.split)
        out[ticker] = Prepared(tape=tape, adj=adj, vol=_ann_vol(tape.dates, adj))
    return out


def _print_index(prep: Prepared, ordinal: int, max_stale: int = PRICE_STALE_SESSIONS) -> int | None:
    idx = prep.tape.index_on_or_before(ordinal)
    if idx is None:
        return None
    if ordinal - int(prep.tape.dates[idx]) > max_stale:
        return None
    px = float(prep.tape.close[idx])
    if not math.isfinite(px) or px <= 0:
        return None
    return idx


def momentum_12_1(prep: Prepared, month_ends: dict[tuple[int, int], int], year: int, month: int) -> float | None:
    """P(end of t-1) / P(end of t-12) - 1. The signal month itself is not in the ratio.

    ``t`` is ``(year, month)``. Both anchors must be real prints within the
    staleness window. Prices are split-adjusted.
    """
    recent = month_ends.get(_add_months(year, month, -1))
    old = month_ends.get(_add_months(year, month, -12))
    if recent is None or old is None:
        return None
    i1 = _print_index(prep, recent)
    i0 = _print_index(prep, old)
    if i1 is None or i0 is None:
        return None
    p1 = float(prep.adj[i1])
    p0 = float(prep.adj[i0])
    if not math.isfinite(p1) or not math.isfinite(p0) or p0 <= 0:
        return None
    return p1 / p0 - 1.0


def _ttm(rows: Sequence[EarnRow], asof: int, field: str) -> float | None:
    synthetic: list[EarnRow] = []
    for row in rows:
        value = getattr(row, field)
        if value is None or not isinstance(value, (int, float)) or not math.isfinite(value):
            continue
        synthetic.append(EarnRow(row.start, row.end, row.received, float(value)))
    value, _source, _when = trailing_earnings(synthetic, asof)
    return value


def _tax_rate(ebt: float | None, ni: float | None) -> float:
    if ebt is None or ni is None or ebt <= 0:
        return STATUTORY_TAX
    rate = (ebt - ni) / ebt
    if not math.isfinite(rate):
        return STATUTORY_TAX
    return float(min(max(rate, 0.0), 0.45))


def quality_components(company: Company, asof: int) -> dict[str, float]:
    """Point-in-time quality inputs. A filing with ``received > asof`` is invisible.

    Financial registrants return nothing: ROIC and leverage are not comparable
    to an industrial balance sheet. Missing inputs stay missing. They are not
    filled with zero.
    """
    if company.financial:
        return {}
    bs = _latest(_source_pair(company.bs_con, company.bs_ind, asof), asof)
    if bs is None:
        return {}
    flows = _earn_source(company.er_con, company.er_ind, asof)
    ni = _ttm(flows, asof, "ni")
    ebit = _ttm(flows, asof, "ebit")
    ebt = _ttm(flows, asof, "ebt")
    revenue = _ttm(flows, asof, "revenue")
    gross = _ttm(flows, asof, "gross_profit")
    out: dict[str, float] = {}
    equity = bs.equity
    assets = bs.assets
    if ni is not None and equity is not None and equity > 0:
        out["roe"] = float(ni) / float(equity)
    debt = None
    if bs.debt_st is not None or bs.debt_lt is not None:
        debt = float(bs.debt_st or 0.0) + float(bs.debt_lt or 0.0)
    if (
        ebit is not None
        and equity is not None
        and equity > 0
        and debt is not None
        and bs.cash is not None
    ):
        capital = float(equity) + debt - float(bs.cash)
        if capital > 0:
            out["roic"] = float(ebit) * (1.0 - _tax_rate(ebt, ni)) / capital
    if revenue is not None and revenue > 0:
        if ebit is not None:
            out["margin"] = float(ebit) / float(revenue)
        elif gross is not None:
            out["margin"] = float(gross) / float(revenue)
    if equity is not None and assets is not None and equity > 0 and assets > 0:
        out["equity_ratio"] = float(equity) / float(assets)
    return out


def _ranks(pairs: Sequence[tuple[str, float]]) -> dict[str, float]:
    """Average-rank percentile in (0, 1]. Higher raw value ranks higher."""
    if not pairs:
        return {}
    values = np.asarray([value for _name, value in pairs], dtype=np.float64)
    if len(pairs) == 1:
        return {pairs[0][0]: 1.0}
    ranks = rankdata(values, method="average")
    n = float(len(pairs))
    return {name: float(rank) / n for (name, _value), rank in zip(pairs, ranks, strict=True)}


@dataclass
class Candidate:
    cnpj: str
    ticker: str
    adv_brl: float
    financial: bool
    mom: float | None
    vol: float | None
    quality: dict[str, float]


def _best_listing(
    company: Company,
    prepared: dict[str, Prepared],
    ordinal: int,
    month_ends: dict[tuple[int, int], int],
) -> Candidate | None:
    best: Candidate | None = None
    day = date.fromordinal(int(ordinal))
    for ticker in active_ticker(company.tickers, ordinal):
        prep = prepared.get(ticker)
        if prep is None:
            continue
        idx = _print_index(prep, ordinal)
        if idx is None or idx < ADV_MIN_OBS:
            continue
        adv_brl, _adv_sh = trailing_adv(prep.tape, idx, ADV_WINDOW)
        if adv_brl < LIQUIDITY_ADV_BRL:
            continue
        vol_value = float(prep.vol[idx])
        cand = Candidate(
            cnpj=company.cnpj,
            ticker=ticker,
            adv_brl=adv_brl,
            financial=company.financial,
            mom=momentum_12_1(prep, month_ends, day.year, day.month),
            vol=vol_value if math.isfinite(vol_value) else None,
            quality=quality_components(company, ordinal),
        )
        if best is None or cand.adv_brl > best.adv_brl:
            best = cand
    return best


def build_candidates(
    companies: Sequence[Company],
    prepared: dict[str, Prepared],
    sessions: Sequence[int],
    ordinals: Sequence[int],
) -> dict[int, list[Candidate]]:
    """One liquid listing per company at each signal. No price after the signal is read."""
    month_ends = calendar_month_ends(sessions)
    table: dict[int, list[Candidate]] = {}
    for ordinal in ordinals:
        rows: list[Candidate] = []
        seen: set[str] = set()
        for company in companies:
            cand = _best_listing(company, prepared, int(ordinal), month_ends)
            if cand is None or cand.cnpj in seen:
                continue
            seen.add(cand.cnpj)
            rows.append(cand)
        table[int(ordinal)] = rows
    return table


def _quality_scores(cands: Sequence[Candidate]) -> dict[str, float]:
    pool = [c for c in cands if not c.financial and len(c.quality) >= MIN_QUALITY_COMPONENTS]
    components = ("roe", "roic", "margin", "equity_ratio")
    ranks = {name: _ranks([(c.ticker, c.quality[name]) for c in pool if name in c.quality]) for name in components}
    out = {}
    for cand in pool:
        parts = [ranks[name][cand.ticker] for name in components if cand.ticker in ranks[name]]
        if len(parts) >= MIN_QUALITY_COMPONENTS:
            out[cand.ticker] = float(np.mean(parts))
    return out


def score_factor(cands: Sequence[Candidate], factor: str) -> dict[str, float]:
    if factor == "momentum_12_1":
        return _ranks([(c.ticker, c.mom) for c in cands if c.mom is not None])
    if factor == "low_vol":
        return _ranks([(c.ticker, -c.vol) for c in cands if c.vol is not None and c.vol >= 0])
    if factor == "quality":
        return _quality_scores(cands)
    if factor == "composite":
        quality = _quality_scores(cands)
        pool = [c for c in cands if c.ticker in quality and c.mom is not None and c.vol is not None and c.vol >= 0]
        mom = _ranks([(c.ticker, c.mom) for c in pool if c.mom is not None])
        vol = _ranks([(c.ticker, -c.vol) for c in pool if c.vol is not None])
        qual = _ranks([(c.ticker, quality[c.ticker]) for c in pool])
        return {c.ticker: (mom[c.ticker] + vol[c.ticker] + qual[c.ticker]) / 3.0 for c in pool}
    raise ValueError(f"unknown factor {factor}")


def top_quintile(scores: dict[str, float]) -> list[str]:
    """Equal-weight names. Fewer than 25 scored names means the book stays in cash."""
    if len(scores) < MIN_ELIGIBLE:
        return []
    ordered = sorted(scores, key=lambda ticker: (-scores[ticker], ticker))
    n_hold = int(math.ceil(len(ordered) * QUINTILE))
    return ordered[: max(n_hold, 0)]


def _rows_for(cands: Sequence[Candidate], tickers: Sequence[str]) -> list[NameRow]:
    by_ticker = {c.ticker: c for c in cands}
    rows = []
    for ticker in tickers:
        cand = by_ticker.get(ticker)
        if cand is None:
            continue
        rows.append(NameRow(cand.cnpj, cand.ticker, 1.0, None, None, cand.adv_brl, 0.0, None, -1))
    return rows


def signal_book(
    cands_by_ord: dict[int, list[Candidate]],
    ordinals: Sequence[int],
    factor: str,
) -> dict[int, list[NameRow]]:
    book: dict[int, list[NameRow]] = {}
    for ordinal in ordinals:
        cands = cands_by_ord.get(int(ordinal), [])
        chosen = top_quintile(score_factor(cands, factor))
        book[int(ordinal)] = _rows_for(cands, chosen)
    return book


def universe_book(cands_by_ord: dict[int, list[Candidate]], ordinals: Sequence[int]) -> dict[int, list[NameRow]]:
    """Equal weight of every liquid name. Not a registered trial."""
    book: dict[int, list[NameRow]] = {}
    for ordinal in ordinals:
        cands = cands_by_ord.get(int(ordinal), [])
        book[int(ordinal)] = _rows_for(cands, [c.ticker for c in cands])
    return book


def _passthrough(_sig: int, rows: list[NameRow], _pos: dict) -> list[NameRow]:
    return list(rows)


def _one_way_turnover(book: dict[int, list[NameRow]]) -> float:
    """Mean one-way turnover after the initial build. The first investment from cash is not included."""
    prev: dict[str, float] | None = None
    turns: list[float] = []
    for ordinal in sorted(book):
        names = [row.ticker for row in book[ordinal]]
        new_w = {ticker: 1.0 / len(names) for ticker in names} if names else {}
        if prev is not None:
            keys = set(prev) | set(new_w)
            turns.append(0.5 * sum(abs(new_w.get(key, 0.0) - prev.get(key, 0.0)) for key in keys))
        prev = new_w
    return float(np.mean(turns)) if turns else 0.0


def _capacity(book: dict[int, list[NameRow]]) -> dict[str, float]:
    typical: list[float] = []
    thin: list[float] = []
    counts: list[int] = []
    for rows in book.values():
        counts.append(len(rows))
        advs = [row.adv_brl for row in rows if row.adv_brl > 0]
        if not advs:
            continue
        n = len(rows)
        typical.append(PARTICIPATION_CAP * float(np.median(advs)) * n)
        thin.append(PARTICIPATION_CAP * float(min(advs)) * n)
    return {
        "median_names": float(np.median(counts)) if counts else 0.0,
        "fraction_rebalances_in_cash": float(np.mean([c == 0 for c in counts])) if counts else 1.0,
        "capacity_typical_10pct_adv": float(np.median(typical)) if typical else 0.0,
        "capacity_thin_10pct_adv": float(np.median(thin)) if thin else 0.0,
        "n_rebalances": len(counts),
    }


def _monthly_pairs(result: dict[str, Any], which: str) -> tuple[list[int], list[float]]:
    return monthly_simple_returns(result["ords"], result[which])


def _slice_perf(result: dict[str, Any], which: str, start_ord: int | None, end_ord: int | None) -> dict[str, Any]:
    ords = [int(o) for o in result["ords"]]
    equity = result[which]
    if not ords:
        return performance([], [], [])
    lo = 0 if start_ord is None else int(np.searchsorted(np.asarray(ords), start_ord, side="left"))
    hi = len(ords) if end_ord is None else int(np.searchsorted(np.asarray(ords), end_ord, side="right"))
    if start_ord is not None and lo > 0:
        lo -= 1
    if hi - lo < 2:
        return performance([], [], [])
    m_ords, m_rets = monthly_simple_returns(ords[lo:hi], equity[lo:hi])
    return performance(ords[lo:hi], equity[lo:hi], m_rets)


def choose_specification(rows: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the sleeve at the selection AUM from the design window only.

    Highest design-window net Sharpe, then higher design net CAGR, then lower
    annual one-way turnover, then monthly before quarterly, then the factor
    name. A row needs at least 36 design months. Fields other than the design
    metrics are ignored, including any out-of-sample number a caller attaches.
    """
    usable = [
        row
        for row in rows
        if row.get("design_sharpe") is not None and int(row.get("n_design") or 0) >= 36
    ]
    if not usable:
        return None

    def sort_key(row: dict[str, Any]) -> tuple:
        return (
            -float(row["design_sharpe"]),
            -(float(row["design_cagr"]) if row.get("design_cagr") is not None else -1e9),
            float(row["design_turnover"]) if row.get("design_turnover") is not None else 1e9,
            0 if row["frequency"] == "monthly" else 1,
            str(row["factor"]),
        )

    return dict(sorted(usable, key=sort_key)[0])


def _cdi_cagr(cdi_ords: np.ndarray, cdi_rates: np.ndarray, start_ord: int, end_ord: int) -> float | None:
    if len(cdi_ords) == 0 or end_ord <= start_ord:
        return None
    growth = cdi_growth(cdi_ords, cdi_rates, start_ord, end_ord)
    years = (end_ord - start_ord) / 365.25
    if years <= 0.05 or growth <= 0:
        return None
    return float(growth ** (1.0 / years) - 1.0)


def _round(value: Any, ndigits: int = 6) -> Any:
    if value is None:
        return None
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return round(value, ndigits)
    return value


def run_study(
    companies: Sequence[Company],
    tapes: dict[str, Tape],
    sessions: Sequence[int],
    ibov_ords: np.ndarray,
    ibov_close: np.ndarray,
    cdi_ords: np.ndarray,
    cdi_rates: np.ndarray,
    registry_path: str,
) -> dict[str, Any]:
    """Run the pre-specified grid, register every full-sample net path, then judge the held-out window.

    Parameters are chosen on month-ends through 2018-12-31 at R$ 1 million.
    The chosen sleeve is scored on the later path only. DSR uses N equal to
    every registered variation, including the AUM variants that were not
    eligible to be chosen. That score does not authorize live trading.
    """
    if len(sessions) < 30:
        raise ValueError("need a session calendar")
    prepared = prepare_tapes(tapes)
    monthly_ords = signal_ordinals(sessions, "monthly")
    quarterly_ords = signal_ordinals(sessions, "quarterly")
    print(f"signals monthly={len(monthly_ords)} quarterly={len(quarterly_ords)}", flush=True)
    cands = build_candidates(companies, prepared, sessions, monthly_ords)
    books = {
        (factor, "monthly"): signal_book(cands, monthly_ords, factor)
        for factor in FACTORS
    }
    books.update(
        {(factor, "quarterly"): signal_book(cands, quarterly_ords, factor) for factor in FACTORS}
    )
    design_end = DESIGN_END.toordinal()
    eval_start = EVAL_START.toordinal()

    def _run(book: dict[int, list[NameRow]], aum: float) -> dict[str, Any]:
        return simulate(sessions, tapes, book, _passthrough, float(aum), hold_until_exit=False)

    results: list[dict[str, Any]] = []
    cache: dict[tuple[str, str, float], dict[str, Any]] = {}
    with TrialRegistry(registry_path) as registry:
        for spec in production_grid():
            key = (spec["factor"], spec["frequency"], float(spec["aum"]))
            book = books[(spec["factor"], spec["frequency"])]
            print(f"trial {spec['factor']} {spec['frequency']} aum={spec['aum']:.0f}", flush=True)
            run = _run(book, float(spec["aum"]))
            cache[key] = run
            m_ords, monthly = _monthly_pairs(run, "net")
            params = {
                "family": FAMILY_ID,
                "factor": spec["factor"],
                "frequency": spec["frequency"],
                "aum_brl": spec["aum"],
                "liquidity_adv_brl": LIQUIDITY_ADV_BRL,
                "quintile": QUINTILE,
                "min_eligible": MIN_ELIGIBLE,
                "costs": "fee+half_spread+participation_slippage",
                "oos_split": "design_through_2018-12-31_eval_from_2019-01-01",
            }
            if len(monthly) >= 3:
                registry.register(
                    FAMILY_ID,
                    params,
                    returns=monthly,
                    costs_included=True,
                    periods_per_year=PERIODS_PER_YEAR,
                    notes=f"{spec['factor']}:{spec['frequency']}",
                )
            results.append({"spec": spec, "run": run, "book": book, "monthly_ords": m_ords, "monthly": monthly, "params": params})
        n_trials = registry.count(FAMILY_ID)

    per_year = {"monthly": 12.0, "quarterly": 4.0}
    public: list[dict[str, Any]] = []
    selection_rows: list[dict[str, Any]] = []
    for item in results:
        spec = item["spec"]
        run = item["run"]
        book = item["book"]
        full_net = performance(run["ords"], run["net"], item["monthly"])
        _g_ords, monthly_g = _monthly_pairs(run, "gross")
        full_gross = performance(run["ords"], run["gross"], monthly_g)
        design_pairs = [(o, r) for o, r in zip(item["monthly_ords"], item["monthly"], strict=False) if int(o) <= design_end]
        design_rets = [r for _o, r in design_pairs]
        design_perf = _slice_perf(run, "net", None, design_end)
        oos_pairs = [(o, r) for o, r in zip(item["monthly_ords"], item["monthly"], strict=False) if int(o) >= eval_start]
        oos_rets = [r for _o, r in oos_pairs]
        oos_net = _slice_perf(run, "net", eval_start, None)
        oos_gross = _slice_perf(run, "gross", eval_start, None)
        cap = _capacity(book)
        turnover = _one_way_turnover(book) * per_year[spec["frequency"]]
        design_book = {int(o): rows for o, rows in book.items() if int(o) <= design_end}
        design_turnover = _one_way_turnover(design_book) * per_year[spec["frequency"]]
        judged = None
        if len(item["monthly"]) >= 3 and n_trials >= 2:
            judged = gate(
                costs_included=True,
                returns=item["monthly"],
                n_trials=float(n_trials),
                periods_per_year=PERIODS_PER_YEAR,
                n_eff=None,
            )
        oos_judged = None
        if len(oos_rets) >= 3 and n_trials >= 2:
            oos_judged = gate(
                costs_included=True,
                returns=oos_rets,
                n_trials=float(n_trials),
                periods_per_year=PERIODS_PER_YEAR,
                n_eff=None,
            )
        oos_ords = [int(o) for o in run["ords"] if int(o) >= eval_start]
        if run["ords"]:
            base = [int(o) for o in run["ords"] if int(o) <= design_end]
            cdi_start = base[-1] if base else int(run["ords"][0])
            cdi_end = int(run["ords"][-1])
        else:
            cdi_start = cdi_end = 0
        oos_cdi = _cdi_cagr(cdi_ords, cdi_rates, cdi_start, cdi_end) if oos_ords else None
        oos_cagr = oos_net.get("cagr")
        excess = None if oos_cagr is None or oos_cdi is None else float(oos_cagr) - float(oos_cdi)
        stats = run["stats"]
        gap = None
        if run["gross"] and run["net"]:
            gap = round(float(run["gross"][-1]) - float(run["net"][-1]), 2)
        components = round(stats.fee + stats.half_spread + stats.slippage, 2)
        row = {
            "factor": spec["factor"],
            "frequency": spec["frequency"],
            "aum_brl": spec["aum"],
            "selection_candidate": bool(spec["aum"] == SELECTION_AUM),
            "cagr_gross": _round(full_gross.get("cagr")),
            "cagr_net": _round(full_net.get("cagr")),
            "sharpe_net": _round(full_net.get("sharpe")),
            "max_drawdown_gross": _round(full_gross.get("max_drawdown")),
            "max_drawdown_net": _round(full_net.get("max_drawdown")),
            "psr": None if judged is None else judged.psr,
            "dsr": None if judged is None else judged.dsr,
            "min_trl_months": None if judged is None or judged.min_trl is None or not math.isfinite(judged.min_trl) else judged.min_trl,
            "min_trl_infinite": bool(judged is not None and judged.min_trl is not None and not math.isfinite(judged.min_trl)),
            "n_obs_months": None if judged is None else judged.n_obs,
            "n_trials": n_trials,
            "turnover_one_way_annual": _round(turnover, 4),
            "design_turnover": _round(design_turnover, 4),
            "capacity_typical_10pct_adv": _round(cap["capacity_typical_10pct_adv"], 2),
            "capacity_thin_10pct_adv": _round(cap["capacity_thin_10pct_adv"], 2),
            "median_names": cap["median_names"],
            "fraction_rebalances_in_cash": _round(cap["fraction_rebalances_in_cash"], 4),
            "n_rebalances": cap["n_rebalances"],
            "design_sharpe": _round(design_perf.get("sharpe")),
            "design_cagr": _round(design_perf.get("cagr")),
            "n_design": len(design_rets),
            "oos_cagr_gross": _round(oos_gross.get("cagr")),
            "oos_cagr_net": _round(oos_cagr),
            "oos_max_drawdown_net": _round(oos_net.get("max_drawdown")),
            "oos_sharpe": _round(oos_net.get("sharpe")),
            "oos_psr": None if oos_judged is None else oos_judged.psr,
            "oos_dsr": None if oos_judged is None else oos_judged.dsr,
            "oos_min_trl_months": None
            if oos_judged is None or oos_judged.min_trl is None or not math.isfinite(oos_judged.min_trl)
            else oos_judged.min_trl,
            "oos_min_trl_infinite": bool(
                oos_judged is not None and oos_judged.min_trl is not None and not math.isfinite(oos_judged.min_trl)
            ),
            "oos_n_months": len(oos_rets),
            "oos_cagr_cdi": _round(oos_cdi),
            "oos_excess_cagr_over_cdi": _round(excess),
            "terminal_gap_brl": gap,
            "cost_components_brl": components,
            "fills_n": stats.n,
            "fills_capped": stats.n_capped,
            "month_ends": [date.fromordinal(int(o)).isoformat() for o in item["monthly_ords"]],
            "monthly_net": [round(float(x), 8) for x in item["monthly"]],
            "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
        }
        public.append(row)
        if spec["aum"] == SELECTION_AUM:
            selection_rows.append(row)

    chosen = choose_specification(selection_rows)
    chosen_row = None
    if chosen is not None:
        for row in public:
            if (
                row["factor"] == chosen["factor"]
                and row["frequency"] == chosen["frequency"]
                and row["aum_brl"] == SELECTION_AUM
            ):
                chosen_row = row
                break
    criterion = False
    if chosen_row is not None:
        dsr = chosen_row.get("oos_dsr")
        excess = chosen_row.get("oos_excess_cagr_over_cdi")
        criterion = bool(dsr is not None and dsr >= 0.95 and excess is not None and excess > 0)

    print("benchmarks", flush=True)
    bench = {}
    for frequency, ords in (("monthly", monthly_ords), ("quarterly", quarterly_ords)):
        book = universe_book(cands, ords)
        run = _run(book, SELECTION_AUM)
        _m_ords, monthly = _monthly_pairs(run, "net")
        _g_ords, monthly_g = _monthly_pairs(run, "gross")
        bench[frequency] = {
            "aum_brl": SELECTION_AUM,
            "net": {k: _round(v) for k, v in performance(run["ords"], run["net"], monthly).items()},
            "gross": {k: _round(v) for k, v in performance(run["ords"], run["gross"], monthly_g).items()},
            "turnover_one_way_annual": _round(_one_way_turnover(book) * per_year[frequency], 4),
            **{k: _round(v, 4) if isinstance(v, float) else v for k, v in _capacity(book).items()},
            "registered_trial": False,
            "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
        }

    sample_ords = sessions
    ibov = _ibov_public(ibov_ords, ibov_close, sample_ords)
    cdi_full = _cdi_cagr(cdi_ords, cdi_rates, int(sessions[0]), int(sessions[-1]))
    try:
        with TrialRegistry(registry_path) as registry:
            eff = registry.effective_n_trials(FAMILY_ID)
    except ValueError:
        eff = {"n_eff": None, "mean_corr": None}

    return {
        "family_id": FAMILY_ID,
        "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
        "n_trials": n_trials,
        "n_eff": None if eff.get("n_eff") is None else round(float(eff["n_eff"]), 4),
        "mean_pairwise_corr": None if eff.get("mean_corr") is None else round(float(eff["mean_corr"]), 4),
        "dsr_n": "all_registered_trials",
        "periods_per_year": PERIODS_PER_YEAR,
        "sample": {
            "first_session": date.fromordinal(int(sessions[0])).isoformat(),
            "last_session": date.fromordinal(int(sessions[-1])).isoformat(),
            "n_sessions": len(sessions),
            "n_monthly_signals": len(monthly_ords),
            "n_quarterly_signals": len(quarterly_ords),
        },
        "method": {
            "momentum": "P(month-end t-1) / P(month-end t-12) - 1, split-adjusted, signal month excluded",
            "quality": "mean percentile of ROE, ROIC, EBIT margin, equity/assets; at least 2; financials excluded",
            "low_vol": "trailing std of up to 252 close-to-close returns, min 120, gaps <= 5 days, sqrt(252)",
            "composite": "equal average of momentum, quality and low-vol percentiles inside their intersection",
            "portfolio": "equal-weight top quintile; cash if fewer than 25 scored names",
            "liquidity": f"60-session median BRL volume >= {LIQUIDITY_ADV_BRL:.0f}, print within 5 days",
            "rebalance": "signal at month-end or quarter-end close, fill at the next session close",
            "costs": "B3 taker fee, half-spread, participation slippage from trading_costs.quote_fill",
            "cash": "idle cash earns 0; CDI is a benchmark, not a credit inside the book",
            "dividends": "stock and equal-weight returns are price returns; dividends are not in the tape",
        },
        "oos_split": {
            "design_end": DESIGN_END.isoformat(),
            "eval_start": EVAL_START.isoformat(),
            "selection_aum_brl": SELECTION_AUM,
            "rule": (
                "Among the 4 sleeves and 2 rebalance frequencies at R$ 1 million, "
                "choose the highest net Sharpe on month-ends through 2018-12-31 "
                "(at least 36 months). Ties break to higher design CAGR, then lower "
                "turnover, then monthly, then factor name. AUM variants are registered "
                "and counted in N, and are not eligible to be chosen. The chosen "
                "sleeve is then scored on month-ends from 2019-01-01 onward. "
                "The path is not flattened at the split."
            ),
            "selected": None
            if chosen_row is None
            else {
                "factor": chosen_row["factor"],
                "frequency": chosen_row["frequency"],
                "aum_brl": chosen_row["aum_brl"],
                "design_sharpe": chosen_row["design_sharpe"],
                "design_cagr": chosen_row["design_cagr"],
                "n_design": chosen_row["n_design"],
            },
            "criterion": "DSR >= 0.95 on the out-of-sample net monthly returns, N = all registered trials, AND out-of-sample net CAGR minus CDI CAGR > 0",
            "criterion_met": criterion,
            "oos_dsr": None if chosen_row is None else chosen_row.get("oos_dsr"),
            "oos_excess_cagr_over_cdi": None if chosen_row is None else chosen_row.get("oos_excess_cagr_over_cdi"),
            "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
        },
        "trials": public,
        "benchmark_equal_weight": bench,
        "benchmark_ibov": ibov,
        "benchmark_cdi": {
            "series": "BCB SGS 12",
            "unit": "daily percent converted to a decimal, compounded",
            "cagr_full_sample": _round(cdi_full),
            "note": "CDI is the opportunity cost. The factor book does not earn it on idle cash.",
        },
        "us": {
            "estimated": False,
            "reason": (
                "No free point-in-time US stock or ETF panel that keeps delisted names "
                "was available. A survivor list from a chart API would not be this "
                "study. No US figure is reported."
            ),
        },
        "verdict": {
            "criterion_met": criterion,
            "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
            "note": "A pass would still be paper research. It does not authorize capital.",
        },
    }


def _ibov_public(ords: np.ndarray, close: np.ndarray, sample: Sequence[int]) -> dict[str, Any]:
    block = _ibov_stats(ords, close, sample)
    if not block.get("available"):
        return block
    return block
