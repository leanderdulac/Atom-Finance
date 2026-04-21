import React, { useState } from 'react';
import {
  Box, Grid, Card, CardContent, Typography, TextField, Button,
  CircularProgress, Alert, Chip, Slider, ToggleButtonGroup,
  ToggleButton, Table, TableBody, TableCell, TableRow, Divider,
} from '@mui/material';
import { api } from '../services/api';
import QuantContextSection from '../components/QuantContextSection';

const sdeFoundations = [
  {
    title: 'Itô SDE — dY = μ dt + σ dW',
    text: 'A Stochastic Differential Equation models the infinitesimal evolution of a state variable. The drift term μ encodes the deterministic tendency; the diffusion term σ scales Brownian noise.',
  },
  {
    title: 'Neural parameterisation',
    text: 'Instead of assuming functional forms for μ and σ, we use neural networks. This allows the model to learn complex, non-linear dynamics directly from data — an approach known as a Neural SDE.',
  },
  {
    title: 'Euler-Maruyama discretisation',
    text: 'The SDE is solved numerically: Y_{t+Δt} ≈ Y_t + μ(t,Y_t)·Δt + σ(t,Y_t)·√Δt·Z, where Z~N(0,1). Milstein adds a second-order correction for higher accuracy.',
  },
];

const sdeNotes = [
  'Neural SDEs generalise classic stochastic volatility models (Heston, SABR) by removing parametric assumptions on drift and diffusion.',
  'Applications include option pricing under learned dynamics, interest-rate modelling, climate tipping-point probability estimation and regime-aware scenario generation.',
  'The Sigmoid activation on σ_net keeps diffusion bounded in (0,1), acting as a built-in positivity constraint without explicit parameter bounds.',
];

// Lightweight sparkline using SVG
function Sparkline({ values, color = '#6366f1', height = 60 }: { values: number[]; color?: string; height?: number }) {
  if (!values || values.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const w = 400;
  const pts = values.map((v, i) => {
    const x = (i / (values.length - 1)) * w;
    const y = height - ((v - min) / range) * (height - 4) - 2;
    return `${x},${y}`;
  }).join(' ');
  return (
    <svg viewBox={`0 0 ${w} ${height}`} style={{ width: '100%', height }} preserveAspectRatio="none">
      <polyline fill="none" stroke={color} strokeWidth="1.5" strokeOpacity="0.7" points={pts} />
    </svg>
  );
}

export default function NeuralSDEPage() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState('');

  // Parameters
  const [y0, setY0] = useState(0.1);
  const [tEnd, setTEnd] = useState(1.0);
  const [nSteps, setNSteps] = useState(100);
  const [nPaths, setNPaths] = useState(20);
  const [hiddenSize, setHiddenSize] = useState(32);
  const [method, setMethod] = useState('euler');
  const [seed, setSeed] = useState<number | ''>( 42);

  const runSimulation = async () => {
    setLoading(true); setError('');
    try {
      const res = await api.neuralSdeSimulate({
        y0,
        t_start: 0,
        t_end: tEnd,
        n_steps: nSteps,
        n_paths: nPaths,
        hidden_size: hiddenSize,
        method,
        seed: seed === '' ? null : seed,
      });
      setResult(res);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const runDemo = async () => {
    setLoading(true); setError('');
    try {
      const res = await api.neuralSdeDemo();
      setResult(res);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box>
      <Typography variant="h4" sx={{ mb: 0.5 }}>Neural SDE</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Neural Stochastic Differential Equations — learned drift μ(t,y) and diffusion σ(t,y) via neural networks
      </Typography>

      <Grid container spacing={2.5}>
        {/* Controls */}
        <Grid size={{ xs: 12, md: 4 }}>
          <Card>
            <CardContent>
              <Typography variant="h6" gutterBottom>Simulation Parameters</Typography>
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>

                <TextField
                  label="Initial state y₀"
                  type="number"
                  value={y0}
                  onChange={(e) => setY0(+e.target.value)}
                  size="small" fullWidth
                  helperText="Starting value of the state variable"
                />

                <TextField
                  label="Time horizon T"
                  type="number"
                  value={tEnd}
                  onChange={(e) => setTEnd(Math.max(0.01, +e.target.value))}
                  inputProps={{ min: 0.01, step: 0.25 }}
                  size="small" fullWidth
                  helperText="Simulation end time (years)"
                />

                <Box>
                  <Typography variant="body2" gutterBottom>
                    Time steps: <strong>{nSteps}</strong>
                  </Typography>
                  <Slider
                    value={nSteps}
                    onChange={(_, v) => setNSteps(v as number)}
                    min={10} max={500} step={10}
                    marks={[{ value: 10, label: '10' }, { value: 250, label: '250' }, { value: 500, label: '500' }]}
                  />
                </Box>

                <Box>
                  <Typography variant="body2" gutterBottom>
                    Trajectories: <strong>{nPaths}</strong>
                  </Typography>
                  <Slider
                    value={nPaths}
                    onChange={(_, v) => setNPaths(v as number)}
                    min={1} max={200} step={5}
                    marks={[{ value: 1, label: '1' }, { value: 100, label: '100' }, { value: 200, label: '200' }]}
                  />
                </Box>

                <Box>
                  <Typography variant="body2" gutterBottom>
                    Hidden units: <strong>{hiddenSize}</strong>
                  </Typography>
                  <Slider
                    value={hiddenSize}
                    onChange={(_, v) => setHiddenSize(v as number)}
                    min={8} max={128} step={8}
                    marks={[{ value: 8, label: '8' }, { value: 64, label: '64' }, { value: 128, label: '128' }]}
                  />
                </Box>

                <ToggleButtonGroup
                  exclusive fullWidth
                  value={method}
                  onChange={(_, v) => v && setMethod(v)}
                >
                  <ToggleButton value="euler">Euler-Maruyama</ToggleButton>
                  <ToggleButton value="milstein">Milstein</ToggleButton>
                </ToggleButtonGroup>

                <TextField
                  label="Random seed"
                  type="number"
                  value={seed}
                  onChange={(e) => setSeed(e.target.value === '' ? '' : +e.target.value)}
                  size="small" fullWidth
                  helperText="Leave blank for random network init"
                />

                <Box sx={{ display: 'flex', gap: 1 }}>
                  <Button variant="outlined" onClick={runDemo} disabled={loading} sx={{ flex: 1 }}>
                    Demo
                  </Button>
                  <Button variant="contained" onClick={runSimulation} disabled={loading} sx={{ flex: 2 }}>
                    {loading ? <CircularProgress size={20} /> : 'Simulate'}
                  </Button>
                </Box>
              </Box>
            </CardContent>
          </Card>
        </Grid>

        {/* Results */}
        <Grid size={{ xs: 12, md: 8 }}>
          {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

          {result && (
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>

              {/* Header chips */}
              <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                <Chip label={`Solver: ${result.solver}`} color="primary" size="small" />
                <Chip label={`SDE type: ${result.sde_type?.toUpperCase()}`} variant="outlined" size="small" />
                <Chip label={`${result.trajectories?.length} paths shown`} variant="outlined" size="small" />
                <Chip label={`${result.time?.length} steps`} variant="outlined" size="small" />
              </Box>

              {/* Trajectory sparklines */}
              {result.trajectories && (
                <Card>
                  <CardContent>
                    <Typography variant="h6" gutterBottom>Simulated Trajectories</Typography>
                    <Typography variant="body2" color="text.secondary" gutterBottom>
                      Each line is an independent realisation of the Neural SDE
                    </Typography>
                    <Box sx={{ bgcolor: 'background.default', borderRadius: 2, p: 1 }}>
                      {result.trajectories.slice(0, 20).map((path: number[], i: number) => (
                        <Sparkline
                          key={i}
                          values={path}
                          color={`hsl(${(i * 37) % 360}, 70%, 55%)`}
                          height={30}
                        />
                      ))}
                    </Box>

                    {/* Mean ± std band */}
                    {result.statistics && (
                      <Box sx={{ mt: 1 }}>
                        <Typography variant="caption" color="text.secondary">
                          Mean trajectory (± 1σ envelope)
                        </Typography>
                        <Sparkline values={result.statistics.mean} color="#6366f1" height={50} />
                      </Box>
                    )}
                  </CardContent>
                </Card>
              )}

              {/* Terminal distribution */}
              {result.terminal && (
                <Card>
                  <CardContent>
                    <Typography variant="h6" gutterBottom>Terminal Distribution  Y(T)</Typography>
                    <Table size="small">
                      <TableBody>
                        {[
                          ['Mean', result.terminal.mean?.toFixed(4)],
                          ['Std dev', result.terminal.std?.toFixed(4)],
                          ['P5  (5th percentile)', result.terminal.p5?.toFixed(4)],
                          ['P50 (median)', result.terminal.p50?.toFixed(4)],
                          ['P95 (95th percentile)', result.terminal.p95?.toFixed(4)],
                        ].map(([label, value]) => (
                          <TableRow key={label}>
                            <TableCell sx={{ color: 'text.secondary' }}>{label}</TableCell>
                            <TableCell align="right" sx={{ fontFamily: 'monospace', fontWeight: 600 }}>
                              {value}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </CardContent>
                </Card>
              )}

              {/* Parameters echoed */}
              {result.parameters && (
                <Card>
                  <CardContent>
                    <Typography variant="subtitle2" gutterBottom>Run Parameters</Typography>
                    <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
                      {Object.entries(result.parameters).map(([k, v]) => (
                        <Chip
                          key={k}
                          label={`${k}: ${v}`}
                          size="small"
                          variant="outlined"
                          sx={{ fontFamily: 'monospace', fontSize: '0.72rem' }}
                        />
                      ))}
                    </Box>
                  </CardContent>
                </Card>
              )}
            </Box>
          )}

          {!result && !loading && !error && (
            <Card sx={{ height: 200, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Typography color="text.secondary">
                Click <strong>Demo</strong> for a quick run or configure parameters and click <strong>Simulate</strong>
              </Typography>
            </Card>
          )}
        </Grid>
      </Grid>

      <QuantContextSection
        conceptsTitle="Neural SDEs in quantitative finance"
        concepts={sdeFoundations}
        notes={sdeNotes}
      />
    </Box>
  );
}
