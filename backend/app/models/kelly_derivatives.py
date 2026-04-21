import numpy as np

def kelly_derivatives(win_prob: float, payout_ratio: float, bankroll: float, fraction: float = 1.0) -> dict:
    """
    Calcula o tamanho da aposta usando Critério de Kelly adaptado para Derivativos (Calls/Puts).
    
    Conceitos aplicados:
    - Nassim Taleb: Aumentar o tamanho da posição expande AS DUAS caudas da distribuição
      (ganho maior E risco de ruína maior). Não dá pra "compensar" risco de cauda só com upside.
      A única forma de reduzir ruína é cortar a cauda diretamente → usar fração menor do Kelly.
    
    - Full Kelly (fraction=1.0): Tamanho ótimo para crescimento logarítmico de riqueza.
      Máximo crescimento esperado, mas alto risco de drawdown/ruína em streaks ruins.
    
    - Quarter Kelly (fraction=0.25): Reduz o tamanho em 75%. Mesma edge, cauda de ruína
      muito menor, crescimento mais estável e "straight line up".
    
    Parâmetros:
        win_prob: Probabilidade de a operação de Call/Put dar lucro real (ex: 0.40)
        payout_ratio: Relação entre Lucro Líquido Esperado e Valor em Risco (Prêmio). (ex: lucro de 150% do prêmio -> 1.5)
        bankroll: Capital total disponível para alocação na carteira (ex: 10000)
        fraction: 1.0 = Full Kelly | 0.25 = Quarter Kelly | 0.5 = Half Kelly etc.
    
    Retorna: dicionário com bet_size e explicação.
    """
    if win_prob <= 0 or win_prob >= 1:
        return {"erro": "Probabilidade (win_prob) deve ser entre 0 e 1."}
    
    q = 1.0 - win_prob
    kelly_full = win_prob - (q / payout_ratio)
    
    if kelly_full <= 0:
        return {"erro": "Sem edge (esperança matemática <= 0). O critério recusa essa operação de derivativo."}
    
    # Kelly fracionado (Taleb-friendly)
    kelly_frac = kelly_full * fraction
    
    # Tamanho da aposta (quanto do bankroll deve ir pro prêmio da opção)
    bet_size = bankroll * kelly_frac
    
    edge_ev = (win_prob * payout_ratio) - q
    
    return {
        "kelly_full": round(kelly_full, 4),
        "kelly_frac": round(kelly_frac, 4),
        "alocacao_dolares": round(bet_size, 2),
        "tipo": "Full Kelly" if fraction == 1.0 else f"Quarter/Fractional Kelly (x{fraction})",
        "explicacao": f"Invista ${bet_size:.2f} (={kelly_frac:.1%} do bankroll) na compra das opções. "
                     f"EV por dólar em risco = {edge_ev:.2f} | Risco de cauda cortado em {int((1-fraction)*100)}%."
    }


def simular_caminhos_kelly_derivativos(win_prob: float, payout_ratio: float, bankroll_inicial: float = 10000,
                                       num_apostas: int = 100, num_simulacoes: int = 10000,
                                       fraction: float = 1.0, seed: int = 42,
                                       include_results: bool = False) -> dict:
    """
    Simulação Monte Carlo dos retornos de opções para evidenciar o efeito Taleb.
    """
    np.random.seed(seed)
    resultados = np.zeros(num_simulacoes)
    
    q = 1.0 - win_prob
    kelly_full = win_prob - (q / payout_ratio)
    
    if kelly_full <= 0:
        return {"erro": "Sem edge para simular."}
        
    kelly_frac = kelly_full * fraction
    
    for i in range(num_simulacoes):
        bankroll = bankroll_inicial
        for _ in range(num_apostas):
            ganhou = np.random.rand() < win_prob
            if ganhou:
                # Ganha e recebe o prêmio original de volta (1) + lucro líquido pelo payout ratio
                bankroll *= (1 + kelly_frac * payout_ratio)
            else:
                # Perde o valor investido no prêmio
                bankroll *= (1 - kelly_frac)
            
            # Ruína (bankroll <= 1% do inicial)
            if bankroll <= bankroll_inicial * 0.01:
                bankroll = 0
                break
        resultados[i] = bankroll
    
    media_final = np.mean(resultados)
    mediana_final = np.median(resultados)
    ruin_prob = np.mean(resultados <= bankroll_inicial * 0.01) * 100
    crescimento_medio = (media_final / bankroll_inicial - 1) * 100
    
    return {
        "tipo": "Full Kelly" if fraction == 1.0 else f"Fractional Kelly (x{fraction})",
        "bankroll_final_media": round(float(media_final), 2),
        "bankroll_final_mediana": round(float(mediana_final), 2),
        "probabilidade_ruina_%": round(float(ruin_prob), 2),
        "crescimento_medio_%": round(float(crescimento_medio), 2),
        "resultado_simulacoes": resultados.tolist() if include_results else []
    }
