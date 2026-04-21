import React, { useState } from 'react';
import {
  Box, Grid, Card, CardContent, Typography, TextField, Button,
  ToggleButtonGroup, ToggleButton, CircularProgress, Alert,
  Chip, Divider,
} from '@mui/material';
import { api } from '../services/api';
import MarketTickerAutocomplete from '../components/MarketTickerAutocomplete';
import ProviderChips from '../components/ProviderChips';
import QuantContextSection from '../components/QuantContextSection';

const strategyFoundations = [
  {
    title: 'Structured payoff design',
    text: 'Options strategies combine elementary instruments into non-linear payoff surfaces. The design problem is to reshape exposure to volatility, direction and convexity.',
  },
  {
    title: 'Greeks aggregation',
    text: 'Portfolio Greeks are the local sensitivity map of the structure. They reveal how a strategy responds to changes in spot, volatility, time decay and rates.',
  },
  {
    title: 'Scenario geometry',
    text: 'Breakeven levels, capped losses and asymmetric profit zones are easier to understand as payoff geometry than as isolated prices.',
  },
];

const strategyNotes = [
  'Straddles express convexity and volatility views more than directional conviction.',
  'Condors and butterflies trade payoff width for premium efficiency and controlled downside.',
  'The real edge comes from aligning structure, implied volatility and market regime rather than selecting legs mechanically.',
];

export default function StrategiesPage() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState('');
  const [strategyType, setStrategyType] = useState('straddle');
  const [ticker, setTicker] = useState('AAPL');
  const [provider, setProvider] = useState('openbb');
  const [marketSource, setMarketSource] = useState('');

  const [params, setParams] = useState({
    spot: 100, sigma: 0.2, rate: 0.05, maturity: 0.25,
    strike: 100,
    k1: 90, k2: 95, k3: 100, k4: 105, k5: 110,
  });

  const update = (key: string, val: number) => setParams((p) => ({ ...p, [key]: val }));

  const loadUnderlyingData = async () => {
    setLoading(true); setError('');
    try {
      const quote: any = await api.quote(ticker, provider);
      const vol: any = await api.volatility(ticker).catch(() => null);
      const spot = Number(quote.price || params.spot);
      const atm = Math.round(spot);
      setParams((p) => ({
        ...p,
        spot,
        strike: atm,
        sigma: Number(vol?.iv_avg || p.sigma),
        k1: atm - 10,
        k2: atm - 5,
        k3: atm,
        k4: atm + 5,
        k5: atm + 10,
      }));
      setMarketSource(quote.provider || quote.source || provider);
    } catch (e: any) { setError(e.message); }
    finally { setLoading(false); }
  };

  const runStrategy = async () => {
    setLoading(true); setError('');
    try {
      const base = { spot: params.spot, sigma: params.sigma, rate: params.rate, maturity: params.maturity };
      let res;

      switch (strategyType) {
        case 'straddle':
          res = await api.straddle({ ...base, strike: params.strike });
          break;
        case 'iron_condor':
          res = await api.ironCondor({ ...base });
          break;
        case 'butterfly':
          res = await api.butterfly({ ...base });
          break;
        case 'custom':
          res = await api.strategy({
            ...base,
            legs: [
              { strike: params.k1, type: 'call', position: 'long', quantity: 1 },
              { strike: params.k3, type: 'call', position: 'short', quantity: 1 },
            ],
          });
          break;
        default:
          res = await api.straddle({ ...base, strike: params.strike });
      }
      setResult(res);
    } catch (e: any) { setError(e.message); }
    finally { setLoading(false); }
  };

  return (
    <Box>
      <Typography variant="h4" sx={{ mb: 0.5 }}>Options Strategies</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Straddle, Iron Condor, Butterfly Spread & Custom Strategies
      </Typography>

      <Grid container spacing={2.5}>
        <Grid size={{ xs: 12, md: 4 }}>
          <Card>
            <CardContent>
              <Typography variant="h6" gutterBottom>Strategy Selection</Typography>
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                <MarketTickerAutocomplete
                  label="Underlying Ticker"
                  value={ticker}
                  onChange={(next) => setTicker(next || ticker)}
                  helperText="Search an underlying and prefill the option setup"
                />
                <ProviderChips value={provider} onChange={setProvider} />
                <ToggleButtonGroup
                  fullWidth exclusive value={strategyType}
                  onChange={(_, v) => v && setStrategyType(v)}
                  orientation="vertical"
                >
                  <ToggleButton value="straddle">Straddle</ToggleButton>
                  <ToggleButton value="iron_condor">Iron Condor</ToggleButton>
                  <ToggleButton value="butterfly">Butterfly Spread</ToggleButton>
                  <ToggleButton value="custom">Custom (Bull Call)</ToggleButton>
                </ToggleButtonGroup>

                <Divider />
                <Typography variant="subtitle2">Common Parameters</Typography>

                <TextField label="Spot Price" type="number" value={params.spot}
                  onChange={(e) => update('spot', +e.target.value)} fullWidth />
                <TextField label="Volatility (σ)" type="number" value={params.sigma}
                  onChange={(e) => update('sigma', +e.target.value)} inputProps={{ step: 0.01 }} fullWidth />
                <TextField label="Risk-free Rate" type="number" value={params.rate}
                  onChange={(e) => update('rate', +e.target.value)} inputProps={{ step: 0.01 }} fullWidth />
                <TextField label="Maturity (years)" type="number" value={params.maturity}
                  onChange={(e) => update('maturity', +e.target.value)} inputProps={{ step: 0.01 }} fullWidth />

                <Button variant="outlined" onClick={loadUnderlyingData} disabled={loading} fullWidth>
                  Load Underlying Data
                </Button>
                {marketSource && <Chip size="small" color="info" label={`Source: ${marketSource}`} />}

                {strategyType === 'straddle' && (
                  <TextField label="Strike" type="number" value={params.strike}
                    onChange={(e) => update('strike', +e.target.value)} fullWidth />
                )}

                <Button variant="contained" onClick={runStrategy} disabled={loading} fullWidth>
                  {loading ? <CircularProgress size={20} /> : 'Analyze Strategy'}
                </Button>
              </Box>
            </CardContent>
          </Card>
        </Grid>

        <Grid size={{ xs: 12, md: 8 }}>
          {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

          {result && (
            <>
              <Card sx={{ mb: 2 }}>
                <CardContent>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                    <Typography variant="h6" sx={{ textTransform: 'capitalize' }}>
                      {result.strategy?.replace(/_/g, ' ')} Analysis
                    </Typography>
                    {marketSource && <Chip size="small" color="info" label={marketSource} />}
                  </Box>

                  <Grid container spacing={2}>
                    <Grid size={{ xs: 6, sm: 3 }}>
                      <Box sx={{ textAlign: 'center', p: 1.5, border: 1, borderColor: 'divider', borderRadius: 2 }}>
                        <Typography variant="caption" color="text.secondary">Premium</Typography>
                        <Typography variant="h6" sx={{ fontFamily: 'monospace' }}>
                          ${result.total_premium?.toFixed(4)}
                        </Typography>
                      </Box>
                    </Grid>
                    <Grid size={{ xs: 6, sm: 3 }}>
                      <Box sx={{ textAlign: 'center', p: 1.5, border: 1, borderColor: 'divider', borderRadius: 2 }}>
                        <Typography variant="caption" color="text.secondary">Max Profit</Typography>
                        <Typography variant="h6" sx={{ fontFamily: 'monospace', color: 'success.main' }}>
                          {typeof result.max_profit === 'string' ? result.max_profit :
                           `$${result.max_profit?.toFixed(2)}`}
                        </Typography>
                      </Box>
                    </Grid>
                    <Grid size={{ xs: 6, sm: 3 }}>
                      <Box sx={{ textAlign: 'center', p: 1.5, border: 1, borderColor: 'divider', borderRadius: 2 }}>
                        <Typography variant="caption" color="text.secondary">Max Loss</Typography>
                        <Typography variant="h6" sx={{ fontFamily: 'monospace', color: 'error.main' }}>
                          ${result.max_loss?.toFixed(2)}
                        </Typography>
                      </Box>
                    </Grid>
                    <Grid size={{ xs: 6, sm: 3 }}>
                      <Box sx={{ textAlign: 'center', p: 1.5, border: 1, borderColor: 'divider', borderRadius: 2 }}>
                        <Typography variant="caption" color="text.secondary">Breakeven</Typography>
                        <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
                          {result.breakeven_points?.map((b: number) => `$${b}`).join(', ') || '—'}
                        </Typography>
                      </Box>
                    </Grid>
                  </Grid>
                </CardContent>
              </Card>

              {/* Greeks */}
              {result.greeks && (
                <Card sx={{ mb: 2 }}>
                  <CardContent>
                    <Typography variant="h6" gutterBottom>Strategy Greeks</Typography>
                    <Grid container spacing={2}>
                      {Object.entries(result.greeks).map(([key, val]) => (
                        <Grid size={{ xs: 4, sm: 2.4 }} key={key}>
                          <Box sx={{ textAlign: 'center', p: 1, border: 1, borderColor: 'divider', borderRadius: 2 }}>
                            <Typography variant="caption" color="text.secondary" sx={{ textTransform: 'capitalize' }}>
                              {key}
                            </Typography>
                            <Typography variant="body1" sx={{ fontFamily: 'monospace', fontWeight: 600 }}>
                              {(val as number).toFixed(6)}
                            </Typography>
                          </Box>
                        </Grid>
                      ))}
                    </Grid>
                  </CardContent>
                </Card>
              )}

              {/* Payoff Data */}
              {result.payoff_y && (
                <Card>
                  <CardContent>
                    <Typography variant="h6" gutterBottom>Payoff Summary</Typography>
                    <Typography variant="body2" color="text.secondary">
                      {result.payoff_x?.length} data points from ${result.payoff_x?.[0]?.toFixed(0)} to ${result.payoff_x?.[result.payoff_x.length - 1]?.toFixed(0)}
                    </Typography>
                    <Alert severity="info" sx={{ mt: 1 }}>
                      The payoff diagram data is available in the API response. Connect a charting library
                      (Chart.js, D3.js, or Recharts) to visualize the payoff curve using the payoff_x and payoff_y arrays.
                    </Alert>
                  </CardContent>
                </Card>
              )}
            </>
          )}
        </Grid>
      </Grid>

      {marketSource && (
        <Alert severity="info" sx={{ mt: 2 }}>
          Live market snapshot loaded for {ticker}. Spot, ATM strike and volatility were updated from {marketSource}.
        </Alert>
      )}

      <QuantContextSection
        conceptsTitle="Strategy theory context"
        concepts={strategyFoundations}
        notes={strategyNotes}
      />
    </Box>
  );
}
