/**
 * Operação pronta — o cliente escolhe ativo, instrumento e horizonte.
 * O arsenal monta o restante. Sem ordem real, sem promessa de retorno.
 */
import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Alert, Box, Button, Card, CardContent, Chip, CircularProgress, Divider,
  Stack, ToggleButton, ToggleButtonGroup, Typography,
} from '@mui/material';
import { api } from '../services/api';
import { useClientConfig, type ClientAsset } from '../contexts/ClientModeContext';

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
  suggested_size?: { quantity: number; risk_budget_brl: number; can_register_paper: boolean; paper_block?: string | null };
  greeks?: { delta: number; gamma: number; theta: number; vega: number; price: number } | null;
  confidence?: string;
  invalidation_reason?: string;
  why?: string;
  reason?: string;
  disclaimer?: string;
  arsenal?: { part: string; used: boolean; note: string }[];
  eligible_for_live_trading?: boolean;
};

const money = (n: number) => n.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', maximumFractionDigits: 2 });
const num = (n: number) => n.toLocaleString('pt-BR', { maximumFractionDigits: 4 });

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

  const [ticker, setTicker] = useState('PETR4');
  const [instrument, setInstrument] = useState('spot');
  const [horizon, setHorizon] = useState('weeks');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<ReadyBody | null>(null);
  const [paperMsg, setPaperMsg] = useState('');

  const asset = useMemo(
    () => universe.find((row) => row.id === ticker) as ClientAsset | undefined,
    [universe, ticker],
  );
  const allowed = asset?.instruments ?? ['spot'];

  async function assemble() {
    setBusy(true); setError(''); setPaperMsg(''); setResult(null);
    try {
      const body = await api.clientReadyOperation({ ticker, instrument, horizon }) as ReadyBody;
      setResult(body);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Não foi possível montar a operação.');
    } finally { setBusy(false); }
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
          Três escolhas. A operação vem pronta.
        </Typography>
        <Typography color="text.secondary" sx={{ mt: 1 }}>
          Você escolhe o ativo, se a operação é à vista, opção ou futuro, e por quanto tempo.
          O arsenal da mesa monta o resto — ou diz, com honestidade, que não tem dado nem sinal suficiente.
          Isto é cenário, não recomendação, e não promete retorno.
        </Typography>
      </Box>

      <Alert severity="info">
        Nenhuma ordem vai à corretora. O registro, se você quiser, entra no diário paper como
        «aguardando gatilho». {cfg.disclaimer}
      </Alert>

      <Card>
        <CardContent>
          <Typography variant="overline" color="text.secondary">1 · O ativo</Typography>
          <ToggleButtonGroup
            exclusive
            value={ticker}
            onChange={(_, v) => {
              if (!v) return;
              setTicker(v);
              setResult(null);
              const next = universe.find((row) => row.id === v);
              if (next && !next.instruments.includes(instrument)) setInstrument('spot');
            }}
            sx={{ flexWrap: 'wrap', gap: 1, mt: 1 }}
          >
            {universe.map((row) => (
              <ToggleButton key={row.id} value={row.id} aria-label={row.label}>{row.label}</ToggleButton>
            ))}
          </ToggleButtonGroup>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Typography variant="overline" color="text.secondary">2 · O instrumento da operação</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            Não é um segundo ticker: é <em>como</em> operar o ativo acima
            (à vista, opção ou futuro/perpétuo — só o que o arsenal realmente cobre).
          </Typography>
          <ToggleButtonGroup
            exclusive
            value={instrument}
            onChange={(_, v) => { if (v) { setInstrument(v); setResult(null); } }}
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

      <Card>
        <CardContent>
          <Typography variant="overline" color="text.secondary">3 · O tempo</Typography>
          <ToggleButtonGroup
            exclusive
            value={horizon}
            onChange={(_, v) => { if (v) { setHorizon(v); setResult(null); } }}
            sx={{ flexWrap: 'wrap', gap: 1, mt: 1 }}
          >
            {horizons.map((row) => (
              <ToggleButton key={row.id} value={row.id} aria-label={row.label}>{row.label}</ToggleButton>
            ))}
          </ToggleButtonGroup>
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
        <Button component={Link} to="/cliente/plano" sx={{ ml: 2 }}>Ver meu plano de investimento</Button>
      </Box>

      {error && <Alert severity="error">{error}</Alert>}
      {paperMsg && <Alert severity="success">{paperMsg}</Alert>}

      {result?.status === 'insufficient' && (
        <Alert severity="warning">
          <Typography fontWeight={700}>O arsenal não montou operação.</Typography>
          <Typography sx={{ mt: 1 }}>{result.reason}</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
            Não inventamos preço, livro nem sinal. Tente outro instrumento ou outro horizonte, ou volte mais tarde.
          </Typography>
        </Alert>
      )}

      {result?.status === 'ready' && (
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
              <Metric label="Preço agora" value={result.spot != null ? num(result.spot) : '—'} />
              <Metric label="Entrada / gatilho" value={result.entry != null ? num(result.entry) : '—'} />
              <Metric label="Invalidação (stop)" value={result.invalidation != null ? num(result.invalidation) : '—'} />
              <Metric label="Alvo" value={result.target != null ? num(result.target) : '—'} />
            </Box>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>{result.invalidation_reason}</Typography>
            {result.suggested_size && (
              <Typography sx={{ mt: 2 }}>
                Tamanho sugerido por risco ({money(result.suggested_size.risk_budget_brl)} de orçamento paper):{' '}
                <strong>{num(result.suggested_size.quantity)}</strong>
                {result.structure?.expiry ? ` · prazo até ${result.structure.expiry}` : null}
              </Typography>
            )}
            {result.greeks && (
              <Typography variant="body2" sx={{ mt: 1 }}>
                Gregas da perna comprada (Black–Scholes, σ do arsenal):
                delta {num(result.greeks.delta)}, gamma {num(result.greeks.gamma)},
                theta {num(result.greeks.theta)}, vega {num(result.greeks.vega)}.
              </Typography>
            )}
            {result.structure?.legs?.length ? (
              <Typography variant="body2" sx={{ mt: 1 }}>
                Estrutura:{' '}
                {result.structure.legs.map((leg) => `${leg.side} ${leg.quantity} ${leg.symbol} K=${leg.strike}`).join(' · ')}
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
              {result.disclaimer} eligible_for_live_trading={String(result.eligible_for_live_trading)}.
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
];
const FALLBACK_INSTRUMENTS = [
  { id: 'spot', label: 'À vista (ação ou cripto)', hint: 'Compra ou venda simulada do próprio ativo.' },
  { id: 'option', label: 'Opção', hint: 'Estrutura condicional se o arsenal tiver livro com bid, ask e quantidade.' },
  { id: 'future', label: 'Futuro / perpétuo', hint: 'Só BTC e ETH, via feed público da Binance.' },
];
const FALLBACK_HORIZONS = [
  { id: 'days', label: 'Alguns dias', holding_days: 5 },
  { id: 'weeks', label: 'Algumas semanas', holding_days: 21 },
  { id: 'months', label: 'Alguns meses', holding_days: 63 },
];
