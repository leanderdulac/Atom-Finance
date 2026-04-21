import React, { useState } from 'react';
import {
  Box, Grid, Card, CardContent, Typography, TextField, Button,
  Select, MenuItem, FormControl, InputLabel, Table, TableBody,
  TableCell, TableContainer, TableHead, TableRow, Paper,
  CircularProgress, Alert, Chip, Tabs, Tab,
} from '@mui/material';
import { api } from '../services/api';
import QuantContextSection from '../components/QuantContextSection';
import MarketTickerAutocomplete from '../components/MarketTickerAutocomplete';
import ProviderChips from '../components/ProviderChips';

const riskConcepts = [
  {
    title: 'Tail risk and EVT',
    text: 'Classical Gaussian assumptions miss fat tails. VaR, CVaR and stress analysis become more credible when the development mindset is informed by extreme-value thinking.',
  },
  {
    title: 'Dependence under stress',
    text: 'Portfolio losses rarely behave independently in crises. Copula-style reasoning and scenario design help explain why diversification can fail exactly when it is most needed.',
  },
  {
    title: 'Volatility regimes',
    text: 'GARCH and stochastic-volatility logic translate market clustering into forecastable persistence, regime shifts and more realistic risk scaling through time.',
  },
];

const riskDevelopmentNotes = [
  'VaR summarizes threshold loss, while CVaR captures what happens after the threshold is breached.',
  'Stress testing is not a substitute for distributional modeling; it complements it with narrative scenario design.',
  'Monte Carlo, EVT and regime models are strongest when used together rather than as isolated diagnostics.',
];

function generateReturns(n: number = 500): number[] {
  const returns: number[] = [];
  let seed = 42;
  for (let i = 0; i < n; i++) {
    seed = (seed * 16807) % 2147483647;
    const u = seed / 2147483647;
    seed = (seed * 16807) % 2147483647;
    const v = seed / 2147483647;
    const z = Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
    returns.push(0.0003 + 0.015 * z);
  }
  // Add fat tails
  returns[100] = -0.08;
  returns[250] = -0.06;
  returns[400] = 0.07;
  return returns;
}

export default function RiskPage() {
  const [tab, setTab] = useState(0);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState('');

  const [ticker, setTicker] = useState('SPY');
  const [provider, setProvider] = useState('openbb');
  const [liveReturns, setLiveReturns] = useState<number[] | null>(null);
  const [dataSource, setDataSource] = useState('');

  const [varParams, setVarParams] = useState({
    confidence: 0.95,
    portfolio_value: 1000000,
    holding_period: 1,
    method: 'historical',
  });

  const [stressParams, setStressParams] = useState({
    equity: 0.6,
    bonds: 0.3,
    gold: 0.1,
  });

  const [garchHorizon, setGarchHorizon] = useState(30);

  const loadMarketReturns = async () => {
    setLoading(true); setError('');
    try {
      const history: any = await api.history(ticker, 252, provider);
      const closes = (history?.close || []).map(Number);
      if (closes.length < 31) throw new Error('Not enough data returned');
      const rets = closes.slice(1).map((p: number, i: number) => Math.log(p / closes[i]));
      setLiveReturns(rets);
      setDataSource(history.provider || history.source || provider);
    } catch (e: any) { setError(e.message); }
    finally { setLoading(false); }
  };

  const runVaR = async () => {
    setLoading(true); setError('');
    try {
      const returns = liveReturns || generateReturns();
      const res = await api.varAll({ returns, ...varParams });
      setResult({ type: 'var', data: res });
    } catch (e: any) { setError(e.message); }
    finally { setLoading(false); }
  };

  const runStress = async () => {
    setLoading(true); setError('');
    try {
      const res = await api.stressTest({ portfolio: stressParams, portfolio_value: varParams.portfolio_value });
      setResult({ type: 'stress', data: res });
    } catch (e: any) { setError(e.message); }
    finally { setLoading(false); }
  };

  const runGarch = async () => {
    setLoading(true); setError('');
    try {
      const returns = liveReturns || generateReturns();
      const res = await api.garch({ returns, forecast_horizon: garchHorizon });
      setResult({ type: 'garch', data: res });
    } catch (e: any) { setError(e.message); }
    finally { setLoading(false); }
  };

  return (
    <Box>
      <Typography variant="h4" sx={{ mb: 0.5 }}>Risk Analysis</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        VaR, CVaR, Stress Testing, GARCH Volatility, Heston Model
      </Typography>

      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        <Tab label="Value at Risk" />
        <Tab label="Stress Testing" />
        <Tab label="GARCH Volatility" />
      </Tabs>

      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      {tab === 0 && (
        <Grid container spacing={2.5}>
          <Grid size={{ xs: 12, md: 4 }}>
            <Card>
              <CardContent>
                <Typography variant="h6" gutterBottom>VaR Parameters</Typography>
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  <MarketTickerAutocomplete label="Ticker" value={ticker} onChange={(v) => setTicker(v || ticker)} helperText="Load real historical returns" />
                  <ProviderChips value={provider} onChange={setProvider} />
                  <Button variant="outlined" onClick={loadMarketReturns} disabled={loading} fullWidth>
                    Load Market Returns
                  </Button>
                  {dataSource && <Chip size="small" color="info" label={`Data: ${dataSource} · ${liveReturns?.length || 0} obs`} />}
                  <TextField label="Confidence Level" type="number" value={varParams.confidence}
                    onChange={(e) => setVarParams(p => ({ ...p, confidence: +e.target.value }))}
                    slotProps={{ htmlInput: { step: 0.01, min: 0.9, max: 0.999 } }} fullWidth />
                  <TextField label="Portfolio Value ($)" type="number" value={varParams.portfolio_value}
                    onChange={(e) => setVarParams(p => ({ ...p, portfolio_value: +e.target.value }))} fullWidth />
                  <TextField label="Holding Period (days)" type="number" value={varParams.holding_period}
                    onChange={(e) => setVarParams(p => ({ ...p, holding_period: +e.target.value }))} fullWidth />
                  <Button variant="contained" onClick={runVaR} disabled={loading}>
                    {loading ? <CircularProgress size={20} /> : 'Calculate VaR (All Methods)'}
                  </Button>
                </Box>
              </CardContent>
            </Card>
          </Grid>
          <Grid size={{ xs: 12, md: 8 }}>
            {result?.type === 'var' && (
              <Card>
                <CardContent>
                  <Typography variant="h6" gutterBottom>Value at Risk Comparison</Typography>
                  <TableContainer component={Paper} variant="outlined">
                    <Table>
                      <TableHead>
                        <TableRow>
                          <TableCell sx={{ fontWeight: 700 }}>Method</TableCell>
                          <TableCell align="right" sx={{ fontWeight: 700 }}>VaR (%)</TableCell>
                          <TableCell align="right" sx={{ fontWeight: 700 }}>VaR ($)</TableCell>
                          <TableCell align="right" sx={{ fontWeight: 700 }}>CVaR (%)</TableCell>
                          <TableCell align="right" sx={{ fontWeight: 700 }}>CVaR ($)</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {['historical', 'parametric', 'monte_carlo'].map((method) => {
                          const d = result.data[method];
                          return (
                            <TableRow key={method}>
                              <TableCell sx={{ textTransform: 'capitalize' }}>{method.replace('_', ' ')}</TableCell>
                              <TableCell align="right" sx={{ fontFamily: 'monospace', color: 'error.main' }}>
                                {d?.var_percentage?.toFixed(4)}%
                              </TableCell>
                              <TableCell align="right" sx={{ fontFamily: 'monospace' }}>
                                ${d?.var_absolute?.toLocaleString()}
                              </TableCell>
                              <TableCell align="right" sx={{ fontFamily: 'monospace', color: 'error.main' }}>
                                {d?.cvar_percentage?.toFixed(4)}%
                              </TableCell>
                              <TableCell align="right" sx={{ fontFamily: 'monospace' }}>
                                ${d?.cvar_absolute?.toLocaleString()}
                              </TableCell>
                            </TableRow>
                          );
                        })}
                      </TableBody>
                    </Table>
                  </TableContainer>
                </CardContent>
              </Card>
            )}
          </Grid>
        </Grid>
      )}

      {tab === 1 && (
        <Grid container spacing={2.5}>
          <Grid size={{ xs: 12, md: 4 }}>
            <Card>
              <CardContent>
                <Typography variant="h6" gutterBottom>Portfolio Allocation</Typography>
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  <TextField label="Equity Weight" type="number" value={stressParams.equity}
                    onChange={(e) => setStressParams(p => ({ ...p, equity: +e.target.value }))}
                    slotProps={{ htmlInput: { step: 0.05, min: 0, max: 1 } }} fullWidth />
                  <TextField label="Bonds Weight" type="number" value={stressParams.bonds}
                    onChange={(e) => setStressParams(p => ({ ...p, bonds: +e.target.value }))}
                    slotProps={{ htmlInput: { step: 0.05, min: 0, max: 1 } }} fullWidth />
                  <TextField label="Gold Weight" type="number" value={stressParams.gold}
                    onChange={(e) => setStressParams(p => ({ ...p, gold: +e.target.value }))}
                    slotProps={{ htmlInput: { step: 0.05, min: 0, max: 1 } }} fullWidth />
                  <Button variant="contained" onClick={runStress} disabled={loading}>
                    Run All Stress Scenarios
                  </Button>
                </Box>
              </CardContent>
            </Card>
          </Grid>
          <Grid size={{ xs: 12, md: 8 }}>
            {result?.type === 'stress' && result.data.scenarios && (
              <Card>
                <CardContent>
                  <Typography variant="h6" gutterBottom>Stress Test Results</Typography>
                  <TableContainer component={Paper} variant="outlined">
                    <Table>
                      <TableHead>
                        <TableRow>
                          <TableCell sx={{ fontWeight: 700 }}>Scenario</TableCell>
                          <TableCell align="right" sx={{ fontWeight: 700 }}>Impact (%)</TableCell>
                          <TableCell align="right" sx={{ fontWeight: 700 }}>Impact ($)</TableCell>
                          <TableCell align="right" sx={{ fontWeight: 700 }}>Portfolio After</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {Object.entries(result.data.scenarios).map(([name, scenario]: [string, any]) => (
                          <TableRow key={name}>
                            <TableCell sx={{ textTransform: 'capitalize' }}>{name.replace(/_/g, ' ')}</TableCell>
                            <TableCell align="right" sx={{
                              fontFamily: 'monospace',
                              color: scenario.total_impact_pct < 0 ? 'error.main' : 'success.main',
                            }}>
                              {scenario.total_impact_pct?.toFixed(2)}%
                            </TableCell>
                            <TableCell align="right" sx={{ fontFamily: 'monospace' }}>
                              ${scenario.total_impact_abs?.toLocaleString()}
                            </TableCell>
                            <TableCell align="right" sx={{ fontFamily: 'monospace' }}>
                              ${scenario.portfolio_after?.toLocaleString()}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </TableContainer>
                </CardContent>
              </Card>
            )}
          </Grid>
        </Grid>
      )}

      {tab === 2 && (
        <Grid container spacing={2.5}>
          <Grid size={{ xs: 12, md: 4 }}>
            <Card>
              <CardContent>
                <Typography variant="h6" gutterBottom>GARCH(1,1) Model</Typography>
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  <TextField label="Forecast Horizon (days)" type="number" value={garchHorizon}
                    onChange={(e) => setGarchHorizon(+e.target.value)} fullWidth />
                  <Button variant="contained" onClick={runGarch} disabled={loading}>
                    Fit GARCH & Forecast
                  </Button>
                </Box>
              </CardContent>
            </Card>
          </Grid>
          <Grid size={{ xs: 12, md: 8 }}>
            {result?.type === 'garch' && (
              <Card>
                <CardContent>
                  <Typography variant="h6" gutterBottom>GARCH(1,1) Results</Typography>
                  <Grid container spacing={2}>
                    {['omega', 'alpha', 'beta', 'persistence'].map((param) => (
                      <Grid size={{ xs: 6, sm: 3 }} key={param}>
                        <Box sx={{ textAlign: 'center', p: 1, border: 1, borderColor: 'divider', borderRadius: 2 }}>
                          <Typography variant="caption" color="text.secondary" sx={{ textTransform: 'capitalize' }}>
                            {param}
                          </Typography>
                          <Typography variant="h6" sx={{ fontFamily: 'monospace' }}>
                            {result.data.fit?.[param]?.toFixed(6)}
                          </Typography>
                        </Box>
                      </Grid>
                    ))}
                  </Grid>
                  {result.data.fit?.long_run_volatility && (
                    <Alert severity="info" sx={{ mt: 2 }}>
                      Long-run annualized volatility: <strong>{(result.data.fit.long_run_volatility * 100).toFixed(2)}%</strong>
                    </Alert>
                  )}
                </CardContent>
              </Card>
            )}
          </Grid>
        </Grid>
      )}

      <QuantContextSection
        conceptsTitle="Quant risk foundations"
        concepts={riskConcepts}
        notes={riskDevelopmentNotes}
      />
    </Box>
  );
}
