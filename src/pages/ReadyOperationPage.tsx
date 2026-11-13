/**
 * Tela única do cliente: ativo(s), horizonte, retorno desejado e tipo de operação.
 * Meu plano (perfil + carteira) vive aqui. Sem menu de mesa.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert, Box, Button, Card, CardContent, Chip, CircularProgress, Divider,
  Stack, ToggleButton, ToggleButtonGroup, Typography,
} from '@mui/material';
import { formatDatePtBr, formatPricePtBr } from '../lib/moneyPtBr';
import { api } from '../services/api';
import { useClientConfig, type ClientAsset } from '../contexts/ClientModeContext';
import {
  PROFILE_QUESTIONS,
  SLEEVES,
  profileFor,
  recommendedProfile,
  type ProfileAnswers,
  type Sleeve,
} from '../data/investorProfiles';

type ReadyBody = {
  status: 'ready' | 'insufficient';
  ticker?: string;
  label?: string;
  instrument?: string;
  horizon_label?: string;
  direction?: 'bullish' | 'bearish';
  structure?: { strategy: string; legs: { side: string; symbol: string; strike: number; quantity: number }[]; expiry: string };
  spot?: number;
  entry?: number;
  invalidation?: number;
  target?: number;
  quantity?: number;
  quote_currency?: 'BRL' | 'USD';
  fx_usd_brl?: { rate: number; source?: string; stale?: boolean };
  suggested_size?: {
    quantity: number;
    risk_budget_brl: number;
    notional_brl?: number | null;
    notional_usd?: number | null;
    can_register_paper: boolean;
    paper_block?: string | null;
  };
  confidence?: string;
  invalidation_reason?: string;
  why?: string;
  reason?: string;
  disclaimer?: string;
  eligible_for_live_trading?: boolean;
};

const money = (n: number, ccy: 'BRL' | 'USD' = 'BRL') =>
  `${ccy === 'USD' ? 'US$' : 'R$'} ${formatPricePtBr(n)}`;
const num = (n: number) => formatPricePtBr(n, 8).replace(/0+$/, '').replace(/,$/, '');
const pct = (n: number) => `${(n * 100).toFixed(1).replace('.', ',')}%`;

const directionLabel: Record<string, string> = { bullish: 'Alta', bearish: 'Baixa' };
const strategyLabel: Record<string, string> = {
  long_stock: 'Compra à vista',
  short_stock: 'Venda à vista (simulação)',
  long_perp: 'Compra de perpétuo (simulação)',
  short_perp: 'Venda de perpétuo (simulação)',
  long_call: 'Compra de call',
  long_put: 'Compra de put',
  bull_call_spread: 'Trava de alta com calls',
  bear_put_spread: 'Trava de baixa com puts',
};

export default function ReadyOperationPage() {
  const cfg = useClientConfig();
  const universe = cfg.universe.length ? cfg.universe : FALLBACK_UNIVERSE;
  const instruments = cfg.instruments.length ? cfg.instruments : FALLBACK_INSTRUMENTS;
  const horizons = cfg.horizons.length ? cfg.horizons : FALLBACK_HORIZONS;

  const [sleeve, setSleeve] = useState<Sleeve>('equities');
  const [ticker, setTicker] = useState('PETR4');
  const [instrument, setInstrument] = useState('spot');
  const [horizon, setHorizon] = useState('weeks');
  const [answers, setAnswers] = useState<ProfileAnswers>({ horizon: null, drop: null, goal: null });
  const [busy, setBusy] = useState(false);
  const [assembling, setAssembling] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<ReadyBody | null>(null);
  const [paperMsg, setPaperMsg] = useState('');
  const abortRef = useRef<AbortController | null>(null);
  const seqRef = useRef(0);

  const visibleAssets = useMemo(() => {
    if (sleeve === 'crypto') return universe.filter((row) => row.asset_class === 'crypto');
    if (sleeve === 'equities') return universe.filter((row) => row.asset_class !== 'crypto');
    return universe;
  }, [universe, sleeve]);

  const asset = useMemo(
    () => universe.find((row) => row.id === ticker) as ClientAsset | undefined,
    [universe, ticker],
  );
  const allowed = asset?.instruments ?? ['spot'];
  const answered = answers.horizon !== null && answers.drop !== null && answers.goal !== null;
  const profile = answered ? recommendedProfile(answers, sleeve) : profileFor('moderado', sleeve);
  const notionalBrl = result?.suggested_size?.notional_brl
    ?? (result?.quantity != null && result?.entry != null
      ? Math.abs(result.quantity * result.entry)
      : null);

  function dropInFlight() {
    abortRef.current?.abort();
    abortRef.current = null;
    seqRef.current += 1;
    setAssembling(false);
    setBusy(false);
  }

  useEffect(() => () => { abortRef.current?.abort(); }, []);

  useEffect(() => {
    if (!visibleAssets.length) return;
    if (!visibleAssets.some((row) => row.id === ticker)) {
      dropInFlight();
      setTicker(visibleAssets[0].id);
      setResult(null);
    }
  }, [visibleAssets, ticker]);

  useEffect(() => {
    if (asset && !asset.instruments.includes(instrument)) {
      dropInFlight();
      setInstrument(asset.instruments[0] || 'spot');
      setResult(null);
    }
  }, [asset, instrument]);

  async function assemble() {
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    const seq = ++seqRef.current;
    setAssembling(true);
    setBusy(true);
    setError('');
    setPaperMsg('');
    setResult(null);
    try {
      const body = await api.clientReadyOperation(
        { ticker, instrument, horizon },
        { signal: ac.signal },
      ) as ReadyBody;
      if (seq !== seqRef.current) return;
      setResult(body);
    } catch (e) {
      if (seq !== seqRef.current) return;
      if (e instanceof Error && e.name === 'AbortError') return;
      setError(e instanceof Error ? e.message : 'Não foi possível montar a operação.');
    } finally {
      if (seq === seqRef.current) {
        setAssembling(false);
        setBusy(false);
        if (abortRef.current === ac) abortRef.current = null;
      }
    }
  }

  async function registerPaper() {
    setBusy(true); setError(''); setPaperMsg('');
    try {
      const body = await api.clientReadyPaper({ ticker, instrument, horizon }) as { message?: string; status?: string };
      setPaperMsg(body.message || 'Registrada como operação paper, aguardando gatilho.');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Não foi possível registrar no diário.');
    } finally { setBusy(false); }
  }

  return (
    <Stack spacing={3} sx={{ maxWidth: 880, mx: 'auto' }}>
      <Box>
        <Chip label="Cliente · simulação paper · sem ordens reais" size="small" />
        <Typography variant="h4" component="h1" sx={{ mt: 2, fontWeight: 750, letterSpacing: '-0.03em' }}>
          Escolha o ativo, o tempo, o retorno e o tipo. A operação vem pronta.
        </Typography>
        <Typography color="text.secondary" sx={{ mt: 1 }}>
          Quatro escolhas. O arsenal monta entrada, stop, alvo e tamanho — ou diz, com honestidade,
          que não tem dado nem sinal suficiente. Isto é cenário, não recomendação, e não promete retorno.
        </Typography>
      </Box>

      <Alert severity="info">
        Nenhuma ordem vai à corretora. O registro, se você quiser, entra no diário paper como
        «aguardando gatilho». {cfg.disclaimer}
      </Alert>

      <Card>
        <CardContent>
          <Typography variant="overline" color="text.secondary">1 · Os ativos</Typography>
          <ToggleButtonGroup
            exclusive
            value={sleeve}
            onChange={(_, v: Sleeve | null) => {
              if (!v) return;
              dropInFlight();
              setSleeve(v);
              setResult(null);
            }}
            sx={{ flexWrap: 'wrap', gap: 1, mt: 1 }}
          >
            {SLEEVES.map((row) => (
              <ToggleButton key={row.id} value={row.id} aria-label={row.label}>{row.label}</ToggleButton>
            ))}
          </ToggleButtonGroup>
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1.5 }}>
            {SLEEVES.find((row) => row.id === sleeve)?.hint}
          </Typography>
          <ToggleButtonGroup
            exclusive
            value={ticker}
            onChange={(_, v) => { if (v) { dropInFlight(); setTicker(v); setResult(null); } }}
            sx={{ flexWrap: 'wrap', gap: 1, mt: 2 }}
          >
            {visibleAssets.map((row) => (
              <ToggleButton key={row.id} value={row.id} aria-label={row.label}>{row.label}</ToggleButton>
            ))}
          </ToggleButtonGroup>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Typography variant="overline" color="text.secondary">2 · O tempo</Typography>
          <ToggleButtonGroup
            exclusive
            value={horizon}
            onChange={(_, v) => { if (v) { dropInFlight(); setHorizon(v); setResult(null); } }}
            sx={{ flexWrap: 'wrap', gap: 1, mt: 1 }}
          >
            {horizons.map((row) => (
              <ToggleButton key={row.id} value={row.id} aria-label={row.label}>{row.label}</ToggleButton>
            ))}
          </ToggleButtonGroup>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Typography variant="overline" color="text.secondary">3 · O retorno desejado</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            Três perguntas curtas. Elas definem o perfil (conservador, moderado ou arrojado) e a carteira sugerida na classe que você escolheu.
          </Typography>
          {PROFILE_QUESTIONS.map((q) => (
            <Box key={q.id} sx={{ mt: 2 }}>
              <Typography variant="body2" fontWeight={600}>{q.question}</Typography>
              <ToggleButtonGroup
                exclusive
                value={answers[q.id]}
                onChange={(_, v: number | null) => {
                  if (v === null) return;
                  setAnswers((prev) => ({ ...prev, [q.id]: v }));
                }}
                sx={{ flexWrap: 'wrap', gap: 1, mt: 1 }}
              >
                {q.options.map((option) => (
                  <ToggleButton key={option.label} value={option.value} aria-label={option.label}>
                    {option.label}
                  </ToggleButton>
                ))}
              </ToggleButtonGroup>
            </Box>
          ))}
          {answered && (
            <Chip
              label={`Perfil sugerido: ${profile.label}`}
              sx={{ mt: 2, bgcolor: profile.bgColor, color: profile.color, fontWeight: 600 }}
            />
          )}
        </CardContent>
      </Card>

      <Card sx={{ border: '1px solid', borderColor: answered ? 'warning.main' : 'divider' }}>
        <CardContent>
          <Typography variant="h6" sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            {profile.label}
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            {profile.description} Carteira na classe {SLEEVES.find((row) => row.id === sleeve)?.label.toLowerCase()}.
          </Typography>
          <Stack spacing={1} sx={{ mt: 2 }}>
            {profile.assets.map((row) => (
              <Box key={row.ticker} sx={{ display: 'flex', justifyContent: 'space-between', gap: 2 }}>
                <Typography>{row.ticker}</Typography>
                <Typography fontWeight={700}>{pct(row.weight)}</Typography>
              </Box>
            ))}
          </Stack>
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 2 }}>
            Mix ilustrativo para este perfil, não uma ordem. Os pesos não prometem retorno.
          </Typography>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Typography variant="overline" color="text.secondary">4 · O tipo de operação</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            Como operar o ativo acima (à vista, opção ou futuro/perpétuo — só o que o arsenal realmente cobre).
          </Typography>
          <ToggleButtonGroup
            exclusive
            value={instrument}
            onChange={(_, v) => { if (v) { dropInFlight(); setInstrument(v); setResult(null); } }}
            sx={{ flexWrap: 'wrap', gap: 1, mt: 1 }}
          >
            {instruments.map((row) => (
              <ToggleButton
                key={row.id}
                value={row.id}
                disabled={!allowed.includes(row.id)}
                aria-label={row.label}
              >
                {row.label}
              </ToggleButton>
            ))}
          </ToggleButtonGroup>
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1.5 }}>
            {instruments.find((row) => row.id === instrument)?.hint}
          </Typography>
        </CardContent>
      </Card>

      <Box>
        <Button
          size="large"
          variant="contained"
          onClick={assemble}
          disabled={busy || !allowed.includes(instrument)}
          startIcon={busy ? <CircularProgress size={16} color="inherit" /> : undefined}
        >
          Montar operação
        </Button>
      </Box>

      {error && <Alert severity="error">{error}</Alert>}
      {paperMsg && <Alert severity="success">{paperMsg}</Alert>}

      {assembling && (
        <Alert severity="info" icon={<CircularProgress size={18} />}>
          Montando o cenário. A explicação aparece só quando o texto final estiver pronto.
        </Alert>
      )}

      {!assembling && result?.status === 'insufficient' && (
        <Alert severity="warning">
          <Typography fontWeight={700}>O arsenal não montou operação.</Typography>
          <Typography sx={{ mt: 1 }}>{result.reason}</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
            Não inventamos preço, livro nem sinal. Tente outro instrumento ou outro horizonte, ou volte mais tarde.
          </Typography>
        </Alert>
      )}

      {!assembling && result?.status === 'ready' && (
        <Card>
          <CardContent>
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
              <Chip label={result.label || result.ticker} />
              <Chip label={directionLabel[result.direction || ''] || result.direction} color={result.direction === 'bullish' ? 'success' : 'warning'} />
              <Chip label={strategyLabel[result.structure?.strategy || ''] || result.structure?.strategy} />
              <Chip label={`Confiança ${result.confidence}`} />
              <Chip label="Paper only" variant="outlined" />
            </Stack>
            <Typography variant="h6" sx={{ mt: 2 }}>
              {strategyLabel[result.structure?.strategy || ''] || 'Operação'} · {result.horizon_label}
            </Typography>
            <Typography sx={{ mt: 1 }}>{result.why}</Typography>
            <Divider sx={{ my: 2 }} />
            <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr 1fr', md: 'repeat(4, 1fr)' }, gap: 2 }}>
              <Metric label="Preço agora" value={result.spot != null ? money(result.spot, result.quote_currency === 'USD' ? 'USD' : 'BRL') : '—'} />
              <Metric label="Entrada / gatilho" value={result.entry != null ? money(result.entry, result.quote_currency === 'USD' ? 'USD' : 'BRL') : '—'} />
              <Metric label="Invalidação (stop)" value={result.invalidation != null ? money(result.invalidation, result.quote_currency === 'USD' ? 'USD' : 'BRL') : '—'} />
              <Metric label="Alvo" value={result.target != null ? money(result.target, result.quote_currency === 'USD' ? 'USD' : 'BRL') : '—'} />
            </Box>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>{result.invalidation_reason}</Typography>
            {result.suggested_size && (
              <Typography sx={{ mt: 2 }}>
                Tamanho sugerido: <strong>{num(result.suggested_size.quantity)}</strong>
                {' · risco máximo de '}
                {money(result.suggested_size.risk_budget_brl)}
                {notionalBrl != null ? ` · nocional da posição ${money(notionalBrl)}` : (
                  result.suggested_size.notional_usd != null
                    ? ` · nocional da posição ${money(result.suggested_size.notional_usd, 'USD')}`
                    : ''
                )}
                {result.fx_usd_brl?.rate
                  ? ` · câmbio USD/BRL ${formatPricePtBr(result.fx_usd_brl.rate, 4)}`
                  : ''}
                {result.structure?.expiry ? (
                  <>
                    {' · prazo até '}
                    <Box component="span" sx={{ whiteSpace: 'nowrap' }}>
                      {formatDatePtBr(result.structure.expiry)}
                    </Box>
                  </>
                ) : null}
              </Typography>
            )}
            {result.structure?.legs?.length ? (
              <Typography variant="body2" sx={{ mt: 1 }}>
                Estrutura:{' '}
                {result.structure.legs.map((leg) => {
                  const side = leg.side === 'buy' ? 'compra' : 'venda';
                  return `${side} de ${num(leg.quantity)} ${leg.symbol}`;
                }).join(' · ')}
              </Typography>
            ) : null}
            <Stack direction="row" spacing={2} sx={{ mt: 3 }} flexWrap="wrap" useFlexGap>
              <Button
                variant="contained"
                onClick={registerPaper}
                disabled={busy || !result.suggested_size?.can_register_paper}
              >
                Registrar como operação paper (aguardando gatilho)
              </Button>
              {!result.suggested_size?.can_register_paper && result.suggested_size?.paper_block && (
                <Typography variant="body2" color="text.secondary" sx={{ alignSelf: 'center' }}>
                  {result.suggested_size.paper_block}
                </Typography>
              )}
            </Stack>
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 2 }}>
              {result.disclaimer}
            </Typography>
          </CardContent>
        </Card>
      )}
    </Stack>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <Box>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      <Typography variant="h6">{value}</Typography>
    </Box>
  );
}

const FALLBACK_UNIVERSE: ClientAsset[] = [
  { id: 'PETR4', label: 'Petrobras (PETR4)', asset_class: 'equity_br', instruments: ['spot', 'option'] },
  { id: 'VALE3', label: 'Vale (VALE3)', asset_class: 'equity_br', instruments: ['spot', 'option'] },
  { id: 'ITUB4', label: 'Itaú Unibanco (ITUB4)', asset_class: 'equity_br', instruments: ['spot', 'option'] },
  { id: 'BBDC4', label: 'Bradesco (BBDC4)', asset_class: 'equity_br', instruments: ['spot', 'option'] },
  { id: 'WEGE3', label: 'WEG (WEGE3)', asset_class: 'equity_br', instruments: ['spot', 'option'] },
  { id: 'BTC', label: 'Bitcoin', asset_class: 'crypto', instruments: ['spot', 'future'] },
  { id: 'ETH', label: 'Ethereum', asset_class: 'crypto', instruments: ['spot', 'future'] },
  { id: 'SOL', label: 'Solana', asset_class: 'crypto', instruments: ['spot', 'future'] },
];
const FALLBACK_INSTRUMENTS = [
  { id: 'spot', label: 'À vista (ação ou cripto)', hint: 'Compra ou venda simulada do próprio ativo.' },
  { id: 'option', label: 'Opção', hint: 'Estrutura condicional se o arsenal tiver livro com bid, ask e quantidade.' },
  { id: 'future', label: 'Futuro / perpétuo', hint: 'Só BTC, ETH e SOL, via feed público da Binance.' },
];
const FALLBACK_HORIZONS = [
  { id: 'days', label: 'Alguns dias', holding_days: 5 },
  { id: 'weeks', label: 'Algumas semanas', holding_days: 21 },
  { id: 'months', label: 'Alguns meses', holding_days: 63 },
];
