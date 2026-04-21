import React, { useState } from 'react';
import {
  Box, Grid, Card, CardContent, Typography, TextField, Button,
  ToggleButtonGroup, ToggleButton, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, Paper, CircularProgress, Alert,
  Tabs, Tab, Divider, Chip,
} from '@mui/material';
import { api } from '../services/api';
import MarketTickerAutocomplete from '../components/MarketTickerAutocomplete';
import ProviderChips from '../components/ProviderChips';
import QuantContextSection from '../components/QuantContextSection';

interface TabPanelProps {
  children?: React.ReactNode;
  value: number;
  index: number;
}

const TabPanel: React.FC<TabPanelProps> = ({ children, value, index }) => (
  <div hidden={value !== index}>{value === index && <Box sx={{ pt: 2 }}>{children}</Box>}</div>
);

const pricingFoundations = [
  {
    title: 'Black-Scholes-Merton',
    text: 'The analytical baseline comes from continuous-time hedging, Itô calculus and risk-neutral valuation. It remains the reference model for European options and Greeks.',
  },
  {
    title: 'Monte Carlo simulation',
    text: 'When payoff structure or state dynamics become complex, simulated paths approximate the expected discounted payoff and expose dispersion through confidence intervals.',
  },
  {
    title: 'Trees and PDE methods',
    text: 'Binomial lattices and finite-difference solvers extend valuation to early exercise, discrete state transitions and richer boundary conditions.',
  },
];

const modelSelectionNotes = [
  'Use Black-Scholes as the clean analytical benchmark and a fast Greeks engine.',
  'Use Monte Carlo when dimensionality, path dependence or custom payoff design dominate the problem.',
  'Use tree and PDE methods when exercise logic, stability and boundary behavior matter more than closed-form elegance.',
];

export default function PricingPage() {
  const [tab, setTab] = useState(0);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState('');
  const [ticker, setTicker] = useState('AAPL');
  const [provider, setProvider] = useState('auto');
  const [marketSource, setMarketSource] = useState<string>('');

  const [params, setParams] = useState({
    spot: 100, strike: 100, maturity: 0.25, rate: 0.05,
    sigma: 0.2, option_type: 'call' as 'call' | 'put',
    dividend_yield: 0, n_simulations: 100000, n_steps: 252,
    american: false,
  });

  const update = (key: string, val: any) => setParams((p) => ({ ...p, [key]: val }));

  const loadMarketData = async () => {
    setLoading(true);
    setError('');
    try {
      const quote: any = await api.quote(ticker, provider);
      const vol: any = await api.volatility(ticker).catch(() => null);

      setParams((p) => ({
        ...p,
        spot: Number(quote.price || p.spot),
        strike: Number(quote.price || p.strike),
        sigma: Number(vol?.iv_avg || p.sigma),
      }));
      setMarketSource(quote.provider || quote.source || provider);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const runModel = async (model: string) => {
    setLoading(true);
    setError('');
    try {
      let res;
      switch (model) {
        case 'black-scholes':
          res = await api.blackScholes(params);
          break;
        case 'monte-carlo':
          res = await api.monteCarlo(params);
          break;
        case 'binomial':
          res = await api.binomial(params);
          break;
        case 'finite-difference':
          res = await api.finiteDifference(params);
          break;
        case 'compare':
          res = await api.compareModels(params);
          break;
        default:
          res = await api.blackScholes(params);
      }
      setResult(res);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box>
      <Typography variant="h4" sx={{ mb: 0.5 }}>Options Pricing</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Black-Scholes, Monte Carlo, Binomial Trees & Finite Difference Methods
      </Typography>

      <Grid container spacing={2.5}>
        <Grid size={{ xs: 12, md: 4 }}>
          <Card>
            <CardContent>
              <Typography variant="h6" gutterBottom>Parameters</Typography>
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                <MarketTickerAutocomplete
                  label="Underlying Ticker"
                  value={ticker}
                  onChange={(next) => setTicker(next || ticker)}
                  helperText="Search equities and load live spot/volatility inputs"
                />
                <ProviderChips value={provider} onChange={setProvider} />
                <Button variant="outlined" onClick={loadMarketData} disabled={loading}>
                  Load Market Data
                </Button>
                {marketSource && <Chip size="small" color="info" label={`Source: ${marketSource}`} />}

                <TextField label="Spot Price (S)" type="number" value={params.spot}
                  onChange={(e) => update('spot', +e.target.value)} fullWidth />
                <TextField label="Strike Price (K)" type="number" value={params.strike}
                  onChange={(e) => update('strike', +e.target.value)} fullWidth />
                <TextField label="Maturity (years)" type="number" value={params.maturity}
                  onChange={(e) => update('maturity', +e.target.value)} inputProps={{ step: 0.01 }} fullWidth />
                <TextField label="Risk-free Rate (r)" type="number" value={params.rate}
                  onChange={(e) => update('rate', +e.target.value)} inputProps={{ step: 0.01 }} fullWidth />
                <TextField label="Volatility (σ)" type="number" value={params.sigma}
                  onChange={(e) => update('sigma', +e.target.value)} inputProps={{ step: 0.01 }} fullWidth />
                <TextField label="Dividend Yield (q)" type="number" value={params.dividend_yield}
                  onChange={(e) => update('dividend_yield', +e.target.value)} inputProps={{ step: 0.01 }} fullWidth />

                <ToggleButtonGroup fullWidth exclusive value={params.option_type}
                  onChange={(_, v) => v && update('option_type', v)}>
                  <ToggleButton value="call">Call</ToggleButton>
                  <ToggleButton value="put">Put</ToggleButton>
                </ToggleButtonGroup>

                <Divider />

                <Button variant="contained" onClick={() => runModel('black-scholes')} disabled={loading}>
                  Black-Scholes
                </Button>
                <Button variant="outlined" onClick={() => runModel('monte-carlo')} disabled={loading}>
                  Monte Carlo
                </Button>
                <Button variant="outlined" onClick={() => runModel('binomial')} disabled={loading}>
                  Binomial Tree
                </Button>
                <Button variant="outlined" onClick={() => runModel('finite-difference')} disabled={loading}>
                  Finite Difference
                </Button>
                <Button variant="contained" color="secondary" onClick={() => runModel('compare')} disabled={loading}>
                  Compare All Models
                </Button>
              </Box>
            </CardContent>
          </Card>
        </Grid>

        <Grid size={{ xs: 12, md: 8 }}>
          {loading && <CircularProgress sx={{ display: 'block', mx: 'auto', my: 4 }} />}
          {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

          {result && (
            <Card>
              <CardContent>
                <Tabs value={tab} onChange={(_, v) => setTab(v)}>
                  <Tab label="Results" />
                  <Tab label="Greeks" />
                  <Tab label="Raw Data" />
                </Tabs>

                <TabPanel value={tab} index={0}>
                  {result.comparison ? (
                    <TableContainer component={Paper} variant="outlined">
                      <Table>
                        <TableHead>
                          <TableRow>
                            <TableCell sx={{ fontWeight: 700 }}>Model</TableCell>
                            <TableCell align="right" sx={{ fontWeight: 700 }}>Price</TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {Object.entries(result.comparison).map(([model, price]) => (
                            <TableRow key={model}>
                              <TableCell sx={{ textTransform: 'capitalize' }}>{model.replace(/_/g, ' ')}</TableCell>
                              <TableCell align="right" sx={{ fontFamily: '"JetBrains Mono", monospace', fontWeight: 600 }}>
                                ${(price as number).toFixed(6)}
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </TableContainer>
                  ) : (
                    <Box>
                      <Typography variant="h3" sx={{ textAlign: 'center', my: 3, fontWeight: 700, color: 'primary.main' }}>
                        ${result.price?.toFixed(6) || '—'}
                      </Typography>
                      <Typography variant="body2" color="text.secondary" textAlign="center">
                        Model: {result.model?.replace(/_/g, ' ')}
                        {result.std_error && ` | Std Error: ${result.std_error.toFixed(6)}`}
                        {result.confidence_95 && ` | 95% CI: [${result.confidence_95[0].toFixed(4)}, ${result.confidence_95[1].toFixed(4)}]`}
                      </Typography>
                    </Box>
                  )}
                </TabPanel>

                <TabPanel value={tab} index={1}>
                  <TableContainer component={Paper} variant="outlined">
                    <Table>
                      <TableBody>
                        {(result.greeks ? Object.entries(result.greeks) : []).map(([key, val]) => (
                          <TableRow key={key}>
                            <TableCell sx={{ fontWeight: 600, textTransform: 'capitalize', width: '40%' }}>
                              {key} ({key === 'delta' ? 'Δ' : key === 'gamma' ? 'Γ' : key === 'theta' ? 'Θ' : key === 'vega' ? 'ν' : 'ρ'})
                            </TableCell>
                            <TableCell align="right" sx={{ fontFamily: '"JetBrains Mono", monospace' }}>
                              {(val as number).toFixed(6)}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </TableContainer>
                </TabPanel>

                <TabPanel value={tab} index={2}>
                  <Box
                    component="pre"
                    sx={{
                      bgcolor: 'background.default',
                      p: 2,
                      borderRadius: 2,
                      overflow: 'auto',
                      maxHeight: 500,
                      fontFamily: '"JetBrains Mono", monospace',
                      fontSize: '0.8rem',
                    }}
                  >
                    {JSON.stringify(result, null, 2)}
                  </Box>
                </TabPanel>
              </CardContent>
            </Card>
          )}
        </Grid>
      </Grid>

      {marketSource && (
        <Alert severity="info" sx={{ mt: 2 }}>
          Market inputs loaded for {ticker} via {marketSource}. Spot, ATM strike and implied volatility were prefilled.
        </Alert>
      )}

      <QuantContextSection
        conceptsTitle="Mathematical framing"
        notesTitle="Model selection notes"
        concepts={pricingFoundations}
        notes={modelSelectionNotes}
      />
    </Box>
  );
}
