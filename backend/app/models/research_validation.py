"""Financial research protocol: causal features, purged walk-forward and net risk."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

POLICY_VERSION = "ATOM-RESEARCH-1.0"
FEATURES = [
    {"name": "return_1d", "rationale": "Short-term reversal or continuation hypothesis; no price level."},
    {"name": "momentum_5d", "rationale": "Short-horizon persistence of returns; may reverse after costs."},
    {"name": "momentum_20d", "rationale": "Medium-horizon trend as a testable behavioral hypothesis."},
    {"name": "volatility_20d", "rationale": "Volatility clustering and conditional risk."},
    {"name": "downside_20d", "rationale": "Asymmetric downside variation as a risk-state descriptor."},
]


@dataclass
class PurgedGroupWalkForward:
    """Keep whole ordered groups; purge overlapping labels and gap prior groups.

    All training precedes testing. ``gap_groups`` is a conservative pre-test
    embargo, not the post-test embargo used by bidirectional PurgedKFold.
    No future observations are ever eligible for training in a fold.
    """

    n_splits: int = 4
    min_train_groups: int = 6
    gap_groups: int = 1

    def split(self, groups, decision_times, label_end_times):
        groups = np.asarray(groups)
        starts, ends = np.asarray(decision_times), np.asarray(label_end_times)
        if not (len(groups) == len(starts) == len(ends)) or len(groups) == 0:
            raise ValueError("Invalid split arrays")
        if np.any(starts[1:] < starts[:-1]) or np.any(ends < starts):
            raise ValueError("Observations must be chronological with causal label intervals")
        ordered = list(dict.fromkeys(groups.tolist()))
        indices = {g: i for i, g in enumerate(ordered)}
        ranks = np.array([indices[g] for g in groups])
        if np.any(np.diff(ranks) < 0):
            raise ValueError("Groups must be contiguous")
        first_test = self.min_train_groups + self.gap_groups
        if len(ordered) - first_test < self.n_splits:
            raise ValueError(
                "Histórico curto: use pelo menos 18 meses de observações diárias "
                f"({self.min_train_groups} meses de treino, {self.gap_groups} de intervalo "
                f"e {self.n_splits} janelas de teste)."
            )
        for block in np.array_split(np.arange(first_test, len(ordered)), self.n_splits):
            test = np.flatnonzero(np.isin(ranks, block))
            candidates = np.flatnonzero(ranks < block[0] - self.gap_groups)
            train = candidates[ends[candidates] < starts[test[0]]]
            if len(train) < 60 or len(test) < 5:
                raise ValueError("Cada janela precisa de 60 observações de treino e 5 de teste.")
            yield train, test


def build_features(prices):
    """Information through close t; trade at t+1 close, label t+1 to t+2."""
    prices = np.asarray(prices, dtype=float)
    if len(prices) < 65 or not np.all(np.isfinite(prices)) or np.any(prices <= 0):
        raise ValueError("Prices must be finite and strictly positive")
    returns = np.diff(prices) / prices[:-1]
    times = np.arange(60, len(prices) - 2)
    rows, vol = [], []
    for t in times:
        window = returns[t - 20:t]
        daily_vol = float(np.std(window, ddof=1))
        rows.append([returns[t - 1], prices[t] / prices[t - 5] - 1,
                     prices[t] / prices[t - 20] - 1, daily_vol,
                     float(np.sqrt(np.mean(np.minimum(window, 0) ** 2)))])
        vol.append(max(daily_vol * np.sqrt(252), 0.01))
    target = prices[times + 2] / prices[times + 1] - 1
    return np.array(rows), target, times, np.array(vol)


def portfolio_metrics(returns, targets, cost_bps, max_drawdown=1.0):
    """Long/cash, no leverage; costs on actual rebalancing and final liquidation.

    Rebalancing targets a fraction of post-cost equity. We solve the cost
    equation explicitly, accounting for weight drift between observations.
    The drawdown brake applies on the NEXT decision; gaps can exceed its limit.
    """
    returns = np.asarray(returns, dtype=float)
    targets = np.asarray(targets, dtype=float)
    if len(returns) == 0 or len(returns) != len(targets):
        raise ValueError("Invalid portfolio arrays")
    rate = cost_bps / 10000
    wealth, gross, peak, previous = 1.0, 1.0, 1.0, 0.0
    halted = False
    brake_at = None
    equity, gross_equity, net_returns, turnovers, weights = [1.0], [1.0], [], [], []
    paid = 0.0
    for i, (ret, target) in enumerate(zip(returns, targets)):
        weight = 0.0 if halted else float(np.clip(target, 0, 1))
        delta = weight - previous
        fee = rate * abs(delta) / (1 + rate * weight if delta >= 0 else 1 - rate * weight)
        turnover = abs(weight * (1 - fee) - previous)
        paid += wealth * fee
        factor = (1 - fee) * (1 + weight * ret)
        wealth *= factor
        gross *= 1 + weight * ret
        previous = weight * (1 + ret) / (1 + weight * ret)
        net_returns.append(factor - 1)
        turnovers.append(turnover)
        weights.append(weight)
        equity.append(wealth)
        gross_equity.append(gross)
        peak = max(peak, wealth)
        if not halted and 1 - wealth / peak >= max_drawdown:
            halted, brake_at = True, i
    liquidation = previous * rate
    paid += wealth * liquidation
    wealth *= 1 - liquidation
    equity[-1] = wealth
    net_returns[-1] = (1 + net_returns[-1]) * (1 - liquidation) - 1
    turnovers[-1] += previous
    values = np.asarray(equity)
    net = np.asarray(net_returns)
    vol = float(np.std(net, ddof=1)) if len(net) > 1 else 0.0
    sharpe = float(np.mean(net) / vol * np.sqrt(252)) if vol > 1e-12 else 0.0
    dd = float(np.max(1 - values / np.maximum.accumulate(values)))
    return {
        "net_return_pct": float((wealth - 1) * 100),
        "gross_return_pct": float((gross - 1) * 100),
        "sharpe_net": sharpe,
        "annualized_volatility_pct": vol * np.sqrt(252) * 100,
        "max_drawdown_pct": dd * 100,
        "turnover_total": float(np.sum(turnovers)),
        "cost_paid_pct_initial": paid * 100,
        "drawdown_brake_triggered": halted,
        "drawdown_brake_index": brake_at,
        "n_observations": len(net),
        "equity": equity,
        "weights": weights,
    }


def evaluate_experiment(prices, dates, *, model, hypothesis, data_source,
                        price_basis, commission_bps=5, slippage_bps=5,
                        target_volatility=0.10, max_drawdown=0.20,
                        n_splits=4, gap_groups=1):
    """Evaluate fixed models on identical out-of-sample chronological windows."""
    prices = [float(p) for p in prices]
    dates = [d.isoformat()[:10] if hasattr(d, "isoformat") else str(d)[:10] for d in dates]
    features, labels, times, volatility = build_features(prices)
    groups = np.array([dates[t][:7] for t in times])
    splitter = PurgedGroupWalkForward(n_splits=n_splits, gap_groups=gap_groups)
    predictions = {name: np.full(len(times), np.nan) for name in ("ridge", "random_forest", "zero", "momentum")}
    fold_reports, test_indices = [], []
    for number, (train, test) in enumerate(splitter.split(groups, times, times + 2), 1):
        # Fixed hyperparameters: neither model nor scaler sees future folds.
        ridge = make_pipeline(StandardScaler(), Ridge(alpha=10.0))
        ridge.fit(features[train], labels[train])
        predictions['ridge'][test] = ridge.predict(features[test])
        if model == 'random_forest':
            forest = RandomForestRegressor(n_estimators=40, max_depth=3,
                min_samples_leaf=20, random_state=42, n_jobs=1)
            forest.fit(features[train], labels[train])
            predictions['random_forest'][test] = forest.predict(features[test])
        predictions['zero'][test] = 0
        predictions['momentum'][test] = features[test, 2] / 20
        test_indices.extend(test.tolist())
        fold_reports.append({
            "fold": number, "train_count": len(train), "test_count": len(test),
            "train_start": dates[times[train[0]]], "train_end": dates[times[train[-1]]],
            "last_train_label_end": dates[times[train[-1]] + 2],
            "test_start": dates[times[test[0]]], "test_end": dates[times[test[-1]] + 2],
            "test_groups": list(dict.fromkeys(groups[test].tolist())),
        })
    oos = np.asarray(test_indices)
    cost = commission_bps + slippage_bps
    sizing = np.minimum(target_volatility / volatility[oos], 1)
    results = {}
    names = ['ridge', 'zero', 'momentum'] + (['random_forest'] if model == 'random_forest' else [])
    for name in names:
        pred = predictions[name][oos]
        # A conservative fixed hurdle for entering, not a claim of known costs.
        weights = (pred > 2 * cost / 10000) * sizing
        perf = portfolio_metrics(labels[oos], weights, cost, max_drawdown)
        perf['mse_oos'] = float(np.mean((pred - labels[oos]) ** 2))
        perf['direction_accuracy_pct'] = float(np.mean((pred > 0) == (labels[oos] > 0)) * 100)
        results[name] = perf
    results['buy_hold'] = portfolio_metrics(labels[oos], np.ones(len(oos)), cost)
    selected = results[model]
    cursor = 0
    # Fold returns use the continuous OOS portfolio, with no free resets.
    for report in fold_reports:
        end = cursor + report['test_count']
        report['net_return_pct'] = (selected['equity'][end] / selected['equity'][cursor] - 1) * 100
        cursor = end
    reasons = []
    if 'synthetic' in data_source.lower() or 'demo' in data_source.lower():
        reasons.append('Dados sintéticos servem apenas para testar o protocolo.')
    if price_basis != 'adjusted':
        reasons.append('Preços ajustados por eventos corporativos não foram confirmados.')
    if cost <= 0:
        reasons.append('Custos zerados não atendem ao protocolo.')
    if len(oos) < 126:
        reasons.append('Menos de 126 observações fora da amostra.')
    if selected['net_return_pct'] <= 0 or selected['sharpe_net'] < 0.5:
        reasons.append('Retorno líquido ou Sharpe não atingiu o critério de pesquisa.')
    if selected['max_drawdown_pct'] > max_drawdown * 100:
        reasons.append('Drawdown realizado excedeu o limite declarado.')
    if sum(f['net_return_pct'] > 0 for f in fold_reports) / n_splits < 0.6 or fold_reports[-1]['net_return_pct'] <= 0:
        reasons.append('Resultado instável entre janelas ou negativo na janela mais recente.')
    baseline = 'ridge' if model == 'random_forest' else 'momentum'
    if selected['sharpe_net'] <= results[baseline]['sharpe_net'] or selected['mse_oos'] >= results['zero']['mse_oos']:
        reasons.append('Não superou o baseline simples em Sharpe líquido e a previsão zero em erro.')
    config = dict(model=model, hypothesis=hypothesis, data_source=data_source,
        price_basis=price_basis, commission_bps=commission_bps, slippage_bps=slippage_bps,
        target_volatility=target_volatility, max_drawdown=max_drawdown,
        n_splits=n_splits, gap_groups=gap_groups, policy_version=POLICY_VERSION)
    fingerprint = hashlib.sha256(json.dumps({'prices': prices, 'dates': dates, 'config': config}, sort_keys=True).encode()).hexdigest()
    return {
        'experiment_id': fingerprint, 'policy_version': POLICY_VERSION,
        'status': 'research_only', 'eligible_for_live_trading': False,
        'assessment': 'insufficient_evidence' if reasons else 'candidate_for_independent_review',
        'reasons': reasons,
        'limitations': [
            'Um resultado favorável não autoriza execução nem comprova alpha. Requer holdout independente e revisão humana.',
            'Repetir experimentos após observar o OOS contamina a seleção; não houve correção por múltiplos testes.',
            'Features de fechamento são proxies de retorno e risco; não incluem fundamentos point-in-time nem microestrutura.',
            'Fonte e ajuste dos preços são declarações do solicitante, não auditoria de qualidade.',
            'Intervalos são tratados como pregões diários; Sharpe usa 252 e caixa rende zero. Custos constantes não modelam impacto/capacidade.',
            'A trava de drawdown reage na próxima decisão e não garante perda máxima durante saltos de preço.',
        ],
        'protocol': {'name': 'purged_group_walk_forward', 'group': 'calendar_month',
                     'gap_groups_before_test': gap_groups, 'label_horizon_bars': 1,
                     'execution_delay_bars': 1, 'information_end_to_label_end_bars': 2,
                     'future_training': False, 'scaler_fit': 'training_fold_only'},
        'config': config, 'features': FEATURES, 'folds': fold_reports,
        'oos_dates': [dates[t + 2] for t in times[oos]], 'results': results,
    }
