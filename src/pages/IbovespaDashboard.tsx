import React, { useState } from 'react';
import {
  Box, Grid, Card, CardContent, Typography, Button, CircularProgress,
  Alert, Chip, TextField, Table, TableBody, TableCell, TableHead,
  TableRow, Divider, LinearProgress, ToggleButton, ToggleButtonGroup,
  Stepper, Step, StepLabel, Tooltip as MuiTooltip,
} from '@mui/material';
import {
  PlayArrow, Download, Shield, Bolt, AutoGraph, CheckCircle,
  TrendingUp, TrendingDown, ShowChart,
} from '@mui/icons-material';
import {
  ComposedChart, AreaChart, Area, Line, XAxis, YAxis, CartesianGrid,
  Tooltip as RTooltip, Legend, ResponsiveContainer, ReferenceLine,
  LineChart, PieChart, Pie, Cell, RadarChart, Radar, PolarGrid,
  PolarAngleAxis, PolarRadiusAxis,
} from 'recharts';
import { api } from '../services/api';

// ── Constants ─────────────────────────────────────────────────────────────────

const PROFILE_CFG = {
  conservador: {
    label: 'Conservador',
    color: '#22c55e',
    bg: '#22c55e18',
    Icon: Shield,
    desc: 'Maximiza Sharpe com penalidade de volatilidade. Prefere ativos defensivos e dividendos.',
    radarColor: '#22c55e',
  },
  agressivo: {
    label: 'Agressivo',
    color: '#ef4444',
    bg: '#ef444418',
    Icon: Bolt,
    desc: 'Maximiza retorno esperado com bônus de Sharpe. Aceita alta volatilidade em busca de ganho.',
    radarColor: '#ef4444',
  },
} as const;

type ProfileKey = keyof typeof PROFILE_CFG;

const SECTOR_COLORS: Record<string, string> = {
  'Energia': '#f97316', 'Mineração': '#6366f1', 'Financeiro': '#3b82f6',
  'Consumo': '#22c55e', 'Industrial': '#8b5cf6', 'Mobilidade': '#14b8a6',
  'Saúde': '#ec4899', 'Siderurgia': '#64748b', 'Alimentos': '#a3e635',
  'Varejo': '#fbbf24', 'Papel/Celulose': '#84cc16',
};

// ── Types ─────────────────────────────────────────────────────────────────────

interface AllocItem {
  ticker: string; sector: string; weight_pct: number;
  allocation_brl: number; mu_pct: number; sigma_pct: number;
  expected_return_pct: number;
}

interface AssetResult {
  ticker: string; sector: string; S0: number; mu: number; sigma: number;
  mean: number[]; p5: number[]; p95: number[];
  mean_pct: number[];
  terminal: { mean: number; p5: number; p95: number; expected_return_pct: number; prob_above_S0: number };
}

interface RLResult {
  profile: string; initial_capital: number;
  algorithm: string; iterations: number;
  portfolio_metrics: {
    expected_return_ann_pct: number; volatility_ann_pct: number;
    sharpe_ratio: number; expected_terminal_capital: number;
  };
  reward_convergence: number[];
  allocation: AllocItem[];
  simulation: { T: number; n_steps: number; n_paths: number; time_days: number[]; assets: AssetResult[] };
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function buildPortfolioChart(result: RLResult): Array<Record<string, number>> {
  const { time_days, assets } = result.simulation;
  const weights = result.allocation.reduce<Record<string, number>>((acc, a) => {
    acc[a.ticker] = a.weight_pct / 100;
    return acc;
  }, {});
  const initial = result.initial_capital;
  return time_days.map((day, t) => {
    const portFactor = assets.reduce((sum, a) => sum + (weights[a.ticker] ?? 0) * (a.mean[t] / a.S0), 0);
    return { day, value: Math.round(initial * portFactor) };
  });
}

function buildSectorPie(allocation: AllocItem[]) {
  const sectorMap: Record<string, number> = {};
  allocation.forEach((a) => {
    sectorMap[a.sector] = (sectorMap[a.sector] ?? 0) + a.weight_pct;
  });
  return Object.entries(sectorMap)
    .map(([sector, value]) => ({ sector, value: parseFloat(value.toFixed(1)) }))
    .sort((a, b) => b.value - a.value);
}

function buildRadarData(result: RLResult) {
  const m = result.portfolio_metrics;
  const alloc = result.allocation;
  const n = alloc.length;
  // Effective N — higher = more diversified
  const hhi = alloc.reduce((s, a) => s + (a.weight_pct / 100) ** 2, 0);
  const effectiveN = Math.round(1 / hhi);

  return [
    { axis: 'Retorno', value: Math.min(100, Math.max(0, m.expected_return_ann_pct * 4)) },
    { axis: 'Sharpe',  value: Math.min(100, Math.max(0, m.sharpe_ratio * 25)) },
    { axis: 'Baixa Vol', value: Math.min(100, Math.max(0, 100 - m.volatility_ann_pct * 2)) },
    { axis: 'Diversif.', value: Math.min(100, (effectiveN / n) * 100) },
    { axis: 'Estabilid.', value: Math.min(100, Math.max(0, 80 - m.volatility_ann_pct)) },
  ];
}

function buildRewardChart(history: number[]) {
  return history.map((r, i) => ({ iter: i * 5, reward: parseFloat(r.toFixed(4)) }));
}

function buildAssetChart(result: RLResult) {
  return result.simulation.time_days.map((day, t) => {
    const pt: Record<string, number> = { day };
    result.allocation.slice(0, 6).forEach((alloc) => {
      const a = result.simulation.assets.find((x) => x.ticker === alloc.ticker);
      if (a) pt[a.ticker] = parseFloat(((a.mean[t] / a.S0 - 1) * 100).toFixed(2));
    });
    return pt;
  });
}

function downsample<T>(arr: T[], max = 200): T[] {
  if (arr.length <= max) return arr;
  const step = Math.ceil(arr.length / max);
  return arr.filter((_, i) => i % step === 0 || i === arr.length - 1);
}

function downloadExcel(initial: number, profile: ProfileKey, nPaths: number, T: number) {
  const BASE = (import.meta as any).env?.VITE_API_URL ?? 'http://localhost:8000/api';
  fetch(`${BASE}/ibovespa/export-excel`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ profile, n_paths: nPaths, T, initial_capital: initial }),
  })
    .then((r) => r.blob())
    .then((blob) => {
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `b3_18ativos_${profile}_R${initial}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    });
}

// ── Tooltip components ────────────────────────────────────────────────────────

function ValTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  const v = payload[0]?.value;
  return (
    <Box sx={{ background: '#161622', border: '1px solid #2a2a3a', borderRadius: 1.5, p: 1.5 }}>
      <Typography variant="caption" color="text.secondary">Dia {label}</Typography>
      {v != null && (
        <Typography variant="body2" fontWeight={700} color="primary">
          R$ {Number(v).toLocaleString('pt-BR', { maximumFractionDigits: 0 })}
        </Typography>
      )}
    </Box>
  );
}

function AssetTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <Box sx={{ background: '#161622', border: '1px solid #2a2a3a', borderRadius: 1.5, p: 1.5, minWidth: 160 }}>
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.5 }}>Dia {label}</Typography>
      {payload.map((p: any) => (
        <Box key={p.dataKey} sx={{ display: 'flex', justifyContent: 'space-between', gap: 2, mb: 0.25 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
            <Box sx={{ width: 6, height: 6, borderRadius: '50%', background: p.color }} />
            <Typography variant="caption" sx={{ color: p.color }}>{p.dataKey}</Typography>
          </Box>
          <Typography variant="caption" fontWeight={600}>
            {Number(p.value) > 0 ? '+' : ''}{Number(p.value).toFixed(1)}%
          </Typography>
        </Box>
      ))}
    </Box>
  );
}

function PieLabelCustom({ cx, cy, midAngle, innerRadius, outerRadius, sector, value }: any) {
  const RADIAN = Math.PI / 180;
  const radius = innerRadius + (outerRadius - innerRadius) * 0.5;
  const x = cx + radius * Math.cos(-midAngle * RADIAN);
  const y = cy + radius * Math.sin(-midAngle * RADIAN);
  if (value < 6) return null;
  return (
    <text x={x} y={y} fill="white" textAnchor="middle" dominantBaseline="central" fontSize={10} fontWeight={600}>
      {`${value.toFixed(0)}%`}
    </text>
  );
}

const STEPS = ['Parâmetros', 'Rodando RL', 'Resultados'];

// ── Main Component ─────────────────────────────────────────────────────────────

export default function IbovespaDashboard() {
  const [profile, setProfile] = useState<ProfileKey>('conservador');
  const [capital, setCapital] = useState(100_000);
  const [nPaths, setNPaths] = useState(500);
  const [horizon, setHorizon] = useState(1.0);
  const [loading, setLoading] = useState(false);
  const [step, setStep] = useState(0);
  const [result, setResult] = useState<RLResult | null>(null);
  const [error, setError] = useState('');
  const [chartMode, setChartMode] = useState<'portfolio' | 'assets' | 'reward' | 'sector' | 'radar'>('portfolio');

  const cfg = PROFILE_CFG[profile];
  const CfgIcon = cfg.Icon;

  const run = async () => {
    setLoading(true);
    setError('');
    setResult(null);
    setStep(1);
    try {
      const data = await api.ibovespaRLOptimize({
        profile, n_paths: nPaths, T: horizon, n_iterations: 60, initial_capital: capital,
      }) as RLResult;
      setResult(data);
      setStep(2);
      setChartMode('portfolio');
    } catch (e: any) {
      setError(e?.message ?? 'Erro na otimização RL.');
      setStep(0);
    } finally {
      setLoading(false);
    }
  };

  const loadDemo = async () => {
    setLoading(true);
    setError('');
    setStep(1);
    try {
      const data = await api.ibovespaRLOptimize({
        profile: 'conservador', n_paths: 300, T: 1.0, n_iterations: 40, initial_capital: 100_000,
      }) as RLResult;
      setResult(data);
      setProfile('conservador');
      setCapital(100_000);
      setStep(2);
      setChartMode('portfolio');
    } catch (e: any) {
      setError(e?.message ?? 'Erro no demo.');
      setStep(0);
    } finally {
      setLoading(false);
    }
  };

  // Chart data
  const portfolioChart = result ? downsample(buildPortfolioChart(result)) : [];
  const rewardChart    = result ? buildRewardChart(result.reward_convergence) : [];
  const assetChart     = result ? downsample(buildAssetChart(result)) : [];
  const sectorPie      = result ? buildSectorPie(result.allocation) : [];
  const radarData      = result ? buildRadarData(result) : [];
  const gradId         = `grad-${profile}`;

  return (
    <Box sx={{ p: 3, maxWidth: 1400, mx: 'auto' }}>
      {/* Header */}
      <Box sx={{ mb: 3 }}>
        <Typography variant="h4" fontWeight={700} gutterBottom>
          Dashboard B3 — 18 Ativos Ibovespa
        </Typography>
        <Typography variant="body2" color="text.secondary">
          GBM correlacionado (Cholesky) + otimização por{' '}
          <strong>Cross-Entropy Method</strong> (RL policy search).
          O agente aprende pesos ótimos iterativamente, sem gradientes, maximizando Sharpe
          ponderado pelo perfil.
        </Typography>
      </Box>

      <Stepper activeStep={step} sx={{ mb: 3 }}>
        {STEPS.map((s, i) => (
          <Step key={s} completed={step > i}>
            <StepLabel>{s}</StepLabel>
          </Step>
        ))}
      </Stepper>

      <Grid container spacing={3}>
        {/* ── Left panel ───────────────────────────────────────────────── */}
        <Grid size={{ xs: 12, md: 3 }}>
          {/* Profile cards */}
          <Card sx={{ mb: 2 }}>
            <CardContent>
              <Typography variant="subtitle1" fontWeight={600} gutterBottom>Perfil de Risco</Typography>
              {(['conservador', 'agressivo'] as ProfileKey[]).map((p) => {
                const c = PROFILE_CFG[p];
                const PIcon = c.Icon;
                const sel = profile === p;
                return (
                  <Card key={p} onClick={() => setProfile(p)} sx={{
                    mb: 1.5, cursor: 'pointer', border: '2px solid',
                    borderColor: sel ? c.color : 'divider',
                    background: sel ? c.bg : 'background.paper',
                    transition: 'border-color 0.15s, background 0.15s',
                    '&:hover': { borderColor: c.color },
                  }}>
                    <CardContent sx={{ p: '12px !important' }}>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                        {sel
                          ? <CheckCircle sx={{ color: c.color, fontSize: 18 }} />
                          : <PIcon sx={{ color: c.color, fontSize: 18 }} />}
                        <Typography variant="body2" fontWeight={700} sx={{ color: c.color }}>{c.label}</Typography>
                      </Box>
                      <Typography variant="caption" color="text.secondary">{c.desc}</Typography>
                    </CardContent>
                  </Card>
                );
              })}
            </CardContent>
          </Card>

          {/* Parameters */}
          <Card>
            <CardContent>
              <Typography variant="subtitle1" fontWeight={600} gutterBottom>Parâmetros</Typography>
              <TextField label="Capital (R$)" type="number" value={capital}
                onChange={(e) => setCapital(Math.max(1000, Number(e.target.value)))}
                size="small" fullWidth sx={{ mb: 2 }} inputProps={{ min: 1000, step: 10000 }} />

              <Typography variant="caption" color="text.secondary">
                Horizonte: {horizon < 1 ? '6 meses' : `${horizon} ano${horizon > 1 ? 's' : ''}`}
              </Typography>
              <Box sx={{ display: 'flex', gap: 0.5, mt: 0.5, mb: 2, flexWrap: 'wrap' }}>
                {[0.5, 1, 2, 3, 5].map((h) => (
                  <Chip key={h} label={h < 1 ? '6m' : `${h}a`} size="small"
                    variant={horizon === h ? 'filled' : 'outlined'}
                    onClick={() => setHorizon(h)} sx={{ cursor: 'pointer' }} />
                ))}
              </Box>

              <Typography variant="caption" color="text.secondary">Simulações MC</Typography>
              <Box sx={{ display: 'flex', gap: 0.5, mt: 0.5, mb: 2 }}>
                {[200, 500, 1000].map((n) => (
                  <Chip key={n} label={n >= 1000 ? '1k' : String(n)} size="small"
                    variant={nPaths === n ? 'filled' : 'outlined'}
                    onClick={() => setNPaths(n)} sx={{ cursor: 'pointer' }} />
                ))}
              </Box>

              <Button variant="contained" fullWidth size="large" sx={{ mb: 1,
                background: `linear-gradient(135deg, ${cfg.color}, ${cfg.color}bb)`,
                '&:hover': { background: cfg.color } }}
                startIcon={loading ? <CircularProgress size={18} color="inherit" /> : <PlayArrow />}
                onClick={run} disabled={loading}>
                Rodar Simulação + RL
              </Button>
              <Button variant="outlined" fullWidth startIcon={<AutoGraph />}
                onClick={loadDemo} disabled={loading} sx={{ mb: 1 }}>
                Demo B3
              </Button>
              {result && (
                <Button variant="outlined" fullWidth startIcon={<Download />}
                  onClick={() => downloadExcel(capital, profile, nPaths, horizon)}>
                  Baixar Excel
                </Button>
              )}
            </CardContent>
          </Card>
        </Grid>

        {/* ── Main area ─────────────────────────────────────────────────── */}
        <Grid size={{ xs: 12, md: 9 }}>
          {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

          {/* Loading */}
          {loading && (
            <Card sx={{ height: 340, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 2 }}>
              <CircularProgress size={56} sx={{ color: cfg.color }} thickness={3} />
              <Box textAlign="center">
                <Typography variant="body1" fontWeight={600}>Otimizando portfólio…</Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                  {nPaths.toLocaleString()} trajetórias × 60 iterações CEM
                </Typography>
              </Box>
            </Card>
          )}

          {/* Empty state */}
          {!result && !loading && (
            <Card sx={{ height: 340, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Box textAlign="center">
                <CfgIcon sx={{ fontSize: 80, opacity: 0.12, color: cfg.color, mb: 1 }} />
                <Typography variant="h6" color="text.secondary" fontWeight={500}>
                  Configure o perfil e capital
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                  Clique em <strong>Rodar Simulação + RL</strong> ou use o <strong>Demo B3</strong>
                </Typography>
              </Box>
            </Card>
          )}

          {result && !loading && (
            <>
              {/* KPI bar */}
              <Grid container spacing={2} sx={{ mb: 2 }}>
                {[
                  {
                    label: 'Retorno Esperado', sub: 'RL otimizado',
                    value: `+${result.portfolio_metrics.expected_return_ann_pct.toFixed(1)}%`,
                    icon: <TrendingUp />, color: 'success.main',
                  },
                  {
                    label: 'Volatilidade a.a.', sub: 'desvio padrão',
                    value: `${result.portfolio_metrics.volatility_ann_pct.toFixed(1)}%`,
                    icon: <ShowChart />, color: 'warning.main',
                  },
                  {
                    label: 'Sharpe Ratio', sub: cfg.label,
                    value: result.portfolio_metrics.sharpe_ratio.toFixed(3),
                    icon: <AutoGraph />, color: cfg.color,
                  },
                  {
                    label: 'Capital Esperado', sub: `em ${horizon < 1 ? '6m' : `${horizon}a`}`,
                    value: `R$ ${result.portfolio_metrics.expected_terminal_capital.toLocaleString('pt-BR', { maximumFractionDigits: 0 })}`,
                    icon: result.portfolio_metrics.expected_terminal_capital > capital
                      ? <TrendingUp /> : <TrendingDown />,
                    color: result.portfolio_metrics.expected_terminal_capital > capital ? 'success.main' : 'error.main',
                  },
                ].map((kpi) => (
                  <Grid size={{ xs: 6, md: 3 }} key={kpi.label}>
                    <Card sx={{ border: '1px solid', borderColor: 'divider',
                      background: 'background.paper', height: '100%' }}>
                      <CardContent sx={{ p: '14px !important' }}>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 0.5 }}>
                          <Box sx={{ color: kpi.color, display: 'flex', '& svg': { fontSize: 16 } }}>{kpi.icon}</Box>
                          <Typography variant="caption" color="text.secondary">{kpi.label}</Typography>
                        </Box>
                        <Typography variant="h6" fontWeight={800} sx={{ color: kpi.color, lineHeight: 1.2 }}>
                          {kpi.value}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">{kpi.sub}</Typography>
                      </CardContent>
                    </Card>
                  </Grid>
                ))}
              </Grid>

              {/* Chart toggle */}
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1.5 }}>
                <ToggleButtonGroup value={chartMode} exclusive
                  onChange={(_, v) => v && setChartMode(v)} size="small">
                  <ToggleButton value="portfolio">Portfólio (R$)</ToggleButton>
                  <ToggleButton value="assets">Top 6 (%)</ToggleButton>
                  <ToggleButton value="sector">Setores</ToggleButton>
                  <ToggleButton value="radar">Perfil</ToggleButton>
                  <ToggleButton value="reward">CEM RL</ToggleButton>
                </ToggleButtonGroup>
              </Box>

              <Card sx={{ mb: 2 }}>
                <CardContent>

                  {/* ── Portfolio value chart with gradient ── */}
                  {chartMode === 'portfolio' && (
                    <>
                      <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                        Evolução do portfólio otimizado — trajetória média
                      </Typography>
                      <ResponsiveContainer width="100%" height={340}>
                        <AreaChart data={portfolioChart} margin={{ top: 10, right: 20, left: 20, bottom: 10 }}>
                          <defs>
                            <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
                              <stop offset="5%"  stopColor={cfg.color} stopOpacity={0.35} />
                              <stop offset="80%" stopColor={cfg.color} stopOpacity={0.02} />
                            </linearGradient>
                          </defs>
                          <CartesianGrid strokeDasharray="3 3" opacity={0.08} />
                          <XAxis dataKey="day" tick={{ fontSize: 11 }}
                            label={{ value: 'Dias', position: 'insideBottom', offset: -4, fontSize: 11 }} />
                          <YAxis
                            tickFormatter={(v) => v >= 1000 ? `R$${(v / 1000).toFixed(0)}k` : `R$${v}`}
                            tick={{ fontSize: 11 }} />
                          <RTooltip content={<ValTooltip />} />
                          <ReferenceLine y={capital} stroke="#555" strokeDasharray="5 5"
                            label={{ value: 'Capital inicial', fontSize: 10, fill: '#777', position: 'insideTopRight' }} />
                          <Area type="monotone" dataKey="value" name={cfg.label}
                            stroke={cfg.color} strokeWidth={2.5}
                            fill={`url(#${gradId})`} dot={false} activeDot={{ r: 5, fill: cfg.color }} />
                        </AreaChart>
                      </ResponsiveContainer>
                    </>
                  )}

                  {/* ── Top-6 assets % ── */}
                  {chartMode === 'assets' && (
                    <>
                      <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                        Retorno acumulado % — Top 6 ativos do portfólio
                      </Typography>
                      <ResponsiveContainer width="100%" height={340}>
                        <LineChart data={assetChart} margin={{ top: 10, right: 20, left: 10, bottom: 10 }}>
                          <CartesianGrid strokeDasharray="3 3" opacity={0.08} />
                          <XAxis dataKey="day" tick={{ fontSize: 11 }} />
                          <YAxis tickFormatter={(v) => `${v > 0 ? '+' : ''}${v.toFixed(0)}%`} tick={{ fontSize: 11 }} />
                          <RTooltip content={<AssetTooltip />} />
                          <Legend />
                          <ReferenceLine y={0} stroke="#444" strokeDasharray="4 4" />
                          {result.allocation.slice(0, 6).map((a) => (
                            <Line key={a.ticker} type="monotone" dataKey={a.ticker}
                              stroke={SECTOR_COLORS[a.sector] ?? '#6366f1'}
                              strokeWidth={2} dot={false} />
                          ))}
                        </LineChart>
                      </ResponsiveContainer>
                    </>
                  )}

                  {/* ── Sector Pie ── */}
                  {chartMode === 'sector' && (
                    <Box sx={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'center' }}>
                      <Box>
                        <Typography variant="subtitle2" color="text.secondary" gutterBottom textAlign="center">
                          Distribuição por Setor
                        </Typography>
                        <PieChart width={300} height={300}>
                          <Pie data={sectorPie} cx={150} cy={150} innerRadius={70} outerRadius={130}
                            dataKey="value" nameKey="sector" paddingAngle={2}
                            labelLine={false} label={<PieLabelCustom />}>
                            {sectorPie.map((entry) => (
                              <Cell key={entry.sector}
                                fill={SECTOR_COLORS[entry.sector] ?? '#6366f1'}
                                stroke="none" />
                            ))}
                          </Pie>
                          <RTooltip formatter={(v: any, name: any) => [`${Number(v).toFixed(1)}%`, name]} />
                        </PieChart>
                      </Box>
                      <Box sx={{ flex: 1, minWidth: 180 }}>
                        <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                          Legenda
                        </Typography>
                        {sectorPie.map((s) => (
                          <Box key={s.sector} sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.8 }}>
                            <Box sx={{ width: 12, height: 12, borderRadius: '50%',
                              background: SECTOR_COLORS[s.sector] ?? '#6366f1', flexShrink: 0 }} />
                            <Typography variant="body2" sx={{ flex: 1 }}>{s.sector}</Typography>
                            <Typography variant="body2" fontWeight={700}
                              sx={{ color: SECTOR_COLORS[s.sector] ?? '#6366f1' }}>
                              {s.value.toFixed(1)}%
                            </Typography>
                          </Box>
                        ))}
                      </Box>
                    </Box>
                  )}

                  {/* ── Radar profile ── */}
                  {chartMode === 'radar' && (
                    <>
                      <Typography variant="subtitle2" color="text.secondary" gutterBottom textAlign="center">
                        Perfil do Portfólio — Radar CEM
                      </Typography>
                      <Box sx={{ display: 'flex', justifyContent: 'center' }}>
                        <RadarChart cx={200} cy={170} outerRadius={130} width={400} height={340} data={radarData}>
                          <PolarGrid stroke="#2a2a3a" />
                          <PolarAngleAxis dataKey="axis" tick={{ fill: '#aaa', fontSize: 12, fontWeight: 600 }} />
                          <PolarRadiusAxis angle={90} domain={[0, 100]} tick={false} axisLine={false} />
                          <Radar name={cfg.label} dataKey="value"
                            stroke={cfg.color} fill={cfg.color} fillOpacity={0.25} strokeWidth={2} />
                          <RTooltip formatter={(v: any) => [`${Number(v).toFixed(0)}/100`]} />
                          <Legend />
                        </RadarChart>
                      </Box>
                      <Typography variant="caption" color="text.secondary" textAlign="center" display="block">
                        Diversificação = 1 / HHI normalizado. Estabilidade inversamente proporcional à volatilidade.
                      </Typography>
                    </>
                  )}

                  {/* ── CEM convergence ── */}
                  {chartMode === 'reward' && (
                    <>
                      <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                        Convergência da recompensa CEM — Cross-Entropy Method (a cada 5 iterações)
                      </Typography>
                      <ResponsiveContainer width="100%" height={340}>
                        <AreaChart data={rewardChart} margin={{ top: 10, right: 20, left: 10, bottom: 10 }}>
                          <defs>
                            <linearGradient id="grad-reward" x1="0" y1="0" x2="0" y2="1">
                              <stop offset="5%"  stopColor="#6366f1" stopOpacity={0.35} />
                              <stop offset="90%" stopColor="#6366f1" stopOpacity={0.02} />
                            </linearGradient>
                          </defs>
                          <CartesianGrid strokeDasharray="3 3" opacity={0.08} />
                          <XAxis dataKey="iter" tick={{ fontSize: 11 }}
                            label={{ value: 'Iteração', position: 'insideBottom', offset: -4, fontSize: 11 }} />
                          <YAxis tick={{ fontSize: 11 }} />
                          <RTooltip formatter={(v: any) => [Number(v).toFixed(4), 'Recompensa']} />
                          <Area type="monotone" dataKey="reward" stroke="#6366f1" strokeWidth={2}
                            fill="url(#grad-reward)" dot={{ r: 3, fill: '#6366f1' }} name="Recompensa" />
                        </AreaChart>
                      </ResponsiveContainer>
                      <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
                        Cada iteração: 300 amostras Dirichlet → avalição por Sharpe (
                        {profile === 'conservador' ? 'penalidade de vol' : 'bônus de retorno'}
                        ) → elite 20% → atualização por Method of Moments.
                      </Typography>
                    </>
                  )}
                </CardContent>
              </Card>

              {/* Allocation table */}
              <Card>
                <CardContent>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1.5 }}>
                    <Typography variant="subtitle1" fontWeight={600}>
                      Alocação RL —{' '}
                      <Chip label={cfg.label} size="small"
                        sx={{ background: cfg.bg, color: cfg.color, fontWeight: 700 }} />
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      {result.allocation.length} ativos · {result.simulation.n_paths.toLocaleString()} simulações
                    </Typography>
                  </Box>
                  <Box sx={{ overflowX: 'auto' }}>
                    <Table size="small">
                      <TableHead>
                        <TableRow>
                          <TableCell>Ativo</TableCell>
                          <TableCell>Setor</TableCell>
                          <TableCell align="right">Peso RL</TableCell>
                          <TableCell align="right">Alocação (R$)</TableCell>
                          <TableCell align="right">μ a.a.</TableCell>
                          <TableCell align="right">σ a.a.</TableCell>
                          <TableCell align="right">Ret. Esp.</TableCell>
                          <TableCell sx={{ minWidth: 100 }}>Distribuição</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {result.allocation.map((a) => (
                          <TableRow key={a.ticker}
                            sx={{ '&:hover': { background: 'action.hover' } }}>
                            <TableCell>
                              <Typography variant="body2" fontWeight={700}>{a.ticker}</Typography>
                            </TableCell>
                            <TableCell>
                              <Chip label={a.sector} size="small"
                                sx={{ fontSize: 10,
                                  background: (SECTOR_COLORS[a.sector] ?? '#6366f1') + '22',
                                  color: SECTOR_COLORS[a.sector] ?? '#6366f1' }} />
                            </TableCell>
                            <TableCell align="right" sx={{ fontWeight: 700, color: cfg.color }}>
                              {a.weight_pct.toFixed(1)}%
                            </TableCell>
                            <TableCell align="right">
                              R$ {a.allocation_brl.toLocaleString('pt-BR', { maximumFractionDigits: 0 })}
                            </TableCell>
                            <TableCell align="right">{a.mu_pct.toFixed(0)}%</TableCell>
                            <TableCell align="right" sx={{ color: 'text.secondary' }}>
                              {a.sigma_pct.toFixed(0)}%
                            </TableCell>
                            <TableCell align="right"
                              sx={{ color: a.expected_return_pct >= 0 ? 'success.main' : 'error.main', fontWeight: 600 }}>
                              {a.expected_return_pct > 0 ? '+' : ''}{a.expected_return_pct.toFixed(1)}%
                            </TableCell>
                            <TableCell>
                              <MuiTooltip title={`${a.weight_pct.toFixed(1)}% do portfólio`}>
                                <LinearProgress variant="determinate"
                                  value={Math.min(a.weight_pct * 4, 100)}
                                  sx={{ height: 6, borderRadius: 3,
                                    backgroundColor: cfg.color + '22',
                                    '& .MuiLinearProgress-bar': { backgroundColor: cfg.color, borderRadius: 3 } }} />
                              </MuiTooltip>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </Box>
                  <Divider sx={{ my: 1.5 }} />
                  <Box sx={{ display: 'flex', gap: 3, flexWrap: 'wrap' }}>
                    <Typography variant="caption" color="text.secondary">
                      <strong>Algoritmo:</strong> {result.algorithm}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      <strong>Iterações:</strong> {result.iterations} × 300 amostras × elite 20%
                    </Typography>
                  </Box>
                  <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: 'block' }}>
                    Modelo educacional — não constitui recomendação de investimento.
                    Para risco de cauda real, use a aba <strong>EVT</strong>.
                  </Typography>
                </CardContent>
              </Card>
            </>
          )}
        </Grid>
      </Grid>
    </Box>
  );
}
