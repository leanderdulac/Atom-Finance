import React, { useState, useEffect } from "react";
import { api } from "../services/api";

// Funções de simulação visual UI
function simulateIntradayCurve(length = 78) { // 78 barras de 5m (6,5 horas)
  const curve = [100];
  let price = 100;
  for (let i = 1; i < length; i++) {
    price += (Math.random() - 0.48) * 0.2; // slight upward drift
    curve.push(price);
  }
  return curve;
}

// ══ MINI CHART (SVG) ══════════════════════════════════════════
function MiniChart({ data, color = "#00ff88", height = 80, showFill = true }: any) {
  if (!data || data.length < 2) return null;
  const min = Math.min(...data), max = Math.max(...data);
  const range = max - min || 1;
  const w = 300, h = height;
  const pts = data.map((v: number, i: number) => `${(i / (data.length - 1)) * w},${h - ((v - min) / range) * (h - 4) - 2}`);
  const polyline = pts.join(" ");
  const fill = `${pts[0]} ${pts.join(" ")} ${w},${h} 0,${h}`;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} style={{ width: "100%", height, display: "block" }} preserveAspectRatio="none">
      {showFill && <polygon points={fill} fill={color + "18"} />}
      <polyline points={polyline} fill="none" stroke={color} strokeWidth="1.5" />
    </svg>
  );
}

function Pill({ label, value, color = "#00ff88", sub }: any) {
  return (
    <div style={{ background: "#0a1628", border: `1px solid ${color}28`, borderRadius: 8, padding: "12px 16px" }}>
      <div style={{ color: "#3a5a7c", fontSize: 10, letterSpacing: 2, marginBottom: 5 }}>{label}</div>
      <div style={{ color, fontSize: 20, fontWeight: 700, fontFamily: "monospace" }}>{value}</div>
      {sub && <div style={{ color: "#3a5a7c", fontSize: 11, marginTop: 3 }}>{sub}</div>}
    </div>
  );
}

const DEFAULT_PYTHON = `import yfinance as yf
import pandas as pd
import numpy as np
import datetime as dt

# ==========================================
# SPY INTRADAY MOMENTUM STRATEGY
# Architecture: Concretum Group Research
# ==========================================

class SPYIntradayMomentum:
    def __init__(self, ticker="SPY", window_mins=30, trailing_stop_pct=0.005):
        self.ticker = ticker
        self.window_mins = window_mins
        self.trailing_stop_pct = trailing_stop_pct
        
    def fetch_intraday_data(self, days=60):
        """Fetch high-frequency 5m bars for SPY"""
        print(f"Buscando histórico intradiário 5m para {self.ticker}...")
        df = yf.download(self.ticker, period=f"{days}d", interval="5m")
        df['Date'] = df.index.date
        df['Time'] = df.index.time
        return df

    def generate_signals(self, df):
        """
        Gera o sinal de Momentum Intradiário:
        Avalia o preço de fechamento após 'window_mins' a partir da abertura.
        Se retorno > 0, sinal = +1 (Long). Se < 0, sinal = -1 (Short).
        Extrai vantagem estrutural no spread Oferta/Demanda matinal.
        """
        df['Signal'] = 0
        df['Day_Open'] = df.groupby('Date')['Open'].transform('first')
        
        eval_time = (dt.datetime.combine(dt.date.today(), dt.time(9, 30)) + dt.timedelta(minutes=self.window_mins)).time()
        
        for date, group in df.groupby('Date'):
            try:
                eval_idx = group[group['Time'] >= eval_time].index[0]
                eval_price = group.loc[eval_idx, 'Close']
                day_open = group['Day_Open'].iloc[0]
                
                # Signal Generation
                momentum = (eval_price / day_open) - 1
                signal = 1 if momentum > 0 else -1
                
                # Assign signal forward for the rest of the day
                df.loc[eval_idx:, 'Signal'] = signal
                
            except IndexError:
                continue
                
        return df

    def apply_dynamic_trailing_stop(self, df):
        """
        Risk Management via Dynamic Trailing Stop.
        Se o preço reverter mais de 'trailing_stop_pct' do pico máximo da posição, saia.
        Garante saídas automáticas em choques intradiários. Fecha tudo às 15:55.
        """
        df['Position'] = 0
        df['Strategy_Returns'] = 0.0
        
        for date, group in df.groupby('Date'):
            in_position = False
            entry_price = 0
            max_price = 0
            min_price = float('inf')
            current_signal = 0
            
            for idx, row in group.iterrows():
                # Entry
                if row['Signal'] != 0 and not in_position:
                    in_position = True
                    current_signal = row['Signal']
                    entry_price = row['Close']
                    max_price = entry_price
                    min_price = entry_price
                
                if in_position:
                    # Trailing Stop Tracker
                    if current_signal == 1:
                        max_price = max(max_price, row['High'])
                        if row['Low'] < max_price * (1 - self.trailing_stop_pct):
                            in_position = False # Stop hit
                            df.loc[idx, 'Position'] = 0
                            continue
                    elif current_signal == -1:
                        min_price = min(min_price, row['Low'])
                        if row['High'] > min_price * (1 + self.trailing_stop_pct):
                            in_position = False # Stop hit
                            df.loc[idx, 'Position'] = 0
                            continue
                    
                    # Exit at close (No overnight risk)
                    if row['Time'] >= dt.time(15, 55):
                        in_position = False
                        df.loc[idx, 'Position'] = 0
                        continue
                        
                    df.loc[idx, 'Position'] = current_signal
                    
        # Calculate Returns
        df['Strategy_Returns'] = df['Position'].shift(1) * df['Close'].pct_change()
        return df

if __name__ == "__main__":
    strategy = SPYIntradayMomentum()
    data = strategy.fetch_intraday_data()
    data_with_signals = strategy.generate_signals(data)
    results = strategy.apply_dynamic_trailing_stop(data_with_signals)
    
    total_return = (1 + results['Strategy_Returns'].fillna(0)).prod() - 1
    print(f"Retorno do Backtest (60 dias - yfinance intraday limit): {total_return:.2%}")
    print("NOTA: Para atingir os 1985% em 17 anos relatados na pesquisa do Concretum Group,")
    print("é necessário alimentar a classe com um histórico proprietário completo de (1m/5m).")
`;

export default function SPYIntradayPage() {
  const [code, setCode] = useState(DEFAULT_PYTHON);
  const [loading, setLoading] = useState(false);
  const [curve, setCurve] = useState<number[]>([]);

  useEffect(() => {
    setCurve(simulateIntradayCurve());
  }, []);
  
  const handleCopy = () => {
    navigator.clipboard.writeText(code);
    alert("Código copiado para a área de transferência!");
  };

  const callPerplexityRefine = async () => {
    setLoading(true);
    try {
      const result = await api.aiRefine(
        code,
        "Implemente melhorias profissionais focadas em slippage e transaction costs. Retorne apenas o script Python puro."
      );
      setCode(result.refined_code);
    } catch (e: any) {
      alert("Falha na automação IA: " + e.message);
    }
    setLoading(false);
  };

  return (
    <div style={{ minHeight: "100%", background: "#050a14", color: "#c8d8e8", fontFamily: "monospace", borderRadius: "8px", overflow: "hidden", paddingBottom: "40px" }}>
      {/* HEADER */}
      <div style={{ background: "#070d1a", borderBottom: "1px solid #1e3a5f", padding: "20px 28px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <div style={{ color: "#00ff88", fontWeight: 700, letterSpacing: 3, fontSize: 18 }}>SPY INTRADAY MOMENTUM</div>
          <div style={{ color: "#3a5a7c", fontSize: 12, marginTop: 4, letterSpacing: 1 }}>Beat the Market — Concretum Group Strategy</div>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))", gap: 20, padding: 20 }}>
        
        {/* SUMMARY & STATS */}
        <div>
          <div style={{ background: "#07101f", border: "1px solid #1e3a5f", borderRadius: 8, padding: 20, marginBottom: 20 }}>
            <div style={{ color: "#3a5a7c", fontSize: 11, letterSpacing: 2, marginBottom: 16 }}>// RESEARCH BACKTEST (2007 - 2024)</div>
            
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 16 }}>
              <Pill label="TOTAL RETURN" value="1,985%" color="#00ff88" sub="Net of costs" />
              <Pill label="ANN. RETURN" value="19.6%" color="#7eb8f7" sub="Annualized" />
              <Pill label="SHARPE" value="1.33" color="#c084fc" sub="Risk Adjusted" />
              <Pill label="TRL. STOP" value="0.5%" color="#ff6b6b" sub="Dynamic Exit" />
            </div>

            <div style={{ borderTop: "1px dashed #1e3a5f", paddingTop: 16, marginTop: 16 }}>
              <div style={{ color: "#5a7a9c", fontSize: 11, lineHeight: 1.6 }}>
                <span style={{color: "#c084fc", fontWeight: "bold"}}>MECÂNICA: </span> Identifica desequilíbrios anormais na oferta/demanda intradiária do S&P500 (SPY). Abre posições "Trend-Following" guiadas por Trailing Stops apertados que controlam perdas e maximizam fugas agressivas de Momentum. Risco "Overnight" = Zero.
              </div>
            </div>
          </div>
          
          <div style={{ background: "#0a1628", border: "1px solid #1e3a5f", borderRadius: 8, padding: 20, marginBottom: 20 }}>
            <div style={{ color: "#3a5a7c", fontSize: 11, letterSpacing: 2, marginBottom: 14 }}>// SIMULAÇÃO INTRADIÁRIA</div>
            <MiniChart data={curve} color="#7eb8f7" height={80} />
            <div style={{ display: "flex", justifyContent: "space-between", marginTop: 8 }}>
              <span style={{ color: "#3a5a7c", fontSize: 10 }}>09:30 AM (Momentum Window)</span>
              <span style={{ color: "#ff6b6b", fontSize: 10 }}>15:55 PM (Hard Exit)</span>
            </div>
          </div>
          
          {/* AI SECURE PROXY NOTE */}
          <div style={{ background: "#0d1b2a", border: "1px solid #3a5a7c", borderRadius: 8, padding: 16 }}>
             <div style={{ color: "#7eb8f7", fontWeight: "bold", fontSize: 11, marginBottom: 8 }}>✦ Refinamento com Perplexity AI (Servidor Seguro)</div>
             <div style={{ color: "#5a7a9c", fontSize: 10 }}>Chamadas processadas no backend — chave de API nunca exposta ao browser.</div>
          </div>

        </div>

        {/* CODE EDITOR */}
        <div style={{ background: "#0a1628", border: "1px solid #1e3a5f", borderRadius: 8, display: "flex", flexDirection: "column", height: "100%" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "12px 16px", borderBottom: "1px solid #1e3a5f", background: "#050a14" }}>
            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <span style={{ width: 12, height: 12, borderRadius: "50%", background: "#ff6b6b" }} />
              <span style={{ width: 12, height: 12, borderRadius: "50%", background: "#ffd700" }} />
              <span style={{ width: 12, height: 12, borderRadius: "50%", background: "#00ff88" }} />
              <span style={{ color: "#3a5a7c", fontSize: 12, marginLeft: 10 }}>spy_momentum.py</span>
            </div>
            
            <div style={{ display: "flex", gap: 8 }}>
              <button 
                onClick={callPerplexityRefine}
                disabled={loading}
                style={{ background: "#1e3a5f", color: "#e8f4ff", border: "none", borderRadius: 4, padding: "6px 12px", fontSize: 11, cursor: "pointer", fontFamily: "monospace", fontWeight: "bold" }}>
                {loading ? "Processando..." : "✦ Adicionar Slippage (Perplexity)"}
              </button>
              <button 
                onClick={handleCopy}
                style={{ background: "#00ff88", color: "#050a14", border: "none", borderRadius: 4, padding: "6px 12px", fontSize: 11, cursor: "pointer", fontFamily: "monospace", fontWeight: "bold" }}>
                📋 Copiar Script
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
