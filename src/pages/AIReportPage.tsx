import React, { useState, useRef } from 'react';
import {
  Box, Card, CardContent, Typography, Button, CircularProgress,
  Alert, Chip, Grid, LinearProgress, Divider, TextField,
  Table, TableBody, TableCell, TableRow, Fade, Tabs, Tab,
} from '@mui/material';
import {
  TrendingUp, TrendingDown, SwapVert, Search,
  AutoGraph, Security, Psychology, ShowChart,
} from '@mui/icons-material';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from 'recharts';
import { api } from '../services/api';
import { Timer, HourglassEmpty } from '@mui/icons-material';

// ── Score gauge ────────────────────────────────────────────────────────────

function BullScoreGauge({ score }: { score: number }) {
  const color = score >= 62 ? '#10b981' : score <= 38 ? '#ef4444' : '#f59e0b';
  const label = score >= 62 ? 'ALTISTA' : score <= 38 ? 'BAIXISTA' : 'NEUTRO';
  const pct = score;

  return (
    <Box sx={{ textAlign: 'center', py: 2 }}>
      <Typography variant="caption" color="text.secondary" sx={{ letterSpacing: '0.1em' }}>
        BULL SCORE
      </Typography>
      <Typography variant="h1" sx={{ fontWeight: 900, color, fontFamily: 'monospace', lineHeight: 1 }}>
        {score}
      </Typography>
      <Typography variant="caption" color="text.secondary">/100</Typography>
      <Box sx={{ mt: 1, px: 2 }}>
        <LinearProgress
          variant="determinate" value={pct}
          sx={{
            height: 10, borderRadius: 5, bgcolor: 'background.default',
            '& .MuiLinearProgress-bar': { bgcolor: color, borderRadius: 5 },
          }}
        />
      </Box>
      <Chip label={label} sx={{ mt: 1, bgcolor: color, color: '#fff', fontWeight: 700, fontSize: '0.85rem' }} />
    </Box>
  );
}

// ── Kelly Sizing card ──────────────────────────────────────────────────────

function KellySizingCard({ kelly }: { kelly: any }) {
  if (!kelly || kelly.erro) return null;
  
  return (
    <Box sx={{ 
      p: 2, borderRadius: 2, bgcolor: 'rgba(99, 102, 241, 0.05)', 
      border: '1px dashed rgba(99, 102, 241, 0.4)',
      mt: 1
    }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
        <Security sx={{ fontSize: 18, color: 'primary.light' }} />
        <Typography variant="subtitle2" sx={{ fontWeight: 800, fontSize: '0.75rem', letterSpacing: '0.05em' }}>
          TAMANHO ÓTIMO (KELLY)
        </Typography>
      </Box>
      
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', mb: 1.5 }}>
        <Box>
          <Typography variant="h4" sx={{ fontWeight: 900, color: 'primary.light', lineHeight: 1 }}>
            {kelly.kelly_frac ? (kelly.kelly_frac * 100).toFixed(2) : '0'}%
          </Typography>
          <Typography variant="caption" color="text.secondary">do Bankroll</Typography>
        </Box>
        <Box sx={{ textAlign: 'right' }}>
          <Typography variant="h6" sx={{ fontWeight: 700, lineHeight: 1 }}>
            ${kelly.alocacao_dolares?.toLocaleString()}
          </Typography>
          <Typography variant="caption" color="text.secondary">Alocação Sugerida</Typography>
        </Box>
      </Box>
      
      <Typography variant="caption" sx={{ display: 'block', color: 'text.secondary', fontSize: '0.7rem', lineHeight: 1.4 }}>
        <strong>Estratégia:</strong> {kelly.tipo}.<br/>
        {kelly.explicacao}
      </Typography>
    </Box>
  );
}

// ── Metric card ────────────────────────────────────────────────────────────

function MetricCard({ icon, label, value, sub, color = 'text.primary' }: {
  icon: React.ReactNode; label: string; value: string; sub?: string; color?: string;
}) {
  return (
    <Box sx={{ p: 1.5, border: 1, borderColor: 'divider', borderRadius: 2, textAlign: 'center' }}>
      <Box sx={{ color: 'primary.main', mb: 0.5 }}>{icon}</Box>
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', fontSize: '0.7rem' }}>
        {label}
      </Typography>
      <Typography variant="h6" sx={{ fontFamily: 'monospace', fontWeight: 700, color }}>
        {value}
      </Typography>
      {sub && <Typography variant="caption" color="text.secondary">{sub}</Typography>}
    </Box>
  );
}

// ── Price + forecast chart ─────────────────────────────────────────────────

function PriceChart({ closes, forecast, currency }: {
  closes: number[]; forecast: number[]; currency: string;
}) {
  const hist = closes.map((v, i) => ({ day: i - closes.length + 1, price: v, type: 'hist' }));
  const fcast = forecast.map((v, i) => ({ day: i + 1, price: v, type: 'forecast' }));
  const data = [...hist, ...fcast];
  const splitDay = 0;

  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={data} margin={{ top: 4, right: 16, bottom: 4, left: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
        <XAxis dataKey="day" tick={{ fill: '#9ca3af', fontSize: 10 }}
          tickFormatter={(v) => v === 0 ? 'hoje' : `${v > 0 ? '+' : ''}${v}d`} />
        <YAxis tick={{ fill: '#9ca3af', fontSize: 10 }}
          tickFormatter={(v) => `${currency === 'BRL' ? 'R$' : '$'}${v.toFixed(0)}`} />
        <Tooltip
          contentStyle={{ background: '#1e1e2e', border: '1px solid #374151', borderRadius: 8 }}
          formatter={(v: any, name: any) => [`${currency === 'BRL' ? 'R$' : '$'}${Number(v).toFixed(2)}`, name === 'price' ? 'Preço' : 'Previsão']}
          labelFormatter={(l) => `Dia ${l}`}
        />
        <ReferenceLine x={splitDay} stroke="#6b7280" strokeDasharray="4 4"
          label={{ value: 'hoje', fill: '#6b7280', fontSize: 10 }} />
        <Line type="monotone" dataKey="price" dot={false} stroke="#6366f1"
          strokeWidth={2} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

// ── Recommendation banner ──────────────────────────────────────────────────

function RecommendationBanner({ rec }: { rec: any }) {
  const bgColor = rec.color === 'success' ? '#064e3b' : rec.color === 'error' ? '#450a0a' : '#422006';
  const textColor = rec.color === 'success' ? '#34d399' : rec.color === 'error' ? '#f87171' : '#fbbf24';
  const Icon = rec.color === 'success' ? TrendingUp : rec.color === 'error' ? TrendingDown : SwapVert;

  return (
    <Box sx={{
      p: 3, borderRadius: 3, bgcolor: bgColor,
      border: `2px solid ${textColor}`,
      display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 1,
    }}>
      <Icon sx={{ fontSize: 48, color: textColor }} />
      <Typography variant="h4" sx={{ color: textColor, fontWeight: 900, letterSpacing: '0.05em' }}>
        {rec.action}
      </Typography>
      <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', justifyContent: 'center' }}>
        <Chip label={`Strike: ${rec.suggested_strike}`} size="small"
          sx={{ bgcolor: 'rgba(255,255,255,0.1)', color: '#e5e7eb', fontFamily: 'monospace' }} />
        <Chip label={`Prazo: ${rec.holding?.days}`} size="small"
          sx={{ bgcolor: 'rgba(255,255,255,0.1)', color: '#e5e7eb' }} />
        <Chip label={`Confiança: ${rec.confidence}`} size="small"
          sx={{ bgcolor: 'rgba(255,255,255,0.1)', color: textColor, fontWeight: 700 }} />
      </Box>
    </Box>
  );
}

// ── Loading steps ──────────────────────────────────────────────────────────

const STEPS = [
  { icon: <ShowChart />, label: 'Buscando dados de mercado...' },
  { icon: <AutoGraph />, label: 'Executando Black-Scholes e CAPM...' },
  { icon: <Psychology />, label: 'Rodando previsão LSTM...' },
  { icon: <Security />, label: 'Calculando VaR e Black Swan...' },
  { icon: <AutoGraph />, label: 'Gerando relatório com IA...' },
];

    </Box>
  );
}

function LoadingSteps({ step }: { step: number }) {
  return (
    <Box sx={{ py: 4 }}>
      {STEPS.map((s, i) => (
        <Box key={i} sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2,
          opacity: i < step ? 0.4 : i === step ? 1 : 0.2 }}>
          <Box sx={{ color: i < step ? '#10b981' : i === step ? 'primary.main' : 'text.disabled' }}>
            {i < step ? '✓' : i === step ? <CircularProgress size={16} /> : s.icon}
          </Box>
          <Typography variant="body2" color={i === step ? 'text.primary' : 'text.secondary'}>
            {s.label}
          </Typography>
        </Box>
      ))}
    </Box>
  );
}

// ── Rate Limit Cool Down ───────────────────────────────────────────────────

function RateLimitCoolDown() {
  return (
    <Card sx={{ 
      border: '2px solid #fbbf24', 
      bgcolor: 'rgba(251, 191, 36, 0.05)',
      textAlign: 'center', 
      py: 6 
    }}>
      <CardContent>
        <HourglassEmpty sx={{ fontSize: 64, color: '#fbbf24', mb: 2 }} />
        <Typography variant="h5" sx={{ fontWeight: 900, color: '#fbbf24', mb: 1 }}>
          LIMITE DE FREQUÊNCIA ATINGIDO
        </Typography>
        <Typography variant="body1" color="text.secondary" sx={{ mb: 3, maxWidth: 500, mx: 'auto' }}>
          Para garantir a estabilidade do sistema e o controle de custos das IAs, o ATOM limita a geração de relatórios profundos.
        </Typography>
        <Box sx={{ display: 'flex', justifyContent: 'center', gap: 2, alignItems: 'center' }}>
          <Chip icon={<Timer fontSize="small" />} label="Reseta em 1 hora" variant="outlined" sx={{ borderColor: '#fbbf24', color: '#fbbf24' }} />
          <Typography variant="caption" color="text.secondary">
            Dica: Use o histórico para ver relatórios recentes sem custo extra.
          </Typography>
        </Box>
      </CardContent>
    </Card>
  );
}

// ── Agent cards ────────────────────────────────────────────────────────────

function AgentCards({ agents }: { agents: any[] }) {
  const signalColor = (signal: string) => {
    if (signal === 'COMPRAR CALL') return '#22c55e';
    if (signal === 'COMPRAR PUT') return '#ef4444';
    if (signal === 'STRADDLE') return '#f59e0b';
    return '#6b7280';
  };
  const signalIcon = (signal: string) => {
    if (signal === 'COMPRAR CALL') return '📈';
    if (signal === 'COMPRAR PUT') return '📉';
    if (signal === 'STRADDLE') return '⚖️';
    return '➖';
  };
  return (
    <Box>
      <Typography variant="h6" sx={{ mb: 2, fontWeight: 700 }}>Consenso de Agentes Fundamentalistas</Typography>
      <Grid container spacing={2}>
        {agents.map((a) => (
          <Grid size={{ xs: 12, sm: 6, md: 4 }} key={a.agent}>
            <Box sx={{ p: 2, border: `1px solid ${signalColor(a.signal)}30`, borderRadius: 2, height: '100%', bgcolor: 'background.paper' }}>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>{a.persona}</Typography>
                <Chip label={`${signalIcon(a.signal)} ${a.signal}`} size="small"
                  sx={{ bgcolor: `${signalColor(a.signal)}20`, color: signalColor(a.signal), fontWeight: 700, fontSize: '0.7rem' }} />
              </Box>
              <LinearProgress variant="determinate" value={a.confidence}
                sx={{ mb: 1, height: 4, borderRadius: 2, bgcolor: 'rgba(255,255,255,0.1)',
                  '& .MuiLinearProgress-bar': { bgcolor: signalColor(a.signal) } }} />
              <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.72rem' }}>
                Confiança: {a.confidence.toFixed(0)}% — {a.reasoning}
              </Typography>
            </Box>
          </Grid>
        ))}
      </Grid>
    </Box>
  );
}

// ── Intelligence Hub ────────────────────────────────────────────────────────

function IntelligenceHub({ analysis }: { analysis: any }) {
  const [tab, setTab] = useState(0);

  if (!analysis) return null;

  return (
    <Card sx={{ border: '1px solid rgba(99, 102, 241, 0.3)', bgcolor: 'rgba(15, 23, 42, 0.6)' }}>
      <CardContent sx={{ p: 0 }}>
        <Box sx={{ borderBottom: 1, borderColor: 'divider', px: 2 }}>
          <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="scrollable" scrollButtons="auto">
            <Tab label="Fundamental (Claude)" sx={{ fontWeight: 700, fontSize: '0.75rem' }} />
            <Tab label="Quant (GPT-5)" sx={{ fontWeight: 700, fontSize: '0.75rem' }} />
            <Tab label="Notícias (Gemini)" sx={{ fontWeight: 700, fontSize: '0.75rem' }} />
            <Tab label="Pulse (Grok)" sx={{ fontWeight: 700, fontSize: '0.75rem', color: '#00f2ff' }} />
            <Tab label="Search (PPLX)" sx={{ fontWeight: 700, fontSize: '0.75rem', color: '#fbbf24' }} />
            {analysis.bridgewise_b3 && <Tab label="Bridgewise B3" sx={{ fontWeight: 900, fontSize: '0.75rem', color: '#6366f1' }} />}
          </Tabs>
        </Box>

        <Box sx={{ p: 3, minHeight: 200 }}>
          {tab === 0 && (
            <Fade in>
              <Box>
                <Typography variant="subtitle2" color="primary" gutterBottom>CLAUDE 3.5 SONNET • ANÁLISE PROFUNDA</Typography>
                <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', color: 'text.secondary', lineHeight: 1.8 }}>
                  {analysis.fundamental_claude}
                </Typography>
              </Box>
            </Fade>
          )}
          {tab === 1 && (
            <Fade in>
              <Box>
                <Typography variant="subtitle2" color="secondary" gutterBottom>GPT-5 • ESTRATÉGIA QUANTITATIVA</Typography>
                <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', color: 'text.secondary', lineHeight: 1.8, fontFamily: 'monospace', bgcolor: 'rgba(0,0,0,0.3)', p: 2, borderRadius: 2 }}>
                  {analysis.quant_strategy_gpt}
                </Typography>
              </Box>
            </Fade>
          )}
          {tab === 2 && (
            <Fade in>
              <Box>
                <Typography variant="subtitle2" color="success.main" gutterBottom>GEMINI 1.5 PRO • RADAR DE NOTÍCIAS</Typography>
                <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', color: 'text.secondary', lineHeight: 1.8 }}>
                  {typeof analysis.news_monitoring_gemini === 'string' 
                    ? analysis.news_monitoring_gemini 
                    : analysis.news_monitoring_gemini.ai_analysis}
                </Typography>
              </Box>
            </Fade>
          )}
          {tab === 3 && (
            <Fade in>
              <Box>
                <Typography variant="subtitle2" sx={{ color: '#00f2ff', mb: 1, fontWeight: 800 }}>GROK-2 (xAI) • REAL-TIME PULSE & RUMORS</Typography>
                <Typography variant="body2" sx={{ 
                  whiteSpace: 'pre-wrap', color: '#e5e7eb', lineHeight: 1.8, 
                  fontFamily: 'monospace', bgcolor: 'rgba(0, 242, 255, 0.05)', 
                  p: 2, borderRadius: 2, border: '1px solid rgba(0, 242, 255, 0.2)' 
                }}>
                  {analysis.pulse_grok}
                </Typography>
              </Box>
            </Fade>
          )}
          {tab === 4 && (
            <Fade in>
              <Box>
                <Typography variant="subtitle2" sx={{ color: '#fbbf24', mb: 1, fontWeight: 800 }}>PERPLEXITY SONAR-PRO • LIVE DEEP SEARCH</Typography>
                <Typography variant="body2" sx={{ 
                  whiteSpace: 'pre-wrap', color: 'text.secondary', lineHeight: 1.8,
                  bgcolor: 'rgba(251, 191, 36, 0.05)', p: 2, borderRadius: 2,
                  border: '1px solid rgba(251, 191, 36, 0.2)'
                }}>
                  {analysis.search_perplexity}
                </Typography>
              </Box>
            </Fade>
          )}
          {tab === 5 && analysis.bridgewise_b3 && (
            <Fade in>
              <Box>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 3 }}>
                  <Box sx={{ position: 'relative', display: 'inline-flex' }}>
                    <CircularProgress 
                      variant="determinate" 
                      value={analysis.bridgewise_b3.overall_grade * 10} 
                      size={80} thickness={6} sx={{ color: '#6366f1' }} 
                    />
                    <Box sx={{ top: 0, left: 0, bottom: 0, right: 0, position: 'absolute', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                      <Typography variant="h5" sx={{ fontWeight: 900 }}>{analysis.bridgewise_b3.overall_grade}</Typography>
                    </Box>
                  </Box>
                  <Box>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      <Typography variant="h6" sx={{ fontWeight: 800 }}>Bridgewise Analysis Grade</Typography>
                      {analysis.bridgewise_b3.is_real_data && (
                        <Chip label="DADOS REAIS" size="small" color="secondary" sx={{ height: 16, fontSize: '0.65rem', fontWeight: 900 }} />
                      )}
                    </Box>
                    <Typography variant="caption" color="text.secondary">Framework Especialista B3 (Asset Selection)</Typography>
                    <Box sx={{ mt: 0.5 }}>
                      <Chip label={analysis.bridgewise_b3.recommendation} color={analysis.bridgewise_b3.recommendation === 'COMPRAR' ? 'success' : 'default'} size="small" />
                      <Chip label={analysis.bridgewise_b3.peer_rank} variant="outlined" size="small" sx={{ ml: 1 }} />
                    </Box>
                  </Box>
                </Box>
                
                {analysis.bridgewise_b3.paragraphs && analysis.bridgewise_b3.paragraphs.length > 0 ? (
                  <Box sx={{ maxHeight: 300, overflowY: 'auto', pr: 1 }}>
                    {analysis.bridgewise_b3.paragraphs.map((p: any, idx: number) => (
                      <Box key={idx} sx={{ mb: 2 }}>
                        <Typography variant="subtitle2" sx={{ color: 'primary.light', mb: 0.5 }}>{p.title}</Typography>
                        <Typography variant="body2" color="text.secondary" sx={{ fontSize: '0.85rem', lineHeight: 1.6 }}>
                          {p.text}
                        </Typography>
                      </Box>
                    ))}
                  </Box>
                ) : (
                  <>
                    <Grid container spacing={2} sx={{ mb: 3 }}>
                      <Grid size={4}>
                        <Typography variant="caption" color="text.secondary">Fundamentalista</Typography>
                        <Typography variant="h6">{analysis.bridgewise_b3.fundamental_score}/10</Typography>
                      </Grid>
                      <Grid size={4}>
                        <Typography variant="caption" color="text.secondary">Estabilidade</Typography>
                        <Typography variant="h6">{analysis.bridgewise_b3.stability_score}/10</Typography>
                      </Grid>
                      <Grid size={4}>
                        <Typography variant="caption" color="text.secondary">Técnico</Typography>
                        <Typography variant="h6">{analysis.bridgewise_b3.technical_score}/10</Typography>
                      </Grid>
                    </Grid>
                    <Divider sx={{ my: 2 }} />
                    <Typography variant="body2" sx={{ fontStyle: 'italic', color: 'text.secondary' }}>
                      "{analysis.bridgewise_b3.bridgewise_narrative}"
                    </Typography>
                  </>
                )}
              </Box>
            </Fade>
          )}
        </Box>
      </CardContent>
    </Card>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────

const POPULAR_BR = ['PETR4', 'VALE3', 'ITUB4', 'BBDC4', 'ABEV3', 'B3SA3', 'WEGE3', 'RENT3'];
const POPULAR_US = ['AAPL', 'MSFT', 'NVDA', 'TSLA', 'AMZN', 'GOOGL', 'META', 'SPY'];

export default function AIReportPage() {
  const [ticker, setTicker] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState('');
  const [rateLimited, setRateLimited] = useState(false);
  const [streamProgress, setStreamProgress] = useState<{ step: number; total: number; message: string } | null>(null);
  const abortRef = useRef<(() => void) | null>(null);

  const runAnalysis = (t?: string) => {
    const sym = (t || ticker).toUpperCase().trim();
    if (!sym) return;
    setTicker(sym);
    setLoading(true);
    setResult(null);
    setError('');
    setRateLimited(false);
    setStreamProgress({ step: 0, total: 6, message: 'Iniciando análise...' });

    if (abortRef.current) abortRef.current();

    abortRef.current = api.aiAnalysisStream(
      sym,
      (step, total, message) => setStreamProgress({ step, total, message }),
      (data) => { setResult(data); setLoading(false); setStreamProgress(null); },
      (msg) => { 
        if (msg.includes('429') || msg.toLowerCase().includes('rate limit')) {
          setRateLimited(true);
        } else {
          setError(msg);
        }
        setLoading(false); 
        setStreamProgress(null); 
      },
    );
  };

  return (
    <Box>
      <Typography variant="h4" sx={{ mb: 0.5 }}>Análise IA</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Escolha qualquer ação da B3, NYSE ou NASDAQ — a IA cruza todos os modelos e gera uma recomendação
      </Typography>

      {/* Search bar */}
      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Box sx={{ display: 'flex', gap: 2, alignItems: 'flex-start', flexWrap: 'wrap' }}>
            <TextField
              label="Ticker"
              value={ticker}
              onChange={(e) => setTicker(e.target.value.toUpperCase())}
              onKeyDown={(e) => e.key === 'Enter' && runAnalysis()}
              placeholder="PETR4, AAPL, MSFT..."
              size="small"
              sx={{ width: 200 }}
              helperText="B3: PETR4, VALE3 · NYSE/NASDAQ: AAPL, TSLA"
            />
            <Button
              variant="contained" size="large"
              onClick={() => runAnalysis()}
              disabled={loading || !ticker.trim()}
              startIcon={loading ? <CircularProgress size={18} /> : <Search />}
              sx={{ height: 40, px: 4, fontWeight: 700 }}
            >
              {loading ? 'Analisando...' : 'Gerar Análise'}
            </Button>
          </Box>

          {/* Quick picks */}
          <Box sx={{ mt: 2 }}>
            <Typography variant="caption" color="text.secondary" sx={{ mr: 1 }}>B3:</Typography>
            {POPULAR_BR.map((t) => (
              <Chip key={t} label={t} size="small" variant="outlined" onClick={() => runAnalysis(t)}
                disabled={loading} sx={{ mr: 0.5, mb: 0.5, cursor: 'pointer', fontFamily: 'monospace' }} />
            ))}
          </Box>
          <Box sx={{ mt: 0.5 }}>
            <Typography variant="caption" color="text.secondary" sx={{ mr: 1 }}>NYSE/NASDAQ:</Typography>
            {POPULAR_US.map((t) => (
              <Chip key={t} label={t} size="small" variant="outlined" onClick={() => runAnalysis(t)}
                disabled={loading} sx={{ mr: 0.5, mb: 0.5, cursor: 'pointer', fontFamily: 'monospace' }} />
            ))}
          </Box>
        </CardContent>
      </Card>

      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {rateLimited && <Box sx={{ mb: 3 }}><RateLimitCoolDown /></Box>}

      {/* Loading */}
      {loading && (
        <Card>
          <CardContent>
            <Box sx={{ textAlign: 'center', py: 4 }}>
              <CircularProgress size={48} sx={{ mb: 3 }} />
              {streamProgress && (
                <>
                  <LinearProgress
                    variant="determinate"
                    value={(streamProgress.step / streamProgress.total) * 100}
                    sx={{ mx: 'auto', maxWidth: 400, mb: 2, height: 6, borderRadius: 3 }}
                  />
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
                    {streamProgress.message}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    Passo {streamProgress.step} de {streamProgress.total}
                  </Typography>
                </>
              )}
            </Box>
          </CardContent>
        </Card>
      )}

      {/* Report */}
      {result && !loading && (
        <Fade in>
          <Box>
            {/* Header */}
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2, flexWrap: 'wrap' }}>
              <Typography variant="h5" sx={{ fontWeight: 700 }}>{result.ticker}</Typography>
              <Chip label={result.market_data?.name} variant="outlined" size="small" />
              <Chip label={result.exchange} color="primary" size="small" />
              <Chip
                label={`${result.market_data?.currency === 'BRL' ? 'R$' : '$'}${result.market_data?.price}`}
                color="default" size="small"
                sx={{ fontFamily: 'monospace', fontWeight: 700 }}
              />
              <Chip
                label={`${result.market_data?.change_pct >= 0 ? '+' : ''}${result.market_data?.change_pct}%`}
                color={result.market_data?.change_pct >= 0 ? 'success' : 'error'}
                size="small"
              />
              <Typography variant="caption" color="text.secondary" sx={{ ml: 'auto' }}>
                Gerado em {result.generated_at}
              </Typography>
            </Box>

            <Grid container spacing={2.5}>
              {/* Left column */}
              <Grid size={{ xs: 12, md: 4 }}>
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>

                  {/* Bull Score */}
                  <Card>
                    <CardContent>
                      <BullScoreGauge score={result.recommendation?.bull_score} />
                    </CardContent>
                  </Card>

                  {/* Recommendation */}
                  <Card>
                    <CardContent>
                      <Typography variant="subtitle2" gutterBottom color="text.secondary">
                        RECOMENDAÇÃO
                      </Typography>
                      <RecommendationBanner rec={result.recommendation} />
                      <Box sx={{ mt: 2 }}>
                        <Typography variant="caption" color="text.secondary">
                          {result.recommendation?.holding?.label} · {result.recommendation?.holding?.days}
                        </Typography>
                        <Typography variant="body2" sx={{ mt: 0.5, color: 'text.secondary', fontSize: '0.8rem' }}>
                          {result.recommendation?.holding?.reason}
                        </Typography>
                      </Box>
                      
                      <KellySizingCard kelly={result.recommendation?.kelly} />
                    </CardContent>
                  </Card>

                  {/* Key scores */}
                  <Card>
                    <CardContent>
                      <Typography variant="subtitle2" gutterBottom color="text.secondary">SINAIS</Typography>
                      <Grid container spacing={1}>
                        <Grid size={6}>
                          <MetricCard icon={<Psychology fontSize="small" />} label="ML (30d)"
                            value={`${result.model_scores?.ml_return_pct > 0 ? '+' : ''}${result.model_scores?.ml_return_pct}%`}
                            color={result.model_scores?.ml_return_pct > 0 ? '#10b981' : '#ef4444'} />
                        </Grid>
                        <Grid size={6}>
                          <MetricCard icon={<AutoGraph fontSize="small" />} label="Beta"
                            value={String(result.model_scores?.beta)}
                            sub={result.model_scores?.beta > 1 ? 'agressivo' : 'defensivo'} />
                        </Grid>
                        <Grid size={6}>
                          <MetricCard icon={<Security fontSize="small" />} label="VaR 95%"
                            value={`${result.model_scores?.var_pct?.toFixed(2)}%`}
                            color={result.model_scores?.var_pct > 3 ? '#ef4444' : '#9ca3af'} />
                        </Grid>
                        <Grid size={6}>
                          <MetricCard icon={<ShowChart fontSize="small" />} label="Black Swan"
                            value={`${result.model_scores?.black_swan_score}/100`}
                            color={result.model_scores?.black_swan_score > 60 ? '#ef4444' :
                                   result.model_scores?.black_swan_score > 40 ? '#f59e0b' : '#10b981'} />
                        </Grid>
                      </Grid>
                    </CardContent>
                  </Card>
                </Box>
              </Grid>

              {/* Right column */}
              <Grid size={{ xs: 12, md: 8 }}>
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>

                  {/* Price chart */}
                  <Card>
                    <CardContent>
                      <Typography variant="h6" gutterBottom>
                        Histórico (60d) + Previsão ML (30d)
                      </Typography>
                      <PriceChart
                        closes={result.price_history?.closes || []}
                        forecast={result.price_history?.ml_forecast || []}
                        currency={result.market_data?.currency || 'USD'}
                      />
                    </CardContent>
                  </Card>

                  {/* Options pricing */}
                  <Card>
                    <CardContent>
                      <Typography variant="h6" gutterBottom>Black-Scholes — Opções ATM</Typography>
                      <Grid container spacing={2}>
                        <Grid size={6}>
                          <Box sx={{ p: 2, border: 1, borderColor: '#10b981', borderRadius: 2, textAlign: 'center' }}>
                            <Typography variant="caption" color="#10b981" sx={{ fontWeight: 700 }}>CALL (compra)</Typography>
                            <Typography variant="h4" sx={{ fontFamily: 'monospace', fontWeight: 700, color: '#10b981' }}>
                              {result.market_data?.currency === 'BRL' ? 'R$' : '$'}{result.model_scores?.bs_call_price?.toFixed(2)}
                            </Typography>
                            <Typography variant="caption" color="text.secondary">
                              Delta: {result.model_scores?.call_delta?.toFixed(3)}
                            </Typography>
                          </Box>
                        </Grid>
                        <Grid size={6}>
                          <Box sx={{ p: 2, border: 1, borderColor: '#ef4444', borderRadius: 2, textAlign: 'center' }}>
                            <Typography variant="caption" color="#ef4444" sx={{ fontWeight: 700 }}>PUT (venda/proteção)</Typography>
                            <Typography variant="h4" sx={{ fontFamily: 'monospace', fontWeight: 700, color: '#ef4444' }}>
                              {result.market_data?.currency === 'BRL' ? 'R$' : '$'}{result.model_scores?.bs_put_price?.toFixed(2)}
                            </Typography>
                            <Typography variant="caption" color="text.secondary">
                              Delta: {result.model_scores?.put_delta?.toFixed(3)}
                            </Typography>
                          </Box>
                        </Grid>
                        <Grid size={4}>
                          <Box sx={{ textAlign: 'center', p: 1, border: 1, borderColor: 'divider', borderRadius: 2 }}>
                            <Typography variant="caption" color="text.secondary">Vol. Implícita</Typography>
                            <Typography variant="h6" sx={{ fontFamily: 'monospace' }}>
                              {result.model_scores?.iv_pct?.toFixed(1)}%
                            </Typography>
                          </Box>
                        </Grid>
                        <Grid size={4}>
                          <Box sx={{ textAlign: 'center', p: 1, border: 1, borderColor: 'divider', borderRadius: 2 }}>
                            <Typography variant="caption" color="text.secondary">Alpha/ano</Typography>
                            <Typography variant="h6" sx={{ fontFamily: 'monospace',
                              color: result.model_scores?.alpha_annual_pct > 0 ? '#10b981' : '#ef4444' }}>
                              {result.model_scores?.alpha_annual_pct > 0 ? '+' : ''}{result.model_scores?.alpha_annual_pct?.toFixed(1)}%
                            </Typography>
                          </Box>
                        </Grid>
                        <Grid size={4}>
                          <Box sx={{ textAlign: 'center', p: 1, border: 1, borderColor: 'divider', borderRadius: 2 }}>
                            <Typography variant="caption" color="text.secondary">GARCH Vol</Typography>
                            <Typography variant="h6" sx={{ fontFamily: 'monospace' }}>
                              {result.model_scores?.garch_vol_pct?.toFixed(1)}%
                            </Typography>
                          </Box>
                        </Grid>
                      </Grid>
                    </CardContent>
                  </Card>

                  {/* Intelligence Hub — New Specialized Multi-Model Section */}
                  <IntelligenceHub analysis={result.specialized_analysis} />

                  {/* Agent consensus banner */}
                  {result.agent_analysis && (
                    <Card>
                      <CardContent>
                        <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 700 }}>
                          Consenso dos Agentes — {result.agent_analysis.consensus} ({result.agent_analysis.consensus_pct}%)
                        </Typography>
                        <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mb: 2 }}>
                          <Chip label={`📈 CALL: ${result.agent_analysis.call_count}`} size="small"
                            sx={{ bgcolor: '#22c55e20', color: '#22c55e' }} />
                          <Chip label={`📉 PUT: ${result.agent_analysis.put_count}`} size="small"
                            sx={{ bgcolor: '#ef444420', color: '#ef4444' }} />
                          <Chip label={`➖ NEUTRO: ${result.agent_analysis.neutral_count}`} size="small"
                            sx={{ bgcolor: '#6b728020', color: '#6b7280' }} />
                        </Box>
                        {result.agent_analysis.signals && (
                          <AgentCards agents={result.agent_analysis.signals} />
                        )}
                      </CardContent>
                    </Card>
                  )}

                  {/* AI Narrative */}
                  <Card>
                    <CardContent>
                      <Typography variant="h6" gutterBottom>📋 Relatório Completo</Typography>
                      <Box sx={{
                        bgcolor: 'background.default', borderRadius: 2, p: 2,
                        '& h2': { color: 'primary.light', mt: 2, mb: 0.5, fontSize: '1rem' },
                        '& strong': { color: 'text.primary' },
                        '& p': { color: 'text.secondary', mb: 1, lineHeight: 1.7 },
                        '& hr': { borderColor: 'divider', my: 1 },
                      }}>
                        {result.narrative?.split('\n').map((line: string, i: number) => {
                          if (line.startsWith('## ')) return (
                            <Typography key={i} variant="h6" sx={{ color: 'primary.light', mt: i > 0 ? 2 : 0, mb: 0.5 }}>
                              {line.replace('## ', '')}
                            </Typography>
                          );
                          if (line.startsWith('### ')) return (
                            <Typography key={i} variant="subtitle1" sx={{ color: 'text.primary', fontWeight: 700, mt: 1.5, mb: 0.5 }}>
                              {line.replace('### ', '')}
                            </Typography>
                          );
                          if (line === '---') return <Divider key={i} sx={{ my: 1.5 }} />;
                          if (line.startsWith('- ')) return (
                            <Typography key={i} variant="body2" color="text.secondary" sx={{ pl: 1, mb: 0.5 }}>
                              • {line.slice(2).replace(/\*\*(.*?)\*\*/g, '$1')}
                            </Typography>
                          );
                          if (!line.trim()) return <Box key={i} sx={{ mb: 0.5 }} />;
                          // Bold text inline
                          const parts = line.split(/\*\*(.*?)\*\*/g);
                          return (
                            <Typography key={i} variant="body2" color="text.secondary" sx={{ mb: 0.5, lineHeight: 1.7 }}>
                              {parts.map((part, j) => j % 2 === 1
                                ? <strong key={j} style={{ color: '#e5e7eb' }}>{part}</strong>
                                : part)}
                            </Typography>
                          );
                        })}
                      </Box>
                    </CardContent>
                  </Card>

                  {/* Full metrics table */}
                  <Card>
                    <CardContent>
                      <Typography variant="subtitle2" gutterBottom color="text.secondary">
                        TODOS OS INDICADORES
                      </Typography>
                      <Table size="small">
                        <TableBody>
                          {[
                            ['Previsão ML 30d', `${result.model_scores?.ml_return_pct > 0 ? '+' : ''}${result.model_scores?.ml_return_pct}%`],
                            ['Beta (vs mercado)', result.model_scores?.beta],
                            ['Alpha anual (CAPM)', `${result.model_scores?.alpha_annual_pct > 0 ? '+' : ''}${result.model_scores?.alpha_annual_pct?.toFixed(2)}%`],
                            ['VaR 95% (1 dia)', `${result.model_scores?.var_pct?.toFixed(4)}%`],
                            ['Score Black Swan', `${result.model_scores?.black_swan_score}/100`],
                            ['Volatilidade Implícita', `${result.model_scores?.iv_pct?.toFixed(1)}%`],
                            ['Volatilidade GARCH', `${result.model_scores?.garch_vol_pct?.toFixed(1)}%`],
                            ['Momentum técnico', result.model_scores?.momentum_raw?.toFixed(1)],
                            ['Bull Score final', `${result.recommendation?.bull_score}/100`],
                            ['Strike sugerido', result.recommendation?.suggested_strike],
                            ['Prazo recomendado', result.recommendation?.holding?.days],
                          ].map(([k, v]) => (
                            <TableRow key={String(k)}>
                              <TableCell sx={{ color: 'text.secondary', fontSize: '0.8rem', py: 0.75 }}>{k}</TableCell>
                              <TableCell sx={{ fontFamily: 'monospace', fontWeight: 600, py: 0.75 }}>{String(v)}</TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </CardContent>
                  </Card>

                  <Alert severity="warning" sx={{ fontSize: '0.78rem' }}>
                    Este relatório é gerado por modelos matemáticos e não constitui recomendação de investimento.
                    Opções envolvem risco de perda total do prêmio. Consulte um profissional habilitado pela CVM/SEC.
                  </Alert>
                </Box>
              </Grid>
            </Grid>
          </Box>
        </Fade>
      )}
    </Box>
  );
}
