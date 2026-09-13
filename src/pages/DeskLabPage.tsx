import React, { useState } from 'react';
import {
  Alert, Box, Button, Card, CardContent, Chip, Tab, Tabs, TextField, Typography,
} from '@mui/material';
import { api } from '../services/api';

function seeded(n: number, drift = 0.0003, vol = 0.012, seed = 7): number[] {
  const out = [100];
  let s = seed;
  const rnd = () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 0xffffffff;
  };
  for (let i = 1; i < n; i++) {
    const u = rnd(), v = rnd();
    const z = Math.sqrt(-2 * Math.log(Math.max(u, 1e-12))) * Math.cos(2 * Math.PI * v);
    out.push(out[i - 1] * Math.exp(drift + vol * z));
  }
  return out;
}

export default function DeskLabPage() {
  const [tab, setTab] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<any>(null);
  const [inventory, setInventory] = useState(0);
  const [ticker, setTicker] = useState('AAPL');
  const [symbol, setSymbol] = useState('BTCUSDT');

  const run = async (fn: () => Promise<unknown>) => {
    setLoading(true); setError(''); setResult(null);
    try { setResult(await fn()); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setLoading(false); }
  };

  const heston = () => run(() => api.deskHestonPrice({
    S0: 100, K: 100, v0: 0.04, r: 0.05, kappa: 2, theta: 0.04, xi: 0.3, rho: -0.7, T: 1, method: 'cf',
  }));

  const calibrate = () => run(() => api.deskHestonCalibrate({
    S0: 100, r: 0.05,
    quotes: [
      { K: 90, T: 0.5, iv: 0.28, option_type: 'call' },
      { K: 95, T: 0.5, iv: 0.24, option_type: 'call' },
      { K: 100, T: 0.5, iv: 0.21, option_type: 'call' },
      { K: 105, T: 0.5, iv: 0.20, option_type: 'call' },
      { K: 110, T: 0.5, iv: 0.195, option_type: 'call' },
    ],
  }));

  const pairs = () => {
    const x = seeded(400, 0.0002, 0.015, 3);
    const y = x.map((px, i) => 2 * px + 3 + (seeded(400, 0, 0.001, 9)[i] - 100));
    return run(() => api.deskPairsBacktest({ x, y, entry_z: 2, exit_z: 0.5 }));
  };

  const johansenRun = () => {
    const x = seeded(250, 0.0002, 0.015, 3);
    const y = x.map((px, i) => 1.6 * px + (seeded(250, 0, 0.002, 11)[i] - 100));
    return run(() => api.deskJohansen({ series: { y, x }, k_ar: 2 }));
  };

  const mm = () => run(() => api.deskMarketMaking({
    mid: 100, inventory, sigma: 0.2, gamma: 0.1, k: 1.5, A: 140, time_remaining: 1,
  }));

  const ff = () => {
    const z = (seed: number) => {
      const p = seeded(253, 0, 0.004, seed);
      return p.slice(1).map((a, i) => a / p[i] - 1);
    };
    const mkt_rf = z(11), smb = z(12), hml = z(13), rmw = z(14), cma = z(15);
    const excess_returns = mkt_rf.map((m, i) => 0.0001 + 1.1 * m + 0.2 * smb[i]);
    return run(() => api.deskFamaFrench({ excess_returns, mkt_rf, smb, hml, rmw, cma }));
  };

  const mr = () => run(() => api.deskMeanReversion({
    universe: { SYN_OU: seeded(300, 0, 0.008, 2), SYN_TREND: seeded(300, 0.0008, 0.01, 4) },
  }));

  const perp = () => run(() => api.deskPerpArb({
    quotes: [
      { venue: 'hyperliquid', bid: 100.0, ask: 100.05, taker_fee_bps: 3.5, funding_8h: 0.0001 },
      { venue: 'binance', bid: 100.4, ask: 100.45, taker_fee_bps: 4.0, funding_8h: -0.00005 },
    ],
    notional: 10_000,
  }));

  const perpLive = () => run(() => api.deskPerpLive(symbol));
  const edgar = () => run(() => api.deskEdgar({ ticker, limit: 6, window_days: 7, min_insiders: 2 }));

  const actions = [
    { label: 'Heston CF', paper: 'Heston 1993', blurb: 'Preço europeu pela função característica (Albrecher), não Euler.', run: heston },
    { label: 'Heston calibração', paper: 'Smile → (v0, κ, θ, ξ, ρ)', blurb: 'Least squares no preço. Cinco parâmetros numa expiry não são identificados — o RMSE do smile é o que importa.', run: calibrate },
    { label: 'Pairs / EG', paper: 'Engle–Granger 1987', blurb: 'β OLS, ADF no residual, backtest com z expanding, fill t+1 e rank de Johansen.', run: pairs },
    { label: 'Johansen', paper: 'Johansen 1991', blurb: 'Trace test no painel. Não escolhe variável dependente; EG escolhe.', run: johansenRun },
    { label: 'Avellaneda–Stoikov', paper: 'Avellaneda & Stoikov 2008', blurb: 'Preço de reserva e spread ótimo; inventário enviesa o book.', run: mm },
    { label: 'Fama–French 5', paper: 'Fama & French 2015', blurb: 'OLS nos cinco fatores. Você fornece as séries — não raspamos Ken French.', run: ff },
    { label: 'Mean-reversion', paper: 'OU / AR(1)', blurb: 'Half-life, Hurst e ADF. Candidato ≠ autorização de trade.', run: mr },
    { label: 'Perp sintético', paper: 'Cross-venue', blurb: 'Edge após fee + 1 funding 8h, books inventados.', run: perp },
    { label: 'Perp live', paper: 'Binance USDM + Hyperliquid', blurb: 'BookTicker e L2 públicos, sem chaves, sem ordem. Top-of-book não é liquidez firme.', run: perpLive },
    { label: 'EDGAR Form 4', paper: 'Cohen–Malloy–Pomorski 2012', blurb: 'P/S em mercado aberto. Exige ATOM_SEC_USER_AGENT com e-mail. Sem isso a API recusa.', run: edgar },
  ];

  const needsInventory = actions[tab].label === 'Avellaneda–Stoikov';
  const needsTicker = actions[tab].label === 'EDGAR Form 4';
  const needsSymbol = actions[tab].label === 'Perp live';
  const liveish = actions[tab].label === 'Perp live' || actions[tab].label === 'EDGAR Form 4';

  return (
    <Box sx={{ maxWidth: 960, mx: 'auto' }}>
      <Typography variant="h4" sx={{ fontWeight: 800, mb: 1 }}>Mesa de papers</Typography>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        Implementações from-scratch. Cada resposta inclui a conta em inglês simples e
        <strong> what broke</strong>. Nada aqui é elegível para execução.
      </Typography>
      <Tabs value={tab} onChange={(_, v) => { setTab(v); setResult(null); setError(''); }} sx={{ mb: 2 }} variant="scrollable">
        {actions.map((a, i) => <Tab key={a.label} label={a.label} value={i} />)}
      </Tabs>
      <Card>
        <CardContent>
          <Chip size="small" label={actions[tab].paper} sx={{ mb: 1 }} />
          <Typography sx={{ mb: 2 }}>{actions[tab].blurb}</Typography>
          {needsInventory && (
            <TextField
              type="number" label="Inventário (contratos)" value={inventory} sx={{ mb: 2, mr: 2 }}
              onChange={(e) => setInventory(Number(e.target.value))}
            />
          )}
          {needsTicker && (
            <TextField
              label="Ticker SEC" value={ticker} sx={{ mb: 2, mr: 2 }}
              onChange={(e) => setTicker(e.target.value.toUpperCase())}
            />
          )}
          {needsSymbol && (
            <TextField
              label="Símbolo perp" value={symbol} sx={{ mb: 2, mr: 2 }}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            />
          )}
          <Button variant="contained" onClick={actions[tab].run} disabled={loading}>
            {loading ? 'Calculando…' : liveish ? 'Consultar livros / EDGAR' : 'Rodar demonstração'}
          </Button>
          {error && <Alert severity="error" sx={{ mt: 2 }}>{error}</Alert>}
          {result && (
            <Box sx={{ mt: 2 }}>
              {result.math && <Alert severity="info" sx={{ mb: 2 }}>{result.math}</Alert>}
              {result.what_broke && (
                <Alert severity="warning" sx={{ mb: 2 }}>
                  <strong>What broke</strong>
                  <ul style={{ margin: '8px 0 0', paddingLeft: 18 }}>
                    {result.what_broke.map((w: string) => <li key={w}>{w}</li>)}
                  </ul>
                </Alert>
              )}
              <pre style={{ overflow: 'auto', fontSize: 12, maxHeight: 420 }}>
                {JSON.stringify(result, null, 2)}
              </pre>
            </Box>
          )}
        </CardContent>
      </Card>
    </Box>
  );
}
