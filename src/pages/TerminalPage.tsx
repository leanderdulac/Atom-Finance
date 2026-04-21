import React, { useState } from 'react';
import {
  Box, Grid, Card, CardContent, Typography, TextField, Button,
  CircularProgress, Alert, Chip, Slider, Divider, Table,
  TableBody, TableCell, TableRow,
} from '@mui/material';
import { api } from '../services/api';
import GBMChart from '../components/charts/GBMChart';
import VaRDistributionChart from '../components/charts/VaRDistributionChart';
import CorrelationHeatmap from '../components/charts/CorrelationHeatmap';
import MarketTickerAutocomplete from '../components/MarketTickerAutocomplete';
import ProviderChips from '../components/ProviderChips';

// ── helpers ────────────────────────────────────────────────────────────────

function syntheticReturns(n = 500, mu = 0.0004, sigma = 0.015, seed = 42) {
  let s = seed;
  const r: number[] = [];
  for (let i = 0; i < n; i++) {
    s = (s * 16807) % 2147483647;
    const u = s / 2147483647;
    s = (s * 16807) % 2147483647;
    const v = s / 2147483647;
    r.push(mu + sigma * Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v));
  }
  return r;
}

function computeCorrelation(matrix: number[][]): number[][] {
  const n = matrix[0].length; // assets
  const T = matrix.length;    // time steps
  const means = Array.from({ length: n }, (_, j) => matrix.reduce((s, row) => s + row[j], 0) / T);
  const stds = Array.from({ length: n }, (_, j) => {
    const m = means[j];
    return Math.sqrt(matrix.reduce((s, row) => s + (row[j] - m) ** 2, 0) / T);
  });
  return Array.from({ length: n }, (_, i) =>
    Array.from({ length: n }, (_, j) => {
      if (stds[i] === 0 || stds[j] === 0) return i === j ? 1 : 0;
      return matrix.reduce((s, row) => s + (row[i] - means[i]) * (row[j] - means[j]), 0)
        / (T * stds[i] * stds[j]);
    })
  );
}

// ── component ──────────────────────────────────────────────────────────────

export default function TerminalPage() {
  // GBM state
  const [gbmLoading, setGbmLoading] = useState(false);
  const [gbmResult, setGbmResult] = useState<any>(null);
  const [gbmError, setGbmError] = useState('');
  const [gbmTicker, setGbmTicker] = useState('AAPL');
  const [gbmProvider, setGbmProvider] = useState('openbb');
  const [S0, setS0] = useState(100);
  const [mu, setMu] = useState(0.08);
  const [sigma, setSigma] = useState(0.20);
  const [T, setT] = useState(1.0);
  const [nPaths, setNPaths] = useState(200);

  // CAPM state
  const [capmLoading, setCapmLoading] = useState(false);
  const [capmResult, setCapmResult] = useState<any>(null);
  const [capmError, setCapmError] = useState('');
  const [assetTicker, setAssetTicker] = useState('AAPL');
  const [capmProvider, setCapmProvider] = useState('openbb');
  const [rfRate, setRfRate] = useState(0.05);
  const [mktPremium, setMktPremium] = useState(0.06);

  // Kelly state
  const [winRate, setWinRate] = useState(0.55);
  const [payoutRatio, setPayoutRatio] = useState(2.0);
  const [kellyFraction, setKellyFraction] = useState(0.5);
  const [kellyResult, setKellyResult] = useState<any>(null);

  // Portfolio risk state
  const [riskLoading, setRiskLoading] = useState(false);
  const [riskError, setRiskError] = useState('');
  const [portfolioTickers, setPortfolioTickers] = useState('AAPL,MSFT,GOOGL,AMZN,SPY');
  const [riskProvider, setRiskProvider] = useState('openbb');
  const [corrMatrix, setCorrMatrix] = useState<number[][] | null>(null);
  const [corrLabels, setCorrLabels] = useState<string[]>([]);
  const [varReturns, setVarReturns] = useState<number[]>(syntheticReturns());
  const [varThreshold, setVarThreshold] = useState(-0.032);
  const [varSource, setVarSource] = useState('synthetic');

  // ── GBM handlers ────────────────────────────────────────────────────────

  const loadGbmFromMarket = async () => {
    setGbmLoading(true); setGbmError('');
    try {
      const [hist, vol]: any[] = await Promise.all([
        api.history(gbmTicker, 252, gbmProvider),
        api.volatility(gbmTicker).catch(() => null),
      ]);
      const closes: number[] = (hist?.close || []).map(Number);
      if (closes.length < 20) throw new Error('Not enough data');
      const s0 = closes[closes.length - 1];
      const logRets = closes.slice(1).map((p, i) => Math.log(p / closes[i]));
      const annVol = vol?.iv_avg && vol.iv_avg < 2 ? vol.iv_avg
        : Math.sqrt(logRets.reduce((s, r) => s + r * r, 0) / logRets.length * 252);
      const annMu = logRets.reduce((s, r) => s + r, 0) / logRets.length * 252;
      setS0(parseFloat(s0.toFixed(2)));
      setSigma(parseFloat(annVol.toFixed(4)));
      setMu(parseFloat(annMu.toFixed(4)));
      const res = await api.capmGbm({ S0: s0, mu: annMu, sigma: annVol, T, n_steps: 252, n_paths: nPaths, seed: 42 });
      setGbmResult(res);
    } catch (e: any) { setGbmError(e.message); }
    finally { setGbmLoading(false); }
  };

  const runGbm = async () => {
    setGbmLoading(true); setGbmError('');
    try {
      const res = await api.capmGbm({ S0, mu, sigma, T, n_steps: 252, n_paths: nPaths, seed: 42 });
      setGbmResult(res);
    } catch (e: any) { setGbmError(e.message); }
    finally { setGbmLoading(false); }
  };

  // ── CAPM handlers ────────────────────────────────────────────────────────

  const runCAPM = async () => {
    setCapmLoading(true); setCapmError('');
    try {
      const [assetHist, mktHist]: any[] = await Promise.all([
        api.history(assetTicker, 252, capmProvider),
        api.history('SPY', 252, capmProvider),
      ]);
      const assetCloses: number[] = (assetHist?.close || []).map(Number);
      const mktCloses: number[] = (mktHist?.close || []).map(Number);
      const n = Math.min(assetCloses.length, mktCloses.length) - 1;
      if (n < 30) throw new Error('Not enough data for CAPM regression');
      const assetRets = assetCloses.slice(-n - 1).slice(1).map((p, i) => Math.log(p / assetCloses[assetCloses.length - n - 1 + i]));
      const mktRets = mktCloses.slice(-n - 1).slice(1).map((p, i) => Math.log(p / mktCloses[mktCloses.length - n - 1 + i]));
      const res = await api.capmBeta({
        asset_returns: assetRets,
        market_returns: mktRets,
        risk_free_rate: rfRate,
        market_premium: mktPremium,
      });
      setCapmResult({ ...(res as any), ticker: assetTicker });
    } catch (e: any) { setCapmError(e.message); }
    finally { setCapmLoading(false); }
  };

  // ── Kelly handler ────────────────────────────────────────────────────────

  const computeKelly = async () => {
    try {
      const res = await api.capmKelly({ win_rate: winRate, payout_ratio: payoutRatio, fraction: kellyFraction });
      setKellyResult(res);
    } catch (e: any) { console.error(e); }
  };

  // ── Portfolio risk handler ───────────────────────────────────────────────

  const loadPortfolioRisk = async () => {
    setRiskLoading(true); setRiskError('');
    try {
      const symbols = portfolioTickers.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean);
      const histories: any[] = await Promise.all(symbols.map((s) => api.history(s, 252, riskProvider).catch(() => null)));
      const validIdx = histories.map((h, i) => (h?.close?.length > 30 ? i : -1)).filter((i) => i >= 0);
      if (validIdx.length < 2) throw new Error('Need at least 2 valid tickers');

      const validSymbols = validIdx.map((i) => symbols[i]);
      const series = validIdx.map((i) => (histories[i]?.close || []).map(Number));
      const minLen = Math.min(...series.map((s) => s.length));
      const aligned = series.map((s) => s.slice(-minLen));
      // [n_days × n_assets] return matrix
      const retMatrix = Array.from({ length: minLen - 1 }, (_, t) =>
        aligned.map((prices) => Math.log(prices[t + 1] / prices[t]))
      );

      const corr = computeCorrelation(retMatrix);
      setCorrMatrix(corr);
      setCorrLabels(validSymbols);

      // Use first asset returns for VaR
      const firstRets = retMatrix.map((row) => row[0]);
      setVarReturns(firstRets);
      const sorted = [...firstRets].sort((a, b) => a - b);
      setVarThreshold(sorted[Math.floor(sorted.length * 0.05)]);
      setVarSource(histories[validIdx[0]]?.source || riskProvider);
    } catch (e: any) { setRiskError(e.message); }
    finally { setRiskLoading(false); }
  };

  return (
    <Box>
      <Typography variant="h4" sx={{ mb: 0.5 }}>Quant Terminal</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        GBM Simulation · CAPM · Kelly Criterion · Correlation · VaR Distribution
      </Typography>

      {/* ── SECTION 1: GBM Simulator ───────────────────────────────────── */}
      <Typography variant="h6" sx={{ mb: 1.5, color: 'primary.main', letterSpacing: '0.05em', textTransform: 'uppercase', fontSize: '0.8rem' }}>
        01 · Geometric Brownian Motion Simulator
      </Typography>
      <Grid container spacing={2.5} sx={{ mb: 4 }}>
        <Grid size={{ xs: 12, md: 3 }}>
          <Card>
            <CardContent>
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                <MarketTickerAutocomplete label="Load from Ticker" value={gbmTicker}
                  onChange={(v) => setGbmTicker(v || gbmTicker)}
                  helperText="Prefills S₀, σ and μ from live data" />
                <ProviderChips value={gbmProvider} onChange={setGbmProvider} />
                <Button variant="outlined" size="small" onClick={loadGbmFromMarket} disabled={gbmLoading} fullWidth>
                  Load & Simulate
                </Button>
                <Divider />
                <TextField label="S₀ (initial price)" type="number" size="small" value={S0}
                  onChange={(e) => setS0(+e.target.value)} fullWidth />
                <Box>
                  <Typography variant="body2" gutterBottom>Annual drift μ: <strong>{(mu * 100).toFixed(1)}%</strong></Typography>
                  <Slider value={mu} onChange={(_, v) => setMu(v as number)} min={-0.3} max={0.5} step={0.01} />
                </Box>
                <Box>
                  <Typography variant="body2" gutterBottom>Annual vol σ: <strong>{(sigma * 100).toFixed(1)}%</strong></Typography>
                  <Slider value={sigma} onChange={(_, v) => setSigma(v as number)} min={0.05} max={1.0} step={0.01} />
                </Box>
                <Box>
                  <Typography variant="body2" gutterBottom>Time horizon T: <strong>{T}y</strong></Typography>
                  <Slider value={T} onChange={(_, v) => setT(v as number)} min={0.25} max={5} step={0.25}
                    marks={[{ value: 1, label: '1y' }, { value: 3, label: '3y' }, { value: 5, label: '5y' }]} />
                </Box>
                <Box>
                  <Typography variant="body2" gutterBottom>Paths: <strong>{nPaths}</strong></Typography>
                  <Slider value={nPaths} onChange={(_, v) => setNPaths(v as number)} min={10} max={1000} step={10} />
                </Box>
                <Button variant="contained" onClick={runGbm} disabled={gbmLoading} fullWidth>
                  {gbmLoading ? <CircularProgress size={20} /> : 'Simulate GBM'}
                </Button>
              </Box>
            </CardContent>
          </Card>
        </Grid>

        <Grid size={{ xs: 12, md: 9 }}>
          {gbmError && <Alert severity="error" sx={{ mb: 2 }}>{gbmError}</Alert>}
          <Card sx={{ height: '100%', minHeight: 420 }}>
            <CardContent>
              {gbmResult ? (
                <>
                  <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mb: 2 }}>
                    {[
                      ['S₀', `$${gbmResult.S0}`],
                      ['μ', `${(gbmResult.mu * 100).toFixed(1)}%`],
                      ['σ', `${(gbmResult.sigma * 100).toFixed(1)}%`],
                      ['T', `${gbmResult.T}y`],
                      ['Paths', gbmResult.n_paths],
                      ['E[S(T)]', `$${gbmResult.terminal?.mean?.toFixed(2)}`],
                      ['P(S>S₀)', `${(gbmResult.terminal?.prob_above_S0 * 100).toFixed(1)}%`],
                    ].map(([k, v]) => (
                      <Chip key={String(k)} label={`${k}: ${v}`} size="small" variant="outlined"
                        sx={{ fontFamily: 'monospace', fontSize: '0.75rem' }} />
                    ))}
                  </Box>
                  <GBMChart data={gbmResult} height={340} />
                </>
              ) : (
                <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 380 }}>
                  <Typography color="text.secondary">
                    Load a ticker or set parameters and click <strong>Simulate GBM</strong>
                  </Typography>
                </Box>
              )}
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {/* ── SECTION 2: CAPM ────────────────────────────────────────────── */}
      <Typography variant="h6" sx={{ mb: 1.5, color: 'primary.main', letterSpacing: '0.05em', textTransform: 'uppercase', fontSize: '0.8rem' }}>
        02 · CAPM — Beta, Alpha &amp; Expected Return
      </Typography>
      <Grid container spacing={2.5} sx={{ mb: 4 }}>
        <Grid size={{ xs: 12, md: 3 }}>
          <Card>
            <CardContent>
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                <MarketTickerAutocomplete label="Asset Ticker" value={assetTicker}
                  onChange={(v) => setAssetTicker(v || assetTicker)}
                  helperText="Regressed against SPY (market)" />
                <ProviderChips value={capmProvider} onChange={setCapmProvider} />
                <TextField label="Risk-free Rate rf" type="number" size="small" value={rfRate}
                  onChange={(e) => setRfRate(+e.target.value)}
                  slotProps={{ htmlInput: { step: 0.005, min: 0, max: 0.2 } }} fullWidth />
                <TextField label="Market Premium E[Rm]−rf" type="number" size="small" value={mktPremium}
                  onChange={(e) => setMktPremium(+e.target.value)}
                  slotProps={{ htmlInput: { step: 0.005, min: 0, max: 0.2 } }} fullWidth />
                <Button variant="contained" onClick={runCAPM} disabled={capmLoading} fullWidth>
                  {capmLoading ? <CircularProgress size={20} /> : 'Run CAPM'}
                </Button>
              </Box>
            </CardContent>
          </Card>
        </Grid>

        <Grid size={{ xs: 12, md: 9 }}>
          {capmError && <Alert severity="error" sx={{ mb: 2 }}>{capmError}</Alert>}
          {capmResult ? (
            <Grid container spacing={2}>
              <Grid size={{ xs: 12, sm: 6 }}>
                <Card>
                  <CardContent>
                    <Typography variant="h6" gutterBottom>
                      {capmResult.ticker} vs SPY
                    </Typography>
                    <Table size="small">
                      <TableBody>
                        {[
                          ['Beta (β)', capmResult.beta?.toFixed(4), capmResult.beta > 1 ? 'More volatile than market' : 'Less volatile than market'],
                          ['Alpha (α/day)', capmResult.alpha_daily?.toFixed(6), ''],
                          ['Alpha (α/year)', `${(capmResult.alpha_annual * 100).toFixed(2)}%`, capmResult.alpha_annual > 0 ? 'Outperforms' : 'Underperforms'],
                          ['R²', capmResult.r_squared?.toFixed(4), `${(capmResult.r_squared * 100).toFixed(1)}% variance explained`],
                          ['p-value', capmResult.p_value?.toFixed(4), capmResult.p_value < 0.05 ? 'Statistically significant' : 'Not significant'],
                          ['Observations', capmResult.n_observations, '252-day window'],
                        ].map(([k, v, note]) => (
                          <TableRow key={String(k)}>
                            <TableCell sx={{ fontWeight: 600, color: 'text.secondary', fontSize: '0.8rem' }}>{k}</TableCell>
                            <TableCell sx={{ fontFamily: 'monospace', fontWeight: 700 }}>{v}</TableCell>
                            <TableCell sx={{ color: 'text.secondary', fontSize: '0.75rem' }}>{note}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </CardContent>
                </Card>
              </Grid>
              <Grid size={{ xs: 12, sm: 6 }}>
                <Card>
                  <CardContent>
                    <Typography variant="h6" gutterBottom>CAPM Expected Return</Typography>
                    <Box sx={{ textAlign: 'center', py: 2 }}>
                      <Typography variant="h3" sx={{ fontWeight: 700, color: 'primary.main', fontFamily: 'monospace' }}>
                        {(capmResult.capm?.expected_return_annual * 100).toFixed(2)}%
                      </Typography>
                      <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                        E[R] = rf + β × Market Premium
                      </Typography>
                      <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace', mt: 0.5, display: 'block' }}>
                        {capmResult.capm?.formula}
                      </Typography>
                    </Box>
                    <Divider sx={{ my: 1 }} />
                    <Box sx={{ display: 'flex', justifyContent: 'space-around', mt: 1 }}>
                      <Box sx={{ textAlign: 'center' }}>
                        <Typography variant="caption" color="text.secondary">Risk-free</Typography>
                        <Typography variant="body1" sx={{ fontFamily: 'monospace', fontWeight: 700 }}>
                          {(capmResult.capm?.risk_free_rate * 100).toFixed(1)}%
                        </Typography>
                      </Box>
                      <Box sx={{ textAlign: 'center' }}>
                        <Typography variant="caption" color="text.secondary">Mkt Premium</Typography>
                        <Typography variant="body1" sx={{ fontFamily: 'monospace', fontWeight: 700 }}>
                          {(capmResult.capm?.market_premium * 100).toFixed(1)}%
                        </Typography>
                      </Box>
                      <Box sx={{ textAlign: 'center' }}>
                        <Typography variant="caption" color="text.secondary">Beta × Premium</Typography>
                        <Typography variant="body1" sx={{ fontFamily: 'monospace', fontWeight: 700 }}>
                          {((capmResult.beta * capmResult.capm?.market_premium) * 100).toFixed(2)}%
                        </Typography>
                      </Box>
                    </Box>
                  </CardContent>
                </Card>
              </Grid>
            </Grid>
          ) : (
            <Card sx={{ height: 200, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Typography color="text.secondary">Select a ticker and click <strong>Run CAPM</strong> to regress against SPY</Typography>
            </Card>
          )}
        </Grid>
      </Grid>

      {/* ── SECTION 3: Kelly Criterion ─────────────────────────────────── */}
      <Typography variant="h6" sx={{ mb: 1.5, color: 'primary.main', letterSpacing: '0.05em', textTransform: 'uppercase', fontSize: '0.8rem' }}>
        03 · Kelly Criterion — Position Sizing
      </Typography>
      <Card sx={{ mb: 4 }}>
        <CardContent>
          <Grid container spacing={3} alignItems="center">
            <Grid size={{ xs: 12, md: 3 }}>
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                <Box>
                  <Typography variant="body2" gutterBottom>
                    Win rate p: <strong>{(winRate * 100).toFixed(0)}%</strong>
                  </Typography>
                  <Slider value={winRate} onChange={(_, v) => setWinRate(v as number)} min={0.1} max={0.9} step={0.01}
                    marks={[{ value: 0.5, label: '50%' }, { value: 0.7, label: '70%' }]} />
                </Box>
                <Box>
                  <Typography variant="body2" gutterBottom>
                    Payout b: <strong>{payoutRatio.toFixed(2)}×</strong>
                  </Typography>
                  <Slider value={payoutRatio} onChange={(_, v) => setPayoutRatio(v as number)} min={0.5} max={10} step={0.1}
                    marks={[{ value: 1, label: '1×' }, { value: 5, label: '5×' }]} />
                </Box>
                <Box>
                  <Typography variant="body2" gutterBottom>
                    Fractional Kelly: <strong>{(kellyFraction * 100).toFixed(0)}%</strong>
                  </Typography>
                  <Slider value={kellyFraction} onChange={(_, v) => setKellyFraction(v as number)} min={0.1} max={1} step={0.1}
                    marks={[{ value: 0.25, label: '¼' }, { value: 0.5, label: '½' }, { value: 1, label: 'Full' }]} />
                </Box>
                <Button variant="contained" onClick={computeKelly} fullWidth>Calculate Kelly</Button>
              </Box>
            </Grid>

            <Grid size={{ xs: 12, md: 9 }}>
              {kellyResult ? (
                <Box>
                  <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap', mb: 2 }}>
                    <Chip
                      label={`Full Kelly: ${(kellyResult.kelly_full * 100).toFixed(1)}%`}
                      color={kellyResult.kelly_full > 0 ? 'primary' : 'error'} sx={{ fontSize: '1rem', px: 1, py: 2.5 }} />
                    <Chip
                      label={`Fractional Kelly: ${kellyResult.recommended_position_pct?.toFixed(1)}%`}
                      color={kellyResult.kelly_fraction > 0 ? 'success' : 'error'} sx={{ fontSize: '1rem', px: 1, py: 2.5 }} />
                    <Chip
                      label={`Edge: ${(kellyResult.edge * 100).toFixed(2)}%`}
                      variant="outlined" sx={{ fontSize: '1rem', px: 1, py: 2.5 }} />
                  </Box>
                  <Alert severity={kellyResult.edge > 0 ? 'success' : 'error'} sx={{ mb: 2 }}>
                    <strong>{kellyResult.interpretation}</strong>
                  </Alert>
                  <Table size="small">
                    <TableBody>
                      {[
                        ['Formula', 'f* = (b·p − q) / b'],
                        ['Win rate p', `${(kellyResult.win_rate * 100).toFixed(0)}%`],
                        ['Loss rate q', `${((1 - kellyResult.win_rate) * 100).toFixed(0)}%`],
                        ['Payout ratio b', `${kellyResult.payout_ratio}×`],
                        ['Expected value (edge)', `${(kellyResult.edge * 100).toFixed(2)}% per bet`],
                        ['Full Kelly f*', `${(kellyResult.kelly_full * 100).toFixed(2)}% of capital`],
                        ['Fractional Kelly', `${kellyResult.recommended_position_pct?.toFixed(2)}% of capital`],
                      ].map(([k, v]) => (
                        <TableRow key={String(k)}>
                          <TableCell sx={{ color: 'text.secondary', fontWeight: 600, width: 200 }}>{k}</TableCell>
                          <TableCell sx={{ fontFamily: 'monospace' }}>{v}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </Box>
              ) : (
                <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 160 }}>
                  <Typography color="text.secondary">Set parameters and click <strong>Calculate Kelly</strong></Typography>
                </Box>
              )}
            </Grid>
          </Grid>
        </CardContent>
      </Card>

      {/* ── SECTION 4: Correlation + VaR ───────────────────────────────── */}
      <Typography variant="h6" sx={{ mb: 1.5, color: 'primary.main', letterSpacing: '0.05em', textTransform: 'uppercase', fontSize: '0.8rem' }}>
        04 · Portfolio Risk — Correlation &amp; VaR Distribution
      </Typography>
      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Grid container spacing={2} alignItems="flex-end" sx={{ mb: 2 }}>
            <Grid size={{ xs: 12, sm: 6 }}>
              <TextField
                label="Tickers (comma-separated)"
                value={portfolioTickers}
                onChange={(e) => setPortfolioTickers(e.target.value)}
                fullWidth size="small"
                helperText="e.g. AAPL,MSFT,GOOGL,AMZN,SPY"
              />
            </Grid>
            <Grid size={{ xs: 12, sm: 4 }}>
              <ProviderChips value={riskProvider} onChange={setRiskProvider} />
            </Grid>
            <Grid size={{ xs: 12, sm: 2 }}>
              <Button variant="contained" onClick={loadPortfolioRisk} disabled={riskLoading} fullWidth>
                {riskLoading ? <CircularProgress size={20} /> : 'Load'}
              </Button>
            </Grid>
          </Grid>
          {riskError && <Alert severity="error" sx={{ mb: 2 }}>{riskError}</Alert>}
          {corrLabels.length > 0 && (
            <Chip size="small" color="info" label={`Source: ${varSource} · ${corrLabels.length} assets`} sx={{ mb: 2 }} />
          )}
        </CardContent>
      </Card>

      <Grid container spacing={2.5}>
        <Grid size={{ xs: 12, md: 7 }}>
          <Card>
            <CardContent>
              <Typography variant="h6" gutterBottom>Correlation Heatmap</Typography>
              {corrMatrix ? (
                <CorrelationHeatmap matrix={corrMatrix} labels={corrLabels} />
              ) : (
                <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 200 }}>
                  <Typography color="text.secondary">Load portfolio to compute correlation matrix</Typography>
                </Box>
              )}
            </CardContent>
          </Card>
        </Grid>

        <Grid size={{ xs: 12, md: 5 }}>
          <Card>
            <CardContent>
              <Typography variant="h6" gutterBottom>VaR Loss Distribution</Typography>
              <VaRDistributionChart
                returns={varReturns}
                varThreshold={varThreshold}
                confidence={0.95}
              />
              <Box sx={{ mt: 1, display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                <Chip size="small" label={`VaR(95%): ${(varThreshold * 100).toFixed(2)}%`} color="error" variant="outlined" />
                <Chip size="small" label={`${varReturns.length} observations`} variant="outlined" />
                <Chip size="small" label={corrLabels[0] || 'synthetic'} variant="outlined" />
              </Box>
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </Box>
  );
}
