"""
Investment Philosophy Agents — inspired by multi-agent hedge fund pattern.
Each agent takes a quant_data dict and returns AgentSignal.
"""
from __future__ import annotations
import dataclasses
from typing import Literal

SignalType = Literal["COMPRAR CALL", "COMPRAR PUT", "NEUTRO", "STRADDLE"]

@dataclasses.dataclass
class AgentSignal:
    agent: str           # agent name
    persona: str         # e.g. "Warren Buffett"
    signal: SignalType
    confidence: float    # 0-100
    reasoning: str
    weight: float        # relative weight in aggregation

# quant_data keys used by agents:
# ml_return_pct, beta, alpha_annual_pct, var_pct, black_swan_score,
# iv_pct, garch_vol_pct, momentum_raw, bull_score, price, change_pct

def buffett_agent(quant_data: dict) -> AgentSignal:
    """
    Warren Buffett: long-term value. Favours low beta, positive alpha, low VaR.
    Buys CALL only on quality undervalued companies. Avoids high IV.
    """
    alpha = quant_data.get("alpha_annual_pct", 0)
    beta = quant_data.get("beta", 1)
    var = quant_data.get("var_pct", 2)
    iv = quant_data.get("iv_pct", 30)
    ml = quant_data.get("ml_return_pct", 0)

    score = 50.0
    if alpha > 5: score += 20
    elif alpha > 0: score += 10
    else: score -= 15
    if beta < 0.8: score += 10
    elif beta > 1.5: score -= 10
    if var < 2: score += 10
    elif var > 4: score -= 10
    if iv > 50: score -= 15  # Buffett avoids expensive options
    if ml > 5: score += 10
    score = max(0, min(100, score))

    if score >= 65 and iv < 45:
        signal = "COMPRAR CALL"
        reasoning = f"Alpha positivo ({alpha:.1f}%), beta controlado ({beta:.2f}) e VaR moderado apontam empresa de qualidade. Margem de segurança presente."
    elif score <= 35:
        signal = "COMPRAR PUT"
        reasoning = f"Alpha negativo, risco elevado e/ou momentum desfavorável contradizem os princípios de valor. Cautela recomendada."
    else:
        signal = "NEUTRO"
        reasoning = f"Empresa não atende plenamente os critérios de qualidade e valor. Aguardar melhor ponto de entrada."

    conf = abs(score - 50) * 2
    return AgentSignal("buffett", "Warren Buffett", signal, min(conf, 95), reasoning, weight=1.5)


def burry_agent(quant_data: dict) -> AgentSignal:
    """
    Michael Burry: contrarian/deep value. Looks for stressed assets with
    high Black Swan signal (market overreaction), high VaR = opportunity.
    """
    swan = quant_data.get("black_swan_score", 50)
    momentum = quant_data.get("momentum_raw", 0)
    change = quant_data.get("change_pct", 0)
    ml = quant_data.get("ml_return_pct", 0)
    var = quant_data.get("var_pct", 2)

    # Burry likes high stress + positive ML reversion
    stress_score = 50.0
    if swan > 70: stress_score += 20   # high fear = opportunity (PUT or contrarian CALL)
    if momentum < -15: stress_score += 15  # oversold
    if var > 3: stress_score += 10
    if ml > 3: stress_score += 15       # model sees reversion
    if ml < -3: stress_score -= 15
    stress_score = max(0, min(100, stress_score))

    # Burry goes contrarian: stressed + ML reversion = CALL
    if stress_score >= 65 and ml > 2:
        signal = "COMPRAR CALL"
        reasoning = f"Mercado excessivamente pessimista (Black Swan: {swan:.0f}/100, momentum: {momentum:.0f}). Modelo ML antecipa reversão de {ml:.1f}%. Tese contrária."
    elif stress_score <= 35 or (swan < 30 and momentum > 15):
        signal = "COMPRAR PUT"
        reasoning = f"Mercado complacente com risco (Black Swan baixo {swan:.0f}/100) e momentum ilusoriamente positivo. Assimetria de risco favorável ao downside."
    else:
        signal = "STRADDLE"
        reasoning = f"Volatilidade elevada e incerteza direcional. Straddle captura movimento independentemente da direção."

    conf = abs(stress_score - 50) * 1.5
    return AgentSignal("burry", "Michael Burry", signal, min(conf, 90), reasoning, weight=1.2)


def wood_agent(quant_data: dict) -> AgentSignal:
    """
    Cathie Wood: growth/disruption. ML return and momentum are everything.
    High IV is OK — volatility is the price of transformation.
    """
    ml = quant_data.get("ml_return_pct", 0)
    momentum = quant_data.get("momentum_raw", 0)
    beta = quant_data.get("beta", 1)

    score = 50.0
    score += ml * 3           # ML return weighted heavily
    score += momentum * 0.5
    if beta > 1.2: score += 10  # high beta = growth profile
    score = max(0, min(100, score))

    if score >= 60:
        signal = "COMPRAR CALL"
        reasoning = f"Modelo projeta retorno de {ml:.1f}% com momentum {'+' if momentum>0 else ''}{momentum:.0f}. Perfil de crescimento disruptivo justifica prêmio de opção."
    elif score <= 35:
        signal = "COMPRAR PUT"
        reasoning = f"Projeção ML negativa ({ml:.1f}%) e momentum fraco indicam deaceleração do crescimento. Downside provável."
    else:
        signal = "NEUTRO"
        reasoning = "Potencial de crescimento não confirmado pelos modelos. Posição neutra enquanto tese se desenvolve."

    conf = abs(score - 50) * 1.8
    return AgentSignal("wood", "Cathie Wood", signal, min(conf, 88), reasoning, weight=1.0)


def graham_agent(quant_data: dict) -> AgentSignal:
    """
    Ben Graham: margin of safety + low risk. Penalises high VaR heavily.
    """
    alpha = quant_data.get("alpha_annual_pct", 0)
    var = quant_data.get("var_pct", 2)
    swan = quant_data.get("black_swan_score", 50)
    iv = quant_data.get("iv_pct", 30)
    beta = quant_data.get("beta", 1)

    score = 50.0
    if alpha > 3: score += 15
    elif alpha < -3: score -= 20
    if var < 1.5: score += 20
    elif var > 3.5: score -= 20
    if swan > 60: score -= 15
    if beta > 1.3: score -= 10
    if iv < 25: score += 10
    score = max(0, min(100, score))

    if score >= 65:
        signal = "COMPRAR CALL"
        reasoning = f"Margem de segurança satisfatória: alpha {alpha:.1f}%, VaR {var:.2f}%, Black Swan {swan:.0f}/100. Risco/retorno favorável."
    elif score <= 35:
        signal = "COMPRAR PUT"
        reasoning = f"Margens de segurança inadequadas: risco (VaR {var:.2f}%, IV {iv:.0f}%) supera retorno esperado (alpha {alpha:.1f}%)."
    else:
        signal = "NEUTRO"
        reasoning = "Preço dentro de faixa razoável, mas sem margem de segurança suficiente para posição direcional."

    conf = abs(score - 50) * 1.6
    return AgentSignal("graham", "Benjamin Graham", signal, min(conf, 92), reasoning, weight=1.3)


def lynch_agent(quant_data: dict) -> AgentSignal:
    """
    Peter Lynch: growth at reasonable price. Momentum + ML aligned = ten-bagger.
    """
    ml = quant_data.get("ml_return_pct", 0)
    momentum = quant_data.get("momentum_raw", 0)
    alpha = quant_data.get("alpha_annual_pct", 0)

    score = 50.0
    # "buy what you understand growing"
    if ml > 5 and momentum > 5: score += 35
    elif ml > 3 or momentum > 5: score += 15
    elif ml < -3 and momentum < -5: score -= 30
    elif ml < 0 or momentum < -5: score -= 15
    if alpha > 2: score += 10
    score = max(0, min(100, score))

    if score >= 65:
        signal = "COMPRAR CALL"
        reasoning = f"Empresa em crescimento visível: ML projeta {ml:.1f}%, momentum {'+' if momentum>0 else ''}{momentum:.0f}, alpha {alpha:.1f}%. Potencial de ten-bagger."
    elif score <= 35:
        signal = "COMPRAR PUT"
        reasoning = f"Crescimento revertendo: ML {ml:.1f}%, momentum deteriorando. Evitar armadilha de valor."
    else:
        signal = "NEUTRO"
        reasoning = "Crescimento moderado sem catalisador claro. Monitorar próximos resultados."

    conf = abs(score - 50) * 1.7
    return AgentSignal("lynch", "Peter Lynch", signal, min(conf, 85), reasoning, weight=1.0)


def risk_manager_agent(quant_data: dict) -> AgentSignal:
    """
    Risk Manager: position sizing and risk override.
    If risk is extreme, overrides bullish signals.
    """
    var = quant_data.get("var_pct", 2)
    swan = quant_data.get("black_swan_score", 50)
    iv = quant_data.get("iv_pct", 30)
    garch = quant_data.get("garch_vol_pct", 25)

    risk_score = (var / 5 * 30) + (swan / 100 * 40) + (garch / 80 * 30)

    if risk_score > 70:
        signal = "COMPRAR PUT"
        reasoning = f"Risco sistêmico elevado: VaR {var:.2f}%, Black Swan {swan:.0f}/100, Volatilidade GARCH {garch:.0f}%. Hedge recomendado."
        conf = min(risk_score, 90)
    elif risk_score < 25:
        signal = "COMPRAR CALL"
        reasoning = f"Ambiente de risco favorável: VaR {var:.2f}%, Black Swan {swan:.0f}/100, volatilidade controlada."
        conf = min((50 - risk_score) * 1.5, 80)
    else:
        signal = "NEUTRO"
        reasoning = f"Risco em nível administrável. VaR {var:.2f}%, Black Swan {swan:.0f}/100."
        conf = 60.0

    return AgentSignal("risk_manager", "Risk Manager", signal, conf, reasoning, weight=2.0)


ALL_AGENTS = [buffett_agent, burry_agent, wood_agent, graham_agent, lynch_agent, risk_manager_agent]


def run_all_agents(quant_data: dict) -> list[AgentSignal]:
    return [agent(quant_data) for agent in ALL_AGENTS]


def aggregate_signals(signals: list[AgentSignal]) -> dict:
    """Weighted vote aggregation → final consensus signal."""
    vote_map: dict[str, float] = {"COMPRAR CALL": 0, "COMPRAR PUT": 0, "NEUTRO": 0, "STRADDLE": 0}
    total_weight = 0
    for s in signals:
        vote_map[s.signal] += s.weight * (s.confidence / 100)
        total_weight += s.weight

    winner = max(vote_map, key=vote_map.__getitem__)
    winner_pct = vote_map[winner] / total_weight * 100 if total_weight else 50

    call_votes = sum(1 for s in signals if s.signal == "COMPRAR CALL")
    put_votes = sum(1 for s in signals if s.signal == "COMPRAR PUT")
    neutral_votes = sum(1 for s in signals if s.signal in ("NEUTRO", "STRADDLE"))

    return {
        "consensus": winner,
        "consensus_pct": round(winner_pct, 1),
        "votes": {k: round(v, 2) for k, v in vote_map.items()},
        "call_count": call_votes,
        "put_count": put_votes,
        "neutral_count": neutral_votes,
        "signals": [dataclasses.asdict(s) for s in signals],
    }
