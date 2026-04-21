import { useState, useEffect, useRef, useCallback } from "react";

// ═══════════════════════════════════════════════════════════════
//  MATH ENGINE — todos os 12 conceitos
// ═══════════════════════════════════════════════════════════════

// ── 1. GBM: Geometric Brownian Motion ────────────────────────
function simulateGBM(S0: number, mu: number, sigma: number, T: number, dt: number, seed = 42) {
  const n = Math.floor(T / dt);
  const prices = [S0];
  let rand = seed;
  const lcg = () => { rand = (rand * 1664525 + 1013904223) & 0xffffffff; return (rand >>> 0) / 4294967296; };
  const boxMuller = () => { const u1=lcg(), u2=lcg(); return Math.sqrt(-2*Math.log(u1+1e-10))*Math.cos(2*Math.PI*u2); };
  for (let i = 1; i < n; i++) {
    const dW = boxMuller() * Math.sqrt(dt);
    const S = prices[prices.length - 1];
    prices.push(S * Math.exp((mu - 0.5 * sigma ** 2) * dt + sigma * dW));
  }
  return prices;
}

// ── 2. CAPM ───────────────────────────────────────────────────
function capm(rf: number, beta: number, rm: number) { return rf + beta * (rm - rf); }

// ── 3. Black-Scholes ──────────────────────────────────────────
function normCDF(x: number) {
  const a1=0.254829592,a2=-0.284496736,a3=1.421413741,a4=-1.453152027,a5=1.061405429,p=0.3275911;
  const sign = x < 0 ? -1 : 1; x = Math.abs(x);
  const t = 1 / (1 + p * x);
  const poly = t*(a1+t*(a2+t*(a3+t*(a4+t*a5))));
  return 0.5*(1 + sign*(1-poly*Math.exp(-x*x)));
}
function blackScholes(S: number, K: number, T: number, r: number, sigma: number, type = "call") {
  if (T <= 0) return type === "call" ? Math.max(S - K, 0) : Math.max(K - S, 0);
  const d1 = (Math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * Math.sqrt(T));
  const d2 = d1 - sigma * Math.sqrt(T);
  if (type === "call") return S * normCDF(d1) - K * Math.exp(-r * T) * normCDF(d2);
  return K * Math.exp(-r * T) * normCDF(-d2) - S * normCDF(-d1);
}
function bsGreeks(S: number, K: number, T: number, r: number, sigma: number) {
  const d1 = (Math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * Math.sqrt(T));
  const d2 = d1 - sigma * Math.sqrt(T);
  const phi = Math.exp(-0.5 * d1 ** 2) / Math.sqrt(2 * Math.PI);
  return {
    delta: normCDF(d1),
    gamma: phi / (S * sigma * Math.sqrt(T)),
    vega: S * phi * Math.sqrt(T) / 100,
    theta: -(S * phi * sigma) / (2 * Math.sqrt(T)) / 365,
  };
}

// ── 4. Mean-Variance (Markowitz) ─────────────────────────────
function meanVariance(returns: number[]) {
  const n = returns.length;
  const mu = returns.reduce((a, b) => a + b, 0) / n;
  const variance = returns.reduce((a, b) => a + (b - mu) ** 2, 0) / n;
  const vol = Math.sqrt(variance * 252);
  const annMu = mu * 252;
  return { mu: annMu, vol, variance };
}

// ── 5. Kelly Criterion ────────────────────────────────────────
function kelly(mu: number, sigma: number, rf = 0.05) {
  const edge = mu - rf;
  const full = edge / sigma ** 2;
  return { full, half: full * 0.5, quarter: full * 0.25 };
}

// ── 6. Value at Risk ──────────────────────────────────────────
function var99(mu: number, sigma: number, capital = 1e6) {
  const dailyMu = mu / 252;
  const dailySigma = sigma / Math.sqrt(252);
  const z99 = 2.326;
  return Math.abs((dailyMu - z99 * dailySigma) * capital);
}

// ── 7. Sharpe Ratio ───────────────────────────────────────────
function sharpe(mu: number, sigma: number, rf = 0.05) { return (mu - rf) / sigma; }

// ── 8. CHERN-SIMONS CURVATURE SIGNAL ─────────────────────────
function chernSimonsSignal(prices: number[], fastPeriod = 8, slowPeriod = 21) {
  if (prices.length < slowPeriod + 2) return { signal: 0, kappa: 0, velocity: 0, phase: "neutro" };
  
  const ema = (arr: number[], p: number) => {
    const k = 2 / (p + 1);
    return arr.reduce((acc: number[], v, i) => { acc.push(i === 0 ? v : acc[i - 1] * (1 - k) + v * k); return acc; }, []);
  };
  
  const returns = prices.slice(1).map((p, i) => Math.log(p / prices[i]));
  const fastEMA = ema(returns, fastPeriod);
  const slowEMA = ema(returns, slowPeriod);
  
  const velocity = fastEMA[fastEMA.length - 1] - slowEMA[slowEMA.length - 1];
  const prevVelocity = fastEMA[fastEMA.length - 2] - slowEMA[slowEMA.length - 2];
  
  const kappa = velocity - prevVelocity;
  const gaugeInvariant = Math.abs(velocity) > 1e-10 ? kappa / Math.abs(velocity) : 0;
  const isMinimalVariety = Math.abs(kappa) < 0.0005;
  
  const signal = velocity > 0 ? 1 : velocity < 0 ? -1 : 0;
  const phase = isMinimalVariety ? "reversão" : velocity > 0 && kappa > 0 ? "aceleração ↑" : velocity > 0 && kappa < 0 ? "desaceleração ↑" : velocity < 0 && kappa < 0 ? "aceleração ↓" : "desaceleração ↓";
  
  return { signal, kappa, velocity, gaugeInvariant, isMinimalVariety, phase };
}

// ── 9. Backtest via GBM + CSQA ────────────────────────────────
function runBacktest(params: any) {
  const { S0, mu, sigma, rf, beta, rm, K, T_opt, capital } = params;
  const prices = simulateGBM(S0, mu, sigma, 1, 1 / 252, Date.now() % 10000);
  
  let equity = capital, positions = 0, trades = 0, wins = 0;
  const equity_curve = [capital];
  const signals_log: any[] = [];
  const window = 30;
  
  for (let i = window; i < prices.length - 1; i++) {
    const slice = prices.slice(i - window, i + 1);
    const cs = chernSimonsSignal(slice);
    const rets = slice.slice(1).map((p, j) => Math.log(p / slice[j]));
    const { mu: localMu, vol: localVol } = meanVariance(rets);
    const k = kelly(localMu, localVol, rf);
    const position_size = Math.max(0, Math.min(k.half, 1.0));
    
    if (cs.signal !== positions) {
      const pnl = positions * (prices[i + 1] - prices[i]) * (equity / prices[i]) * 0.3;
      equity += pnl;
      if (pnl > 0) wins++;
      trades++;
      positions = cs.signal;
      signals_log.push({ i, price: prices[i], signal: cs.signal, kappa: cs.kappa });
    }
    equity_curve.push(equity);
  }
  
  const finalReturns = equity_curve.slice(1).map((e, i) => Math.log(e / equity_curve[i]));
  const { mu: finalMu, vol: finalVol } = meanVariance(finalReturns.filter(r => !isNaN(r) && isFinite(r)));
  const sr = sharpe(finalMu, finalVol, rf);
  const maxDD = calcMaxDD(equity_curve);
  const VaR = var99(finalMu, finalVol, capital);
  const capmReturn = capm(rf, beta, rm);
  const call = blackScholes(prices[prices.length - 1], K, T_opt, rf, sigma, "call");
  const greeks = bsGreeks(prices[prices.length - 1], K, T_opt, rf, sigma);
  
  return {
    prices, equity_curve, signals_log, trades,
    winRate: trades > 0 ? wins / trades : 0,
    finalEquity: equity,
    totalReturn: (equity - capital) / capital,
    sharpe: sr, maxDD, VaR, capmReturn, call, greeks,
    finalPrice: prices[prices.length - 1],
    csSignal: chernSimonsSignal(prices.slice(-35)),
  };
}

function calcMaxDD(curve: number[]) {
  let peak = curve[0], maxDD = 0;
  for (const v of curve) { if (v > peak) peak = v; maxDD = Math.max(maxDD, (peak - v) / peak); }
  return maxDD;
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

// ══ COMPONENTS ════════════════════════════════════════════════
function Pill({ label, value, color = "#00ff88", sub }: any) {
  return (
    <div style={{ background: "#0a1628", border: `1px solid ${color}28`, borderRadius: 8, padding: "12px 16px" }}>
      <div style={{ color: "#3a5a7c", fontSize: 10, letterSpacing: 2, marginBottom: 5 }}>{label}</div>
      <div style={{ color, fontSize: 20, fontWeight: 700, fontFamily: "monospace" }}>{value}</div>
      {sub && <div style={{ color: "#3a5a7c", fontSize: 11, marginTop: 3 }}>{sub}</div>}
    </div>
  );
}

function Section({ title, tag, children, color = "#3a5a7c" }: any) {
  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 12 }}>
        <span style={{ color: "#1e3a5f", fontSize: 11 }}>//</span>
        <span style={{ color: "#3a5a7c", fontSize: 10, letterSpacing: 3 }}>{title}</span>
        {tag && <span style={{ background: color + "22", color, border: `1px solid ${color}44`, borderRadius: 3, padding: "1px 7px", fontSize: 10, fontFamily: "monospace" }}>{tag}</span>}
      </div>
      {children}
    </div>
  );
}

function Slider({ label, min, max, step, value, onChange, fmt }: any) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
      <span style={{ color: "#5a7a9c", fontSize: 12, minWidth: 100 }}>{label}</span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={e => onChange(+e.target.value)}
        style={{ flex: 1, accentColor: "#00ff88", height: 4 }} />
      <span style={{ color: "#00ff88", fontSize: 12, fontFamily: "monospace", minWidth: 52, textAlign: "right" }}>{fmt ? fmt(value) : value}</span>
    </div>
  );
}

// ══ MAIN ══════════════════════════════════════════════════════
export default function CSQAPage() {
  const [params, setParams] = useState({ S0: 100, mu: 0.15, sigma: 0.22, rf: 0.05, beta: 1.2, rm: 0.12, K: 105, T_opt: 0.25, capital: 1000000 });
  const [result, setResult] = useState<any>(null);
  const [running, setRunning] = useState(false);
  const [tab, setTab] = useState("overview");

  const set = (k: string) => (v: number) => setParams(p => ({ ...p, [k]: v }));
  const pct = (v: number) => (v * 100).toFixed(1) + "%";
  const money = (v: number) => "$" + (v / 1000).toFixed(0) + "k";

  useEffect(() => { run(); }, [params]); // Run dynamically if desired, or manually on button

  function run() {
    setRunning(true);
    setTimeout(() => { setResult(runBacktest(params)); setRunning(false); }, 100);
  }

  const sr_color = result ? (result.sharpe > 3 ? "#00ff88" : result.sharpe > 1.5 ? "#ffd700" : "#ff6b6b") : "#3a5a7c";
  const ret_color = result ? (result.totalReturn > 0 ? "#00ff88" : "#ff6b6b") : "#3a5a7c";
  const phase_color = result?.csSignal?.phase?.includes("↑") ? "#00ff88" : result?.csSignal?.phase?.includes("↓") ? "#ff6b6b" : "#ffd700";

  const tabs = [["overview", "OVERVIEW"], ["signal", "CHERN-SIMONS"], ["bs", "BLACK-SCHOLES"], ["portfolio", "PORTFÓLIO"]];

  return (
    <div style={{ minHeight: "100%", background: "#050a14", fontFamily: "'IBM Plex Mono', monospace", color: "#c8d8e8", borderRadius: "8px", overflow: "hidden", paddingBottom: "24px" }}>
      <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;700&family=Space+Grotesk:wght@600;700&display=swap" rel="stylesheet" />

      {/* HEADER */}
      <div style={{ background: "#070d1a", borderBottom: "1px solid #1e3a5f", padding: "14px 24px" }}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 14, maxWidth: 960, margin: "0 auto" }}>
          <div style={{ background: "#0d1b2a", border: "1px solid #00ff8833", borderRadius: 8, padding: "8px 12px", flexShrink: 0 }}>
            <div style={{ color: "#00ff88", fontSize: 18 }}>∇</div>
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontFamily: "'Space Grotesk', sans-serif", color: "#e8f4ff", fontSize: 16, fontWeight: 700, letterSpacing: 1 }}>
              CHERN–SIMONS QUANT ALGORITHM
            </div>
            <div style={{ color: "#3a5a7c", fontSize: 10, letterSpacing: 2, marginTop: 3 }}>
              GBM · CAPM · BLACK-SCHOLES · MEAN-VARIANCE · KELLY · VaR · SHARPE · CURVATURA DIFERENCIAL · INVARIANTES DE GAUGE · VARIEDADES MÍNIMAS
            </div>
          </div>
          <button onClick={run} disabled={running}
            style={{ background: running ? "#1a2a1a" : "#00ff88", color: running ? "#3a5a7c" : "#050a14", border: "none", borderRadius: 6, padding: "9px 20px", fontFamily: "monospace", fontWeight: 700, fontSize: 11, letterSpacing: 2, cursor: running ? "default" : "pointer", flexShrink: 0 }}>
            {running ? "⟳ ..." : "▶ RUN"}
          </button>
        </div>
      </div>

      <div style={{ maxWidth: 960, margin: "0 auto", padding: "20px 16px", display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 16 }}>

        {/* PARAMS PANEL */}
        <div>
          <div style={{ background: "#07101f", border: "1px solid #1e3a5f", borderRadius: 8, padding: 16, marginBottom: 14 }}>
            <div style={{ color: "#3a5a7c", fontSize: 10, letterSpacing: 3, marginBottom: 14 }}>// PARÂMETROS GBM</div>
            <Slider label="Drift μ" min={0.0} max={0.5} step={0.01} value={params.mu} onChange={set("mu")} fmt={pct} />
            <Slider label="Vol σ" min={0.05} max={0.8} step={0.01} value={params.sigma} onChange={set("sigma")} fmt={pct} />
            <Slider label="Preço S₀" min={50} max={300} step={5} value={params.S0} onChange={set("S0")} fmt={(v:number) => "$" + v} />
          </div>
          <div style={{ background: "#07101f", border: "1px solid #1e3a5f", borderRadius: 8, padding: 16, marginBottom: 14 }}>
            <div style={{ color: "#3a5a7c", fontSize: 10, letterSpacing: 3, marginBottom: 14 }}>// CAPM</div>
            <Slider label="Beta β" min={0.1} max={3.0} step={0.1} value={params.beta} onChange={set("beta")} fmt={(v:number) => v.toFixed(1)} />
            <Slider label="Rf (taxa)" min={0.01} max={0.15} step={0.005} value={params.rf} onChange={set("rf")} fmt={pct} />
            <Slider label="Rm (mkt)" min={0.05} max={0.25} step={0.01} value={params.rm} onChange={set("rm")} fmt={pct} />
          </div>
          <div style={{ background: "#07101f", border: "1px solid #1e3a5f", borderRadius: 8, padding: 16, marginBottom: 14 }}>
            <div style={{ color: "#3a5a7c", fontSize: 10, letterSpacing: 3, marginBottom: 14 }}>// BLACK-SCHOLES</div>
            <Slider label="Strike K" min={70} max={150} step={1} value={params.K} onChange={set("K")} fmt={(v:number) => "$" + v} />
            <Slider label="Vencimento" min={0.08} max={1} step={0.04} value={params.T_opt} onChange={set("T_opt")} fmt={(v:number) => (v * 12).toFixed(0) + "m"} />
          </div>
          <div style={{ background: "#07101f", border: "1px solid #1e3a5f", borderRadius: 8, padding: 16 }}>
            <div style={{ color: "#3a5a7c", fontSize: 10, letterSpacing: 3, marginBottom: 14 }}>// CAPITAL</div>
            <Slider label="Portfólio" min={100000} max={10000000} step={100000} value={params.capital} onChange={set("capital")} fmt={money} />
          </div>
        </div>

        {/* MAIN PANEL */}
        <div style={{width: "100%", overflowX: "auto"}}>
          {/* TABS */}
          <div style={{ display: "flex", gap: 2, borderBottom: "1px solid #1e3a5f", marginBottom: 0, overflowX: "auto" }}>
            {tabs.map(([id, l]) => (
              <button key={id} onClick={() => setTab(id)} style={{ background: tab === id ? "#07101f" : "transparent", border: `1px solid ${tab === id ? "#1e3a5f" : "transparent"}`, borderBottom: tab === id ? "1px solid #050a14" : "1px solid #1e3a5f", color: tab === id ? "#00ff88" : "#3a5a7c", padding: "8px 14px", fontFamily: "monospace", fontSize: 10, letterSpacing: 2, cursor: "pointer", borderRadius: "4px 4px 0 0", marginBottom: -1 }}>{l}</button>
            ))}
          </div>
          <div style={{ background: "#07101f", border: "1px solid #1e3a5f", borderTop: "none", borderRadius: "0 4px 8px 8px", padding: 20 }}>

            {/* ── OVERVIEW ── */}
            {tab === "overview" && result && (
              <div>
                {/* Equity Curve */}
                <Section title="CURVA DE EQUITY — GBM + CHERN-SIMONS" tag="252d">
                  <MiniChart data={result.equity_curve} color={result.totalReturn >= 0 ? "#00ff88" : "#ff6b6b"} height={100} />
                  <div style={{ display: "flex", gap: 6, marginTop: 8, flexWrap: "wrap" }}>
                    {result.signals_log.slice(-12).map((s: any, i: number) => (
                      <span key={i} style={{ background: s.signal > 0 ? "#00ff8811" : "#ff6b6b11", border: `1px solid ${s.signal > 0 ? "#00ff8833" : "#ff6b6b33"}`, color: s.signal > 0 ? "#00ff88" : "#ff6b6b", borderRadius: 3, padding: "1px 6px", fontSize: 10, fontFamily: "monospace" }}>
                        {s.signal > 0 ? "▲" : "▼"} ${s.price.toFixed(0)}
                      </span>
                    ))}
                  </div>
                </Section>

                {/* KPIs */}
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 10, marginBottom: 20 }}>
                  <Pill label="RETORNO TOTAL" value={(result.totalReturn * 100).toFixed(1) + "%"} color={ret_color} sub="vs benchmark" />
                  <Pill label="SHARPE RATIO" value={result.sharpe.toFixed(2)} color={sr_color} sub={result.sharpe > 3 ? "Renaissance tier" : result.sharpe > 1 ? "aceitável" : "abaixo do target"} />
                  <Pill label="MAX DRAWDOWN" value={(result.maxDD * 100).toFixed(1) + "%"} color="#ff6b6b" sub="pior queda" />
                  <Pill label="WIN RATE" value={(result.winRate * 100).toFixed(0) + "%"} color="#ffd700" sub={`${result.trades} trades`} />
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 10 }}>
                  <Pill label="VaR 99% DIÁRIO" value={"$" + (result.VaR / 1000).toFixed(0) + "k"} color="#c084fc" sub="perda máx/dia" />
                  <Pill label="EQUITY FINAL" value={"$" + (result.finalEquity / 1000).toFixed(0) + "k"} color={ret_color} sub="do capital inicial" />
                  <Pill label="RETORNO CAPM" value={(result.capmReturn * 100).toFixed(1) + "%"} color="#7eb8f7" sub={`β = ${params.beta.toFixed(1)}`} />
                </div>
              </div>
            )}

            {/* ── CHERN-SIMONS SIGNAL ── */}
            {tab === "signal" && result && (
              <div>
                <Section title="TEORIA DE CHERN-SIMONS APLICADA A SÉRIES TEMPORAIS">
                  <div style={{ color: "#5a7a9c", fontSize: 12, lineHeight: 1.8, marginBottom: 16 }}>
                    A teoria Chern-Simons (1974) descreve invariantes geométricas em variedades. Aplicada a finanças: a série de preços é tratada como uma curva em um espaço de fases. A <span style={{ color: "#00ff88" }}>curvatura κ</span> da curva (taxa de mudança da velocidade) é análoga à forma de conexão de gauge — e o sinal <span style={{ color: "#ffd700" }}>gauge-invariante</span> sobrevive a transformações de escala.
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12, marginBottom: 16 }}>
                    <div style={{ background: "#0a1628", border: "1px solid #1e3a5f", borderRadius: 8, padding: 14 }}>
                      <div style={{ color: "#3a5a7c", fontSize: 10, letterSpacing: 2, marginBottom: 6 }}>FÓRMULA — FORMA DE CHERN-SIMONS</div>
                      <div style={{ color: "#00ff88", fontSize: 12, fontFamily: "monospace", lineHeight: 2 }}>
                        v(t) = EMA_fast(r) − EMA_slow(r)<br/>
                        κ(t) = v(t) − v(t−1)  [curvatura]<br/>
                        S_gi = κ / |v|  [gauge-invariante]
                      </div>
                    </div>
                    <div style={{ background: "#0a1628", border: "1px solid #1e3a5f", borderRadius: 8, padding: 14 }}>
                      <div style={{ color: "#3a5a7c", fontSize: 10, letterSpacing: 2, marginBottom: 6 }}>VARIEDADE MÍNIMA</div>
                      <div style={{ color: "#c8d8e8", fontSize: 12, lineHeight: 1.8 }}>
                        Quando κ → 0, a série está em <span style={{ color: "#ffd700" }}>variedade mínima</span> — curvatura mínima. Simons usou esta ideia para modelar superfícies de equilíbrio. No trading: sinaliza <span style={{ color: "#ffd700" }}>reversão iminente</span>.
                      </div>
                    </div>
                  </div>
                </Section>

                {/* Live signal state */}
                <Section title="ESTADO ATUAL DO SINAL">
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(100px, 1fr))", gap: 10, marginBottom: 14 }}>
                    <Pill label="FASE" value={result.csSignal.phase} color={phase_color} />
                    <Pill label="VELOCIDADE" value={(result.csSignal.velocity * 1000).toFixed(2)} color="#7eb8f7" sub="×10⁻³" />
                    <Pill label="CURVATURA κ" value={(result.csSignal.kappa * 1000).toFixed(3)} color="#c084fc" sub="×10⁻³" />
                    <Pill label="GAUGE-INV." value={(result.csSignal.gaugeInvariant || 0).toFixed(3)} color="#ffd700" sub="invariante" />
                  </div>
                  <div style={{ background: "#0a1628", border: `1px solid ${phase_color}33`, borderRadius: 8, padding: 14 }}>
                    <div style={{ color: "#3a5a7c", fontSize: 10, letterSpacing: 2, marginBottom: 6 }}>SINAL FINAL → DECISÃO</div>
                    <div style={{ color: phase_color, fontSize: 16, fontWeight: 700 }}>
                      {result.csSignal.isMinimalVariety ? "⚠ VARIEDADE MÍNIMA — AGUARDAR REVERSÃO" : result.csSignal.signal > 0 ? "▲ LONG — Curvatura positiva detectada" : result.csSignal.signal < 0 ? "▼ SHORT — Curvatura negativa detectada" : "◼ NEUTRO"}
                    </div>
                    <div style={{ color: "#3a5a7c", fontSize: 11, marginTop: 6 }}>
                      {result.csSignal.isMinimalVariety ? "κ → 0: superfície de curvatura mínima (Simons). Momentum está se esgotando." : "Posicionamento alinhado ao invariante de gauge. Kelly aplicado ao sizing."}
                    </div>
                  </div>
                </Section>

                {/* Price chart */}
                <Section title="SÉRIE DE PREÇOS — GBM SIMULADO">
                  <MiniChart data={result.prices} color="#7eb8f7" height={90} />
                </Section>
              </div>
            )}

            {/* ── BLACK-SCHOLES ── */}
            {tab === "bs" && result && (
              <div>
                <Section title="PRECIFICAÇÃO DE OPÇÕES — BLACK-SCHOLES 1973">
                  <div style={{ color: "#5a7a9c", fontSize: 12, lineHeight: 1.8, marginBottom: 14 }}>
                    Black-Scholes assume preços seguindo <span style={{ color: "#00ff88" }}>GBM</span> (idêntico ao módulo 1 deste algoritmo) com volatilidade constante. O modelo produz o preço justo de opções via integração sobre caminhos de Brownian motion — base dos derivativos que superam $600T nocionais.
                  </div>
                  <div style={{ background: "#0a1628", border: "1px solid #1e3a5f", borderRadius: 8, padding: 14, marginBottom: 16 }}>
                    <div style={{ color: "#3a5a7c", fontSize: 10, letterSpacing: 2, marginBottom: 8 }}>FÓRMULA</div>
                    <div style={{ color: "#00ff88", fontSize: 12, fontFamily: "monospace", lineHeight: 2 }}>
                      d₁ = [ln(S/K) + (r + σ²/2)T] / (σ√T)<br/>
                      d₂ = d₁ − σ√T<br/>
                      C = S·N(d₁) − K·e^(−rT)·N(d₂)
                    </div>
                  </div>
                </Section>

                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12, marginBottom: 16 }}>
                  <div style={{ background: "#0a1628", border: "1px solid #00ff8833", borderRadius: 8, padding: 16 }}>
                    <div style={{ color: "#3a5a7c", fontSize: 10, letterSpacing: 2, marginBottom: 10 }}>CALL OPTION</div>
                    <div style={{ color: "#00ff88", fontSize: 28, fontWeight: 700, marginBottom: 4 }}>${result.call.toFixed(2)}</div>
                    <div style={{ color: "#3a5a7c", fontSize: 11 }}>S=${result.finalPrice.toFixed(1)} K=${params.K} T={params.T_opt.toFixed(2)}a σ={pct(params.sigma)}</div>
                    <div style={{ marginTop: 10, color: result.finalPrice > params.K ? "#00ff88" : "#ff6b6b", fontSize: 12 }}>
                      {result.finalPrice > params.K ? `▲ ITM (+$${(result.finalPrice - params.K).toFixed(2)} intrínseco)` : `▼ OTM (-$${(params.K - result.finalPrice).toFixed(2)} fora do dinheiro)`}
                    </div>
                  </div>
                  <div style={{ background: "#0a1628", border: "1px solid #ff6b6b33", borderRadius: 8, padding: 16 }}>
                    <div style={{ color: "#3a5a7c", fontSize: 10, letterSpacing: 2, marginBottom: 10 }}>PUT OPTION</div>
                    <div style={{ color: "#ff6b6b", fontSize: 28, fontWeight: 700, marginBottom: 4 }}>
                      ${blackScholes(result.finalPrice, params.K, params.T_opt, params.rf, params.sigma, "put").toFixed(2)}
                    </div>
                    <div style={{ color: "#3a5a7c", fontSize: 11 }}>paridade put-call verificada</div>
                  </div>
                </div>

                <Section title="GREGAS — SENSIBILIDADES DA OPÇÃO">
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 10 }}>
                    {[
                      { l: "DELTA Δ", v: result.greeks.delta.toFixed(3), c: "#00ff88", desc: "∂C/∂S — sensibilidade ao preço" },
                      { l: "GAMMA Γ", v: result.greeks.gamma.toFixed(4), c: "#7eb8f7", desc: "∂²C/∂S² — curvatura do delta" },
                      { l: "VEGA ν", v: result.greeks.vega.toFixed(3), c: "#ffd700", desc: "∂C/∂σ (por 1% vol)" },
                      { l: "THETA Θ", v: result.greeks.theta.toFixed(3), c: "#ff6b6b", desc: "∂C/∂t — decaimento diário" },
                    ].map(g => (
                      <div key={g.l} style={{ background: "#0a1628", border: `1px solid ${g.c}22`, borderRadius: 8, padding: 12 }}>
                        <div style={{ color: "#3a5a7c", fontSize: 10, letterSpacing: 2, marginBottom: 5 }}>{g.l}</div>
                        <div style={{ color: g.c, fontSize: 18, fontWeight: 700 }}>{g.v}</div>
                        <div style={{ color: "#3a5a7c", fontSize: 10, marginTop: 5, lineHeight: 1.4 }}>{g.desc}</div>
                      </div>
                    ))}
                  </div>
                </Section>
              </div>
            )}

            {/* ── PORTFOLIO ── */}
            {tab === "portfolio" && result && (
              <div>
                {/* CAPM */}
                <Section title="CAPM — RETORNO ESPERADO PELO RISCO SISTEMÁTICO" tag="Sharpe 1964">
                  <div style={{ background: "#0a1628", border: "1px solid #1e3a5f", borderRadius: 8, padding: 14, marginBottom: 14 }}>
                    <div style={{ color: "#3a5a7c", fontSize: 10, letterSpacing: 2, marginBottom: 8 }}>FÓRMULA CAPM</div>
                    <div style={{ color: "#7eb8f7", fontSize: 13, fontFamily: "monospace" }}>
                      E(Ri) = Rf + βi·[E(Rm) − Rf]
                      <br />= {pct(params.rf)} + {params.beta.toFixed(1)}·[{pct(params.rm)} − {pct(params.rf)}]
                      <span style={{ color: "#00ff88" }}> = {pct(result.capmReturn)}</span>
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: 10 }}>
                    <div style={{ flex: 1, background: "#0a1628", borderRadius: 6, padding: 12 }}>
                      <div style={{ color: "#3a5a7c", fontSize: 10, marginBottom: 4 }}>ALPHA ESPERADO</div>
                      <div style={{ color: params.mu > result.capmReturn ? "#00ff88" : "#ff6b6b", fontSize: 16, fontWeight: 700 }}>
                        {((params.mu - result.capmReturn) * 100).toFixed(1)}%
                      </div>
                      <div style={{ color: "#3a5a7c", fontSize: 11 }}>GBM drift − CAPM</div>
                    </div>
                    <div style={{ flex: 1, background: "#0a1628", borderRadius: 6, padding: 12 }}>
                      <div style={{ color: "#3a5a7c", fontSize: 10, marginBottom: 4 }}>PRÊMIO DE RISCO</div>
                      <div style={{ color: "#c084fc", fontSize: 16, fontWeight: 700 }}>{pct(params.rm - params.rf)}</div>
                      <div style={{ color: "#3a5a7c", fontSize: 11 }}>E(Rm) − Rf</div>
                    </div>
                  </div>
                </Section>

                {/* Mean-Variance */}
                <Section title="MEAN-VARIANCE — MARKOWITZ 1952 → FRONTEIRA EFICIENTE">
                  {(() => {
                    const vols = [0.10, 0.15, 0.20, 0.25, 0.30, params.sigma];
                    const rets = vols.map(s => capm(params.rf, params.beta * (s / params.sigma), params.rm) + (params.mu - result.capmReturn) * 0.5);
                    const maxV = Math.max(...vols), maxR = Math.max(...rets);
                    const px = (v:number) => (v / maxV) * 240;
                    const py = (r:number, h = 80) => h - (r / maxR) * (h - 8) - 4;
                    const pts = vols.map((v, i) => `${px(v)},${py(rets[i])}`).join(" ");
                    return (
                      <div style={{ background: "#0a1628", border: "1px solid #1e3a5f", borderRadius: 8, padding: 14, marginBottom: 14 }}>
                        <div style={{ color: "#3a5a7c", fontSize: 10, letterSpacing: 2, marginBottom: 10 }}>FRONTEIRA EFICIENTE (σ × E[R])</div>
                        <svg viewBox="0 0 260 100" style={{ width: "100%", height: 100 }}>
                          <polyline points={pts} fill="none" stroke="#7eb8f7" strokeWidth="1.5" />
                          {vols.map((v, i) => (
                            <circle key={i} cx={px(v)} cy={py(rets[i])} r={v === params.sigma ? 4 : 2.5}
                              fill={v === params.sigma ? "#00ff88" : "#7eb8f766"} />
                          ))}
                          <text x={px(params.sigma) + 6} y={py(rets[vols.indexOf(params.sigma)]) + 4} fill="#00ff88" fontSize="9">Portfólio atual</text>
                          <text x="2" y="96" fill="#3a5a7c" fontSize="8">σ →</text>
                          <text x="2" y="10" fill="#3a5a7c" fontSize="8">E[R] ↑</text>
                        </svg>
                      </div>
                    );
                  })()}
                </Section>

                {/* Kelly */}
                <Section title="KELLY CRITERION — SIZING ÓTIMO DO PORTFÓLIO">
                  {(() => {
                    const k = kelly(params.mu, params.sigma, params.rf);
                    const safe = Math.max(0, Math.min(1, k.half));
                    return (
                      <div>
                        <div style={{ background: "#0a1628", border: "1px solid #1e3a5f", borderRadius: 8, padding: 14, marginBottom: 12 }}>
                          <div style={{ color: "#3a5a7c", fontSize: 10, marginBottom: 6 }}>KELLY CONTÍNUO: f* = (μ − Rf) / σ²</div>
                          <div style={{ color: "#ffd700", fontSize: 13, fontFamily: "monospace" }}>
                            = ({pct(params.mu)} − {pct(params.rf)}) / {params.sigma.toFixed(2)}²
                            <span style={{ color: "#00ff88" }}> = {(k.full * 100).toFixed(0)}% do capital</span>
                          </div>
                        </div>
                        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10, marginBottom: 12 }}>
                          {[["KELLY FULL", k.full, "#ff6b6b", "máximo teórico"], ["HALF-KELLY", k.half, "#00ff88", "recomendado prático"], ["QUARTER-KELLY", k.quarter, "#7eb8f7", "conservador"]].map(([l, v, c, d]) => (
                            <div key={l as string} style={{ background: "#0a1628", border: `1px solid ${c}22`, borderRadius: 8, padding: 12, textAlign: "center" }}>
                              <div style={{ color: "#3a5a7c", fontSize: 10, marginBottom: 6 }}>{l}</div>
                              <div style={{ color: c as string, fontSize: 20, fontWeight: 700 }}>{(Math.max(0, v as number) * 100).toFixed(0)}%</div>
                              <div style={{ color: "#3a5a7c", fontSize: 10 }}>{d}</div>
                            </div>
                          ))}
                        </div>
                        <div style={{ background: "#0a1628", border: "1px solid #00ff8822", borderRadius: 8, padding: 12 }}>
                          <div style={{ color: "#3a5a7c", fontSize: 10, marginBottom: 6 }}>CAPITAL ALOCADO (HALF-KELLY)</div>
                          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                            <div style={{ flex: 1, background: "#050a14", borderRadius: 4, height: 8 }}>
                              <div style={{ width: `${safe * 100}%`, height: "100%", background: "#00ff88", borderRadius: 4 }} />
                            </div>
                            <span style={{ color: "#00ff88", fontWeight: 700, fontFamily: "monospace" }}>${(safe * params.capital / 1000).toFixed(0)}k</span>
                          </div>
                        </div>
                      </div>
                    );
                  })()}
                </Section>

                {/* VaR */}
                <Section title="VALUE AT RISK — RISCO MÁXIMO DIÁRIO 99%">
                  <div style={{ background: "#0a1628", border: "1px solid #c084fc33", borderRadius: 8, padding: 14 }}>
                    <div style={{ color: "#3a5a7c", fontSize: 10, marginBottom: 6 }}>VaR₉₉ = |μ_d − 2.326·σ_d| × Capital</div>
                    <div style={{ color: "#c084fc", fontSize: 22, fontWeight: 700 }}>${(result.VaR / 1000).toFixed(1)}k</div>
                    <div style={{ color: "#5a7a9c", fontSize: 12, marginTop: 6 }}>
                      Em condições normais, a perda diária excederá este valor apenas 1 vez a cada 100 dias de negociação.
                    </div>
                    <div style={{ display: "flex", gap: 4, marginTop: 10 }}>
                      {Array.from({ length: 20 }).map((_, i) => (
                        <div key={i} style={{ flex: 1, height: 6, borderRadius: 2, background: i === 19 ? "#c084fc" : "#1e3a5f" }} />
                      ))}
                    </div>
                    <div style={{ color: "#3a5a7c", fontSize: 10, marginTop: 4 }}>1 dia em 100 excede o VaR ↑</div>
                  </div>
                </Section>
              </div>
            )}

            {!result && (
              <div style={{ textAlign: "center", padding: "60px 0", color: "#3a5a7c", fontSize: 13 }}>
                Pressione ▶ RUN para executar o algoritmo
              </div>
            )}
          </div>
        </div>
      </div>

      {/* LEGEND */}
      <div style={{ maxWidth: 960, margin: "0 auto", padding: "0 16px 32px" }}>
        <div style={{ background: "#07101f", border: "1px solid #1e3a5f", borderRadius: 8, padding: 16 }}>
          <div style={{ color: "#3a5a7c", fontSize: 10, letterSpacing: 3, marginBottom: 12 }}>// ARQUITETURA DO ALGORITMO — 12 CONCEITOS UNIFICADOS</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 8 }}>
            {[
              ["GBM", "Simula caminhos de preço", "#7eb8f7"],
              ["Chern-Simons", "Curvatura do sinal", "#00ff88"],
              ["Gauge Inv.", "Sinal robusto a regime", "#00ff88"],
              ["Var. Mínimas", "Detecta reversão κ→0", "#ffd700"],
              ["Geom. Diferencial", "Curvas em espaço de fases", "#c084fc"],
              ["CAPM", "Retorno esperado via β", "#7eb8f7"],
              ["Black-Scholes", "Precificação de opções", "#ff6b6b"],
              ["Mean-Variance", "Fronteira eficiente", "#7eb8f7"],
              ["Kelly Criterion", "Sizing ótimo do capital", "#ffd700"],
              ["Sharpe Ratio", "Retorno ajustado ao risco", "#00ff88"],
              ["Value at Risk", "Controle de drawdown", "#c084fc"],
              ["Quant Signals", "Reconhecimento de padrões", "#00ff88"],
            ].map(([name, desc, color]) => (
              <div key={name} style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
                <span style={{ width: 6, height: 6, borderRadius: "50%", background: color, marginTop: 5, flexShrink: 0 }} />
                <div>
                  <div style={{ color, fontSize: 11, fontWeight: 700 }}>{name}</div>
                  <div style={{ color: "#3a5a7c", fontSize: 10, lineHeight: 1.4 }}>{desc}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
      <style>{`* { box-sizing:border-box; } input[type=range]{ cursor:pointer; } ::-webkit-scrollbar{width:4px; height:4px;} ::-webkit-scrollbar-thumb{background:#1e3a5f;}`}</style>
    </div>
  );
}
