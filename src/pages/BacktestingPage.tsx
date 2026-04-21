import React, { useState } from 'react';
import {
  Box, Grid, Card, CardContent, Typography, TextField, Button,
  ToggleButtonGroup, ToggleButton, CircularProgress, Alert,
  Table, TableBody, TableCell, TableRow, Chip,
} from '@mui/material';
import { api } from '../services/api';
import MarketTickerAutocomplete from '../components/MarketTickerAutocomplete';
import ProviderChips from '../components/ProviderChips';
import QuantContextSection from '../components/QuantContextSection';

const backtestingFoundations = [
  {
    title: 'Historical simulation',
    text: 'Backtesting approximates how a rule-based strategy would have behaved under realized price paths, making path dependency and execution assumptions explicit.',
  },
  {
    title: 'Performance decomposition',
    text: 'Sharpe, drawdown, win rate and final value are not interchangeable. Each metric captures a different dimension of edge, fragility and capital efficiency.',
  },
  {
    title: 'Research discipline',
    text: 'A backtest is evidence, not proof. Regime shifts, transaction costs and overfitting risk mean validation must be iterative and skeptical.',
  },
];

const backtestingNotes = [
  'Historical data quality and realistic trading frictions often dominate the headline result.',
  'Monte Carlo and stress testing should complement backtests to expose path dependence beyond the realized sample.',
  'The strongest workflow links signal design, strategy replay and risk diagnostics in one loop.',
];

function generatePrices(n: number = 500): number[] {
  const prices: number[] = [100];
  let seed = 42;
  for (let i = 1; i < n; i++) {
    seed = (seed * 16807) % 2147483647;
    const u = seed / 2147483647;
    seed = (seed * 16807) % 2147483647;
    const v = seed / 2147483647;
    const z = Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
    prices.push(prices[i - 1] * Math.exp(0.0003 + 0.015 * z));
  }
  return prices;
}

export default function BacktestingPage() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState('');
  const [strategy, setStrategy] = useState('sma_crossover');
  const [capital, setCapital] = useState(100000);
  const [commission, setCommission] = useState(0.001);
  const [ticker, setTicker] = useState('SPY');
  const [provider, setProvider] = useState('openbb');
  const [historyDays, setHistoryDays] = useState(252);
  const [priceData, setPriceData] = useState<{ prices: number[]; source: string } | null>(null);

  const prices = generatePrices();

  const loadMarketPrices = async () => {
    setLoading(true); setError('');
    try {
      const history: any = await api.history(ticker, historyDays, provider);
      const livePrices = (history?.close || []).map((v: number) => Number(v));
      if (livePrices.length < 30) throw new Error('Not enough historical data returned');
      setPriceData({ prices: livePrices, source: history.provider || history.source || provider });
    } catch (e: any) {
      setError(e.message);
    } finally { setLoading(false); }
  };

  const runBacktest = async () => {
    setLoading(true); setError('');
    try {
      const res = await api.backtest({
        prices: priceData?.prices || prices,
        strategy,
        initial_capital: capital,
        commission,
      });
      setResult(res);
    } catch (e: any) { setError(e.message); }
    finally { setLoading(false); }
  };

  return (
    <Box>
      <Typography variant="h4" sx={{ mb: 0.5 }}>Backtesting</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Test trading strategies with historical simulation
      </Typography>

      <Grid container spacing={2.5}>
        <Grid size={{ xs: 12, md: 4 }}>
          <Card>
            <CardContent>
              <Typography variant="h6" gutterBottom>Strategy</Typography>
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                <MarketTickerAutocomplete
                  label="Ticker"
                  value={ticker}
                  onChange={(next) => setTicker(next || ticker)}
                  helperText="Search an asset and backtest on live historical closes"
                />
                <ProviderChips value={provider} onChange={setProvider} />
                <TextField label="Lookback Days" type="number" value={historyDays}
                  onChange={(e) => setHistoryDays(+e.target.value)} fullWidth />
                <ToggleButtonGroup
                  fullWidth exclusive value={strategy}
                  onChange={(_, v) => v && setStrategy(v)}
                  orientation="vertical"
                >
                  <ToggleButton value="sma_crossover">SMA Crossover</ToggleButton>
                  <ToggleButton value="mean_reversion">Mean Reversion</ToggleButton>
                  <ToggleButton value="momentum">Momentum</ToggleButton>
                  <ToggleButton value="rsi">RSI Strategy</ToggleButton>
                </ToggleButtonGroup>

                <TextField label="Initial Capital ($)" type="number" value={capital}
                  onChange={(e) => setCapital(+e.target.value)} fullWidth />
                <TextField label="Commission Rate" type="number" value={commission}
                  onChange={(e) => setCommission(+e.target.value)}
                  inputProps={{ step: 0.0005, min: 0 }} fullWidth />

                <Button variant="outlined" onClick={loadMarketPrices} disabled={loading} fullWidth>
                  Load Market Prices
                </Button>
                {priceData?.source && <Chip size="small" color="info" label={`Data: ${priceData.source}`} />}

                <Button variant="contained" onClick={runBacktest} disabled={loading} fullWidth>
                  {loading ? <CircularProgress size={20} /> : 'Run Backtest'}
                </Button>
              </Box>
            </CardContent>
          </Card>
        </Grid>

        <Grid size={{ xs: 12, md: 8 }}>
          {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

          {result?.performance && (
            <>
              <Card sx={{ mb: 2 }}>
                <CardContent>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                    <Typography variant="h6">Performance Metrics</Typography>
                    <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                      <Chip
                        label={`${result.strategy?.replace('_', ' ')?.toUpperCase()}`}
                        color="primary"
                        sx={{ fontWeight: 700 }}
                      />
                      {priceData?.source && <Chip label={priceData.source} color="info" variant="outlined" />}
                    </Box>
                  </Box>

                  <Grid container spacing={2}>
                    {Object.entries(result.performance).map(([key, val]: [string, any]) => (
                      <Grid size={{ xs: 6, sm: 4, md: 3 }} key={key}>
                        <Box sx={{ textAlign: 'center', p: 1.5, border: 1, borderColor: 'divider', borderRadius: 2 }}>
                          <Typography variant="caption" color="text.secondary" sx={{ textTransform: 'capitalize', fontSize: '0.7rem' }}>
                            {key.replace(/_/g, ' ').replace(' pct', '')}
                          </Typography>
                          <Typography variant="body1" sx={{
                            fontFamily: '"JetBrains Mono", monospace',
                            fontWeight: 700,
                            color: key.includes('return') || key === 'alpha'
                              ? ((val as number) > 0 ? 'success.main' : 'error.main')
                              : key === 'max_drawdown_pct'
                              ? 'error.main'
                              : 'text.primary',
                          }}>
                            {typeof val === 'number'
                              ? key.includes('pct') || key.includes('rate')
                                ? `${(val as number).toFixed(2)}%`
                                : key === 'final_value'
                                ? `$${(val as number).toLocaleString()}`
                                : (val as number).toFixed(4)
                              : val}
                          </Typography>
                        </Box>
                      </Grid>
                    ))}
                  </Grid>
                </CardContent>
              </Card>

              {/* Recent Trades */}
              {result.trades && result.trades.length > 0 && (
                <Card>
                  <CardContent>
                    <Typography variant="h6" gutterBottom>
                      Recent Trades ({result.n_trades} total)
                    </Typography>
                    <Table size="small">
                      <TableBody>
                        {result.trades.slice(-10).map((trade: any, i: number) => (
                          <TableRow key={i}>
                            <TableCell>Day {trade.day}</TableCell>
                            <TableCell>
                              <Chip
                                size="small"
                                label={trade.type}
                                color={trade.type === 'BUY' ? 'success' : 'error'}
                                sx={{ fontWeight: 600 }}
                              />
                            </TableCell>
                            <TableCell sx={{ fontFamily: 'monospace' }}>${trade.price}</TableCell>
                            <TableCell sx={{ fontFamily: 'monospace' }}>{trade.shares} shares</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </CardContent>
                </Card>
              )}
            </>
          )}
        </Grid>
      </Grid>

      <QuantContextSection
        conceptsTitle="Backtesting context"
        concepts={backtestingFoundations}
        notes={backtestingNotes}
      />
    </Box>
  );
}
