import React, { useEffect, useState } from 'react';
import {
  Box, Grid, Card, CardContent, Typography, Chip, LinearProgress,
  Table, TableBody, TableCell, TableRow, Alert,
} from '@mui/material';
import {
  ShowChart, TrendingUp, TrendingDown, Warning, Water, Hub,
} from '@mui/icons-material';
import { api } from '../services/api';

const StatCard: React.FC<{
  title: string; value: string; subtitle?: string;
  color?: string; icon?: React.ReactNode; trend?: 'up' | 'down';
}> = ({ title, value, subtitle, color = '#6366f1', icon, trend }) => (
  <Card>
    <CardContent>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
        <Typography variant="body2" color="text.secondary">{title}</Typography>
        <Box sx={{ color }}>{icon}</Box>
      </Box>
      <Typography variant="h5" sx={{ fontWeight: 700 }}>{value}</Typography>
      {subtitle && (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mt: 0.5 }}>
          {trend === 'up' ? <TrendingUp sx={{ fontSize: 16, color: '#10b981' }} /> :
           trend === 'down' ? <TrendingDown sx={{ fontSize: 16, color: '#ef4444' }} /> : null}
          <Typography variant="caption" color={trend === 'up' ? '#10b981' : trend === 'down' ? '#ef4444' : 'text.secondary'}>
            {subtitle}
          </Typography>
        </Box>
      )}
    </CardContent>
  </Card>
);

export default function Dashboard() {
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<Record<string, any>>({});

  useEffect(() => {
    async function load() {
      try {
        const [liveQuote, providerStatus, ghostData, swanData] = await Promise.all([
          api.quote('AAPL', 'auto').catch(() => null),
          api.marketProviders().catch(() => null),
          api.ghostDemo().catch(() => ({ ghost_ratio: 0.42, liquidity_score: 58.0, risk_level: 'MEDIUM' })),
          api.blackSwanDemo().catch(() => ({ combined_score: 34.2, alert_level: 'MODERATE' })),
        ]);

        // Price real BS with live AAPL spot if available
        let bsResult = { price: '—', greeks: null };
        if ((liveQuote as any)?.price) {
          const spot = Number((liveQuote as any).price);
          const vol: any = await api.volatility('AAPL').catch(() => null);
          const sigma = vol?.iv_avg && vol.iv_avg < 2 ? vol.iv_avg : 0.25;
          const bs: any = await api.blackScholes({
            spot, strike: Math.round(spot / 5) * 5,
            maturity: 0.25, rate: 0.05, sigma, option_type: 'call',
          }).catch(() => null);
          if (bs?.price) bsResult = bs;
        }

        setData({ bs: bsResult, ghost: ghostData, swan: swanData, liveQuote, providerStatus });
      } catch (e) {
        console.error(e);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  if (loading) return <LinearProgress />;

  return (
    <Box>
      <Typography variant="h4" sx={{ mb: 0.5 }}>Dashboard</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Quantitative finance analytics at a glance
      </Typography>

      <Grid container spacing={2.5}>
        <Grid size={{ xs: 12, sm: 6, md: 3 }}>
          <StatCard title="AAPL Spot" value={data.liveQuote?.price ? `$${Number(data.liveQuote.price).toFixed(2)}` : '—'}
            subtitle={data.liveQuote?.provider || 'market feed'} icon={<ShowChart />} color="#6366f1"
            trend={Number(data.liveQuote?.change_pct || 0) >= 0 ? 'up' : 'down'} />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 3 }}>
          <StatCard
            title="BS Option Price (AAPL ATM Call)"
            value={data.bs?.price && data.bs.price !== '—' ? `$${Number(data.bs.price).toFixed(2)}` : '—'}
            subtitle={data.bs?.greeks ? `Δ ${Number(data.bs.greeks.delta).toFixed(3)}` : 'live pricing'}
            icon={<TrendingUp />} color="#06b6d4" trend="up" />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 3 }}>
          <StatCard title="Ghost Liquidity" value={`${((data.ghost?.ghost_ratio || 0) * 100).toFixed(1)}%`}
            subtitle={`Score: ${data.ghost?.liquidity_score || '—'}`} icon={<Water />}
            color="#f59e0b" trend="down" />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, md: 3 }}>
          <StatCard title="Black Swan Score" value={data.swan?.combined_score?.toFixed(1) || '—'}
            subtitle={`Alert: ${data.swan?.alert_level || '—'}`} icon={<Warning />}
            color={data.swan?.combined_score > 50 ? '#ef4444' : '#10b981'} />
        </Grid>
      </Grid>

      <Grid container spacing={2.5} sx={{ mt: 1 }}>
        <Grid size={{ xs: 12, md: 6 }}>
          <Card>
            <CardContent>
              <Typography variant="h6" gutterBottom>Greeks Overview</Typography>
              <Table size="small">
                <TableBody>
                  {data.bs?.greeks && Object.entries(data.bs.greeks).map(([key, val]) => (
                    <TableRow key={key}>
                      <TableCell sx={{ fontWeight: 600, textTransform: 'capitalize' }}>{key}</TableCell>
                      <TableCell align="right" sx={{ fontFamily: '"JetBrains Mono", monospace' }}>
                        {(val as number).toFixed(6)}
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
              <Typography variant="h6" gutterBottom sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <Hub fontSize="small" /> Market Data Providers
              </Typography>
              <Table size="small" sx={{ mb: 2 }}>
                <TableBody>
                  <TableRow>
                    <TableCell sx={{ fontWeight: 600 }}>Default Route</TableCell>
                    <TableCell align="right">{data.providerStatus?.default_provider || 'auto'}</TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell sx={{ fontWeight: 600 }}>OpenBB</TableCell>
                    <TableCell align="right">{data.providerStatus?.providers?.openbb?.openbb_available ? 'Enabled' : 'Optional'}</TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell sx={{ fontWeight: 600 }}>Yahoo Finance</TableCell>
                    <TableCell align="right">Enabled</TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell sx={{ fontWeight: 600 }}>Fallback</TableCell>
                    <TableCell align="right">Synthetic</TableCell>
                  </TableRow>
                </TableBody>
              </Table>

              <Typography variant="h6" gutterBottom>Platform Capabilities</Typography>
              <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mt: 1 }}>
                {[
                  'OpenBB', 'Black-Scholes', 'Monte Carlo', 'Binomial Tree', 'Finite Difference',
                  'GARCH', 'Heston Model', 'VaR/CVaR', 'Markowitz',
                  'Risk Parity', 'Black-Litterman', 'LSTM', 'Random Forest',
                  'ARIMA', 'DQN Trading', 'Ghost Liquidity', 'Black Swan Detection',
                  'Greeks', 'IV Surface', 'Straddle', 'Iron Condor', 'Butterfly',
                  'Backtesting', 'Stress Testing', 'NLP Sentiment',
                ].map((cap) => (
                  <Chip key={cap} label={cap} size="small" variant="outlined"
                    sx={{ fontSize: '0.75rem', borderColor: 'primary.main', color: 'primary.light' }} />
                ))}
              </Box>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      <Alert severity="info" sx={{ mt: 3 }}>
        <strong>Market data pipeline:</strong> the app now routes quotes, history, profiles and options
        through OpenBB when available, then Yahoo Finance, and finally synthetic fallback data.
      </Alert>
    </Box>
  );
}
