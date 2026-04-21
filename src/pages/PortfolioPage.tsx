import React, { useState } from 'react';
import {
  Box, Grid, Card, CardContent, Typography, TextField, Button,
  CircularProgress, Alert, Table, TableBody, TableCell, TableRow,
  Chip, ToggleButtonGroup, ToggleButton,
} from '@mui/material';
import { api } from '../services/api';
import MarketTickerAutocomplete from '../components/MarketTickerAutocomplete';
import ProviderChips from '../components/ProviderChips';
import QuantContextSection from '../components/QuantContextSection';

const portfolioFoundations = [
  {
    title: 'Mean-variance optimization',
    text: 'Markowitz formalized portfolio construction as a trade-off between expected return and covariance-driven risk, making diversification a geometric optimization problem.',
  },
  {
    title: 'Efficient frontier and Sharpe',
    text: 'The efficient frontier maps feasible risk-return combinations, while the maximum Sharpe portfolio identifies the tangent allocation under a chosen risk-free rate.',
  },
  {
    title: 'Risk budgeting',
    text: 'Risk parity shifts the focus from capital weights to risk contribution, useful when concentration and hidden dependence matter more than nominal allocation.',
  },
];

const portfolioNotes = [
  'Covariance estimation quality often matters more than the optimizer itself.',
  'Live histories improve realism, but regime shifts and dependence breakdowns still require stress thinking.',
  'Modern portfolio construction is strongest when optimization, scenario analysis and tail-risk diagnostics are combined.',
];

function generateMultiAssetReturns(): { returns: number[][]; names: string[] } {
  const names = ['AAPL', 'GOOGL', 'MSFT', 'AMZN', 'TSLA'];
  const n = 252;
  const returns: number[][] = [];
  let seed = 123;

  for (let i = 0; i < n; i++) {
    const row: number[] = [];
    for (let j = 0; j < names.length; j++) {
      seed = (seed * 16807 + j * 1000) % 2147483647;
      const u = seed / 2147483647;
      seed = (seed * 16807) % 2147483647;
      const v = seed / 2147483647;
      const z = Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
      row.push(0.0004 * (j + 1) + 0.015 * z);
    }
    returns.push(row);
  }
  return { returns, names };
}

export default function PortfolioPage() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState('');
  const [method, setMethod] = useState('efficient-frontier');
  const [riskFreeRate, setRiskFreeRate] = useState(0.02);
  const [tickerList, setTickerList] = useState('AAPL,MSFT,GOOGL,AMZN,TSLA');
  const [provider, setProvider] = useState('openbb');
  const [marketState, setMarketState] = useState<any>(null);

  const { returns, names } = generateMultiAssetReturns();

  const loadMarketReturns = async () => {
    const symbols = tickerList.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean);
    if (symbols.length < 2) return null;

    const histories: any[] = await Promise.all(symbols.map((symbol) => api.history(symbol, 252, provider)));
    const series = histories.map((history: any) => (history?.close || []).map((v: number) => Number(v)));
    const cleanSeries = series.filter((s) => s.length > 10);
    const cleanSymbols = symbols.filter((_, idx) => series[idx].length > 10);

    if (cleanSeries.length < 2) return null;

    const minLen = Math.min(...cleanSeries.map((s) => s.length));
    const aligned = cleanSeries.map((s) => s.slice(-minLen));
    const assetReturns = Array.from({ length: minLen - 1 }, (_, i) =>
      aligned.map((prices) => prices[i + 1] / prices[i] - 1)
    );

    const firstHistory: any = histories[0] || {};
    const source = firstHistory.provider || firstHistory.source || provider;
    const state = { assetReturns, assetNames: cleanSymbols, source };
    setMarketState(state);
    return state;
  };

  const runOptimization = async () => {
    setLoading(true); setError('');
    try {
      const live = await loadMarketReturns().catch(() => null);
      const payload = {
        returns: live?.assetReturns || marketState?.assetReturns || returns,
        asset_names: live?.assetNames || marketState?.assetNames || names,
        risk_free_rate: riskFreeRate,
      };
      let res;
      switch (method) {
        case 'efficient-frontier':
          res = await api.efficientFrontier(payload);
          break;
        case 'max-sharpe':
          res = await api.maxSharpe(payload);
          break;
        case 'risk-parity':
          res = await api.riskParity(payload);
          break;
        default:
          res = await api.efficientFrontier(payload);
      }
      setResult(res);
    } catch (e: any) { setError(e.message); }
    finally { setLoading(false); }
  };

  return (
    <Box>
      <Typography variant="h4" sx={{ mb: 0.5 }}>Portfolio Optimization</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Markowitz, Risk Parity, Black-Litterman & Modern Portfolio Theory
      </Typography>

      <Grid container spacing={2.5}>
        <Grid size={{ xs: 12, md: 4 }}>
          <Card>
            <CardContent>
              <Typography variant="h6" gutterBottom>Optimization Method</Typography>
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                <MarketTickerAutocomplete
                  label="Portfolio Tickers"
                  multiple
                  values={tickerList.split(',').map((item) => item.trim()).filter(Boolean)}
                  onValuesChange={(next) => setTickerList(next.join(','))}
                  helperText="Search and select multiple assets for optimization"
                />
                <ProviderChips value={provider} onChange={setProvider} />
                <ToggleButtonGroup
                  fullWidth exclusive value={method}
                  onChange={(_, v) => v && setMethod(v)}
                  orientation="vertical"
                >
                  <ToggleButton value="efficient-frontier">Markowitz Efficient Frontier</ToggleButton>
                  <ToggleButton value="max-sharpe">Maximum Sharpe Ratio</ToggleButton>
                  <ToggleButton value="risk-parity">Risk Parity</ToggleButton>
                </ToggleButtonGroup>

                <TextField label="Risk-free Rate" type="number" value={riskFreeRate}
                  onChange={(e) => setRiskFreeRate(+e.target.value)} inputProps={{ step: 0.005 }} fullWidth />

                <TextField label="Tickers String" value={tickerList} fullWidth disabled />

                <Alert severity="info" sx={{ fontSize: '0.75rem' }}>
                  {marketState?.source
                    ? `Loaded live market history via ${marketState.source} for ${marketState.assetNames.join(', ')}`
                    : `If live data fails, synthetic data is used for: ${names.join(', ')}`}
                </Alert>

                <Button variant="outlined" onClick={loadMarketReturns} disabled={loading} fullWidth>
                  Load Market History
                </Button>

                <Button variant="contained" onClick={runOptimization} disabled={loading} fullWidth>
                  {loading ? <CircularProgress size={20} /> : 'Optimize Portfolio'}
                </Button>
              </Box>
            </CardContent>
          </Card>
        </Grid>

        <Grid size={{ xs: 12, md: 8 }}>
          {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

          {result && (
            <>
              {/* Optimal Portfolio Weights */}
              {(result.max_sharpe_portfolio || result.weights) && (
                <Card sx={{ mb: 2 }}>
                  <CardContent>
                    <Typography variant="h6" gutterBottom>
                      {method === 'efficient-frontier' ? 'Maximum Sharpe Portfolio' :
                       method === 'max-sharpe' ? 'Optimal Weights' : 'Risk Parity Weights'}
                    </Typography>
                    {marketState?.source && (
                      <Chip size="small" color="info" label={`Data: ${marketState.source}`} sx={{ mb: 2 }} />
                    )}
                    <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mb: 2 }}>
                      {Object.entries(
                        (result.max_sharpe_portfolio?.weights || result.weights || {})
                      ).map(([name, weight]) => (
                        <Chip
                          key={name}
                          label={`${name}: ${((weight as number) * 100).toFixed(1)}%`}
                          sx={{
                            bgcolor: (weight as number) > 0 ? 'primary.main' : 'error.main',
                            color: '#fff',
                            fontWeight: 600,
                          }}
                        />
                      ))}
                    </Box>
                    <Table size="small">
                      <TableBody>
                        <TableRow>
                          <TableCell sx={{ fontWeight: 600 }}>Expected Return</TableCell>
                          <TableCell align="right" sx={{ fontFamily: 'monospace' }}>
                            {(result.max_sharpe_portfolio?.expected_return || result.expected_return)?.toFixed(2)}%
                          </TableCell>
                        </TableRow>
                        <TableRow>
                          <TableCell sx={{ fontWeight: 600 }}>Volatility</TableCell>
                          <TableCell align="right" sx={{ fontFamily: 'monospace' }}>
                            {(result.max_sharpe_portfolio?.volatility || result.volatility)?.toFixed(2)}%
                          </TableCell>
                        </TableRow>
                        {(result.max_sharpe_portfolio?.sharpe_ratio || result.sharpe_ratio) && (
                          <TableRow>
                            <TableCell sx={{ fontWeight: 600 }}>Sharpe Ratio</TableCell>
                            <TableCell align="right" sx={{ fontFamily: 'monospace', color: 'primary.main', fontWeight: 700 }}>
                              {(result.max_sharpe_portfolio?.sharpe_ratio || result.sharpe_ratio)?.toFixed(4)}
                            </TableCell>
                          </TableRow>
                        )}
                      </TableBody>
                    </Table>
                  </CardContent>
                </Card>
              )}

              {/* Efficient Frontier Data */}
              {result.frontier && (
                <Card>
                  <CardContent>
                    <Typography variant="h6" gutterBottom>Efficient Frontier</Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                      {result.frontier.returns.length} portfolios computed along the frontier
                    </Typography>
                    <Box sx={{
                      display: 'grid',
                      gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))',
                      gap: 1,
                    }}>
                      {result.frontier.returns.slice(0, 10).map((ret: number, i: number) => (
                        <Box key={i} sx={{ p: 1, border: 1, borderColor: 'divider', borderRadius: 1, textAlign: 'center' }}>
                          <Typography variant="caption" color="text.secondary">Return</Typography>
                          <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>{ret.toFixed(2)}%</Typography>
                          <Typography variant="caption" color="text.secondary">Risk</Typography>
                          <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
                            {result.frontier.volatilities[i]?.toFixed(2)}%
                          </Typography>
                        </Box>
                      ))}
                    </Box>
                  </CardContent>
                </Card>
              )}
            </>
          )}
        </Grid>
      </Grid>

      <QuantContextSection
        conceptsTitle="Portfolio theory context"
        concepts={portfolioFoundations}
        notes={portfolioNotes}
      />
    </Box>
  );
}
