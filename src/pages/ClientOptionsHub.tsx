import React, { useState, useEffect } from "react";
import { TrendingUp, TrendingDown, ShowChart, Diamond, Shield, VisibilityOff } from '@mui/icons-material';

// --- B3 ASSETS (GHOST DIMENSION INTEGRATED) ---
const B3_ASSETS = [
  // Linha de Frente (Blue Chips)
  { ticker: "PETR4", price: 38.50, iv: 0.35, type: "Blue Chip", name: "Petrobras PN" },
  { ticker: "VALE3", price: 62.20, iv: 0.32, type: "Blue Chip", name: "Vale ON" },
  { ticker: "ITUB4", price: 34.10, iv: 0.28, type: "Blue Chip", name: "Itaú Unibanco PN" },
  { ticker: "BBDC4", price: 13.50, iv: 0.29, type: "Blue Chip", name: "Bradesco PN" },
  { ticker: "WEGE3", price: 46.80, iv: 0.30, type: "Blue Chip", name: "WEG ON" },
  { ticker: "B3SA3", price: 11.20, iv: 0.33, type: "Blue Chip", name: "B3 ON" },
  { ticker: "PRIO3", price: 44.90, iv: 0.45, type: "Mid Cap", name: "PetroRio ON" },
  // Dimensão Oculta (Small/Micro Caps - High IV)
  { ticker: "MGLU3", price: 1.40, iv: 0.85, type: "Small Cap", name: "Magazine Luiza ON" },
  { ticker: "COGN3", price: 2.80, iv: 0.70, type: "Small Cap", name: "Cogna ON" },
  { ticker: "IRBR3", price: 42.10, iv: 0.65, type: "Small Cap", name: "IRB Brasil" },
  { ticker: "OIBR3", price: 1.50, iv: 1.20, type: "Micro Cap", name: "Oi ON" },
  { ticker: "AMER3", price: 0.55, iv: 1.50, type: "Micro Cap", name: "Americanas" },
];

// --- STOCHASTIC ENGINE (MATH CORE) ---
function ndist(x: number): number {
    const sign = x < 0 ? -1 : 1;
    const xAbs = Math.abs(x) / Math.sqrt(2.0);
    const t = 1.0 / (1.0 + 0.3275911 * xAbs);
    const erf = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-xAbs * xAbs);
    return 0.5 * (1.0 + sign * erf);
}

function blackScholes(S: number, K: number, T: number, r: number, sigma: number, type: "call" | "put"): number {
    if (T <= 0.001) return type === "call" ? Math.max(0, S - K) : Math.max(0, K - S);
    const d1 = (Math.log(S / K) + (r + sigma * sigma / 2) * T) / (sigma * Math.sqrt(T));
    const d2 = d1 - sigma * Math.sqrt(T);
    if (type === "call") {
        return S * ndist(d1) - K * Math.exp(-r * T) * ndist(d2);
    } else {
        return K * Math.exp(-r * T) * ndist(-d2) - S * ndist(-d1);
    }
}

// Fokker-Planck (Kolmogorov Forward) -> Probability N(d2)
function kolmogorovProbability(S: number, K: number, T: number, r: number, sigma: number, type: "call" | "put"): number {
    if (T <= 0.001) return (type === "call" ? S > K : S < K) ? 1.0 : 0.0;
    // Lema de Ito para ajuste geométrico do drift: (r - sigma^2/2)
    const d2 = (Math.log(S / K) + (r - sigma * sigma / 2) * T) / (sigma * Math.sqrt(T));
    return type === "call" ? ndist(d2) : ndist(-d2);
}
// ----------------------------------------------

export default function ClientOptionsHub() {
  const [assetIdx, setAssetIdx] = useState<number>(0);
  const selectedAsset = B3_ASSETS[assetIdx];

  const [capital, setCapital] = useState<number>(10000);
  const [optType, setOptType] = useState<"call" | "put">("call");
  const [spotPrice, setSpotPrice] = useState<number>(B3_ASSETS[0].price);
  const [targetMovePct, setTargetMovePct] = useState<number>(15);

  // Auto-sync Spot price when changing Asset
  useEffect(() => {
    setSpotPrice(selectedAsset.price);
  }, [selectedAsset]);
  
  // Market Constants
  const r = 0.105; // Selic 10.5%
  const iv = selectedAsset.iv; // Ghost Dimension Volatility Factor
  const daysToExp = 30; // 1 month to expiry

  // Temporal Setup
  const T_initial = daysToExp / 365;
  const targetSpot = spotPrice * (1 + targetMovePct / 100);
  const T_sim = Math.max(0.001, (daysToExp - 10) / 365); // Expectation: move hits 10 days before expiry
  
  // Strike Matrix (ATM, 5% OTM, 10% OTM)
  const levels = [
    { id: "atm", title: "Conservador (ATM)", badge: "Equilíbrio", desc: "Strike no preço atual. Compra de delta simétrico sem sustos.", otmPct: 0, color: "#7eb8f7", icon: <Shield style={{ color: "#7eb8f7" }} /> },
    { id: "otm5", title: "Moderado (OTM 5%)", badge: "Alavancado", desc: "Strike 5% fora do dinheiro. Exige ignição antes do Theta matar o prêmio.", otmPct: 5, color: "#c084fc", icon: <TrendingUp style={{ color: "#c084fc" }} /> },
    { id: "otm10", title: "Agressivo (OTM 10%)", badge: "Pó Extremo", desc: "Fora da curva normal. Assimetria massiva contra a quebra do prêmio de risco.", otmPct: 10, color: "#ff6b6b", icon: <Diamond style={{ color: "#ff6b6b" }} /> },
  ];

  const scenarios = levels.map(lvl => {
    const K = optType === "call" ? spotPrice * (1 + lvl.otmPct/100) : spotPrice * (1 - lvl.otmPct/100);
    // Minimum option price in B3 is 0.01 (1 cent)
    const initialOptPrice = Math.max(0.01, blackScholes(spotPrice, K, T_initial, r, iv, optType)); 
    const targetOptPrice = Math.max(0.00, blackScholes(targetSpot, K, T_sim, r, iv, optType));
    
    // Fokker-Planck Base Probability of Expiry ITM
    const pop = kolmogorovProbability(spotPrice, K, T_initial, r, iv, optType) * 100;

    const optionsBought = Math.floor(capital / initialOptPrice); // Comprar lotes inteiros
    const finalCapital = optionsBought * targetOptPrice;
    
    let profit = finalCapital - capital;
    const profitPct = (profit / capital) * 100;

    return { ...lvl, K, initialOptPrice, targetOptPrice, optionsBought, finalCapital, profit, profitPct, pop };
  });

  return (
    <div style={{ minHeight: "100%", background: "#050a14", color: "#c8d8e8", fontFamily: "'Inter', sans-serif", borderRadius: "12px", padding: "30px", paddingBottom: "60px" }}>
      
      {/* HEADER OVERVIEW */}
      <div style={{ textAlign: "center", marginBottom: 30 }}>
        <h1 style={{ margin: 0, fontSize: 32, fontWeight: 800, color: "#fff", letterSpacing: -1 }}>Painel Cliente: <span style={{ color: "#00ff88" }}>Opções de Ganho</span></h1>
        <p style={{ color: "#5a7a9c", fontSize: 15, marginTop: 8 }}>Mecânica de Kolmogorov e Lema de Itô acoplados no motor para identificar operações OTM estruturalmente vantajosas.</p>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 24, '@media (min-width: 1024px)': { flexDirection: "row" } as any }}>
        
        {/* PARAMS ROW */}
        <div style={{ background: "#0a1628", borderRadius: 16, padding: "24px 30px", border: "1px solid #1e3a5f", display: "flex", flexWrap: "wrap", gap: 30 }}>
          
          <div style={{ flex: 1, minWidth: 200 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
              <label style={{ fontSize: 13, color: "#7eb8f7", fontWeight: 700, textTransform: "uppercase", letterSpacing: 1 }}>🏛️ Ativo B3</label>
              {selectedAsset.iv >= 0.70 && (
                <div style={{ display: "flex", alignItems: "center", gap: 4, color: "#ff6b6b", fontSize: 10, fontWeight: "bold", background: "#ff6b6b22", padding: "2px 6px", borderRadius: 4 }}>
                  <VisibilityOff style={{ fontSize: 12 }} /> GHOST IV {Math.round(selectedAsset.iv * 100)}%
                </div>
              )}
            </div>
            <select 
              value={assetIdx} 
              onChange={e => setAssetIdx(Number(e.target.value))} 
              style={{ width: "100%", background: "#050a14", border: "1px solid #3a5a7c", color: "#fff", padding: "14px 16px", borderRadius: 8, fontSize: 16, fontWeight: "bold", appearance: "none", cursor: "pointer" }}
            >
              {B3_ASSETS.map((asset, idx) => (
                <option key={asset.ticker} value={idx}>{asset.ticker} | {asset.type} (IV {Math.round(asset.iv*100)}%)</option>
              ))}
            </select>
          </div>

          <div style={{ flex: 1, minWidth: 200 }}>
            <label style={{ display: "block", fontSize: 13, color: "#00ff88", marginBottom: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: 1 }}>📈 Direção Foco</label>
            <div style={{ display: "flex", borderRadius: 8, overflow: "hidden", border: "1px solid #3a5a7c" }}>
              <button 
                onClick={() => setOptType("call")}
                style={{ flex: 1, padding: "14px", border: "none", background: optType === "call" ? "#00ff8822" : "#050a14", color: optType === "call" ? "#00ff88" : "#5a7a9c", fontWeight: 700, cursor: "pointer", transition: "0.2s" }}
              >CALL (Alta)</button>
              <button 
                onClick={() => setOptType("put")}
                style={{ flex: 1, padding: "14px", border: "none", background: optType === "put" ? "#ff6b6b22" : "#050a14", color: optType === "put" ? "#ff6b6b" : "#5a7a9c", fontWeight: 700, cursor: "pointer", transition: "0.2s", borderLeft: "1px solid #3a5a7c" }}
              >PUT (Queda)</button>
            </div>
          </div>

          <div style={{ flex: 1, minWidth: 200 }}>
            <label style={{ display: "block", fontSize: 13, color: "#c084fc", marginBottom: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: 1 }}>💰 Caixa Global (R$)</label>
            <input 
              type="number" 
              value={capital}
              onChange={e => setCapital(Number(e.target.value))}
              style={{ width: "100%", background: "#050a14", border: "1px solid #3a5a7c", color: "#fff", padding: "14px 16px", borderRadius: 8, fontSize: 16, fontWeight: "bold" }}
            />
          </div>

        </div>

      </div>

      {/* HORIZONTAL TARGET SLIDER */}
      <div style={{ background: "#07101f", borderRadius: 16, padding: "30px 40px", border: "1px dashed #3a5a7c", marginTop: 24, textAlign: "center", position: "relative" }}>
        {selectedAsset.iv >= 0.70 && (
           <div style={{ position: "absolute", top: 12, right: 20, fontSize: 10, fontWeight: "bold", color: "#ffb86c", border: "1px solid #ffb86c", background: "#ffb86c22", padding: "4px 8px", borderRadius: 16 }}>
             ALERTA: SMALLCAP COM ALTA VOLATILIDADE
           </div>
        )}
        <h3 style={{ margin: "0 0 16px 0", color: "#fff", fontSize: 20 }}>
          Alvo Final da Análise: Movimento <span style={{ color: targetMovePct >= 0 ? "#00ff88" : "#ff6b6b" }}>{targetMovePct > 0 ? "+" : ""}{targetMovePct}%</span>
        </h3>
        <p style={{ color: "#5a7a9c", margin: "0 0 24px 0", fontSize: 14 }}>{selectedAsset.ticker} transita de <strong>R$ {spotPrice.toFixed(2)}</strong> para <strong>R$ {targetSpot.toFixed(2)}</strong> (em D+{daysToExp - 10}).</p>
        
        <input 
          type="range" 
          min="-50" 
          max="50" 
          step="1"
          value={targetMovePct} 
          onChange={e => setTargetMovePct(Number(e.target.value))}
          style={{ width: "100%", maxWidth: 600, accentColor: targetMovePct >= 0 ? "#00ff88" : "#ff6b6b" }}
        />
      </div>

      {/* MATRIX RESULTS */}
      <h2 style={{ fontSize: 14, color: "#3a5a7c", textTransform: "uppercase", letterSpacing: 2, margin: "40px 0 20px 0" }}>// Painel de Retorno Exponencial por Strike</h2>
      
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 24 }}>
        {scenarios.map((s) => {
          const isProfit = s.profitPct > 0;
          const displayColor = isProfit ? "#00ff88" : (s.profitPct <= -90 ? "#ff6b6b" : "#ffb86c");
          const gradientStart = isProfit ? s.color + "22" : "#ff6b6b11";
          
          return (
            <div key={s.id} style={{ background: `linear-gradient(180deg, ${gradientStart} 0%, #0a1628 100%)`, borderRadius: 16, padding: 30, border: `1px solid ${s.color}44`, position: "relative", overflow: "hidden" }}>
              
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 20 }}>
                {s.icon}
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                   <div style={{ fontSize: 10, color: "#5a7a9c", fontWeight: "bold" }}>POP: <span style={{ color: s.pop > 35 ? "#00ff88" : (s.pop > 15 ? "#ffb86c" : "#ff6b6b") }}>{s.pop.toFixed(1)}%</span></div>
                   <div style={{ background: "#050a1488", color: s.color, padding: "4px 8px", borderRadius: 4, fontSize: 10, fontWeight: "bold", textTransform: "uppercase", border: `1px solid ${s.color}55` }}>
                     {s.badge}
                   </div>
                </div>
              </div>
              
              <h3 style={{ color: s.color, margin: "0 0 6px 0", fontSize: 18 }}>{s.title}</h3>
              <p style={{ color: "#5a7a9c", fontSize: 12, margin: 0, minHeight: 34 }}>{s.desc}</p>

              <div style={{ marginTop: 24, borderTop: "1px dashed #1e3a5f", paddingTop: 20 }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12, fontSize: 13 }}>
                  <span style={{ color: "#c8d8e8" }}>🎯 Strike Inicial</span>
                  <span style={{ color: "#fff", fontWeight: "bold" }}>R$ {s.K.toFixed(2)}</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12, fontSize: 13 }}>
                  <span style={{ color: "#c8d8e8" }}>💵 Custo do Prêmio</span>
                  <span style={{ color: "#fff", fontWeight: "bold" }}>R$ {s.initialOptPrice.toFixed(2)}</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 16, fontSize: 13 }}>
                  <span style={{ color: "#c8d8e8" }}>📦 Lastro Acumulado</span>
                  <span style={{ color: "#fff", fontWeight: "bold" }}>{s.optionsBought.toLocaleString()} lotes</span>
                </div>
              </div>

              <div style={{ background: "#050a14", borderRadius: 12, padding: 20, marginTop: 10, border: "1px solid #1e3a5f", position: "relative" }}>
                <div style={{ fontSize: 11, color: "#5a7a9c", textTransform: "uppercase", letterSpacing: 1, marginBottom: 8, textAlign: "center" }}>Conversão de Cenário</div>
                <div style={{ fontSize: 38, fontWeight: 900, color: displayColor, textAlign: "center", lineHeight: 1 }}>
                  {s.profitPct > 0 ? "+" : ""}{s.profitPct.toFixed(1)}%
                </div>
                <div style={{ fontSize: 16, fontWeight: 600, color: "#fff", textAlign: "center", marginTop: 10 }}>
                  R$ {s.finalCapital.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </div>
              </div>

            </div>
          );
        })}
      </div>

    </div>
  );
}
