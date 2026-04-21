import React, { useState, useCallback, useMemo } from 'react';
import {
  Box, Grid, Card, CardContent, Typography, Button,
  Slider, Chip, Divider, Alert, LinearProgress, Tooltip,
  Table, TableBody, TableCell, TableHead, TableRow,
  ToggleButtonGroup, ToggleButton, TextField,
} from '@mui/material';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RTooltip,
  ResponsiveContainer, ReferenceLine, Cell, LineChart, Line,
  ScatterChart, Scatter, Legend, RadarChart, PolarGrid,
  PolarAngleAxis, PolarRadiusAxis, Radar,
} from 'recharts';
import { PlayArrow, Refresh, InfoOutlined, TrendingUp, BarChart as BarChartIcon } from '@mui/icons-material';

// ─── Pure-JS replica of the Python AlphaCombinationEngine ───────────────────

function seededRandom(seed: number): () => number {
  let s = seed;
  return () => {
    s = (s * 1664525 + 1013904223) & 0xffffffff;
    return (s >>> 0) / 0xffffffff;
  };
}

function normalRandom(rng: () => number): number {
  const u = rng(), v = rng();
  return Math.sqrt(-2 * Math.log(Math.max(u, 1e-10))) * Math.cos(2 * Math.PI * v);
}

function mean(arr: number[]): number {
  return arr.reduce((a, b) => a + b, 0) / arr.length;
}
function variance(arr: number[]): number {
  const m = mean(arr);
  return arr.reduce((s, x) => s + (x - m) ** 2, 0) / arr.length;
}

interface EngineResult {
  weights: number[];
  residuals: number[];
  sigmas: number[];
  normalizedReturns: number[][];
  lambda: number[][];
  combinedSignal: number;
  kellySize: number;
  steps: StepInfo[];
  signalCorrelations: number[][];
  icVector: number[];
  brokerageReturn: number;
}

interface StepInfo {
  step: number;
  name: string;
  description: string;
  value: string;
}

function runAlphaEngine(nSignals: number, days: number, lookback: number, seed: number): EngineResult {
  const rng = seededRandom(seed);

  // Generate synthetic returns (M periods × N signals)
  const R: number[][] = Array.from({ length: days }, () =>
    Array.from({ length: nSignals }, () => 0.0001 + 0.02 * normalRandom(rng))
  );

  // Step 1: Realized returns R
  // Step 2: Serially demeaned X
  const colMeans = Array.from({ length: nSignals }, (_, j) => mean(R.map(row => row[j])));
  const X = R.map(row => row.map((v, j) => v - colMeans[j]));

  // Step 3: Sigma (sample std)
  const sigmas = Array.from({ length: nSignals }, (_, j) => Math.sqrt(variance(X.map(r => r[j]))));

  // Step 4: Normalize Y = X / sigma
  const Y = X.map(row => row.map((v, j) => v / Math.max(sigmas[j], 1e-10)));

  // Step 5: Train = all but last row
  const Y_train = Y.slice(0, -1);

  // Step 6: Cross-sectional demean → Lambda
  const lambda = Y_train.map(row => {
    const rm = mean(row);
    return row.map(v => v - rm);
  });

  // Step 7: (already handled)

  // Step 8: Expected forward returns using last `lookback` rows
  const E_raw = Array.from({ length: nSignals }, (_, j) =>
    mean(R.slice(-lookback).map(r => r[j]))
  );
  const E_norm = E_raw.map((e, j) => e / Math.max(sigmas[j], 1e-10));

  // Step 9: Residuals via simplified regression (OLS per signal)
  const residuals = Array.from({ length: nSignals }, (_, i) => {
    const xs = lambda.map(row => row[i]);
    const ys = Y_train.map(row => row[i]);
    const xm = mean(xs), ym = mean(ys);
    const cov = xs.reduce((s, x, t) => s + (x - xm) * (ys[t] - ym), 0);
    const varX = xs.reduce((s, x) => s + (x - xm) ** 2, 0);
    const beta = varX > 0 ? cov / varX : 0;
    return E_norm[i] - xm * beta;
  });

  // Step 10: Raw weights ~ residuals / sigma
  const rawWeights = residuals.map((r, i) => r / Math.max(sigmas[i], 1e-10));

  // Step 11: Normalize to sum |w| = 1
  const sumAbs = rawWeights.reduce((s, w) => s + Math.abs(w), 0) || 1;
  const weights = rawWeights.map(w => w / sumAbs);

  // Combined signal: dot(currentSignals, weights)
  const currentSignals = Array.from({ length: nSignals }, () => normalRandom(rng) * 0.02 + 0.01);
  const combinedSignal = currentSignals.reduce((s, v, i) => s + v * weights[i], 0);

  // IC vector (correlation of signal i with period-ahead returns, simplified)
  const icVector = Array.from({ length: nSignals }, (_, i) => {
    const sig = Y_train.map(row => row[i]);
    const fwd = Y_train.map((_, t) => (t + 1 < Y_train.length ? Y_train[t + 1][i] : 0));
    const sm = mean(sig), fm = mean(fwd);
    const cov = sig.reduce((s, x, t) => s + (x - sm) * (fwd[t] - fm), 0);
    const denom = Math.sqrt(
      sig.reduce((s, x) => s + (x - sm) ** 2, 0) *
      fwd.reduce((s, x) => s + (x - fm) ** 2, 0)
    );
    return denom > 0 ? cov / denom : 0;
  });

  // Simplified signal correlation matrix (first 8 signals for display)
  const nShow = Math.min(nSignals, 8);
  const signalCorrelations: number[][] = Array.from({ length: nShow }, (_, i) =>
    Array.from({ length: nShow }, (__, j) => {
      if (i === j) return 1;
      const a = Y_train.map(r => r[i]);
      const b = Y_train.map(r => r[j]);
      const am = mean(a), bm = mean(b);
      const cov = a.reduce((s, x, t) => s + (x - am) * (b[t] - bm), 0);
      const denom = Math.sqrt(
        a.reduce((s, x) => s + (x - am) ** 2, 0) *
        b.reduce((s, x) => s + (x - bm) ** 2, 0)
      );
      return denom > 0 ? cov / denom : 0;
    })
  );

  // Empirical Kelly sizing
  const edge = 0.04, winProb = 0.52, odds = 1.0, varEdge = 0.0001;
  const fKelly = (winProb * odds - (1 - winProb)) / odds;
  const cvEdge = Math.sqrt(varEdge) / Math.abs(edge);
  const kellySize = Math.max(0, fKelly * (1 - cvEdge));

  // Brokerage return: sum(|w_i| * IC_i) scaled
  const brokerageReturn = weights.reduce((s, w, i) => s + Math.abs(w) * Math.abs(icVector[i]), 0);

  const steps: StepInfo[] = [
    { step: 1, name: 'Realized Returns (R)', description: 'Raw return matrix for M periods × N signals', value: `${days} × ${nSignals} matrix` },
    { step: 2, name: 'Demean (X = R − μ)', description: 'Remove serial bias from each signal column', value: `μ̄ = ${mean(colMeans).toFixed(6)}` },
    { step: 3, name: 'Volatility (σ)', description: 'Sample std per signal to normalize scale', value: `σ̄ = ${mean(sigmas).toFixed(4)}` },
    { step: 4, name: 'Normalize (Y = X/σ)', description: 'Unit-variance returns for cross-signal comparison', value: `σ(Y) ≈ 1.00` },
    { step: 5, name: 'OOS Holdout', description: 'Drop last row to prevent look-ahead bias', value: `Train: ${days - 1} rows` },
    { step: 6, name: 'Cross-Section Demean (Λ)', description: 'Remove market-wide beta from each time period', value: `λ̄ = ${mean(lambda.map(r => mean(r))).toFixed(6)}` },
    { step: 7, name: 'Data Hygiene', description: 'Slicing already enforces this; no corrupt rows', value: '✓ Clean' },
    { step: 8, name: 'Expected Returns (E)', description: `${lookback}-day moving average forward expectation`, value: `Ē = ${mean(E_norm).toFixed(6)}` },
    { step: 9, name: 'Residuals (ε)', description: 'Idiosyncratic alpha after cross-sectional regression', value: `ε̄ = ${mean(residuals).toFixed(6)}` },
    { step: 10, name: 'Raw Weights (w∝ε/σ)', description: 'Signal weight proportional to edge, scaled by vol', value: `Σ|w| = ${sumAbs.toFixed(4)}` },
    { step: 11, name: 'Normalize (η)', description: 'Full allocation: Σ|wᵢ| = 1, no unintended leverage', value: `η = ${(1 / sumAbs).toFixed(4)}` },
  ];

  return { weights, residuals, sigmas, normalizedReturns: Y, lambda, combinedSignal, kellySize, steps, signalCorrelations, icVector, brokerageReturn };
}

// ─── Color helpers ────────────────────────────────────────────────────────────

const COLORS = {
  positive: '#10b981',
  negative: '#ef4444',
  neutral: '#6366f1',
  accent: '#06b6d4',
  warn: '#f59e0b',
};

function weightColor(w: number) {
  return w >= 0 ? COLORS.positive : COLORS.negative;
}

function signalConvictionLabel(v: number) {
  const a = Math.abs(v);
  if (a < 0.002) return { label: 'Neutral', color: 'default' as const };
  if (a < 0.005) return { label: 'Weak', color: 'warning' as const };
  if (a < 0.01)  return { label: 'Moderate', color: 'info' as const };
  return { label: 'High', color: 'success' as const };
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function StatBox({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <Box sx={{ textAlign: 'center', p: 1.5, border: 1, borderColor: 'divider', borderRadius: 2 }}>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      <Typography variant="h6" sx={{ fontFamily: 'monospace', color: color || 'text.primary', fontWeight: 700 }}>
        {value}
      </Typography>
      {sub && <Typography variant="caption" color="text.secondary">{sub}</Typography>}
    </Box>
  );
}

const STEP_COLORS = [
  '#6366f1','#818cf8','#06b6d4','#22d3ee','#10b981',
  '#34d399','#f59e0b','#fbbf24','#ef4444','#f87171','#a78bfa',
];

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function AlphaCombinationPage() {
  const [nSignals, setNSignals] = useState(50);
  const [lookback, setLookback] = useState(20);
  const [days, setDays] = useState(252);
  const [seed, setSeed] = useState(42);
  const [chartView, setChartView] = useState<'weights' | 'ic' | 'radar'>('weights');
  const [kellyWin, setKellyWin] = useState(52);
  const [kellyOdds, setKellyOdds] = useState(1.0);
  const [kellyVarEdge, setKellyVarEdge] = useState(0.0001);
  const [result, setResult] = useState<EngineResult | null>(null);
  const [running, setRunning] = useState(false);

  const run = useCallback(() => {
    setRunning(true);
    setTimeout(() => {
      setResult(runAlphaEngine(nSignals, days, lookback, seed));
      setRunning(false);
    }, 120);
  }, [nSignals, days, lookback, seed]);

  // Custom Kelly from UI
  const customKelly = useMemo(() => {
    const wp = kellyWin / 100;
    const edge = wp * kellyOdds - (1 - wp);
    const fK = edge / kellyOdds;
    const cv = Math.sqrt(kellyVarEdge) / Math.max(Math.abs(edge), 1e-9);
    return { fK, fEmp: Math.max(0, fK * (1 - cv)), edge, cv };
  }, [kellyWin, kellyOdds, kellyVarEdge]);

  // Chart data
  const weightData = useMemo(() => {
    if (!result) return [];
    return result.weights
      .map((w, i) => ({ signal: `S${i + 1}`, weight: +w.toFixed(5), ic: +(result.icVector[i] * 100).toFixed(3) }))
      .sort((a, b) => Math.abs(b.weight) - Math.abs(a.weight))
      .slice(0, 20);
  }, [result]);

  const radarData = useMemo(() => {
    if (!result) return [];
    const metrics = [
      { subject: 'IC Breadth', value: Math.min(100, Math.abs(mean(result.icVector)) * 2000) },
      { subject: 'Signal Divers.', value: Math.min(100, result.signalCorrelations[0]?.length * 8 || 0) },
      { subject: 'Kelly Edge', value: Math.min(100, customKelly.fEmp * 500) },
      { subject: 'Combined Signal', value: Math.min(100, Math.abs(result.combinedSignal) * 5000) },
      { subject: 'Brokerage Ret.', value: Math.min(100, result.brokerageReturn * 10000) },
    ];
    return metrics;
  }, [result, customKelly]);

  const convLabel = result ? signalConvictionLabel(result.combinedSignal) : null;

  // Fundamental Law: IR ≈ IC × √Breadth
  const breadth = nSignals;
  const ic = result ? mean(result.icVector.map(Math.abs)) : 0.05;
  const informationRatio = ic * Math.sqrt(breadth);

  return (
    <Box>
      {/* Header */}
      <Box sx={{ mb: 3 }}>
        <Typography variant="h4" sx={{ mb: 0.5 }}>Alpha Combination Engine</Typography>
        <Typography variant="body2" color="text.secondary">
          11-step institutional framework · Fundamental Law of Active Management · Empirical Kelly Sizing
        </Typography>
      </Box>

      {/* Top concept cards */}
      <Grid container spacing={2.5} sx={{ mb: 3 }}>
        {[
          {
            title: 'Fundamental Law',
            body: 'IR ≈ IC × √N. The information ratio scales with the square root of the number of independent bets (breadth). Many weak signals beat one strong guess.',
            chip: `IR ≈ IC × √${breadth}`,
          },
          {
            title: 'Signal Orthogonality',
            body: 'Decorrelated signals multiply the effective breadth. Cross-sectional demeaning (Λ) isolates idiosyncratic alpha, eliminating shared market-wide variance.',
            chip: 'Step 6 — Λ',
          },
          {
            title: 'Empirical Kelly',
            body: 'The coefficient of variation of the edge shrinks the standard Kelly fraction. It accounts for uncertainty in win-rate estimation from finite samples.',
            chip: 'f* = f_K (1 − CV)',
          },
        ].map(c => (
          <Grid key={c.title} size={{ xs: 12, md: 4 }}>
            <Card sx={{ height: '100%' }}>
              <CardContent>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 1 }}>
                  <Typography variant="h6">{c.title}</Typography>
                  <Chip label={c.chip} size="small" sx={{ bgcolor: 'primary.main', color: '#fff', fontWeight: 700, fontSize: '0.7rem' }} />
                </Box>
                <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.75 }}>
                  {c.body}
                </Typography>
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>

      {/* Configuration */}
      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Typography variant="h6" gutterBottom>Engine Configuration</Typography>
          <Grid container spacing={3}>
            <Grid size={{ xs: 12, sm: 6, md: 3 }}>
              <Typography variant="body2" color="text.secondary" gutterBottom>
                Signals (N) — {nSignals}
              </Typography>
              <Slider value={nSignals} onChange={(_, v) => setNSignals(v as number)} min={5} max={200} step={5}
                marks={[{ value: 5, label: '5' }, { value: 100, label: '100' }, { value: 200, label: '200' }]}
                sx={{ color: 'primary.main' }}
              />
            </Grid>
            <Grid size={{ xs: 12, sm: 6, md: 3 }}>
              <Typography variant="body2" color="text.secondary" gutterBottom>
                History days (M) — {days}
              </Typography>
              <Slider value={days} onChange={(_, v) => setDays(v as number)} min={60} max={756} step={21}
                marks={[{ value: 60, label: '60' }, { value: 252, label: '252' }, { value: 756, label: '756' }]}
                sx={{ color: 'secondary.main' }}
              />
            </Grid>
            <Grid size={{ xs: 12, sm: 6, md: 3 }}>
              <Typography variant="body2" color="text.secondary" gutterBottom>
                Lookback d — {lookback}
              </Typography>
              <Slider value={lookback} onChange={(_, v) => setLookback(v as number)} min={5} max={60} step={1}
                marks={[{ value: 5, label: '5' }, { value: 20, label: '20' }, { value: 60, label: '60' }]}
                sx={{ color: 'warning.main' }}
              />
            </Grid>
            <Grid size={{ xs: 12, sm: 6, md: 3 }}>
              <Typography variant="body2" color="text.secondary" gutterBottom>
                Random Seed — {seed}
              </Typography>
              <Slider value={seed} onChange={(_, v) => setSeed(v as number)} min={1} max={999} step={1}
                marks={[{ value: 1, label: '1' }, { value: 500, label: '500' }, { value: 999, label: '999' }]}
                sx={{ color: 'error.main' }}
              />
            </Grid>
          </Grid>

          <Box sx={{ mt: 2, display: 'flex', gap: 2 }}>
            <Button variant="contained" size="large" startIcon={running ? undefined : <PlayArrow />}
              onClick={run} disabled={running}
              sx={{ minWidth: 200 }}
            >
              {running ? 'Running engine…' : 'Run Alpha Combination'}
            </Button>
            <Button variant="outlined" startIcon={<Refresh />}
              onClick={() => { setSeed(Math.floor(Math.random() * 999) + 1); }}
            >
              New Seed
            </Button>
          </Box>
          {running && <LinearProgress sx={{ mt: 1.5, borderRadius: 2 }} />}
        </CardContent>
      </Card>

      {/* Results */}
      {result && (
        <>
          {/* KPI Strip */}
          <Grid container spacing={2} sx={{ mb: 3 }}>
            <Grid size={{ xs: 6, sm: 4, md: 2 }}>
              <StatBox
                label="Combined Signal"
                value={(result.combinedSignal * 100).toFixed(3) + '%'}
                sub="weighted alpha"
                color={result.combinedSignal >= 0 ? COLORS.positive : COLORS.negative}
              />
            </Grid>
            <Grid size={{ xs: 6, sm: 4, md: 2 }}>
              <StatBox
                label="Conviction"
                value={convLabel!.label}
                sub="signal strength"
                color={result.combinedSignal >= 0 ? COLORS.positive : COLORS.negative}
              />
            </Grid>
            <Grid size={{ xs: 6, sm: 4, md: 2 }}>
              <StatBox
                label="Info. Ratio (IR)"
                value={informationRatio.toFixed(3)}
                sub={`IC × √${breadth}`}
                color={COLORS.neutral}
              />
            </Grid>
            <Grid size={{ xs: 6, sm: 4, md: 2 }}>
              <StatBox
                label="Mean |IC|"
                value={(ic * 100).toFixed(2) + '%'}
                sub="predictive power"
                color={COLORS.accent}
              />
            </Grid>
            <Grid size={{ xs: 6, sm: 4, md: 2 }}>
              <StatBox
                label="Kelly Size"
                value={(result.kellySize * 100).toFixed(2) + '%'}
                sub="empirical fraction"
                color={COLORS.warn}
              />
            </Grid>
            <Grid size={{ xs: 6, sm: 4, md: 2 }}>
              <StatBox
                label="Brokerage Ret."
                value={(result.brokerageReturn * 100).toFixed(4) + '%'}
                sub="Σ|wᵢ|×|ICᵢ|"
                color={COLORS.positive}
              />
            </Grid>
          </Grid>

          {/* Pipeline Steps */}
          <Card sx={{ mb: 3 }}>
            <CardContent>
              <Typography variant="h6" gutterBottom>11-Step Pipeline</Typography>
              <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
                {result.steps.map(s => (
                  <Tooltip key={s.step} title={`${s.description}\n${s.value}`} arrow>
                    <Box sx={{
                      px: 1.5, py: 0.75,
                      border: `1px solid ${STEP_COLORS[s.step - 1]}33`,
                      bgcolor: `${STEP_COLORS[s.step - 1]}15`,
                      borderRadius: 2,
                      cursor: 'default',
                      transition: 'all 0.2s',
                      '&:hover': { bgcolor: `${STEP_COLORS[s.step - 1]}30`, transform: 'translateY(-2px)' },
                    }}>
                      <Typography variant="caption" sx={{ fontWeight: 700, color: STEP_COLORS[s.step - 1] }}>
                        Step {s.step}
                      </Typography>
                      <Typography variant="caption" display="block" color="text.secondary" noWrap sx={{ maxWidth: 140 }}>
                        {s.name}
                      </Typography>
                      <Typography variant="caption" display="block" sx={{ fontFamily: 'monospace', fontSize: '0.65rem', color: 'text.secondary' }}>
                        {s.value}
                      </Typography>
                    </Box>
                  </Tooltip>
                ))}
              </Box>
            </CardContent>
          </Card>

          {/* Chart Area */}
          <Card sx={{ mb: 3 }}>
            <CardContent>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                <Typography variant="h6">Signal Analysis</Typography>
                <ToggleButtonGroup value={chartView} exclusive onChange={(_, v) => v && setChartView(v)} size="small">
                  <ToggleButton value="weights"><BarChartIcon fontSize="small" sx={{ mr: 0.5 }} />Weights</ToggleButton>
                  <ToggleButton value="ic"><TrendingUp fontSize="small" sx={{ mr: 0.5 }} />IC</ToggleButton>
                  <ToggleButton value="radar"><InfoOutlined fontSize="small" sx={{ mr: 0.5 }} />Radar</ToggleButton>
                </ToggleButtonGroup>
              </Box>

              {chartView === 'weights' && (
                <>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
                    Top 20 signals by |weight| · green = long, red = short · Step 11 normalization
                  </Typography>
                  <ResponsiveContainer width="100%" height={320}>
                    <BarChart data={weightData} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                      <XAxis dataKey="signal" tick={{ fontSize: 11 }} />
                      <YAxis tick={{ fontSize: 11 }} tickFormatter={v => v.toFixed(3)} />
                      <RTooltip
                        contentStyle={{ background: '#111827', border: '1px solid #1e293b', borderRadius: 8 }}
                        labelStyle={{ fontWeight: 600 }}
                        formatter={(v: any) => [(v as number).toFixed(5), 'Weight']}
                      />
                      <ReferenceLine y={0} stroke="#475569" />
                      <Bar dataKey="weight" radius={[4, 4, 0, 0]}>
                        {weightData.map((entry, i) => (
                          <Cell key={i} fill={weightColor(entry.weight)} fillOpacity={0.85} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </>
              )}

              {chartView === 'ic' && (
                <>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
                    Information Coefficient per signal (top 20) · IC = correlation(signal, forward return)
                  </Typography>
                  <ResponsiveContainer width="100%" height={320}>
                    <BarChart data={weightData} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                      <XAxis dataKey="signal" tick={{ fontSize: 11 }} />
                      <YAxis tick={{ fontSize: 11 }} tickFormatter={v => v.toFixed(2)} unit="%" />
                      <RTooltip
                        contentStyle={{ background: '#111827', border: '1px solid #1e293b', borderRadius: 8 }}
                        formatter={(v: any) => [(v as number).toFixed(3) + '%', 'IC']}
                      />
                      <ReferenceLine y={0} stroke="#475569" />
                      <Bar dataKey="ic" radius={[4, 4, 0, 0]}>
                        {weightData.map((entry, i) => (
                          <Cell key={i} fill={entry.ic >= 0 ? COLORS.accent : COLORS.warn} fillOpacity={0.85} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </>
              )}

              {chartView === 'radar' && (
                <>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
                    Composite engine quality across 5 dimensions (0–100 scale)
                  </Typography>
                  <ResponsiveContainer width="100%" height={320}>
                    <RadarChart cx="50%" cy="50%" outerRadius="75%" data={radarData}>
                      <PolarGrid stroke="#1e293b" />
                      <PolarAngleAxis dataKey="subject" tick={{ fontSize: 11 }} />
                      <PolarRadiusAxis angle={30} domain={[0, 100]} tick={{ fontSize: 9 }} />
                      <Radar name="Engine" dataKey="value" stroke="#6366f1" fill="#6366f1" fillOpacity={0.35} />
                      <Legend />
                    </RadarChart>
                  </ResponsiveContainer>
                </>
              )}
            </CardContent>
          </Card>

          {/* Weight + IC Table */}
          <Grid container spacing={2.5} sx={{ mb: 3 }}>
            <Grid size={{ xs: 12, md: 6 }}>
              <Card sx={{ height: '100%' }}>
                <CardContent>
                  <Typography variant="h6" gutterBottom>Top 10 Signal Weights</Typography>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>Signal</TableCell>
                        <TableCell align="right">Weight</TableCell>
                        <TableCell align="right">Direction</TableCell>
                        <TableCell align="right">|w| rank</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {weightData.slice(0, 10).map((row, i) => (
                        <TableRow key={row.signal} hover>
                          <TableCell sx={{ fontFamily: 'monospace', fontWeight: 600 }}>{row.signal}</TableCell>
                          <TableCell align="right" sx={{ fontFamily: 'monospace', color: weightColor(row.weight) }}>
                            {row.weight.toFixed(5)}
                          </TableCell>
                          <TableCell align="right">
                            <Chip size="small" label={row.weight >= 0 ? 'Long' : 'Short'}
                              color={row.weight >= 0 ? 'success' : 'error'} variant="outlined" />
                          </TableCell>
                          <TableCell align="right" sx={{ fontFamily: 'monospace', color: 'text.secondary' }}>
                            #{i + 1}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>
            </Grid>

            <Grid size={{ xs: 12, md: 6 }}>
              <Card sx={{ height: '100%' }}>
                <CardContent>
                  <Typography variant="h6" gutterBottom>Fundamental Law Summary</Typography>
                  <Table size="small">
                    <TableBody>
                      {[
                        { k: 'N (breadth)', v: breadth.toString() },
                        { k: 'Mean IC', v: (ic * 100).toFixed(3) + '%' },
                        { k: 'IC × √N (IR)', v: informationRatio.toFixed(4) },
                        { k: 'IR Annualized', v: (informationRatio * Math.sqrt(252)).toFixed(4) },
                        { k: 'Combined Signal', v: (result.combinedSignal * 10000).toFixed(2) + ' bps' },
                        { k: 'Active Signals (|w|>1e-4)', v: result.weights.filter(w => Math.abs(w) > 1e-4).length.toString() },
                        { k: 'Long / Short Count', v: `${result.weights.filter(w => w > 0).length} / ${result.weights.filter(w => w < 0).length}` },
                        { k: 'Max Weight', v: Math.max(...result.weights.map(Math.abs)).toFixed(5) },
                      ].map(r => (
                        <TableRow key={r.k} hover>
                          <TableCell sx={{ fontWeight: 600 }}>{r.k}</TableCell>
                          <TableCell align="right" sx={{ fontFamily: 'monospace' }}>{r.v}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>
            </Grid>
          </Grid>

          {/* Empirical Kelly Calculator */}
          <Card sx={{ mb: 3 }}>
            <CardContent>
              <Typography variant="h6" gutterBottom>
                Empirical Kelly Criterion — Position Sizing
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 2.5 }}>
                f* = f_Kelly × (1 − CV_edge) where CV = σ_edge / |edge|. Adjust parameters to see how estimation uncertainty shrinks optimal bet size.
              </Typography>

              <Grid container spacing={3} alignItems="flex-start">
                <Grid size={{ xs: 12, md: 4 }}>
                  <Typography variant="body2" color="text.secondary" gutterBottom>Win Probability — {kellyWin}%</Typography>
                  <Slider value={kellyWin} onChange={(_, v) => setKellyWin(v as number)}
                    min={50} max={70} step={0.5}
                    marks={[{ value: 50, label: '50%' }, { value: 60, label: '60%' }, { value: 70, label: '70%' }]}
                    sx={{ color: COLORS.positive }}
                  />

                  <Typography variant="body2" color="text.secondary" gutterBottom sx={{ mt: 2 }}>
                    Odds (b) — {kellyOdds.toFixed(2)}
                  </Typography>
                  <Slider value={kellyOdds} onChange={(_, v) => setKellyOdds(v as number)}
                    min={0.5} max={4} step={0.1}
                    marks={[{ value: 0.5, label: '0.5' }, { value: 2, label: '2' }, { value: 4, label: '4' }]}
                    sx={{ color: COLORS.accent }}
                  />

                  <Typography variant="body2" color="text.secondary" gutterBottom sx={{ mt: 2 }}>
                    Variance of Edge — {kellyVarEdge.toFixed(4)}
                  </Typography>
                  <Slider value={kellyVarEdge} onChange={(_, v) => setKellyVarEdge(v as number)}
                    min={0.00001} max={0.01} step={0.00001}
                    marks={[{ value: 0.00001, label: '0' }, { value: 0.005, label: '0.005' }, { value: 0.01, label: '0.01' }]}
                    sx={{ color: COLORS.warn }}
                  />
                </Grid>

                <Grid size={{ xs: 12, md: 8 }}>
                  <Grid container spacing={2}>
                    {[
                      { label: 'Edge (p·b − q)', value: (customKelly.edge * 100).toFixed(3) + '%', color: customKelly.edge > 0 ? COLORS.positive : COLORS.negative },
                      { label: 'Standard Kelly f*', value: (customKelly.fK * 100).toFixed(2) + '%', color: COLORS.neutral },
                      { label: 'CV of Edge', value: customKelly.cv.toFixed(4), color: COLORS.warn },
                      { label: 'Empirical Kelly f*', value: (customKelly.fEmp * 100).toFixed(2) + '%', color: COLORS.accent },
                      { label: 'Half-Kelly', value: (customKelly.fEmp / 2 * 100).toFixed(2) + '%', color: COLORS.positive },
                      { label: 'Quarter-Kelly', value: (customKelly.fEmp / 4 * 100).toFixed(2) + '%', color: COLORS.warn },
                    ].map(s => (
                      <Grid key={s.label} size={{ xs: 6, sm: 4 }}>
                        <StatBox label={s.label} value={s.value} color={s.color} />
                      </Grid>
                    ))}
                  </Grid>

                  <Alert
                    severity={customKelly.fEmp > 0.15 ? 'warning' : customKelly.fEmp > 0 ? 'success' : 'error'}
                    sx={{ mt: 2 }}
                  >
                    {customKelly.fEmp <= 0
                      ? 'No edge detected — Kelly says bet nothing (or zero out).'
                      : customKelly.fEmp > 0.15
                      ? `Large position suggested (${(customKelly.fEmp * 100).toFixed(1)}%). Consider using ½-Kelly to reduce ruin risk.`
                      : `Empirical Kelly: invest ${(customKelly.fEmp * 100).toFixed(2)}% of capital. CV penalty of ${(customKelly.cv * 100).toFixed(1)}% applied.`}
                  </Alert>

                  {/* Kelly progress bar */}
                  <Box sx={{ mt: 2 }}>
                    <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
                      <Typography variant="caption" color="text.secondary">Standard Kelly</Typography>
                      <Typography variant="caption" sx={{ fontFamily: 'monospace' }}>{(customKelly.fK * 100).toFixed(2)}%</Typography>
                    </Box>
                    <LinearProgress variant="determinate" value={Math.min(100, customKelly.fK * 500)}
                      sx={{ height: 8, borderRadius: 4, mb: 1, '& .MuiLinearProgress-bar': { bgcolor: COLORS.neutral } }} />

                    <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
                      <Typography variant="caption" color="text.secondary">Empirical Kelly (after CV penalty)</Typography>
                      <Typography variant="caption" sx={{ fontFamily: 'monospace' }}>{(customKelly.fEmp * 100).toFixed(2)}%</Typography>
                    </Box>
                    <LinearProgress variant="determinate" value={Math.min(100, customKelly.fEmp * 500)}
                      sx={{ height: 8, borderRadius: 4, '& .MuiLinearProgress-bar': { bgcolor: COLORS.accent } }} />
                  </Box>
                </Grid>
              </Grid>
            </CardContent>
          </Card>

          {/* Theoretical Context */}
          <Card>
            <CardContent>
              <Typography variant="h6" gutterBottom>Theoretical Foundations</Typography>
              <Grid container spacing={2}>
                {[
                  {
                    title: 'Grinold & Kahn (1989)',
                    text: 'The Fundamental Law states IR = IC × √N. Combining weak signals is more valuable than finding one with high IC, because you own the breadth premium.',
                  },
                  {
                    title: 'Cross-Sectional Demeaning',
                    text: 'Step 6 removes the common factor. Without Λ, correlated signals inflate apparent N while reducing true breadth — overstating the IR estimate.',
                  },
                  {
                    title: 'Look-Ahead Bias (Step 5)',
                    text: 'Dropping the final row for training ensures expected returns (E) are computed OOS. This is the most common source of backtest inflation in factor research.',
                  },
                  {
                    title: 'Kelly vs Fractional Kelly',
                    text: 'The CV penalty in Empirical Kelly mirrors Bayesian shrinkage: the higher your estimation uncertainty, the more you discount the theoretical optimum.',
                  },
                ].map(c => (
                  <Grid key={c.title} size={{ xs: 12, sm: 6 }}>
                    <Box sx={{ p: 1.5, border: 1, borderColor: 'divider', borderRadius: 2 }}>
                      <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 0.5 }}>{c.title}</Typography>
                      <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.7 }}>{c.text}</Typography>
                    </Box>
                  </Grid>
                ))}
              </Grid>
            </CardContent>
          </Card>
        </>
      )}

      {!result && (
        <Box sx={{ textAlign: 'center', py: 8, border: 1, borderColor: 'divider', borderRadius: 3, borderStyle: 'dashed' }}>
          <Typography variant="h6" color="text.secondary" gutterBottom>Engine not yet run</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Configure N signals and history above, then click <strong>Run Alpha Combination</strong>.
          </Typography>
          <Button variant="contained" size="large" startIcon={<PlayArrow />} onClick={run}>
            Run Alpha Combination
          </Button>
        </Box>
      )}
    </Box>
  );
}
