import React, { useState } from 'react';
import {
  Box, Grid, Card, CardContent, Typography, Button, CircularProgress,
  Alert, Chip, Slider, TextField, Table, TableBody, TableCell,
  TableHead, TableRow, ToggleButton, ToggleButtonGroup, Divider,
  IconButton, Tooltip,
} from '@mui/material';
import { Add, Remove, PlayArrow, AutoGraph } from '@mui/icons-material';
import {
  ComposedChart, Line, Area, XAxis, YAxis, CartesianGrid,
  Tooltip as RTooltip, Legend, ResponsiveContainer, ReferenceLine,
} from 'recharts';
import { api } from '../services/api';

// ── Palette ───────────────────────────────────────────────────────────────────
const COLORS = ['#6366f1', '#22c55e', '#f59e0b', '#ef4444', '#06b6d4',
                '#a855f7', '#ec4899', '#14b8a6', '#f97316', '#84cc16'];

const B3_PRESETS: AssetConfig[] = [
  { ticker: 'PETR4', S0: 40,  mu: 0.12, sigma: 0.38, enabled: true },
  { ticker: 'VALE3', S0: 65,  mu: 0.10, sigma: 0.32, enabled: true },
  { ticker: 'ITUB4', S0: 35,  mu: 0.10, sigma: 0.26, enabled: true },
  { ticker: 'BBDC4', S0: 15,  mu: 0.08, sigma: 0.28, enabled: false },
  { ticker: 'ABEV3', S0: 14,  mu: 0.07, sigma: 0.22, enabled: false },
];

// ── Types ─────────────────────────────────────────────────────────────────────
interface AssetConfig {
  ticker: string;
  S0: number;
  mu: number;
  sigma: number;
  enabled: boolean;
}

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

// ── Helpers ───────────────────────────────────────────────────────────────────
function buildOverlayData(result: SimResult) {
  return result.time_days.map((day, i) => {
    const pt: Record<string, number> = { day };
    result.assets.forEach((a) => { pt[a.ticker] = a.mean_pct[i]; });
    return pt;
  });
}

function buildDetailData(asset: AssetResult, time_days: number[]) {
  return time_days.map((day, i) => ({
    day,
    p5: asset.p5[i],
    band: asset.p95[i] - asset.p5[i],   // stacked area trick
    mean: asset.mean[i],
  }));
}

// Custom tooltip
function PctTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <Box sx={{ background: '#1e1e2e', border: '1px solid #333', borderRadius: 1, p: 1.5 }}>
      <Typography variant="caption" color="text.secondary">Dia {label}</Typography>
      {payload.map((p: any) => (
        <Box key={p.dataKey} sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
          <Box sx={{ width: 8, height: 8, borderRadius: '50%', background: p.color }} />
          <Typography variant="caption" sx={{ color: p.color }}>
            {p.dataKey}: {p.value > 0 ? '+' : ''}{Number(p.value).toFixed(2)}%
          </Typography>
        </Box>
      ))}
    </Box>
  );
}

function PriceTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  const mean = payload.find((p: any) => p.dataKey === 'mean');
  return (
    <Box sx={{ background: '#1e1e2e', border: '1px solid #333', borderRadius: 1, p: 1.5 }}>
      <Typography variant="caption" color="text.secondary">Dia {label}</Typography>
      {mean && (
        <Typography variant="caption" display="block" color="primary">
          Média: R$ {Number(mean.value).toFixed(2)}
        </Typography>
      )}
    </Box>
  );
}

// ── Main Component ─────────────────────────────────────────────────────────────
export default function SimulacaoB3Page() {
  const [assets, setAssets] = useState<AssetConfig[]>(B3_PRESETS);
  const [horizon, setHorizon] = useState(1.0);
  const [nPaths, setNPaths] = useState(500);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<SimResult | null>(null);
  const [error, setError] = useState('');
  const [view, setView] = useState<'overlay' | 'detail'>('overlay');
  const [selectedAsset, setSelectedAsset] = useState<string>('');

  const activeAssets = assets.filter((a) => a.enabled);

  // ── Asset config helpers ──────────────────────────────────────────────────
  const toggleAsset = (ticker: string) =>
    setAssets((prev) => prev.map((a) => a.ticker === ticker ? { ...a, enabled: !a.enabled } : a));

  const updateAsset = (ticker: string, field: keyof AssetConfig, value: number | string) =>
    setAssets((prev) => prev.map((a) => a.ticker === ticker ? { ...a, [field]: value } : a));

  // ── Run simulation ────────────────────────────────────────────────────────
  const runSim = async () => {
    if (activeAssets.length === 0) {
      setError('Selecione ao menos um ativo.');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const payload = {
        assets: activeAssets.map(({ ticker, S0, mu, sigma }) => ({ ticker, S0, mu, sigma })),
        T: horizon,
        n_steps: Math.round(horizon * 252),
        n_paths: nPaths,
      };
      const data = await api.capmGbmMulti(payload) as SimResult;
      setResult(data);
      setSelectedAsset(data.assets[0]?.ticker ?? '');
    } catch (e: any) {
      setError(e?.message ?? 'Erro na simulação.');
    } finally {
      setLoading(false);
    }
  };

  const loadDemo = async () => {
    setLoading(true);
    setError('');
    try {
      const data = await api.capmGbmMultiDemo() as SimResult;
      setResult(data);
      setAssets(prev => prev.map(a => ({ ...a, enabled: data.assets.some((r: AssetResult) => r.ticker === a.ticker) })));
      setSelectedAsset(data.assets[0]?.ticker ?? '');
    } catch (e: any) {
      setError(e?.message ?? 'Erro no demo.');
    } finally {
      setLoading(false);
    }
  };

  // ── Chart data ────────────────────────────────────────────────────────────
  const overlayData = result ? buildOverlayData(result) : [];
  const detailAsset = result?.assets.find((a) => a.ticker === selectedAsset);
  const detailData = detailAsset && result ? buildDetailData(detailAsset, result.time_days) : [];

  // Downsample for performance (max 300 points)
  const downsample = <T,>(arr: T[], max = 300): T[] => {
    if (arr.length <= max) return arr;
    const step = Math.ceil(arr.length / max);
    return arr.filter((_, i) => i % step === 0 || i === arr.length - 1);
  };

  return (
    <Box sx={{ p: 3, maxWidth: 1400, mx: 'auto' }}>
      {/* Header */}
      <Box sx={{ mb: 3 }}>
        <Typography variant="h4" fontWeight={700} gutterBottom>
          Simulação B3 — GBM Correlacionado
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Movimento Browniano Geométrico (dS = μS dt + σS dW) com correlação entre ativos via decomposição de Cholesky.
          Bandas de confiança P5/P95 geradas por Monte Carlo.
        </Typography>
      </Box>

      <Grid container spacing={3}>
        {/* ── Config panel ─────────────────────────────────────────────── */}
        <Grid size={{ xs: 12, md: 3 }}>
          <Card>
            <CardContent>
              <Typography variant="subtitle1" fontWeight={600} gutterBottom>
                Ativos B3
              </Typography>
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
                {assets.map((a, idx) => (
                  <Box key={a.ticker}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                      <Box sx={{ width: 10, height: 10, borderRadius: '50%', background: COLORS[idx] }} />
                      <Chip
                        label={a.ticker}
                        size="small"
                        onClick={() => toggleAsset(a.ticker)}
                        variant={a.enabled ? 'filled' : 'outlined'}
                        sx={{ cursor: 'pointer', fontWeight: 600,
                          ...(a.enabled ? { background: COLORS[idx] + '33', color: COLORS[idx], borderColor: COLORS[idx] } : {})
                        }}
                      />
                      <Typography variant="caption" color="text.secondary">
                        R$ {a.S0}
                      </Typography>
                    </Box>
                    {a.enabled && (
                      <Box sx={{ pl: 2.5, display: 'flex', gap: 1 }}>
                        <TextField
                          label="μ/ano"
                          size="small"
                          type="number"
                          value={a.mu}
                          onChange={(e) => updateAsset(a.ticker, 'mu', parseFloat(e.target.value) || 0)}
                          sx={{ width: 80 }}
                          inputProps={{ step: 0.01 }}
                        />
                        <TextField
                          label="σ/ano"
                          size="small"
                          type="number"
                          value={a.sigma}
                          onChange={(e) => updateAsset(a.ticker, 'sigma', parseFloat(e.target.value) || 0.01)}
                          sx={{ width: 80 }}
                          inputProps={{ step: 0.01, min: 0.01 }}
                        />
                      </Box>
                    )}
                  </Box>
                ))}
              </Box>

              <Divider sx={{ my: 2 }} />

              <Typography variant="subtitle2" gutterBottom>
                Horizonte: {horizon === 1 ? '1 ano' : `${horizon} anos`}
              </Typography>
              <Slider
                value={horizon}
                onChange={(_, v) => setHorizon(v as number)}
                min={0.25} max={5} step={0.25}
                marks={[{ value: 1, label: '1a' }, { value: 3, label: '3a' }, { value: 5, label: '5a' }]}
                sx={{ mb: 2 }}
              />

              <Typography variant="subtitle2" gutterBottom>
                Simulações: {nPaths.toLocaleString()}
              </Typography>
              <Slider
                value={nPaths}
                onChange={(_, v) => setNPaths(v as number)}
                min={100} max={2000} step={100}
                marks={[{ value: 500, label: '500' }, { value: 1000, label: '1k' }, { value: 2000, label: '2k' }]}
                sx={{ mb: 2 }}
              />

              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, mt: 1 }}>
                <Button
                  variant="contained"
                  fullWidth
                  startIcon={loading ? <CircularProgress size={16} /> : <PlayArrow />}
                  onClick={runSim}
                  disabled={loading || activeAssets.length === 0}
                >
                  Simular
                </Button>
                <Button
                  variant="outlined"
                  fullWidth
                  startIcon={<AutoGraph />}
                  onClick={loadDemo}
                  disabled={loading}
                >
                  Demo B3
                </Button>
              </Box>

              {error && <Alert severity="error" sx={{ mt: 1 }}>{error}</Alert>}
            </CardContent>
          </Card>
        </Grid>

        {/* ── Charts ───────────────────────────────────────────────────── */}
        <Grid size={{ xs: 12, md: 9 }}>
          {!result && !loading && (
            <Card sx={{ height: 420, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Box textAlign="center">
                <AutoGraph sx={{ fontSize: 64, opacity: 0.2, mb: 1 }} />
                <Typography color="text.secondary">
                  Configure os ativos e clique em <strong>Simular</strong> ou <strong>Demo B3</strong>
                </Typography>
              </Box>
            </Card>
          )}

          {loading && (
            <Card sx={{ height: 420, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Box textAlign="center">
                <CircularProgress size={48} sx={{ mb: 2 }} />
                <Typography color="text.secondary">
                  Simulando {nPaths.toLocaleString()} trajetórias…
                </Typography>
              </Box>
            </Card>
          )}

          {result && !loading && (
            <>
              {/* View toggle */}
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1.5 }}>
                <ToggleButtonGroup
                  value={view}
                  exclusive
                  onChange={(_, v) => v && setView(v)}
                  size="small"
                >
                  <ToggleButton value="overlay">Comparativo (%)</ToggleButton>
                  <ToggleButton value="detail">Detalhe (R$)</ToggleButton>
                </ToggleButtonGroup>

                {view === 'detail' && (
                  <Box sx={{ display: 'flex', gap: 1 }}>
                    {result.assets.map((a, i) => (
                      <Chip
                        key={a.ticker}
                        label={a.ticker}
                        size="small"
                        onClick={() => setSelectedAsset(a.ticker)}
                        variant={selectedAsset === a.ticker ? 'filled' : 'outlined'}
                        sx={{
                          cursor: 'pointer',
                          ...(selectedAsset === a.ticker
                            ? { background: COLORS[i] + '33', color: COLORS[i], borderColor: COLORS[i] }
                            : {}),
                        }}
                      />
                    ))}
                  </Box>
                )}
              </Box>

              {/* Overlay chart — normalised % returns with gradient areas */}
              {view === 'overlay' && (
                <Card>
                  <CardContent>
                    <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                      Retorno acumulado esperado — trajetória média de cada ativo
                    </Typography>
                    <ResponsiveContainer width="100%" height={380}>
                      <ComposedChart data={downsample(overlayData)} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
                        <defs>
                          {result.assets.map((a, i) => (
                            <linearGradient key={a.ticker} id={`ovgrad-${a.ticker}`} x1="0" y1="0" x2="0" y2="1">
                              <stop offset="5%"  stopColor={COLORS[i]} stopOpacity={0.22} />
                              <stop offset="90%" stopColor={COLORS[i]} stopOpacity={0.01} />
                            </linearGradient>
                          ))}
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
                        <XAxis
                          dataKey="day"
                          label={{ value: 'Dias', position: 'insideBottom', offset: -2 }}
                          tick={{ fontSize: 11 }}
                          tickFormatter={(v) => String(v)}
                        />
                        <YAxis
                          tickFormatter={(v) => `${v > 0 ? '+' : ''}${v.toFixed(0)}%`}
                          tick={{ fontSize: 11 }}
                        />
                        <RTooltip content={<PctTooltip />} />
                        <Legend />
                        <ReferenceLine y={0} stroke="#666" strokeDasharray="4 4" />
                        {result.assets.map((a, i) => (
                          <Area
                            key={a.ticker}
                            type="monotone"
                            dataKey={a.ticker}
                            stroke={COLORS[i]}
                            strokeWidth={2}
                            fill={`url(#ovgrad-${a.ticker})`}
                            dot={false}
                            activeDot={{ r: 4 }}
                          />
                        ))}
                      </ComposedChart>
                    </ResponsiveContainer>
                  </CardContent>
                </Card>
              )}

              {/* Detail chart — absolute price with gradient confidence band */}
              {view === 'detail' && detailAsset && (() => {
                const assetIdx = result.assets.findIndex((a) => a.ticker === selectedAsset);
                const color = COLORS[assetIdx];
                return (
                  <Card>
                    <CardContent>
                      <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                        {detailAsset.ticker} — Trajetória média com banda de confiança P5/P95
                      </Typography>
                      <ResponsiveContainer width="100%" height={380}>
                        <ComposedChart data={downsample(detailData)} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
                          <defs>
                            <linearGradient id="detailBand" x1="0" y1="0" x2="0" y2="1">
                              <stop offset="0%"  stopColor={color} stopOpacity={0.30} />
                              <stop offset="100%" stopColor={color} stopOpacity={0.04} />
                            </linearGradient>
                            <linearGradient id="detailMean" x1="0" y1="0" x2="0" y2="1">
                              <stop offset="5%"  stopColor={color} stopOpacity={0.18} />
                              <stop offset="95%" stopColor={color} stopOpacity={0.0} />
                            </linearGradient>
                          </defs>
                          <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
                          <XAxis
                            dataKey="day"
                            label={{ value: 'Dias', position: 'insideBottom', offset: -2 }}
                            tick={{ fontSize: 11 }}
                          />
                          <YAxis
                            tickFormatter={(v) => `R$${v.toFixed(0)}`}
                            tick={{ fontSize: 11 }}
                          />
                          <RTooltip content={<PriceTooltip />} />
                          {/* P5 base — transparent, stacked below band */}
                          <Area
                            type="monotone"
                            dataKey="p5"
                            stackId="band"
                            stroke={color}
                            strokeWidth={1}
                            strokeDasharray="3 3"
                            strokeOpacity={0.5}
                            fill="transparent"
                            name="P5"
                            dot={false}
                          />
                          {/* Band width stacked on top of P5 — gets the gradient fill */}
                          <Area
                            type="monotone"
                            dataKey="band"
                            stackId="band"
                            stroke={color}
                            strokeWidth={1}
                            strokeDasharray="3 3"
                            strokeOpacity={0.5}
                            fill="url(#detailBand)"
                            name="P95"
                            dot={false}
                          />
                          {/* Mean line with subtle area fill */}
                          <Area
                            type="monotone"
                            dataKey="mean"
                            stroke={color}
                            strokeWidth={2.5}
                            fill="url(#detailMean)"
                            dot={false}
                            name="Média"
                          />
                          <ReferenceLine
                            y={detailAsset.S0}
                            stroke="#888"
                            strokeDasharray="4 4"
                            label={{ value: 'S₀', fontSize: 11, fill: '#999' }}
                          />
                          <Legend />
                        </ComposedChart>
                      </ResponsiveContainer>
                    </CardContent>
                  </Card>
                );
              })()}

              {/* Terminal statistics table */}
              <Card sx={{ mt: 2 }}>
                <CardContent>
                  <Typography variant="subtitle1" fontWeight={600} gutterBottom>
                    Distribuição Terminal — T = {result.T === 1 ? '1 ano' : `${result.T} anos`} ({result.n_paths.toLocaleString()} simulações)
                  </Typography>
                  <Box sx={{ overflowX: 'auto' }}>
                    <Table size="small">
                      <TableHead>
                        <TableRow>
                          <TableCell>Ativo</TableCell>
                          <TableCell align="right">S₀ (R$)</TableCell>
                          <TableCell align="right">Média (R$)</TableCell>
                          <TableCell align="right">P5 (R$)</TableCell>
                          <TableCell align="right">P50 (R$)</TableCell>
                          <TableCell align="right">P95 (R$)</TableCell>
                          <TableCell align="right">Ret. Esp.</TableCell>
                          <TableCell align="right">{'P(>S₀)'}</TableCell>
                          <TableCell align="right">σ/ano</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {result.assets.map((a, i) => (
                          <TableRow
                            key={a.ticker}
                            sx={{ cursor: 'pointer', '&:hover': { background: 'action.hover' } }}
                            onClick={() => { setSelectedAsset(a.ticker); setView('detail'); }}
                          >
                            <TableCell>
                              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                <Box sx={{ width: 8, height: 8, borderRadius: '50%', background: COLORS[i] }} />
                                <Typography variant="body2" fontWeight={600}>{a.ticker}</Typography>
                              </Box>
                            </TableCell>
                            <TableCell align="right">{a.S0.toFixed(2)}</TableCell>
                            <TableCell align="right">{a.terminal.mean.toFixed(2)}</TableCell>
                            <TableCell align="right" sx={{ color: 'error.main' }}>{a.terminal.p5.toFixed(2)}</TableCell>
                            <TableCell align="right">{a.terminal.p50.toFixed(2)}</TableCell>
                            <TableCell align="right" sx={{ color: 'success.main' }}>{a.terminal.p95.toFixed(2)}</TableCell>
                            <TableCell align="right" sx={{ color: a.terminal.expected_return_pct >= 0 ? 'success.main' : 'error.main', fontWeight: 600 }}>
                              {a.terminal.expected_return_pct > 0 ? '+' : ''}{a.terminal.expected_return_pct.toFixed(1)}%
                            </TableCell>
                            <TableCell align="right">{(a.terminal.prob_above_S0 * 100).toFixed(1)}%</TableCell>
                            <TableCell align="right" sx={{ color: 'text.secondary' }}>{(a.sigma * 100).toFixed(0)}%</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </Box>
                  <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
                    Clique em um ativo para ver a trajetória detalhada. μ = drift anual, σ = volatilidade anual.
                    GBM assume retornos log-normalmente distribuídos — dS = μS dt + σS dW.
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
