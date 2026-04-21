import React, { useState } from 'react';
import {
  Box, Typography, Slider, Button, Card, CardContent, Chip,
  CircularProgress, LinearProgress, Divider, Fade, Zoom, Grid,
  ToggleButton, ToggleButtonGroup, Tooltip, Collapse, Alert
} from '@mui/material';
import {
  AutoFixHigh, RocketLaunch, Shield, LocalFireDepartment,
  Balance, Visibility, VisibilityOff, CheckCircle, Warning,
  TrendingUp, TrendingDown, Psychology, Search as SearchIcon
} from '@mui/icons-material';
import axios from 'axios';

// ── Types ────────────────────────────────────────────────────────────────────

interface Scenario { pct: number; brl: number; }

interface Operation {
  profile: string;
  profile_emoji: string;
  profile_color: string;
  ticker: string;
  ticker_name: string;
  direction: string;
  direction_en: string;
  strike: number;
  spot_price: number;
  option_premium: number;
  num_options: number;
  total_cost: number;
  expiry_label: string;
  scenario_bear: Scenario;
  scenario_base: Scenario;
  scenario_bull: Scenario;
  max_loss: number;
  probability_of_profit: number;
  bull_score: number;
  ai_consensus: string;
  narrative_summary: string;
  validated: boolean;
}

interface AutopilotResult {
  capital: number;
  horizon_days: number;
  generated_at: string;
  operations: Operation[];
  disclaimer: string;
}

// ── Formatting Helpers ───────────────────────────────────────────────────────

const fmt = (n: number) => n.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
const horizonLabels: Record<number, string> = { 7: '1 Semana', 30: '1 Mês', 90: '3 Meses', 180: '6 Meses' };

// ── Loading Animation ────────────────────────────────────────────────────────

const stages = [
  { icon: <SearchIcon />, label: 'Escaneando 18 ativos B3...', color: '#fbbf24' },
  { icon: <Psychology />, label: 'Claude analisando fundamentos...', color: '#F97316' },
  { icon: <TrendingUp />, label: 'GPT-5 calculando estratégias...', color: '#10B981' },
  { icon: <AutoFixHigh />, label: 'Gemini monitorando notícias...', color: '#6495ED' },
  { icon: <RocketLaunch />, label: 'Grok detectando rumores...', color: '#00f2ff' },
  { icon: <Shield />, label: 'Backtesting matemático...', color: '#a855f7' },
  { icon: <CheckCircle />, label: 'Validando operações...', color: '#22c55e' },
];

function LoadingCinematic() {
  const [stage, setStage] = React.useState(0);
  React.useEffect(() => {
    const t = setInterval(() => setStage(s => (s + 1) % stages.length), 2500);
    return () => clearInterval(t);
  }, []);
  const s = stages[stage];
  return (
    <Box sx={{ textAlign: 'center', py: 10 }}>
      <Box sx={{ mb: 4, display: 'flex', justifyContent: 'center', gap: 2 }}>
        {stages.map((st, i) => (
          <Box key={i} sx={{
            width: 40, height: 40, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center',
            bgcolor: i <= stage ? `${st.color}22` : 'rgba(255,255,255,0.03)',
            border: `2px solid ${i <= stage ? st.color : 'rgba(255,255,255,0.05)'}`,
            transition: 'all 0.5s ease',
            color: i <= stage ? st.color : 'rgba(255,255,255,0.1)',
            transform: i === stage ? 'scale(1.3)' : 'scale(1)',
          }}>
            {React.cloneElement(st.icon, { sx: { fontSize: '1.2rem' } })}
          </Box>
        ))}
      </Box>
      <CircularProgress size={60} sx={{ color: s.color, mb: 3 }} />
      <Typography variant="h6" sx={{ color: s.color, fontWeight: 800, mb: 1, transition: 'color 0.5s' }}>
        {s.label}
      </Typography>
      <Typography variant="body2" sx={{ color: 'rgba(255,255,255,0.3)' }}>
        Processando 6 modelos de IA em paralelo para os 18 ativos do Ibovespa...
      </Typography>
      <LinearProgress sx={{ mt: 4, mx: 'auto', maxWidth: 400, height: 6, borderRadius: 3, bgcolor: 'rgba(255,255,255,0.05)', '& .MuiLinearProgress-bar': { bgcolor: s.color } }} />
    </Box>
  );
}

// ── Operation Card ───────────────────────────────────────────────────────────

function OperationCard({ op, idx }: { op: Operation; idx: number }) {
  const [expanded, setExpanded] = useState(false);
  const profileIcons: Record<string, JSX.Element> = {
    'Conservador': <Shield sx={{ color: '#3b82f6' }} />,
    'Moderado': <Balance sx={{ color: '#a855f7' }} />,
    'Agressivo': <LocalFireDepartment sx={{ color: '#ef4444' }} />,
  };

  return (
    <Zoom in style={{ transitionDelay: `${idx * 200}ms` }}>
      <Card sx={{
        bgcolor: 'rgba(20, 20, 35, 0.9)',
        backdropFilter: 'blur(20px)',
        border: `2px solid ${op.profile_color}33`,
        borderRadius: 4,
        position: 'relative',
        overflow: 'visible',
        transition: 'all 0.3s ease',
        '&:hover': { border: `2px solid ${op.profile_color}66`, transform: 'translateY(-4px)', boxShadow: `0 20px 40px ${op.profile_color}15` },
      }}>
        {op.validated && (
          <Chip icon={<CheckCircle sx={{ fontSize: '0.9rem !important' }} />} label="VALIDADO" size="small"
            sx={{ position: 'absolute', top: -12, right: 16, bgcolor: '#22c55e', color: '#fff', fontWeight: 900, fontSize: '0.65rem' }} />
        )}
        <CardContent sx={{ p: 3 }}>
          {/* Header */}
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 2 }}>
            {profileIcons[op.profile] || <Shield />}
            <Box>
              <Typography variant="subtitle2" sx={{ color: op.profile_color, fontWeight: 900, fontSize: '0.9rem' }}>
                {op.profile_emoji} {op.profile.toUpperCase()}
              </Typography>
              <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.4)' }}>
                {op.ai_consensus}
              </Typography>
            </Box>
          </Box>

          {/* Ticker & Direction */}
          <Box sx={{ bgcolor: 'rgba(0,0,0,0.3)', p: 2, borderRadius: 2, mb: 2 }}>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
              <Typography variant="h5" sx={{ fontWeight: 900, color: '#fff' }}>{op.ticker}</Typography>
              <Typography variant="body2" sx={{ color: op.profile_color, fontWeight: 800 }}>
                R$ {op.spot_price.toFixed(2)}
              </Typography>
            </Box>
            <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.4)', display: 'block', mb: 1.5 }}>{op.ticker_name}</Typography>
            <Chip label={op.direction} sx={{
              bgcolor: op.direction_en.includes('CALL') ? 'rgba(34,197,94,0.15)' : op.direction_en.includes('PUT') ? 'rgba(239,68,68,0.15)' : 'rgba(251,191,36,0.15)',
              color: op.direction_en.includes('CALL') ? '#22c55e' : op.direction_en.includes('PUT') ? '#ef4444' : '#fbbf24',
              fontWeight: 900, fontSize: '0.85rem',
            }} />
          </Box>

          {/* Operation Details */}
          <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 1, mb: 2 }}>
            <Box sx={{ bgcolor: 'rgba(255,255,255,0.03)', p: 1.5, borderRadius: 1 }}>
              <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.3)', display: 'block' }}>STRIKE</Typography>
              <Typography variant="body2" sx={{ color: '#fff', fontWeight: 800 }}>R$ {op.strike.toFixed(2)}</Typography>
            </Box>
            <Box sx={{ bgcolor: 'rgba(255,255,255,0.03)', p: 1.5, borderRadius: 1 }}>
              <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.3)', display: 'block' }}>PRÊMIO</Typography>
              <Typography variant="body2" sx={{ color: '#fff', fontWeight: 800 }}>R$ {op.option_premium.toFixed(2)}</Typography>
            </Box>
            <Box sx={{ bgcolor: 'rgba(255,255,255,0.03)', p: 1.5, borderRadius: 1 }}>
              <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.3)', display: 'block' }}>LOTES</Typography>
              <Typography variant="body2" sx={{ color: '#fff', fontWeight: 800 }}>{op.num_options} opções</Typography>
            </Box>
            <Box sx={{ bgcolor: 'rgba(255,255,255,0.03)', p: 1.5, borderRadius: 1 }}>
              <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.3)', display: 'block' }}>CUSTO TOTAL</Typography>
              <Typography variant="body2" sx={{ color: '#fff', fontWeight: 800 }}>{fmt(op.total_cost)}</Typography>
            </Box>
          </Box>

          {/* Scenarios */}
          <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.3)', mb: 1, display: 'block', fontWeight: 700 }}>CENÁRIOS DE RETORNO</Typography>
          {[
            { label: '🐻 Pessimista', data: op.scenario_bear, color: '#ef4444' },
            { label: '📊 Base', data: op.scenario_base, color: '#fbbf24' },
            { label: '🚀 Otimista', data: op.scenario_bull, color: '#22c55e' },
          ].map(s => (
            <Box key={s.label} sx={{ display: 'flex', justifyContent: 'space-between', py: 0.5, px: 1 }}>
              <Typography variant="body2" sx={{ color: 'rgba(255,255,255,0.5)', fontSize: '0.8rem' }}>{s.label}</Typography>
              <Typography variant="body2" sx={{ color: s.color, fontWeight: 800, fontSize: '0.8rem' }}>
                {s.data.pct >= 0 ? '+' : ''}{s.data.pct}% ({fmt(s.data.brl)})
              </Typography>
            </Box>
          ))}

          <Divider sx={{ my: 2, borderColor: 'rgba(255,255,255,0.05)' }} />

          {/* Bottom Metrics */}
          <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
            <Box>
              <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.3)' }}>PROB. LUCRO</Typography>
              <Typography variant="body1" sx={{ color: op.probability_of_profit >= 50 ? '#22c55e' : '#fbbf24', fontWeight: 900 }}>
                {op.probability_of_profit}%
              </Typography>
            </Box>
            <Box sx={{ textAlign: 'center' }}>
              <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.3)' }}>BULL SCORE</Typography>
              <Typography variant="body1" sx={{ color: op.bull_score >= 62 ? '#22c55e' : '#fbbf24', fontWeight: 900 }}>
                {op.bull_score}/100
              </Typography>
            </Box>
            <Box sx={{ textAlign: 'right' }}>
              <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.3)' }}>PERDA MÁX</Typography>
              <Typography variant="body1" sx={{ color: '#ef4444', fontWeight: 900 }}>{fmt(op.max_loss)}</Typography>
            </Box>
          </Box>

          {/* Expandable narrative */}
          <Button size="small" onClick={() => setExpanded(!expanded)} startIcon={expanded ? <VisibilityOff /> : <Visibility />}
            sx={{ mt: 1, color: 'rgba(255,255,255,0.3)', fontSize: '0.7rem' }}>
            {expanded ? 'Ocultar' : 'Ver'} Relatório IA
          </Button>
          <Collapse in={expanded}>
            <Box sx={{ mt: 1, p: 2, bgcolor: 'rgba(255,255,255,0.02)', borderRadius: 2 }}>
              <Typography variant="body2" sx={{ color: 'rgba(255,255,255,0.6)', whiteSpace: 'pre-wrap', fontSize: '0.8rem', lineHeight: 1.7 }}>
                {op.narrative_summary}
              </Typography>
            </Box>
          </Collapse>
        </CardContent>
      </Card>
    </Zoom>
  );
}

// ── Main Autopilot Page ──────────────────────────────────────────────────────

export default function AutopilotPage() {
  const [capital, setCapital] = useState(10000);
  const [horizon, setHorizon] = useState(30);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AutopilotResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleGenerate = async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await axios.post('http://127.0.0.1:8000/api/autopilot/generate', {
        capital,
        horizon_days: horizon,
      });
      setResult(res.data);
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Erro ao processar. Verifique as chaves de API.');
    } finally {
      setLoading(false);
    }
  };

  const capitalMarks = [
    { value: 1000, label: 'R$ 1k' },
    { value: 10000, label: 'R$ 10k' },
    { value: 50000, label: 'R$ 50k' },
    { value: 100000, label: 'R$ 100k' },
    { value: 500000, label: 'R$ 500k' },
  ];

  return (
    <Box sx={{ minHeight: '100vh', background: 'radial-gradient(ellipse at 20% 50%, rgba(15, 10, 30, 1) 0%, rgba(5, 5, 15, 1) 100%)', p: 4 }}>
      {/* Title */}
      <Fade in timeout={800}>
        <Box sx={{ textAlign: 'center', mb: 6 }}>
          <Typography variant="h3" sx={{ fontWeight: 900, color: '#fff', mb: 1, letterSpacing: '-0.03em' }}>
            <RocketLaunch sx={{ fontSize: '2.5rem', color: '#fbbf24', mr: 2, verticalAlign: 'middle' }} />
            ATOM AUTOPILOT
          </Typography>
          <Typography variant="subtitle1" sx={{ color: 'rgba(255,255,255,0.4)', maxWidth: 600, mx: 'auto' }}>
            Insira quanto quer investir e por quanto tempo. Nossa inteligência artificial faz o resto.
          </Typography>
        </Box>
      </Fade>

      {/* Input Wizard */}
      {!loading && !result && (
        <Fade in timeout={1000}>
          <Card sx={{
            maxWidth: 700, mx: 'auto', bgcolor: 'rgba(20, 20, 35, 0.9)', backdropFilter: 'blur(20px)',
            border: '1px solid rgba(251, 191, 36, 0.15)', borderRadius: 4, p: 4,
          }}>
            <CardContent>
              {/* Capital Slider */}
              <Typography variant="subtitle2" sx={{ color: '#fbbf24', fontWeight: 800, mb: 1 }}>
                💰 QUANTO DESEJA INVESTIR?
              </Typography>
              <Typography variant="h4" sx={{ color: '#fff', fontWeight: 900, mb: 2, textAlign: 'center' }}>
                {fmt(capital)}
              </Typography>
              <Slider
                value={capital}
                onChange={(_, v) => setCapital(v as number)}
                min={1000} max={500000} step={1000}
                marks={capitalMarks}
                sx={{
                  color: '#fbbf24', mb: 5,
                  '& .MuiSlider-markLabel': { color: 'rgba(255,255,255,0.3)', fontSize: '0.7rem' },
                  '& .MuiSlider-thumb': { boxShadow: '0 0 12px rgba(251, 191, 36, 0.5)' },
                }}
              />

              {/* Horizon Selector */}
              <Typography variant="subtitle2" sx={{ color: '#fbbf24', fontWeight: 800, mb: 2 }}>
                ⏱️ POR QUANTO TEMPO?
              </Typography>
              <ToggleButtonGroup
                value={horizon}
                exclusive
                onChange={(_, v) => v && setHorizon(v)}
                fullWidth
                sx={{ mb: 4 }}
              >
                {[7, 30, 90, 180].map(d => (
                  <ToggleButton key={d} value={d} sx={{
                    color: 'rgba(255,255,255,0.4)', fontWeight: 700,
                    borderColor: 'rgba(255,255,255,0.1)',
                    '&.Mui-selected': { bgcolor: 'rgba(251,191,36,0.15)', color: '#fbbf24', borderColor: '#fbbf24' },
                  }}>
                    {horizonLabels[d]}
                  </ToggleButton>
                ))}
              </ToggleButtonGroup>

              {/* Generate Button */}
              <Button
                fullWidth variant="contained" size="large"
                onClick={handleGenerate}
                sx={{
                  bgcolor: '#fbbf24', color: '#000', fontWeight: 900, py: 2, fontSize: '1.1rem',
                  borderRadius: 3,
                  boxShadow: '0 0 40px rgba(251, 191, 36, 0.3)',
                  '&:hover': { bgcolor: '#f59e0b', boxShadow: '0 0 60px rgba(251, 191, 36, 0.5)' },
                }}
                startIcon={<RocketLaunch />}
              >
                GERAR MINHA OPERAÇÃO
              </Button>

              <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.2)', mt: 2, display: 'block', textAlign: 'center' }}>
                6 modelos de IA + backtest matemático • Resultado em segundos
              </Typography>
            </CardContent>
          </Card>
        </Fade>
      )}

      {/* Loading State */}
      {loading && <LoadingCinematic />}

      {/* Error */}
      {error && (
        <Alert severity="error" sx={{ maxWidth: 600, mx: 'auto', mt: 4 }}>{error}</Alert>
      )}

      {/* Results */}
      {result && (
        <Fade in timeout={800}>
          <Box>
            {/* Summary Header */}
            <Box sx={{ textAlign: 'center', mb: 4 }}>
              <Chip label="GABARITO VALIDADO" icon={<CheckCircle />} sx={{ bgcolor: '#22c55e', color: '#fff', fontWeight: 900, mb: 2, px: 2, fontSize: '0.85rem' }} />
              <Typography variant="h5" sx={{ color: '#fff', fontWeight: 800 }}>
                Investimento de {fmt(result.capital)} por {horizonLabels[result.horizon_days] || `${result.horizon_days} dias`}
              </Typography>
              <Typography variant="body2" sx={{ color: 'rgba(255,255,255,0.3)', mt: 1 }}>
                Gerado em {new Date(result.generated_at).toLocaleString('pt-BR')}
              </Typography>
            </Box>

            {/* Operation Cards */}
            <Grid container spacing={3} sx={{ maxWidth: 1200, mx: 'auto' }}>
              {result.operations.map((op, idx) => (
                <Grid xs={12} md={4} key={op.profile}>
                  <OperationCard op={op} idx={idx} />
                </Grid>
              ))}
            </Grid>

            {/* Disclaimer */}
            <Box sx={{ maxWidth: 800, mx: 'auto', mt: 4 }}>
              <Alert severity="warning" sx={{ bgcolor: 'rgba(251,191,36,0.05)', border: '1px solid rgba(251,191,36,0.15)', color: 'rgba(255,255,255,0.5)' }}>
                {result.disclaimer}
              </Alert>
            </Box>

            {/* Retry */}
            <Box sx={{ textAlign: 'center', mt: 4 }}>
              <Button variant="outlined" onClick={() => setResult(null)}
                sx={{ color: '#fbbf24', borderColor: '#fbbf24', fontWeight: 700, '&:hover': { borderColor: '#f59e0b', bgcolor: 'rgba(251,191,36,0.05)' } }}>
                NOVA OPERAÇÃO
              </Button>
            </Box>
          </Box>
        </Fade>
      )}
    </Box>
  );
}
