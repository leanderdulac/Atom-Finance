import React, { useState } from "react";

const MODULES = [
  { id: 1, name: "Coleta de dados", desc: "coletar_dados() via yfinance B3 (.SA)", color: "#7eb8f7" },
  { id: 2, name: "Quant Signals", desc: "quant_signals() — momentum multi-janela + z-score", color: "#00ff88" },
  { id: 3, name: "Curvatura geométrica", desc: "curvatura_preco() — κ = |P''| / (1 + P'²)^{3/2}", color: "#c084fc" },
  { id: 4, name: "Gauge Invariants", desc: "gauge_alpha() — alpha puro sem beta de mercado", color: "#ffd700" },
  { id: 5, name: "CAPM", desc: "calcular_capm() — β, retorno esperado, alpha", color: "#7eb8f7" },
  { id: 6, name: "GBM + Monte Carlo", desc: "simular_gbm() — 10.000 trajetórias", color: "#ff6b6b" },
  { id: 7, name: "Black-Scholes", desc: "black_scholes() — preço + delta, gamma, theta, vega", color: "#00ff88" },
  { id: 8, name: "Sharpe Ratio", desc: "sharpe_ratio() — anualizado com Selic como Rf", color: "#ffd700" },
  { id: 9, name: "Markowitz", desc: "otimizar_markowitz() — pesos que maximizam Sharpe", color: "#c084fc" },
  { id: 10, name: "VaR + CVaR", desc: "calcular_var() — 3 métodos com capital em R$", color: "#ff6b6b" },
  { id: 11, name: "Kelly Criterion", desc: "kelly_sizing() — Half-Kelly por ativo", color: "#00ff88" },
];

const DEFAULT_PYTHON = `import yfinance as yf
import numpy as np
import pandas as pd
from scipy.stats import norm
import scipy.optimize as sco
import datetime as dt

# ==========================================
# 1. Coleta de dados via yfinance B3
# ==========================================
def coletar_dados(tickers, start="2020-01-01", end=dt.datetime.today().strftime('%Y-%m-%d')):
    symbols = [t + ".SA" for t in tickers]
    data = yf.download(symbols, start=start, end=end)['Close']
    return data

# ==========================================
# 2. Quant Signals (Momentum + Z-Score)
# ==========================================
def quant_signals(prices, window=20):
    returns = prices.pct_change()
    momentum = prices / prices.shift(window) - 1
    z_score = (prices - prices.rolling(window).mean()) / prices.rolling(window).std()
    return momentum, z_score

# ==========================================
# 3. Curvatura Geométrica κ = |P''| / (1 + P'^2)^(3/2)
# ==========================================
def curvatura_preco(prices):
    p1 = np.gradient(prices)
    p2 = np.gradient(p1)
    kappa = np.abs(p2) / (1 + p1**2)**1.5
    return kappa

# ==========================================
# 4. Gauge Invariants (Alpha Puro)
# ==========================================
def gauge_alpha(returns, mkt_returns):
    cov = returns.cov(mkt_returns)
    var = mkt_returns.var()
    beta = cov / var
    alpha_puro = returns.mean() - beta * mkt_returns.mean()
    return alpha_puro

# ==========================================
# 5. CAPM
# ==========================================
def calcular_capm(returns, mkt_returns, rf=0.105):
    cov_matrix = np.cov(returns, mkt_returns)
    beta = cov_matrix[0, 1] / cov_matrix[1, 1]
    expected_ret = rf + beta * (mkt_returns.mean() * 252 - rf)
    return beta, expected_ret

# ==========================================
# 6. GBM + Monte Carlo (10.000 trajetórias)
# ==========================================
def simular_gbm(S0, mu, sigma, T=252, n_sims=10000):
    dt = 1/252
    paths = np.zeros((T, n_sims))
    paths[0] = S0
    for t in range(1, T):
        Z = np.random.standard_normal(n_sims)
        paths[t] = paths[t-1] * np.exp((mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * Z)
    return paths

# ==========================================
# 7. Black-Scholes + Gregas
# ==========================================
def black_scholes(S, K, T, r, sigma, tipo="call"):
    d1 = (np.log(S/K) + (r + 0.5 * sigma**2)*T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    if tipo == "call":
        C = S * norm.cdf(d1) - K * np.exp(-r*T) * norm.cdf(d2)
        delta = norm.cdf(d1)
    else:
        C = K * np.exp(-r*T) * norm.cdf(-d2) - S * norm.cdf(-d1)
        delta = norm.cdf(d1) - 1
        
    gamma = norm.pdf(d1) / (S * sigma * np.sqrt(T))
    vega = S * norm.pdf(d1) * np.sqrt(T) / 100
    theta = -(S * norm.pdf(d1) * sigma) / (2 * np.sqrt(T)) - r * K * np.exp(-r*T) * norm.cdf(d2)
    return {"preco": C, "delta": delta, "gamma": gamma, "vega": vega, "theta": theta/365}

# ==========================================
# 8. Sharpe Ratio (Anualizado, Selic=10.5%)
# ==========================================
def sharpe_ratio(returns, rf=0.105/252):
    mu = returns.mean()
    sigma = returns.std()
    return (mu - rf) / sigma * np.sqrt(252)

# ==========================================
# 9. Markowitz (Max Sharpe)
# ==========================================
def otimizar_markowitz(returns, rf=0.105):
    mean_rets = returns.mean() * 252
    cov_matrix = returns.cov() * 252
    num_assets = len(returns.columns)
    
    def neg_sharpe(weights):
        p_ret = np.sum(mean_rets * weights)
        p_vol = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))
        return -(p_ret - rf) / p_vol
        
    constraints = ({'type': 'eq', 'fun': lambda x: np.sum(x) - 1})
    bounds = tuple((0, 1) for _ in range(num_assets))
    init_guess = num_assets * [1. / num_assets,]
    
    opt = sco.minimize(neg_sharpe, init_guess, method='SLSQP', bounds=bounds, constraints=constraints)
    return opt.x

# ==========================================
# 10. VaR + CVaR (3 métodos)
# ==========================================
def calcular_var(returns, capital=100000, alpha=0.01):
    # Paramétrico
    mu = returns.mean()
    sigma = returns.std()
    var_param = (mu - norm.ppf(1-alpha) * sigma) * capital
    
    # Histórico
    var_hist = np.percentile(returns.dropna(), alpha * 100) * capital
    
    # CVaR
    cvar = returns[returns <= np.percentile(returns.dropna(), alpha * 100)].mean() * capital
    return abs(var_param), abs(var_hist), abs(cvar)

# ==========================================
# 11. Kelly Criterion (Half-Kelly)
# ==========================================
def kelly_sizing(mu, sigma, rf=0.105/252):
    edge = mu - rf
    full_kelly = edge / (sigma**2)
    half_kelly = full_kelly / 2
    return max(0, min(1, half_kelly))

if __name__ == "__main__":
    print("Módulos B3 Quant carregados com sucesso. Pronto para execução offline.")
`;

export default function PaperCrawlerPage() {
  const [code, setCode] = useState(DEFAULT_PYTHON);
  const [apiKey, setApiKey] = useState(() => localStorage.getItem("perplexity_key") || "");
  const [loading, setLoading] = useState(false);
  
  const handleCopy = () => {
    navigator.clipboard.writeText(code);
    alert("Código copiado para a área de transferência!");
  };

  const callPerplexityRefine = async () => {
    if (!apiKey) return alert("Insira sua API Key Perplexity para utilizar a IA.");
    setLoading(true);
    try {
      const response = await fetch("/perplexity-api/chat/completions", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${apiKey}`,
        },
        body: JSON.stringify({
          model: "sonar-pro",
          messages: [
            { role: "system", "content": "Você é um arquiteto Python Senior focando em finanças quantitativas para B3. Altere o código enviado e forneça apenas o código em python puro, sem marcações." },
            { role: "user", "content": "Implemente melhorias profissionais e vetorizadas em cima deste código B3 Quant:\\n" + code }
          ],
        }),
      });

      if (!response.ok) throw new Error("Erro na requisição. Verifique sua chave.");
      const d = await response.json();
      const text = d.choices?.[0]?.message?.content || "";
      const cleaned = text.replace(/```python|```/g, "").trim();
      setCode(cleaned);
    } catch (e: any) {
      alert("Falha na formatação via IA: " + e.message);
    }
    setLoading(false);
  };

  return (
    <div style={{ minHeight: "100%", background: "#050a14", color: "#c8d8e8", fontFamily: "monospace", borderRadius: "8px", overflow: "hidden", paddingBottom: "40px" }}>
      {/* HEADER */}
      <div style={{ background: "#070d1a", borderBottom: "1px solid #1e3a5f", padding: "20px 28px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <div style={{ color: "#00ff88", fontWeight: 700, letterSpacing: 3, fontSize: 18 }}>B3 QUANT ARCHITECT</div>
          <div style={{ color: "#3a5a7c", fontSize: 12, marginTop: 4, letterSpacing: 1 }}>Gerador de Algoritmos Institucionais — 11 Módulos Core</div>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))", gap: 20, padding: 20 }}>
        
        {/* PARAMS PORTAL */}
        <div>
          <div style={{ background: "#0d1b2a", border: "1px solid #c084fc", borderRadius: 8, padding: 16, marginBottom: 20 }}>
            <div style={{ color: "#c084fc", fontWeight: "bold", fontSize: 13, marginBottom: 8 }}>🔑 PERPLEXITY_API_KEY</div>
            <input 
              type="password" 
              value={apiKey} 
              onChange={e => { setApiKey(e.target.value); localStorage.setItem("perplexity_key", e.target.value); }}
              placeholder="Apenas para refinamento avançado IA..." 
              style={{ width: "100%", background: "#050a14", border: "1px solid #1e3a5f", color: "#c8d8e8", padding: "10px 14px", borderRadius: 4, fontFamily: "monospace" }} 
            />
          </div>

          <div style={{ background: "#07101f", border: "1px solid #1e3a5f", borderRadius: 8, padding: 20 }}>
            <div style={{ color: "#3a5a7c", fontSize: 11, letterSpacing: 2, marginBottom: 16 }}>// ARQUITETURA GERADA (11 MÓDULOS)</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {MODULES.map((m) => (
                <div key={m.id} style={{ display: "grid", gridTemplateColumns: "20px 1fr", gap: 8 }}>
                  <div style={{ color: m.color, fontWeight: 700, fontSize: 12 }}>{m.id}.</div>
                  <div>
                    <div style={{ color: m.color, fontSize: 12, fontWeight: 700 }}>{m.name}</div>
                    <div style={{ color: "#5a7a9c", fontSize: 10, marginTop: 2, lineHeight: 1.4 }}>{m.desc}</div>
                  </div>
                </div>
              ))}
            </div>
            
            <div style={{ marginTop: 24, padding: 12, borderTop: "1px solid #1e3a5f" }}>
                <div style={{ color: "#00ff88", fontSize: 11, textAlign: "center", lineHeight: 1.5 }}>
                  ✓ Tudo pronto para exportar. <br/>
                  ✓ Estrutura já formatada e compilável em .py.
                </div>
            </div>
          </div>
        </div>

        {/* CODE WINDOW */}
        <div style={{ background: "#0a1628", border: "1px solid #1e3a5f", borderRadius: 8, display: "flex", flexDirection: "column" }}>
          
          <div style={{ display: "flex", justifyContent: "space-between", padding: "12px 16px", borderBottom: "1px solid #1e3a5f", background: "#050a14" }}>
            <div style={{ display: "flex", gap: 6 }}>
              <span style={{ width: 12, height: 12, borderRadius: "50%", background: "#ff6b6b" }} />
              <span style={{ width: 12, height: 12, borderRadius: "50%", background: "#ffd700" }} />
              <span style={{ width: 12, height: 12, borderRadius: "50%", background: "#00ff88" }} />
              <span style={{ color: "#3a5a7c", fontSize: 12, marginLeft: 10 }}>quant_engine_b3.py</span>
            </div>
            
            <div style={{ display: "flex", gap: 8 }}>
              <button 
                onClick={callPerplexityRefine}
                disabled={loading}
                style={{ background: "#1e3a5f", color: "#e8f4ff", border: "none", borderRadius: 4, padding: "6px 12px", fontSize: 11, cursor: "pointer", fontFamily: "monospace", fontWeight: "bold" }}>
                {loading ? "Processando..." : "✦ Refinar (Perplexity)"}
              </button>
              <button 
                onClick={handleCopy}
                style={{ background: "#00ff88", color: "#050a14", border: "none", borderRadius: 4, padding: "6px 12px", fontSize: 11, cursor: "pointer", fontFamily: "monospace", fontWeight: "bold" }}>
                📋 Copiar
              </button>
            </div>
          </div>

          <div style={{ padding: 16, flex: 1, overflowY: "auto", maxHeight: "75vh" }}>
            <pre style={{ margin: 0, fontSize: 12, lineHeight: 1.5, color: "#c8d8e8", whiteSpace: "pre-wrap" }}>
              {code}
            </pre>
          </div>
        </div>
      </div>
    </div>
  );
}
