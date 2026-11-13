import React, { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Alert, Box, Button, Card, CardContent, Chip, CircularProgress, Divider, Grid,
  LinearProgress, Step, StepLabel, Stepper, Table, TableBody, TableCell,
  TableHead, TableRow, TextField, Typography,
} from '@mui/material';
import {
  ArrowForward, CheckCircle, Replay, ShowChart, AutoGraph, MenuBook,
} from '@mui/icons-material';
import {
  Area, AreaChart, CartesianGrid, Line, ReferenceLine, ResponsiveContainer,
  Tooltip as RTooltip, XAxis, YAxis,
} from 'recharts';
import { api } from '../services/api';
import { INVESTOR_PROFILES, type Profile } from '../data/investorProfiles';

// ── Types (same shape as /perfil-investidor and /simulacao-b3) ────────────────

interface AssetResult {
  ticker: string;
  S0: number;
  mu: number;
  sigma: number;
  mean: number[];
  p5: number[];
  p95: number[];
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

type Scenario = { profile: Profile; sim: SimResult };

const N_PATHS = 500;

const QUESTIONS = [
  {
    id: 'horizon',
    question: 'Quando você pretende usar esse dinheiro?',
    options: [
      { label: 'Em até 1 ano', value: 0, hint: 'Prazo curto: oscilação tem pouco tempo para se recuperar.' },
      { label: 'Entre 1 e 3 anos', value: 1, hint: 'Prazo médio: dá para atravessar um ciclo ruim.' },
      { label: 'Daqui a 3 anos ou mais', value: 2, hint: 'Prazo longo: o tempo trabalha a favor.' },
    ],
  },
  {
    id: 'drop',
    question: 'Se a carteira caísse 20% em um mês, o que você faria?',
    options: [
      { label: 'Venderia para parar a perda', value: 0, hint: 'Perder no papel incomoda mais do que a chance de recuperar.' },
      { label: 'Não mexeria e esperaria', value: 1, hint: 'Aguenta a queda sem mudar o plano.' },
      { label: 'Aproveitaria para comprar mais', value: 2, hint: 'Queda é oportunidade, não motivo de saída.' },
    ],
  },
  {
    id: 'goal',
    question: 'O que você quer desse investimento?',
    options: [
      { label: 'Proteger o que já tenho', value: 0, hint: 'Preservar vale mais que render.' },
      { label: 'Crescer com equilíbrio', value: 1, hint: 'Render, mas sem sustos grandes.' },
      { label: 'Buscar o maior retorno possível', value: 2, hint: 'Aceita oscilar muito para tentar render mais.' },
    ],
  },
] as const;

type AnswerKey = (typeof QUESTIONS)[number]['id'];
type Answers = Record<AnswerKey, number | null>;

const HORIZON_YEARS = [1, 3, 5] as const;

// ── Helpers ───────────────────────────────────────────────────────────────────

const brl = (value: number) =>
  value.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', maximumFractionDigits: 0 });

const pct = (value: number) =>
  `${value >= 0 ? '+' : ''}${value.toFixed(1).replace('.', ',')}%`;

function recommendedProfile(answers: Answers): Profile {
  const score = (answers.horizon ?? 0) + (answers.drop ?? 0) + (answers.goal ?? 0);
  if (score <= 2) return INVESTOR_PROFILES[0];
  if (score <= 4) return INVESTOR_PROFILES[1];
  return INVESTOR_PROFILES[2];
}

/** Portfolio value along the path, using each asset's mean/p5/p95 series. */
function portfolioPath(sim: SimResult, profile: Profile, initial: number, field: 'mean' | 'p5' | 'p95'): number[] {
  return sim.time_days.map((_, t) =>
    initial * profile.assets.reduce((acc, alloc) => {
      const asset = sim.assets.find((a) => a.ticker === alloc.ticker);
      if (!asset) return acc;
      return acc + alloc.weight * (asset[field][t] / alloc.S0);
    }, 0),
  );
}

/**
 * Terminal values in R$ built from each asset's terminal quantiles. This is a
 * weighted mixture of per-asset quantiles, not the joint distribution of the
 * portfolio (assets are simulated independently) — the UI states that.
 */
function terminalPortfolio(sim: SimResult, profile: Profile, initial: number) {
  const mix = (field: 'mean' | 'p50' | 'p5' | 'p95') =>
    initial * profile.assets.reduce((acc, alloc) => {
      const asset = sim.assets.find((a) => a.ticker === alloc.ticker);
      if (!asset) return acc;
      return acc + alloc.weight * (asset.terminal[field] / alloc.S0);
    }, 0);
  return { mean: mix('mean'), median: mix('p50'), p5: mix('p5'), p95: mix('p95') };
}

function maxDrawdown(values: number[]): number {
  let peak = values[0];
  let worst = 0;
  for (const v of values) {
    if (v > peak) peak = v;
    worst = Math.max(worst, (peak - v) / peak);
  }
  return worst * 100;
}

function downsample<T>(arr: T[], max = 220): T[] {
  if (arr.length <= max) return arr;
  const step = Math.ceil(arr.length / max);
  return arr.filter((_, i) => i % step === 0 || i === arr.length - 1);
}

function KpiCard({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <Card sx={{ height: '100%' }}>
      <CardContent>
        <Typography variant="caption" color="text.secondary" sx={{ textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          {label}
        </Typography>
        <Typography variant="h5" fontWeight={700} sx={{ mt: 0.5 }}>
          {value}
        </Typography>
        {detail && (
          <Typography variant="caption" color="text.secondary">
            {detail}
          </Typography>
        )}
      </CardContent>
    </Card>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ClientExperiencePage() {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [answers, setAnswers] = useState<Answers>({ horizon: null, drop: null, goal: null });
  const [amount, setAmount] = useState('10000');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [scenarios, setScenarios] = useState<Scenario[] | null>(null);

  const initial = Number(amount.replace(/\./g, '').replace(',', '.'));
  const validAmount = Number.isFinite(initial) && initial >= 100;
  const answered = QUESTIONS.every((q) => answers[q.id] !== null);
  const recommended = recommendedProfile(answers);
  const horizonYears = HORIZON_YEARS[answers.horizon ?? 0];

  const recommendedScenario = scenarios?.find((s) => s.profile.id === recommended.id) ?? scenarios?.[0];

  const result = useMemo(() => {
    if (!recommendedScenario) return null;
    const { sim, profile } = recommendedScenario;
    const terminal = terminalPortfolio(sim, profile, initial);
    const meanPath = portfolioPath(sim, profile, initial, 'mean');
    const p5Path = portfolioPath(sim, profile, initial, 'p5');
    const p95Path = portfolioPath(sim, profile, initial, 'p95');
    const chart = downsample(
      sim.time_days.map((day, t) => ({
        day,
        mean: Math.round(meanPath[t]),
        p5: Math.round(p5Path[t]),
        band: Math.round(p95Path[t] - p5Path[t]),
      })),
    );
    return {
      terminal,
      meanPath,
      chart,
      maxDd: maxDrawdown(meanPath),
      expectedReturnPct: (terminal.mean / initial - 1) * 100,
      worstPct: (terminal.p5 / initial - 1) * 100,
    };
  }, [recommendedScenario, initial]);

  const runSimulation = async () => {
    setLoading(true);
    setError('');
    try {
      const runs = await Promise.all(
        INVESTOR_PROFILES.map((profile) =>
          api
            .capmGbmMulti({
              assets: profile.assets.map(({ ticker, S0, mu, sigma }) => ({ ticker, S0, mu, sigma })),
              T: horizonYears,
              n_steps: Math.round(horizonYears * 252),
              n_paths: N_PATHS,
            })
            .then((sim) => ({ profile, sim: sim as SimResult })),
        ),
      );
      setScenarios(runs);
      setStep(2);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Não foi possível rodar a simulação.');
    } finally {
      setLoading(false);
    }
  };

  const restart = () => {
    setStep(0);
    setAnswers({ horizon: null, drop: null, goal: null });
    setScenarios(null);
    setError('');
  };

  return (
    <Box sx={{ p: 3, maxWidth: 1200, mx: 'auto' }}>
      <Box sx={{ mb: 3 }}>
        <Typography variant="h4" fontWeight={700} gutterBottom>
          Meu plano
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Três perguntas para descobrir o perfil que combina com você, um valor para dar escala ao resultado,
          e um cenário simulado para ver o que pode acontecer — em reais, não em jargão.
        </Typography>
      </Box>

      <Stepper activeStep={step} sx={{ mb: 4 }}>
        <Step completed={answered}><StepLabel>Seu perfil</StepLabel></Step>
        <Step completed={scenarios !== null}><StepLabel>Valor e prazo</StepLabel></Step>
        <Step><StepLabel>Cenário</StepLabel></Step>
      </Stepper>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>
          {error}
        </Alert>
      )}

      {/* ── Step 1: quiz ─────────────────────────────────────────────── */}
      {step === 0 && (
        <Box>
          {QUESTIONS.map((q, qi) => (
            <Card key={q.id} sx={{ mb: 2 }}>
              <CardContent>
                <Typography variant="subtitle1" fontWeight={600} gutterBottom>
                  {qi + 1}. {q.question}
                </Typography>
                <Grid container spacing={1.5}>
                  {q.options.map((option) => {
                    const selected = answers[q.id] === option.value;
                    return (
                      <Grid size={{ xs: 12, md: 4 }} key={option.label}>
                        <Card
                          variant="outlined"
                          onClick={() => setAnswers((prev) => ({ ...prev, [q.id]: option.value }))}
                          sx={{
                            cursor: 'pointer',
                            height: '100%',
                            borderColor: selected ? 'primary.main' : 'divider',
                            bgcolor: selected ? 'action.selected' : 'background.paper',
                            transition: 'border-color 0.15s',
                            '&:hover': { borderColor: 'primary.main' },
                          }}
                        >
                          <CardContent sx={{ py: 1.5 }}>
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                              {selected && <CheckCircle color="primary" sx={{ fontSize: 18 }} />}
                              <Typography variant="body2" fontWeight={600}>
                                {option.label}
                              </Typography>
                            </Box>
                            <Typography variant="caption" color="text.secondary">
                              {option.hint}
                            </Typography>
                          </CardContent>
                        </Card>
                      </Grid>
                    );
                  })}
                </Grid>
              </CardContent>
            </Card>
          ))}

          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
            <Button
              variant="contained"
              endIcon={<ArrowForward />}
              disabled={!answered}
              onClick={() => setStep(1)}
            >
              Ver meu plano
            </Button>
            {answered && (
              <Chip
                label={`Perfil sugerido: ${recommended.label}`}
                sx={{ bgcolor: recommended.bgColor, color: recommended.color, fontWeight: 600 }}
              />
            )}
          </Box>
        </Box>
      )}

      {/* ── Step 2: amount + horizon ─────────────────────────────────── */}
      {step === 1 && (
        <Grid container spacing={3}>
          <Grid size={{ xs: 12, md: 7 }}>
            <Card>
              <CardContent>
                <Typography variant="subtitle1" fontWeight={600} gutterBottom>
                  Quanto você quer simular?
                </Typography>
                <TextField
                  label="Valor inicial"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  fullWidth
                  sx={{ mt: 1 }}
                  helperText={
                    validAmount
                      ? 'O valor entra só na escala dos resultados; a simulação é a mesma.'
                      : 'Informe um valor a partir de R$ 100.'
                  }
                  error={!validAmount}
                  slotProps={{ input: { startAdornment: <Typography sx={{ mr: 1 }}>R$</Typography> } }}
                />
                <Box sx={{ display: 'flex', gap: 1, mt: 2, alignItems: 'center', flexWrap: 'wrap' }}>
                  <Chip label={`Prazo: ${horizonYears} ${horizonYears === 1 ? 'ano' : 'anos'}`} />
                  <Chip
                    label={recommended.label}
                    sx={{ bgcolor: recommended.bgColor, color: recommended.color, fontWeight: 600 }}
                  />
                  <Typography variant="caption" color="text.secondary">
                    {N_PATHS.toLocaleString('pt-BR')} trajetórias simuladas por perfil
                  </Typography>
                </Box>
                <Box sx={{ mt: 3, display: 'flex', gap: 1 }}>
                  <Button onClick={() => setStep(0)}>Voltar</Button>
                  <Button
                    variant="contained"
                    onClick={runSimulation}
                    disabled={!validAmount || loading}
                    startIcon={loading ? <CircularProgress size={16} color="inherit" /> : <ShowChart />}
                  >
                    {loading ? 'Simulando…' : 'Simular meu cenário'}
                  </Button>
                </Box>
              </CardContent>
            </Card>
          </Grid>
          <Grid size={{ xs: 12, md: 5 }}>
            <Card sx={{ borderColor: recommended.color, borderWidth: 2, borderStyle: 'solid' }}>
              <CardContent>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                  <recommended.Icon sx={{ color: recommended.color }} />
                  <Typography variant="h6" fontWeight={700} sx={{ color: recommended.color }}>
                    {recommended.label}
                  </Typography>
                </Box>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                  {recommended.description}
                </Typography>
                <Divider sx={{ mb: 1.5 }} />
                {recommended.assets.map((a) => (
                  <Box key={a.ticker} sx={{ mb: 1 }}>
                    <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
                      <Typography variant="caption" fontWeight={600}>{a.ticker}</Typography>
                      <Typography variant="caption" fontWeight={600} sx={{ color: recommended.color }}>
                        {(a.weight * 100).toFixed(0)}%
                      </Typography>
                    </Box>
                    <LinearProgress
                      variant="determinate"
                      value={a.weight * 100}
                      sx={{
                        height: 4, borderRadius: 2,
                        backgroundColor: recommended.color + '22',
                        '& .MuiLinearProgress-bar': { backgroundColor: recommended.color },
                      }}
                    />
                  </Box>
                ))}
                <Divider sx={{ my: 1.5 }} />
                <Typography variant="caption" color="text.secondary">
                  Retorno esperado {(recommended.expectedReturn * 100).toFixed(1)}% ao ano ·
                  volatilidade {(recommended.expectedVol * 100).toFixed(1)}% ao ano
                </Typography>
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      )}

      {/* ── Step 3: results ──────────────────────────────────────────── */}
      {step === 2 && result && recommendedScenario && (
        <Box>
          <Alert severity="warning" sx={{ mb: 3 }}>
            Cenário sintético, não previsão: μ e σ fixos por ativo, ativos simulados de forma independente
            (sem correlação) e sem custos, impostos ou dividendos. Não é recomendação de investimento.
          </Alert>

          <Grid container spacing={2} sx={{ mb: 3 }}>
            <Grid size={{ xs: 12, sm: 6, md: 3 }}>
              <KpiCard
                label="Cenário típico"
                value={brl(result.terminal.mean)}
                detail={`${pct(result.expectedReturnPct)} sobre ${brl(initial)} em ${horizonYears} ${horizonYears === 1 ? 'ano' : 'anos'}`}
              />
            </Grid>
            <Grid size={{ xs: 12, sm: 6, md: 3 }}>
              <KpiCard
                label="9 em 10 cenários entre"
                value={`${brl(result.terminal.p5)} – ${brl(result.terminal.p95)}`}
                detail="Faixa montada somando as quantis de cada ativo"
              />
            </Grid>
            <Grid size={{ xs: 12, sm: 6, md: 3 }}>
              <KpiCard
                label="Pior cenário (10%)"
                value={brl(result.terminal.p5)}
                detail={`${pct(result.worstPct)} sobre o valor investido`}
              />
            </Grid>
            <Grid size={{ xs: 12, sm: 6, md: 3 }}>
              <KpiCard
                label="Queda máxima no caminho médio"
                value={`${result.maxDd.toFixed(1).replace('.', ',')}%`}
                detail={`Volatilidade do perfil: ${(recommendedScenario.profile.expectedVol * 100).toFixed(1)}% ao ano`}
              />
            </Grid>
          </Grid>

          <Card sx={{ mb: 3 }}>
            <CardContent>
              <Typography variant="subtitle1" fontWeight={600} gutterBottom>
                Trajetória média do perfil {recommendedScenario.profile.label}
              </Typography>
              <Box sx={{ height: 320 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={result.chart} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
                    <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                    <XAxis dataKey="day" tickFormatter={(d: number) => `${Math.round(d / 30)}m`} />
                    <YAxis tickFormatter={(v: number) => `${Math.round(v / 1000)}k`} width={48} />
                    <RTooltip
                      formatter={(value) => brl(Number(value))}
                      labelFormatter={(day) => `Dia ${String(day)}`}
                    />
                    <ReferenceLine y={initial} stroke="#94a3b8" strokeDasharray="4 4" />
                    <Area dataKey="p5" stackId="band" stroke="none" fill="transparent" tooltipType="none" />
                    <Area
                      dataKey="band"
                      name="Faixa p5–p95"
                      stackId="band"
                      stroke="none"
                      fill={recommendedScenario.profile.color}
                      fillOpacity={0.18}
                      tooltipType="none"
                    />
                    <Line
                      dataKey="mean"
                      name="Média"
                      stroke={recommendedScenario.profile.color}
                      strokeWidth={2}
                      dot={false}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </Box>
              <Typography variant="caption" color="text.secondary">
                Linha tracejada = valor investido. A faixa cobre os 90% centrais das trajetórias simuladas.
              </Typography>
            </CardContent>
          </Card>

          <Card sx={{ mb: 3 }}>
            <CardContent>
              <Typography variant="subtitle1" fontWeight={600} gutterBottom>
                Mesmo valor, mesmo prazo: os três perfis
              </Typography>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Perfil</TableCell>
                    <TableCell align="right">Cenário típico</TableCell>
                    <TableCell align="right">Pior cenário (10%)</TableCell>
                    <TableCell align="right">Volatilidade</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {scenarios?.map(({ profile, sim }) => {
                    const terminal = terminalPortfolio(sim, profile, initial);
                    const isRecommended = profile.id === recommended.id;
                    return (
                      <TableRow key={profile.id} selected={isRecommended}>
                        <TableCell>
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                            <profile.Icon sx={{ fontSize: 16, color: profile.color }} />
                            <Typography variant="body2" fontWeight={isRecommended ? 700 : 500}>
                              {profile.label}
                            </Typography>
                            {isRecommended && (
                              <Chip label="seu perfil" size="small" sx={{ bgcolor: profile.bgColor, color: profile.color }} />
                            )}
                          </Box>
                        </TableCell>
                        <TableCell align="right">
                          {brl(terminal.mean)}
                          <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                            {pct((terminal.mean / initial - 1) * 100)}
                          </Typography>
                        </TableCell>
                        <TableCell align="right">
                          {brl(terminal.p5)}
                          <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                            {pct((terminal.p5 / initial - 1) * 100)}
                          </Typography>
                        </TableCell>
                        <TableCell align="right">{(profile.expectedVol * 100).toFixed(1)}%</TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          <Card>
            <CardContent>
              <Typography variant="subtitle1" fontWeight={600} gutterBottom>
                Próximos passos
              </Typography>
              <Grid container spacing={2}>
                <Grid size={{ xs: 12, md: 4 }}>
                  <Button fullWidth variant="contained" startIcon={<ShowChart />} onClick={() => navigate('/cliente')}>
                    Montar uma operação pronta
                  </Button>
                </Grid>
                <Grid size={{ xs: 12, md: 4 }}>
                  <Button fullWidth variant="outlined" startIcon={<AutoGraph />} onClick={() => navigate('/cliente')}>
                    Escolher ativo, instrumento e prazo
                  </Button>
                </Grid>
                <Grid size={{ xs: 12, md: 4 }}>
                  <Button fullWidth variant="outlined" startIcon={<MenuBook />} onClick={restart}>
                    Refazer o questionário
                  </Button>
                </Grid>
              </Grid>
              <Box sx={{ mt: 3, display: 'flex', gap: 1 }}>
                <Button startIcon={<Replay />} onClick={restart}>
                  Refazer o questionário
                </Button>
                <Button onClick={() => setStep(1)}>Mudar valor ou prazo</Button>
              </Box>
            </CardContent>
          </Card>
        </Box>
      )}
    </Box>
  );
}
