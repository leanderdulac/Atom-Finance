import React, { useState } from 'react';
import {
  Box, Grid, Card, CardContent, Typography, Button,
  CircularProgress, Alert, Chip, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, Paper, LinearProgress,
} from '@mui/material';
import { api } from '../services/api';
import QuantContextSection from '../components/QuantContextSection';
import MarketTickerAutocomplete from '../components/MarketTickerAutocomplete';
import ProviderChips from '../components/ProviderChips';

const blackSwanFoundations = [
  {
    title: 'Extreme value theory',
    text: 'Black swan monitoring starts in the tails: kurtosis, extreme-event counts and tail-index proxies test whether rare losses are more common than Gaussian models imply.',
  },
  {
    title: 'Regime diagnostics',
    text: 'Volatility clustering and regime breaks matter because instability often arrives as a transition, not a single point estimate. The engine tracks shifts before they become obvious.',
  },
  {
    title: 'AI and narrative signals',
    text: 'News sentiment adds a second layer to market statistics. The convergence of NLP, tail modeling and scenario thinking is what makes systemic monitoring operational.',
  },
];

const blackSwanConvergence = [
  'EVT improves the treatment of rare, high-impact losses beyond normal-distribution assumptions.',
  'Monte Carlo scenarios can be made more realistic when the tail behavior is informed by extreme-event diagnostics.',
  'The same stack is adaptable to climate risk, catastrophe insurance and broader systemic tipping-point analysis.',
];

function generateReturns(): number[] {
  const returns: number[] = [];
  let seed = 42;
  for (let i = 0; i < 500; i++) {
    seed = (seed * 16807) % 2147483647;
    const u = seed / 2147483647;
    seed = (seed * 16807) % 2147483647;
    const v = seed / 2147483647;
    const z = Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
    returns.push(0.0003 + 0.015 * z);
  }
  returns[100] = -0.08;
  returns[250] = -0.06;
  returns[400] = 0.07;
  return returns;
}

export default function BlackSwanPage() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState('');

  const [ticker, setTicker] = useState('SPY');
  const [provider, setProvider] = useState('openbb');
  const [liveReturns, setLiveReturns] = useState<number[] | null>(null);
  const [dataSource, setDataSource] = useState('');

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

  const runFullAnalysis = async () => {
    setLoading(true); setError('');
    try {
      const returns = liveReturns || generateReturns();
      const res = await api.blackSwanFull({ returns });
      setResult(res);
    } catch (e: any) { setError(e.message); }
    finally { setLoading(false); }
  };

  const alertColor = (level: string) => {
    switch (level) {
      case 'CRITICAL': return 'error';
      case 'HIGH': return 'error';
      case 'MODERATE': return 'warning';
      default: return 'success';
    }
  };

  return (
    <Box>
      <Typography variant="h4" sx={{ mb: 0.5 }}>Black Swan Detection</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Tail risk analysis, regime change detection & NLP news sentiment
      </Typography>

      <Grid container spacing={2.5} sx={{ mb: 3 }}>
        {blackSwanFoundations.map((item) => (
          <Grid key={item.title} size={{ xs: 12, md: 4 }}>
            <Card sx={{ height: '100%' }}>
              <CardContent>
                <Typography variant="h6" gutterBottom>
                  {item.title}
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.75 }}>
                  {item.text}
                </Typography>
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>

      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Typography variant="h6" gutterBottom>Market Data</Typography>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <MarketTickerAutocomplete label="Ticker" value={ticker} onChange={(v) => setTicker(v || ticker)} helperText="Analyse real return series" />
            <ProviderChips value={provider} onChange={setProvider} />
            <Button variant="outlined" onClick={loadMarketReturns} disabled={loading} fullWidth>
              Load Market Returns
            </Button>
            {dataSource && <Chip size="small" color="info" label={`Data: ${dataSource} · ${liveReturns?.length || 0} obs`} />}
          </Box>
        </CardContent>
      </Card>

      <Box sx={{ mb: 3 }}>
        <Button variant="contained" onClick={runFullAnalysis} disabled={loading} size="large">
          {loading ? <CircularProgress size={20} /> : 'Run Full Black Swan Analysis'}
        </Button>
      </Box>

      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      {result && (
        <>
          {/* Combined Score */}
          <Card sx={{ mb: 2 }}>
            <CardContent>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                <Typography variant="h5">Black Swan Risk Score</Typography>
                <Chip
                  label={`${result.alert_level}`}
                  color={alertColor(result.alert_level) as any}
                  sx={{ fontWeight: 700, fontSize: '1rem', px: 2, py: 2.5 }}
                />
              </Box>

              <Typography variant="h2" sx={{ textAlign: 'center', fontWeight: 700, color: 'primary.main', my: 2 }}>
                {result.combined_score?.toFixed(1)}
                <Typography component="span" variant="h5" color="text.secondary"> / 100</Typography>
              </Typography>

              <LinearProgress
                variant="determinate"
                value={result.combined_score || 0}
                sx={{
                  height: 12, borderRadius: 6, bgcolor: 'background.default',
                  '& .MuiLinearProgress-bar': {
                    bgcolor: result.combined_score > 75 ? 'error.main' :
                             result.combined_score > 50 ? 'warning.main' :
                             result.combined_score > 25 ? 'primary.main' : 'success.main',
                    borderRadius: 6,
                  },
                }}
              />

              {result.scores && (
                <Grid container spacing={2} sx={{ mt: 2 }}>
                  <Grid size={{ xs: 4 }}>
                    <Box sx={{ textAlign: 'center', p: 1, border: 1, borderColor: 'divider', borderRadius: 2 }}>
                      <Typography variant="caption" color="text.secondary">Market Score</Typography>
                      <Typography variant="h6" sx={{ fontFamily: 'monospace' }}>
                        {result.scores.market_score?.toFixed(1)}
                      </Typography>
                    </Box>
                  </Grid>
                  <Grid size={{ xs: 4 }}>
                    <Box sx={{ textAlign: 'center', p: 1, border: 1, borderColor: 'divider', borderRadius: 2 }}>
                      <Typography variant="caption" color="text.secondary">News Score</Typography>
                      <Typography variant="h6" sx={{ fontFamily: 'monospace' }}>
                        {result.scores.news_score?.toFixed(1)}
                      </Typography>
                    </Box>
                  </Grid>
                  <Grid size={{ xs: 4 }}>
                    <Box sx={{ textAlign: 'center', p: 1, border: 1, borderColor: 'divider', borderRadius: 2 }}>
                      <Typography variant="caption" color="text.secondary">Regime Score</Typography>
                      <Typography variant="h6" sx={{ fontFamily: 'monospace' }}>
                        {result.scores.regime_score?.toFixed(1)}
                      </Typography>
                    </Box>
                  </Grid>
                </Grid>
              )}
            </CardContent>
          </Card>

          {/* Tail Risk Details */}
          {result.components?.market_tail_risk && (
            <Grid container spacing={2}>
              <Grid size={{ xs: 12, md: 6 }}>
                <Card>
                  <CardContent>
                    <Typography variant="h6" gutterBottom>Tail Risk Statistics</Typography>
                    <Table size="small">
                      <TableBody>
                        {result.components.market_tail_risk.statistics &&
                          Object.entries(result.components.market_tail_risk.statistics).map(([key, val]) => (
                            <TableRow key={key}>
                              <TableCell sx={{ textTransform: 'capitalize', fontWeight: 600 }}>
                                {key.replace(/_/g, ' ')}
                              </TableCell>
                              <TableCell align="right" sx={{ fontFamily: 'monospace' }}>
                                {typeof val === 'number' ? (val as number).toFixed(4) : String(val)}
                              </TableCell>
                            </TableRow>
                          ))}
                      </TableBody>
                    </Table>
                  </CardContent>
                </Card>
              </Grid>

              <Grid size={{ xs: 12, md: 6 }}>
                <Card>
                  <CardContent>
                    <Typography variant="h6" gutterBottom>Extreme Events</Typography>
                    <Table size="small">
                      <TableBody>
                        {result.components.market_tail_risk.tail_analysis &&
                          Object.entries(result.components.market_tail_risk.tail_analysis).map(([key, val]) => (
                            <TableRow key={key}>
                              <TableCell sx={{ textTransform: 'capitalize', fontWeight: 600, fontSize: '0.8rem' }}>
                                {key.replace(/_/g, ' ')}
                              </TableCell>
                              <TableCell align="right" sx={{ fontFamily: 'monospace' }}>
                                {typeof val === 'number' ? (val as number).toFixed(4) : String(val)}
                              </TableCell>
                            </TableRow>
                          ))}
                      </TableBody>
                    </Table>
                  </CardContent>
                </Card>
              </Grid>
            </Grid>
          )}

          {/* News Sentiment */}
          {result.components?.news_sentiment && (
            <Card sx={{ mt: 2 }}>
              <CardContent>
                <Typography variant="h6" gutterBottom>News Sentiment Analysis</Typography>
                <Box sx={{ display: 'flex', gap: 2, mb: 2 }}>
                  <Chip label={`Positive: ${result.components.news_sentiment.sentiment_distribution.positive}`} color="success" />
                  <Chip label={`Neutral: ${result.components.news_sentiment.sentiment_distribution.neutral}`} color="default" />
                  <Chip label={`Negative: ${result.components.news_sentiment.sentiment_distribution.negative}`} color="error" />
                </Box>

                {result.components.news_sentiment.articles?.slice(0, 5).map((article: any, i: number) => (
                  <Box key={i} sx={{ p: 1.5, mb: 1, border: 1, borderColor: 'divider', borderRadius: 2 }}>
                    <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <Typography variant="body2" sx={{ fontWeight: 600 }}>{article.title}</Typography>
                      <Chip
                        size="small"
                        label={`${article.sentiment?.toFixed(2)}`}
                        color={article.sentiment_label === 'negative' ? 'error' : article.sentiment_label === 'positive' ? 'success' : 'default'}
                      />
                    </Box>
                    {article.tail_risk_flag && (
                      <Chip size="small" label="TAIL RISK" color="error" variant="outlined" sx={{ mt: 0.5 }} />
                    )}
                  </Box>
                ))}
              </CardContent>
            </Card>
          )}

        </>
      )}

      <QuantContextSection
        conceptsTitle="Black swan theory context"
        notesTitle="Why this module matters"
        concepts={blackSwanFoundations}
        notes={blackSwanConvergence}
      />
    </Box>
  );
}
