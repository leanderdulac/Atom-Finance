import React, { useState } from 'react';
import {
  Box, Grid, Card, CardContent, Typography, Button, CircularProgress,
  Alert, Chip, TextField, Table, TableBody, TableCell, TableHead,
  TableRow, Divider, LinearProgress, Tooltip,
} from '@mui/material';
import {
  PlayArrow, Download, Shield, TrendingUp, Bolt, CheckCircle,
} from '@mui/icons-material';
import {
  ComposedChart, AreaChart, Area, Line, XAxis, YAxis, CartesianGrid,
  Tooltip as RTooltip, Legend, ResponsiveContainer, ReferenceLine,
} from 'recharts';
import { api } from '../services/api';

// ── Profile definitions ───────────────────────────────────────────────────────

interface AssetAlloc {
  ticker: string;
  S0: number;
  mu: number;
  sigma: number;
  weight: number;       // portfolio weight 0-1
}

interface Profile {
  id: 'conservador' | 'moderado' | 'agressivo';
  label: string;
  description: string;
  color: string;
  bgColor: string;
  Icon: React.ElementType;
  assets: AssetAlloc[];
  expectedReturn: number;   // weighted mu
  expectedVol: number;      // approximate weighted sigma
}

const PROFILES: Profile[] = [
  {
    id: 'conservador',
    label: 'Conservador',
    description: 'Prioriza preservação de capital. Ativos defensivos, alta previsibilidade de dividendos e menor oscilação.',
    color: '#22c55e',
    bgColor: '#22c55e18',
    Icon: Shield,
    assets: [
      { ticker: 'ABEV3', S0: 14.0, mu: 0.07, sigma: 0.20, weight: 0.40 },
      { ticker: 'ITUB4', S0: 35.0, mu: 0.09, sigma: 0.24, weight: 0.35 },
      { ticker: 'VALE3', S0: 65.0, mu: 0.08, sigma: 0.26, weight: 0.25 },
    ],
    expectedReturn: 0.0795,
    expectedVol: 0.232,
  },
  {
    id: 'moderado',
    label: 'Moderado',
    description: 'Equilíbrio entre crescimento e proteção. Mix de blue chips com exposição controlada a commodities.',
    color: '#f59e0b',
    bgColor: '#f59e0b18',
    Icon: TrendingUp,
    assets: [
      { ticker: 'ITUB4', S0: 35.0, mu: 0.10, sigma: 0.26, weight: 0.30 },
      { ticker: 'PETR4', S0: 40.0, mu: 0.11, sigma: 0.36, weight: 0.25 },
      { ticker: 'VALE3', S0: 65.0, mu: 0.10, sigma: 0.30, weight: 0.25 },
      { ticker: 'ABEV3', S0: 14.0, mu: 0.07, sigma: 0.20, weight: 0.20 },
    ],
    expectedReturn: 0.097,
    expectedVol: 0.286,
  },
  {
    id: 'agressivo',
    label: 'Agressivo',
    description: 'Maximiza retorno potencial aceitando alta volatilidade. Concentrado em commodities e ativos de alto beta.',
    color: '#ef4444',
    bgColor: '#ef444418',
    Icon: Bolt,
    assets: [
      { ticker: 'PETR4', S0: 40.0, mu: 0.14, sigma: 0.40, weight: 0.40 },
      { ticker: 'VALE3', S0: 65.0, mu: 0.12, sigma: 0.34, weight: 0.35 },
      { ticker: 'BBDC4', S0: 15.0, mu: 0.10, sigma: 0.30, weight: 0.25 },
    ],
    expectedReturn: 0.124,
    expectedVol: 0.368,
  },
];

// ── Types ─────────────────────────────────────────────────────────────────────

interface AssetResult {
  ticker: string;
  S0: number;
  mu: number;
  sigma: number;
  mean: number[];
  p5: number[];
  p95: number[];
  mean_pct: number[];
  terminal: {
    mean: number; std: number; p5: number; p50: number; p95: number;
    prob_above_S0: number; expected_return_pct: number;
  };
}

interface SimResult {
  T: number;
  n_steps: number;
  n_paths: number;
  time_days: number[];
  assets: AssetResult[];
}

interface ProfileResult {
  profile: Profile;
  sim: SimResult;
}

// ── Portfolio aggregation helpers ─────────────────────────────────────────────

function portfolioValue(
  sim: SimResult,
  profile: Profile,
  initial: number,
  field: 'mean' | 'p5' | 'p95'
): number[] {
  return sim.time_days.map((_, t) => {
    const portFactor = profile.assets.reduce((sum, alloc) => {
      const assetResult = sim.assets.find((a) => a.ticker === alloc.ticker);
      if (!assetResult) return sum;
      const normalised = assetResult[field][t] / alloc.S0;
      return sum + alloc.weight * normalised;
    }, 0);
    return initial * portFactor;
  });
}

function portfolioRiskMetrics(sim: SimResult, profile: Profile, initial: number) {
  const meanVals = portfolioValue(sim, profile, initial, 'mean');
  const p5Vals   = portfolioValue(sim, profile, initial, 'p5');
  const terminalMean = meanVals[meanVals.length - 1];
  const terminalP5   = p5Vals[p5Vals.length - 1];

  // Max drawdown from mean path
  let peak = meanVals[0];
  let maxDD = 0;
  for (const v of meanVals) {
    if (v > peak) peak = v;
    const dd = (peak - v) / peak;
    if (dd > maxDD) maxDD = dd;
  }

  return {
    terminalMean,
    terminalP5,
    expectedReturn: ((terminalMean / initial - 1) * 100),
    worstCase: ((terminalP5 / initial - 1) * 100),
    maxDrawdown: maxDD * 100,
    probLoss: terminalP5 < initial ? 100 * (1 - terminalP5 / initial) / 100 : 0,
  };
}

// ── Chart data builder ────────────────────────────────────────────────────────

interface ChartPoint {
  day: number;
  conservador?: number;
  moderado?: number;
  agressivo?: number;
  band_p5?: number;
  band_width?: number;
}

function buildChartData(results: ProfileResult[], initial: number): ChartPoint[] {
  const days = results[0].sim.time_days;
  return days.map((day, t) => {
    const pt: ChartPoint = { day };
    for (const { profile, sim } of results) {
      const vals = portfolioValue(sim, profile, initial, 'mean');
      pt[profile.id] = Math.round(vals[t] * 100) / 100;
    }
    return pt;
  });
}

// Downsample for perf
function downsample<T>(arr: T[], max = 300): T[] {
  if (arr.length <= max) return arr;
  const step = Math.ceil(arr.length / max);
  return arr.filter((_, i) => i % step === 0 || i === arr.length - 1);
}

// ── CSV export ────────────────────────────────────────────────────────────────

function exportCSV(chartData: ChartPoint[], initial: number, horizon: number) {
  const cols = ['Dia', 'Conservador (R$)', 'Moderado (R$)', 'Agressivo (R$)'];
  const rows = chartData.map((d) => [
    d.day,
    (d.conservador ?? '').toString(),
    (d.moderado ?? '').toString(),
    (d.agressivo ?? '').toString(),
  ]);
  const csv = [cols.join(','), ...rows.map((r) => r.join(','))].join('\n');
  const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8' }); // BOM for Excel
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `simulacao_b3_${horizon}a_R$${initial}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// ── Custom tooltip ────────────────────────────────────────────────────────────

function PortfolioTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <Box sx={{ background: '#1e1e2e', border: '1px solid #333', borderRadius: 1, p: 1.5, minWidth: 180 }}>
      <Typography variant="caption" color="text.secondary">Dia {label}</Typography>
      {payload.filter((p: any) => p.value != null && !p.name?.includes('band')).map((p: any) => (
        <Box key={p.dataKey} sx={{ display: 'flex', justifyContent: 'space-between', gap: 2 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
            <Box sx={{ width: 8, height: 8, borderRadius: '50%', background: p.color }} />
            <Typography variant="caption" sx={{ color: p.color }}>{p.name}</Typography>
          </Box>
          <Typography variant="caption" fontWeight={600}>
            R$ {Number(p.value).toLocaleString('pt-BR', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
          </Typography>
        </Box>
      ))}
    </Box>
  );
}

// ── Main Component ─────────────────────────────────────────────────────────────

export default function PerfilInvestidorPage() {
  const [selectedProfiles, setSelectedProfiles] = useState<Set<string>>(
    new Set(['conservador', 'moderado', 'agressivo'])
  );
  const [initial, setInitial] = useState(10000);
  const [horizon, setHorizon] = useState(1.0);
  const [nPaths, setNPaths] = useState(500);
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<ProfileResult[] | null>(null);
  const [error, setError] = useState('');

  const toggleProfile = (id: string) => {
    setSelectedProfiles((prev) => {
      const next = new Set(prev);
      if (next.has(id)) { if (next.size > 1) next.delete(id); }
      else next.add(id);
      return next;
    });
  };

  const runSim = async () => {
    const profilesToRun = PROFILES.filter((p) => selectedProfiles.has(p.id));
    setLoading(true);
    setError('');
    setResults(null);
    try {
      const simResults = await Promise.all(
        profilesToRun.map((profile) =>
          api.capmGbmMulti({
            assets: profile.assets.map(({ ticker, S0, mu, sigma }) => ({ ticker, S0, mu, sigma })),
            T: horizon,
            n_steps: Math.round(horizon * 252),
            n_paths: nPaths,
          }).then((sim) => ({ profile, sim: sim as SimResult }))
        )
      );
      setResults(simResults);
    } catch (e: any) {
      setError(e?.message ?? 'Erro na simulação.');
    } finally {
      setLoading(false);
    }
  };

  const chartData = results ? downsample(buildChartData(results, initial)) : [];

  return (
    <Box sx={{ p: 3, maxWidth: 1300, mx: 'auto' }}>
      {/* Header */}
      <Box sx={{ mb: 3 }}>
        <Typography variant="h4" fontWeight={700} gutterBottom>
          Dashboard B3 — Conservador ou Agressivo?
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Simulação GBM por perfil de risco. Cada perfil usa portfólios B3 pré-configurados com pesos, drift (μ) e
          volatilidade (σ) anuais distintos. Monte Carlo com {nPaths.toLocaleString()} trajetórias.
        </Typography>
      </Box>

      <Grid container spacing={3}>
        {/* ── Profile cards ──────────────────────────────────────────── */}
        {PROFILES.map((profile) => {
          const selected = selectedProfiles.has(profile.id);
          const Icon = profile.Icon;
          return (
            <Grid size={{ xs: 12, md: 4 }} key={profile.id}>
              <Card
                onClick={() => toggleProfile(profile.id)}
                sx={{
                  cursor: 'pointer',
                  border: '2px solid',
                  borderColor: selected ? profile.color : 'divider',
                  background: selected ? profile.bgColor : 'background.paper',
                  transition: 'all 0.15s',
                  '&:hover': { borderColor: profile.color },
                  position: 'relative',
                }}
              >
                {selected && (
                  <CheckCircle
                    sx={{ position: 'absolute', top: 10, right: 10, color: profile.color, fontSize: 20 }}
                  />
                )}
                <CardContent>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                    <Icon sx={{ color: profile.color, fontSize: 28 }} />
                    <Typography variant="h6" fontWeight={700} sx={{ color: profile.color }}>
                      {profile.label}
                    </Typography>
                  </Box>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 2, minHeight: 48 }}>
                    {profile.description}
                  </Typography>
                  <Divider sx={{ mb: 1.5 }} />
                  {/* Asset allocation */}
                  {profile.assets.map((a) => (
                    <Box key={a.ticker} sx={{ mb: 0.8 }}>
                      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.3 }}>
                        <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
                          <Typography variant="caption" fontWeight={600}>{a.ticker}</Typography>
                          <Typography variant="caption" color="text.secondary">
                            μ={( a.mu * 100).toFixed(0)}% σ={(a.sigma * 100).toFixed(0)}%
                          </Typography>
                        </Box>
                        <Typography variant="caption" fontWeight={600} sx={{ color: profile.color }}>
                          {(a.weight * 100).toFixed(0)}%
                        </Typography>
                      </Box>
                      <LinearProgress
                        variant="determinate"
                        value={a.weight * 100}
                        sx={{
                          height: 4,
                          borderRadius: 2,
                          backgroundColor: profile.color + '22',
                          '& .MuiLinearProgress-bar': { backgroundColor: profile.color },
                        }}
                      />
                    </Box>
                  ))}
                  <Divider sx={{ my: 1.5 }} />
                  <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
                    <Box>
                      <Typography variant="caption" color="text.secondary">Ret. esperado/ano</Typography>
                      <Typography variant="body2" fontWeight={700} sx={{ color: profile.color }}>
                        +{(profile.expectedReturn * 100).toFixed(1)}%
                      </Typography>
                    </Box>
                    <Box>
                      <Typography variant="caption" color="text.secondary">Volatilidade/ano</Typography>
                      <Typography variant="body2" fontWeight={700}>
                        {(profile.expectedVol * 100).toFixed(0)}%
                      </Typography>
                    </Box>
                  </Box>
                </CardContent>
              </Card>
            </Grid>
          );
        })}

        {/* ── Controls ────────────────────────────────────────────────── */}
        <Grid size={{ xs: 12 }}>
          <Card>
            <CardContent sx={{ display: 'flex', gap: 3, flexWrap: 'wrap', alignItems: 'center' }}>
              <TextField
                label="Capital inicial (R$)"
                type="number"
                value={initial}
                onChange={(e) => setInitial(Math.max(100, Number(e.target.value)))}
                size="small"
                sx={{ width: 180 }}
                inputProps={{ min: 100, step: 1000 }}
              />
              <Box sx={{ minWidth: 200 }}>
                <Typography variant="caption" color="text.secondary">
                  Horizonte: {horizon === 1 ? '1 ano' : `${horizon} anos`}
                </Typography>
                <Box sx={{ display: 'flex', gap: 1, mt: 0.5 }}>
                  {[0.5, 1, 2, 3, 5].map((h) => (
                    <Chip
                      key={h}
                      label={h < 1 ? '6m' : `${h}a`}
                      size="small"
                      variant={horizon === h ? 'filled' : 'outlined'}
                      onClick={() => setHorizon(h)}
                      sx={{ cursor: 'pointer' }}
                    />
                  ))}
                </Box>
              </Box>
              <Box sx={{ minWidth: 160 }}>
                <Typography variant="caption" color="text.secondary">Simulações</Typography>
                <Box sx={{ display: 'flex', gap: 1, mt: 0.5 }}>
                  {[200, 500, 1000].map((n) => (
                    <Chip
                      key={n}
                      label={n >= 1000 ? '1k' : String(n)}
                      size="small"
                      variant={nPaths === n ? 'filled' : 'outlined'}
                      onClick={() => setNPaths(n)}
                      sx={{ cursor: 'pointer' }}
                    />
                  ))}
                </Box>
              </Box>
              <Button
                variant="contained"
                size="large"
                startIcon={loading ? <CircularProgress size={18} color="inherit" /> : <PlayArrow />}
                onClick={runSim}
                disabled={loading}
                sx={{ ml: 'auto', px: 4 }}
              >
                Rodar Simulação
              </Button>
              {results && (
                <Button
                  variant="outlined"
                  startIcon={<Download />}
                  onClick={() => exportCSV(downsample(buildChartData(results, initial), 10000), initial, horizon)}
                >
                  Baixar Excel / CSV
                </Button>
              )}
            </CardContent>
          </Card>
        </Grid>

        {error && (
          <Grid size={{ xs: 12 }}>
            <Alert severity="error">{error}</Alert>
          </Grid>
        )}

        {loading && (
          <Grid size={{ xs: 12 }}>
            <Card sx={{ p: 4, textAlign: 'center' }}>
              <CircularProgress size={48} sx={{ mb: 2 }} />
              <Typography color="text.secondary">
                Simulando {nPaths.toLocaleString()} trajetórias por perfil…
              </Typography>
            </Card>
          </Grid>
        )}

        {/* ── Comparison chart ─────────────────────────────────────────── */}
        {results && !loading && (
          <Grid size={{ xs: 12 }}>
            <Card>
              <CardContent>
                <Typography variant="subtitle1" fontWeight={600} gutterBottom>
                  Evolução do portfólio — Capital R${' '}
                  {initial.toLocaleString('pt-BR')} ao longo de{' '}
                  {horizon === 1 ? '1 ano' : `${horizon} anos`}
                </Typography>
                <Typography variant="caption" color="text.secondary" sx={{ mb: 2, display: 'block' }}>
                  Trajetória média por perfil. Bandas não exibidas para legibilidade — veja detalhes na tabela abaixo.
                </Typography>
                <ResponsiveContainer width="100%" height={380}>
                  <AreaChart data={chartData} margin={{ top: 10, right: 20, left: 20, bottom: 10 }}>
                    <defs>
                      {results.map(({ profile }) => (
                        <linearGradient key={profile.id} id={`pfgrad-${profile.id}`} x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%"  stopColor={profile.color} stopOpacity={0.28} />
                          <stop offset="85%" stopColor={profile.color} stopOpacity={0.02} />
                        </linearGradient>
                      ))}
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" opacity={0.08} />
                    <XAxis dataKey="day"
                      label={{ value: 'Dias', position: 'insideBottom', offset: -4, fontSize: 11 }}
                      tick={{ fontSize: 11 }} />
                    <YAxis
                      tickFormatter={(v) => v >= 1000 ? `R$${(v / 1000).toFixed(0)}k` : `R$${v.toFixed(0)}`}
                      tick={{ fontSize: 11 }} />
                    <RTooltip content={<PortfolioTooltip />} />
                    <Legend />
                    <ReferenceLine y={initial} stroke="#555" strokeDasharray="5 5"
                      label={{ value: 'Capital inicial', fontSize: 10, fill: '#777', position: 'insideTopRight' }} />
                    {results.map(({ profile }) => (
                      <Area key={profile.id} type="monotone" dataKey={profile.id}
                        name={profile.label} stroke={profile.color} strokeWidth={2.5}
                        fill={`url(#pfgrad-${profile.id})`} dot={false}
                        activeDot={{ r: 5, fill: profile.color }} />
                    ))}
                  </AreaChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          </Grid>
        )}

        {/* ── Risk metrics table ────────────────────────────────────────── */}
        {results && !loading && (
          <Grid size={{ xs: 12 }}>
            <Card>
              <CardContent>
                <Typography variant="subtitle1" fontWeight={600} gutterBottom>
                  Métricas por Perfil — Capital R$ {initial.toLocaleString('pt-BR')} / Horizonte{' '}
                  {horizon === 1 ? '1 ano' : `${horizon} anos`}
                </Typography>
                <Box sx={{ overflowX: 'auto' }}>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>Perfil</TableCell>
                        <TableCell align="right">Capital Final (média)</TableCell>
                        <TableCell align="right">Retorno Esperado</TableCell>
                        <TableCell align="right">Pior Caso (P5)</TableCell>
                        <TableCell align="right">Capital Mínimo P5</TableCell>
                        <TableCell align="right">Drawdown Máx.</TableCell>
                        <TableCell align="right">Ativos</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {results.map(({ profile, sim }) => {
                        const m = portfolioRiskMetrics(sim, profile, initial);
                        return (
                          <TableRow key={profile.id}>
                            <TableCell>
                              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                <Box sx={{ width: 10, height: 10, borderRadius: '50%', background: profile.color }} />
                                <Typography variant="body2" fontWeight={700} sx={{ color: profile.color }}>
                                  {profile.label}
                                </Typography>
                              </Box>
                            </TableCell>
                            <TableCell align="right" sx={{ fontWeight: 700 }}>
                              R$ {m.terminalMean.toLocaleString('pt-BR', { maximumFractionDigits: 0 })}
                            </TableCell>
                            <TableCell
                              align="right"
                              sx={{ color: m.expectedReturn >= 0 ? 'success.main' : 'error.main', fontWeight: 700 }}
                            >
                              {m.expectedReturn > 0 ? '+' : ''}{m.expectedReturn.toFixed(1)}%
                            </TableCell>
                            <TableCell
                              align="right"
                              sx={{ color: m.worstCase >= 0 ? 'success.main' : 'error.main' }}
                            >
                              {m.worstCase > 0 ? '+' : ''}{m.worstCase.toFixed(1)}%
                            </TableCell>
                            <TableCell align="right" sx={{ color: 'text.secondary' }}>
                              R$ {m.terminalP5.toLocaleString('pt-BR', { maximumFractionDigits: 0 })}
                            </TableCell>
                            <TableCell align="right" sx={{ color: 'warning.main' }}>
                              -{m.maxDrawdown.toFixed(1)}%
                            </TableCell>
                            <TableCell align="right">
                              <Box sx={{ display: 'flex', gap: 0.5, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
                                {profile.assets.map((a) => (
                                  <Chip
                                    key={a.ticker}
                                    label={`${a.ticker} ${(a.weight * 100).toFixed(0)}%`}
                                    size="small"
                                    sx={{ fontSize: 10, background: profile.color + '20', color: profile.color }}
                                  />
                                ))}
                              </Box>
                            </TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                </Box>
                <Typography variant="caption" color="text.secondary" sx={{ mt: 1.5, display: 'block' }}>
                  Pior Caso = percentil 5% da distribuição terminal. Drawdown calculado sobre a trajetória média.
                  GBM assume retornos log-normais — não captura fat tails. Para risco de cauda use a aba{' '}
                  <strong>EVT</strong>.
                </Typography>
              </CardContent>
            </Card>
          </Grid>
        )}
      </Grid>
    </Box>
  );
}
