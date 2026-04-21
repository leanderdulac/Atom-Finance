import React, { useState } from 'react';
import {
  Box, Grid, Card, CardContent, Typography, TextField, Button,
  ToggleButtonGroup, ToggleButton, CircularProgress, Alert, Chip,
  Table, TableBody, TableCell, TableRow,
} from '@mui/material';
import { api } from '../services/api';
import MarketTickerAutocomplete from '../components/MarketTickerAutocomplete';
import ProviderChips from '../components/ProviderChips';
import QuantContextSection from '../components/QuantContextSection';

const mlFoundations = [
  {
    title: 'Sequence models',
    text: 'LSTMs model temporal dependence directly, making them useful when lag structure and non-linear state carry matter more than explicit parametric assumptions.',
  },
  {
    title: 'Ensemble and statistical models',
    text: 'Random forests and ARIMA sit on different sides of the modeling spectrum: one is flexible and non-linear, the other is structured and interpretable for time series.',
  },
  {
    title: 'Reinforcement learning',
    text: 'RL reframes prediction as sequential decision-making, where policies are judged by cumulative reward rather than one-step forecast accuracy alone.',
  },
];

const mlConvergenceNotes = [
  'Machine learning complements, rather than replaces, stochastic and econometric models.',
  'Feature extraction and non-linearity are strongest when paired with disciplined validation and market-state awareness.',
  'The longer-term roadmap is hybrid: AI for calibration, classical models for structure, and simulation for scenario robustness.',
];

function generatePrices(n: number = 252, base: number = 100): number[] {
  const prices: number[] = [base];
  let seed = 42;
  for (let i = 1; i < n; i++) {
    seed = (seed * 16807) % 2147483647;
    const u = seed / 2147483647;
    seed = (seed * 16807) % 2147483647;
    const v = seed / 2147483647;
    const z = Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
    const ret = 0.0003 + 0.015 * z;
    prices.push(prices[i - 1] * Math.exp(ret));
  }
  return prices;
}

export default function MLPage() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState('');
  const [model, setModel] = useState('lstm');
  const [forecastDays, setForecastDays] = useState(30);

  const [ticker, setTicker] = useState('AAPL');
  const [provider, setProvider] = useState('openbb');
  const [livePrices, setLivePrices] = useState<number[] | null>(null);
  const [dataSource, setDataSource] = useState('');

  const loadMarketPrices = async () => {
    setLoading(true); setError('');
    try {
      const history: any = await api.history(ticker, 252, provider);
      const closes = (history?.close || []).map(Number);
      if (closes.length < 60) throw new Error('Not enough data (need ≥ 60 closes)');
      setLivePrices(closes);
      setDataSource(history.provider || history.source || provider);
    } catch (e: any) { setError(e.message); }
    finally { setLoading(false); }
  };

  const runPrediction = async () => {
    setLoading(true); setError('');
    try {
      const prices = livePrices || generatePrices(300);
      const res = await api.predict({ prices, forecast_days: forecastDays, model });
      setResult(res);
    } catch (e: any) { setError(e.message); }
    finally { setLoading(false); }
  };

  return (
    <Box>
      <Typography variant="h4" sx={{ mb: 0.5 }}>ML Predictions</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        LSTM, Random Forest, ARIMA & Reinforcement Learning
      </Typography>

      <Grid container spacing={2.5}>
        <Grid size={{ xs: 12, md: 4 }}>
          <Card>
            <CardContent>
              <Typography variant="h6" gutterBottom>Prediction Model</Typography>
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                <MarketTickerAutocomplete
                  label="Ticker"
                  value={ticker}
                  onChange={(v) => setTicker(v || ticker)}
                  helperText="Load real price history for prediction"
                />
                <ProviderChips value={provider} onChange={setProvider} />
                <Button variant="outlined" onClick={loadMarketPrices} disabled={loading} fullWidth>
                  Load Market Prices
                </Button>
                {dataSource && (
                  <Chip size="small" color="info" label={`Data: ${dataSource} · ${livePrices?.length || 0} closes`} />
                )}

                <ToggleButtonGroup
                  fullWidth exclusive value={model}
                  onChange={(_, v) => v && setModel(v)}
                  orientation="vertical"
                >
                  <ToggleButton value="lstm">LSTM Neural Network</ToggleButton>
                  <ToggleButton value="random_forest">Random Forest</ToggleButton>
                  <ToggleButton value="arima">ARIMA</ToggleButton>
                  <ToggleButton value="dqn">DQN Trading Agent</ToggleButton>
                </ToggleButtonGroup>

                <TextField label="Forecast Days" type="number" value={forecastDays}
                  onChange={(e) => setForecastDays(+e.target.value)} fullWidth />

                <Button variant="contained" onClick={runPrediction} disabled={loading} fullWidth>
                  {loading ? <CircularProgress size={20} /> : 'Run Prediction'}
                </Button>
              </Box>
            </CardContent>
          </Card>
        </Grid>

        <Grid size={{ xs: 12, md: 8 }}>
          {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

          {result && (
            <Card>
              <CardContent>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                  <Typography variant="h6">
                    {result.model?.replace(/_/g, ' ').toUpperCase()} Results
                  </Typography>
                  {result.direction && (
                    <Chip
                      label={result.direction}
                      color={result.direction === 'bullish' ? 'success' : 'error'}
                    />
                  )}
                </Box>

                {result.predictions && (
                  <>
                    <Typography variant="body2" color="text.secondary" gutterBottom>
                      Last price: ${result.last_actual_price} | Forecast: {result.predictions.length} days
                    </Typography>

                    <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', my: 2 }}>
                      <Chip label={`Day 1: $${result.predictions[0]}`} variant="outlined" size="small" />
                      {result.predictions.length > 7 && (
                        <Chip label={`Day 7: $${result.predictions[6]}`} variant="outlined" size="small" />
                      )}
                      {result.predictions.length > 14 && (
                        <Chip label={`Day 14: $${result.predictions[13]}`} variant="outlined" size="small" />
                      )}
                      <Chip
                        label={`Day ${result.predictions.length}: $${result.predictions[result.predictions.length - 1]}`}
                        color="primary" size="small"
                      />
                    </Box>

                    {result.predicted_return != null && (
                      <Alert severity={result.predicted_return > 0 ? 'success' : 'warning'}>
                        Predicted return: <strong>{result.predicted_return}%</strong> over {result.forecast_days} days
                      </Alert>
                    )}
                  </>
                )}

                {/* DQN Trading Performance */}
                {result.performance && (
                  <Table size="small" sx={{ mt: 2 }}>
                    <TableBody>
                      {Object.entries(result.performance).map(([key, val]) => (
                        <TableRow key={key}>
                          <TableCell sx={{ fontWeight: 600, textTransform: 'capitalize' }}>
                            {key.replace(/_/g, ' ')}
                          </TableCell>
                          <TableCell align="right" sx={{ fontFamily: 'monospace' }}>
                            {typeof val === 'number' ? (val as number).toFixed(2) : String(val)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}

                {/* Feature Importance */}
                {result.feature_importance && (
                  <Box sx={{ mt: 2 }}>
                    <Typography variant="subtitle2" gutterBottom>Feature Importance</Typography>
                    {Object.entries(result.feature_importance).map(([feat, imp]) => (
                      <Box key={feat} sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                        <Typography variant="body2" sx={{ width: 100 }}>{feat}</Typography>
                        <Box sx={{
                          height: 12, bgcolor: 'primary.main', borderRadius: 1,
                          width: `${(imp as number) * 100 * 3}%`, transition: 'width 0.3s',
                        }} />
                        <Typography variant="caption" sx={{ fontFamily: 'monospace' }}>
                          {((imp as number) * 100).toFixed(1)}%
                        </Typography>
                      </Box>
                    ))}
                  </Box>
                )}

                {/* Raw JSON */}
                <Box
                  component="pre"
                  sx={{
                    mt: 2, bgcolor: 'background.default', p: 2, borderRadius: 2,
                    overflow: 'auto', maxHeight: 300, fontSize: '0.75rem',
                    fontFamily: '"JetBrains Mono", monospace',
                  }}
                >
                  {JSON.stringify(result, null, 2)}
                </Box>
              </CardContent>
            </Card>
          )}
        </Grid>
      </Grid>

      <QuantContextSection
        conceptsTitle="ML in quant finance"
        concepts={mlFoundations}
        notes={mlConvergenceNotes}
      />
    </Box>
  );
}
