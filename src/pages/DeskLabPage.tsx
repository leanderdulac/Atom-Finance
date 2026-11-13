import React, { useState } from 'react';
import {
  Alert, Box, Button, Card, CardContent, Chip, Divider, MenuItem, Table,
  TableBody, TableCell, TableHead, TableRow, Tab, Tabs, TextField, Typography,
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
  const [pbCapital, setPbCapital] = useState(100_000);
  const [pbMode, setPbMode] = useState<'synthetic' | 'live'>('synthetic');
  const [pbRegime, setPbRegime] = useState<'calm' | 'trending' | 'crisis'>('calm');
  const [pbEntryZ, setPbEntryZ] = useState(1.8);

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
  const playbook = () => run(() => api.deskPlaybookScan({
    mode: pbMode,
    regime_demo: pbRegime,
    capital: pbCapital,
    entry_z: pbEntryZ,
    exit_z: 0.5,
  }));

  const actions = [
    { label: 'Playbook 3 Frentes', paper: 'Engle–Granger + Johansen + Perp Carry + Regime Half-Kelly', blurb: 'Scanner unificado do Tripé Quantitativo com Boleta de Montagem (Order Ticket): Pares B3 & Commodities cointegrados, Arbitragem de Funding Cripto (BTC/ETH/SOL) e Alocação de Capital por Regime.', run: playbook },
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

  const isPlaybook = actions[tab].label === 'Playbook 3 Frentes';
  const needsInventory = actions[tab].label === 'Avellaneda–Stoikov';
  const needsTicker = actions[tab].label === 'EDGAR Form 4';
  const needsSymbol = actions[tab].label === 'Perp live';
  const liveish = actions[tab].label === 'Perp live' || actions[tab].label === 'EDGAR Form 4';

  return (
    <Box sx={{ maxWidth: 1080, mx: 'auto' }}>
      <Typography variant="h4" sx={{ fontWeight: 800, mb: 1 }}>Mesa de papers</Typography>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        Implementações from-scratch. Cada resposta inclui a conta em inglês simples e
        <strong> what broke</strong>. Nada aqui é elegível para execução direta sem validação em Paper Trading.
      </Typography>
      <Tabs value={tab} onChange={(_, v) => { setTab(v); setResult(null); setError(''); }} sx={{ mb: 2 }} variant="scrollable">
        {actions.map((a, i) => <Tab key={a.label} label={a.label} value={i} />)}
      </Tabs>
      <Card>
        <CardContent>
          <Chip size="small" label={actions[tab].paper} sx={{ mb: 1 }} />
          <Typography sx={{ mb: 2 }}>{actions[tab].blurb}</Typography>
          {isPlaybook && (
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 2, mb: 2 }}>
              <TextField
                type="number"
                size="small"
                label="Capital Total (R$)"
                value={pbCapital}
                onChange={(e) => setPbCapital(Math.max(1000, Number(e.target.value)))}
              />
              <TextField
                select
                size="small"
                label="Regime de Mercado"
                value={pbRegime}
                onChange={(e) => setPbRegime(e.target.value as 'calm' | 'trending' | 'crisis')}
                sx={{ minWidth: 180 }}
              >
                <MenuItem value="calm">Calmo / Mean-Rev</MenuItem>
                <MenuItem value="trending">Tendência (Trending)</MenuItem>
                <MenuItem value="crisis">Crise (Stress / Risk-Off)</MenuItem>
              </TextField>
              <TextField
                select
                size="small"
                label="Fonte de Dados"
                value={pbMode}
                onChange={(e) => setPbMode(e.target.value as 'synthetic' | 'live')}
                sx={{ minWidth: 170 }}
              >
                <MenuItem value="synthetic">Benchmark Determinístico</MenuItem>
                <MenuItem value="live">Cotações Live (Yahoo/B3)</MenuItem>
              </TextField>
              <TextField
                type="number"
                size="small"
                label="Gatilho |Z-Score|"
                inputProps={{ step: 0.1, min: 1.0, max: 3.5 }}
                value={pbEntryZ}
                onChange={(e) => setPbEntryZ(Math.max(0.8, Number(e.target.value)))}
                sx={{ width: 150 }}
              />
            </Box>
          )}
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
            {loading ? 'Calculando…' : isPlaybook ? 'Gerar Scanner & Boletas de Montagem' : liveish ? 'Consultar livros / EDGAR' : 'Rodar demonstração'}
          </Button>
          {error && <Alert severity="error" sx={{ mt: 2 }}>{error}</Alert>}
          {result && (
            <Box sx={{ mt: 2 }}>
              {result.pillar_1_pairs_and_commodities && (
                <Box sx={{ mb: 3 }}>
                  <Alert severity={result.regime_summary?.regime === 'crisis' ? 'error' : 'success'} sx={{ mb: 2 }}>
                    <strong>Regime Detectado: {result.regime_summary?.regime}</strong> — Reserva em Caixa Recomendada:{' '}
                    <strong>R$ {result.capital_allocation?.cash_reserve?.toLocaleString('pt-BR')} ({result.capital_allocation?.cash_reserve_pct}%)</strong>
                    {' | '}DSR (Probabilidade Anti-Overfitting):{' '}
                    <strong>{((result.multiple_testing_audit?.deflated_sharpe_prob ?? 0) * 100).toFixed(1)}%</strong>
                  </Alert>

                  <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>
                    1. Orçamento por Estratégia (Half-Kelly + Corte de Correlação)
                  </Typography>
                  <Table size="small" sx={{ mb: 3 }}>
                    <TableHead>
                      <TableRow>
                        <TableCell>Caixa Estratégica</TableCell>
                        <TableCell>Ação</TableCell>
                        <TableCell align="right">Peso Alvo (%)</TableCell>
                        <TableCell align="right">Capital Alocado (R$)</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {result.capital_allocation?.strategies?.map((s: any) => (
                        <TableRow key={s.strategy_id}>
                          <TableCell>{s.strategy_name}</TableCell>
                          <TableCell><Chip size="small" label={s.action} /></TableCell>
                          <TableCell align="right">{s.target_weight_pct}%</TableCell>
                          <TableCell align="right">R$ {Number(s.allocated_capital).toLocaleString('pt-BR')}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>

                  <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>
                    2. Boletas de Montagem — Pares Cointegrados (B3 & Commodities)
                  </Typography>
                  <Table size="small" sx={{ mb: 3 }}>
                    <TableHead>
                      <TableRow>
                        <TableCell>Par / Categoria</TableCell>
                        <TableCell align="right">Z-Score / Meia-Vida</TableCell>
                        <TableCell>Ponta Y (Ações / Preço)</TableCell>
                        <TableCell>Ponta X (Ações / Preço)</TableCell>
                        <TableCell>Regras de Saída (Alvo / Stops)</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {result.pillar_1_pairs_and_commodities.map((p: any) => {
                        const t = p.order_ticket;
                        return (
                          <TableRow key={p.pair}>
                            <TableCell>
                              <strong>{p.pair}</strong>
                              <Typography variant="caption" display="block" color="text.secondary">
                                {p.label} ({p.bucket})
                              </Typography>
                              <Chip
                                size="small"
                                color={p.actionable ? 'success' : 'default'}
                                label={p.actionable ? 'ACIONÁVEL' : 'AGUARDAR'}
                                sx={{ mt: 0.5 }}
                              />
                            </TableCell>
                            <TableCell align="right">
                              <strong>{p.current_z > 0 ? `+${p.current_z}` : p.current_z}</strong>
                              <Typography variant="caption" display="block" color="text.secondary">
                                HL: {p.half_life_days ?? '—'}d | β={p.hedge_ratio_beta}
                              </Typography>
                            </TableCell>
                            <TableCell>
                              <Chip size="small" color={t?.leg_y?.side === 'BUY' ? 'success' : t?.leg_y?.side === 'SELL_SHORT' ? 'warning' : 'default'} label={t?.leg_y?.side} sx={{ mr: 0.5 }} />
                              <strong>{t?.leg_y?.shares_exact}</strong> un. ({t?.leg_y?.ticker} @ {t?.leg_y?.last_price})
                              <Typography variant="caption" display="block" color="text.secondary">
                                Lote padrão: {t?.leg_y?.b3_standard_lot} + Frac: {t?.leg_y?.fractional_shares} (R$ {t?.leg_y?.notional?.toLocaleString('pt-BR')})
                              </Typography>
                            </TableCell>
                            <TableCell>
                              <Chip size="small" color={t?.leg_x?.side === 'BUY' ? 'success' : t?.leg_x?.side === 'SELL_SHORT' ? 'warning' : 'default'} label={t?.leg_x?.side} sx={{ mr: 0.5 }} />
                              <strong>{t?.leg_x?.shares_exact}</strong> un. ({t?.leg_x?.ticker} @ {t?.leg_x?.last_price})
                              <Typography variant="caption" display="block" color="text.secondary">
                                Lote padrão: {t?.leg_x?.b3_standard_lot} + Frac: {t?.leg_x?.fractional_shares} (R$ {t?.leg_x?.notional?.toLocaleString('pt-BR')})
                              </Typography>
                            </TableCell>
                            <TableCell>
                              <Typography variant="caption" display="block">
                                <strong>Alvo:</strong> {t?.rules?.take_profit_z}
                              </Typography>
                              <Typography variant="caption" display="block">
                                <strong>Stop Z:</strong> {t?.rules?.stop_loss_z}
                              </Typography>
                              <Typography variant="caption" display="block">
                                <strong>Time-Stop:</strong> {t?.rules?.time_stop_trading_days} pregões
                              </Typography>
                            </TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>

                  <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>
                    3. Boletas de Montagem — Cash-and-Carry Cripto Delta-Neutro (Δ = 0)
                  </Typography>
                  <Table size="small" sx={{ mb: 2 }}>
                    <TableHead>
                      <TableRow>
                        <TableCell>Ativo</TableCell>
                        <TableCell align="right">Funding Anualizado</TableCell>
                        <TableCell>Ponta 1: Compra Spot</TableCell>
                        <TableCell>Ponta 2: Short Perpétuo (1x)</TableCell>
                        <TableCell align="right">Carry Diário Est.</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {result.pillar_2_crypto_funding_carry?.map((c: any) => (
                        <TableRow key={c.symbol}>
                          <TableCell><strong>{c.symbol}</strong></TableCell>
                          <TableCell align="right">
                            <Chip size="small" color="success" label={`${c.annualized_funding_pct}% a.a.`} />
                          </TableCell>
                          <TableCell>
                            <strong>BUY {c.order_ticket?.spot_leg?.quantity}</strong> @ {c.order_ticket?.spot_leg?.reference_price}
                            <Typography variant="caption" display="block" color="text.secondary">
                              Notional: R$ {c.order_ticket?.spot_leg?.notional?.toLocaleString('pt-BR')}
                            </Typography>
                          </TableCell>
                          <TableCell>
                            <strong>SHORT {c.order_ticket?.perp_leg?.quantity}</strong> ({c.order_ticket?.perp_leg?.venue})
                            <Typography variant="caption" display="block" color="text.secondary">
                              Margem 1x: R$ {c.order_ticket?.perp_leg?.margin_posted_1x?.toLocaleString('pt-BR')}
                            </Typography>
                          </TableCell>
                          <TableCell align="right">
                            <strong>R$ {c.order_ticket?.expected_daily_carry?.toLocaleString('pt-BR')}/dia</strong>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                  <Divider sx={{ my: 2 }} />
                </Box>
              )}
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
