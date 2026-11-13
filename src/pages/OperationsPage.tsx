/**
 * Mesa de operações — cockpit do operador.
 *
 * Fluxo único: o que exige atenção agora (bandas de saída vs último preço,
 * prazos, alertas) → nova operação assistida (mercado → ativo → tese →
 * livro declarado → planos) → diário imutável.
 *
 * Doutrina: o diário (`/paper-trades`) segue sendo o ÚNICO escritor das
 * operações em curso — este cockpit lê o estado agregado e auxilia a
 * criação de planos novos; cotações das pernas continuam declaradas pelo
 * operador (PAPER-TRADING.md), sem ordens reais.
 */
import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Alert, Box, Button, Card, CardContent, Chip, Divider, FormControlLabel,
  Checkbox, LinearProgress, Stack, Table, TableBody, TableCell, TableHead,
  TableRow, TextField, ToggleButton, ToggleButtonGroup, Typography,
} from '@mui/material';
import { api, getAccessToken } from '../services/api';
import type { OperatorTrade, OperationsState } from '../types/paperTrading';

const money = (n: number) => n.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
const strategyLabels: Record<string, string> = {
  long_call: 'Compra de call', long_put: 'Compra de put',
  bull_call_spread: 'Trava de alta com calls', bear_put_spread: 'Trava de baixa com puts',
};
const statusLabels: Record<string, string> = {
  watching: 'Aguardando entrada', open: 'Aberta (simulação)', closed: 'Encerrada', cancelled: 'Cancelada',
};

type QuoteInfo = { name?: string; price?: number; current_price?: number; change_pct?: number };
type Leg = { symbol: string; side: string; kind: string; strike: number; limit_reference: number; quantity: number; exercise: string };
type PlanCard = {
  ticker: string; direction: 'long_bias' | 'short_bias'; strategy: string; rationale: string; expiry: string;
  holding_days: number; close_by: string; legs: Leg[]; premium_outlay_brl: number; fees_reserved_brl: number;
  modeled_max_loss_brl: number; modeled_max_profit_brl: number | null; breakeven_at_expiry: number;
  target_scenario_reward_risk: number; quantity_per_leg: number;
  entry: { underlying_trigger: number; comparison: string; max_net_debit_per_unit: number; quote_valid_until: string; instruction: string };
  exit: { underlying_invalidation: number; underlying_target: number; take_profit_net_brl: number; stop_loss_net_brl: number; instruction: string };
};
type PlanReport = {
  id: string; status: string; source: string; as_of: string; plans: PlanCard[];
  rejected: { ticker: string; reason: string }[]; limitations: string[];
};
type BookRow = {
  symbol: string; kind: 'call' | 'put'; strike: string; expiry: string; exercise: 'european' | 'american';
  bid: string; ask: string; bid_size: string; ask_size: string; multiplier: string; lot_size: string;
};

const emptyBook = (kind: 'call' | 'put', strike: number, expiry: string): BookRow => ({
  symbol: '', kind, strike: String(strike), expiry, exercise: 'european',
  bid: '', ask: '', bid_size: '', ask_size: '', multiplier: '100', lot_size: '1',
});

export default function OperationsPage() {
  const [ops, setOps] = useState<OperationsState | null>(null);
  const [regime, setRegime] = useState<{ regime?: string; kill_switch?: { armed?: boolean } } | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  // ── Nova operação (etapa 1-2: mercado e ativo) ──
  const [ticker, setTicker] = useState('');
  const [quote, setQuote] = useState<QuoteInfo | null>(null);
  // ── Etapa 3: tese + livro ──
  const [direction, setDirection] = useState<'bullish' | 'bearish'>('bullish');
  const [entry, setEntry] = useState(''); const [invalidation, setInvalidation] = useState('');
  const [target, setTarget] = useState(''); const [holdingDays, setHoldingDays] = useState(15);
  const [rationale, setRationale] = useState(''); const [eventsChecked, setEventsChecked] = useState(false);
  const [nextEvent, setNextEvent] = useState('');
  const [capital, setCapital] = useState(10000); const [riskPct, setRiskPct] = useState(1);
  const [totalRiskPct, setTotalRiskPct] = useState(3); const [existingRisk, setExistingRisk] = useState(0);
  const [fee, setFee] = useState(0.05);
  const [books, setBooks] = useState<BookRow[]>([]);

  // ── Planos montados ──
  const [plan, setPlan] = useState<PlanReport | null>(null);

  const refreshOps = useCallback((active = true) => {
    api.paperOperations().then(v => { if (active) setOps(v); }).catch(e => { if (active) setError(e.message); });
  }, []);
  useEffect(() => { let active = true; refreshOps(active); return () => { active = false; }; }, [refreshOps]);
  useEffect(() => {
    let active = true;
    api.deskRegimeLive(false).then(v => { if (active) setRegime(v); }).catch(() => { /* regime é opcional no cockpit */ });
    return () => { active = false; };
  }, []);

  const spot = Number(quote?.price ?? quote?.current_price ?? 0);

  async function fetchQuote() {
    if (!ticker.trim()) return;
    setBusy(true); setError(''); setQuote(null);
    try {
      const q = await api.quote(ticker.trim().toUpperCase()) as QuoteInfo;
      setQuote(q);
      if (!entry && q?.price) setEntry(String(q.price));
    } catch (e) { setError(e instanceof Error ? e.message : 'Falha ao buscar cotação.'); } finally { setBusy(false); }
  }

  function suggestBooks() {
    if (!spot) return;
    const date = new Date(Date.now() + 45 * 864e5).toISOString().slice(0, 10);
    const strikes = direction === 'bullish'
      ? [Math.round(spot * 1.01 * 100) / 100, Math.round(spot * 1.08 * 100) / 100]
      : [Math.round(spot * 0.99 * 100) / 100, Math.round(spot * 0.92 * 100) / 100];
    setBooks(strikes.map((strike) => {
      const kind = direction === 'bullish' ? 'call' : 'put';
      const row = emptyBook(kind, strike, date);
      row.symbol = `${ticker.trim().toUpperCase()||'TICKER'} ${kind === 'call' ? 'C' : 'P'}${strike}${date.slice(2, 4)}`;
      row.kind = kind; row.strike = String(strike);
      return row;
    }));
  }

  function validatePayload(): Record<string, unknown> | null {
    if (!ticker.trim() || !spot) throw new Error('Escolha o ativo e busque a cotação antes de montar o plano.');
    const e = Number(entry), inv = Number(invalidation), tgt = Number(target);
    if (!entry || !invalidation || !target) throw new Error('Informe entrada, invalidação e alvo da tese.');
    if (direction === 'bullish' && !(inv < e && e < tgt)) throw new Error('Alta exige invalidação < entrada < alvo.');
    if (direction === 'bearish' && !(tgt < e && e < inv)) throw new Error('Baixa exige alvo < entrada < invalidação.');
    if (rationale.trim().length < 30) throw new Error('Descreva a tese com pelo menos 30 caracteres — sem raciocínio, não há plano.');
    if (!eventsChecked) throw new Error('Confirme que o calendário de eventos do ativo foi conferido.');
    const options = books.map(b => ({
      symbol: b.symbol.trim(), kind: b.kind, strike: Number(b.strike), expiry: b.expiry, exercise: b.exercise,
      bid: Number(b.bid), ask: Number(b.ask), bid_size: Number(b.bid_size) || 0, ask_size: Number(b.ask_size) || 0,
      multiplier: Number(b.multiplier), lot_size: Number(b.lot_size),
    }));
    for (const o of options) {
      if (!o.symbol || o.bid <= 0 || o.ask <= 0 || !o.expiry) throw new Error(`Preencha contrato, bid, ask e vencimento de ${o.symbol || 'cada perna'} — o livro é declarado por você.`);
      if (o.bid > o.ask) throw new Error(`Bid acima de ask em ${o.symbol}.`);
    }
    if (new Set(options.map(o => o.symbol)).size !== options.length) throw new Error('Contratos duplicados.');
    return {
      source: 'ATOM cockpit · livro e tese declarados pelo operador',
      provenance: 'user_supplied', as_of: new Date().toISOString(),
      capital: capital, risk_per_trade_pct: riskPct, total_risk_pct: totalRiskPct,
      existing_risk_brl: existingRisk, fee_per_contract_side: fee,
      theses: [{
        ticker: ticker.trim().toUpperCase(), spot, direction, rationale: rationale.trim(),
        entry: e, invalidation: inv, target: tgt, holding_days: holdingDays,
        events_checked: eventsChecked, next_event: nextEvent || null, options,
      }],
    };
  }

  async function mountPlans() {
    setBusy(true); setError(''); setPlan(null);
    try {
      const payload = validatePayload();
      if (!payload) return;
      const result = await api.derivativePlan(payload) as PlanReport;
      setPlan(result);
      refreshOps();
    } catch (e) { setError(e instanceof Error ? e.message : 'Falha ao montar planos.'); } finally { setBusy(false); }
  }

  async function track(index: number) {
    if (!plan) return;
    setBusy(true); setError('');
    return await api.paperTrack(plan.id, index)
      .then((trade) => { refreshOps(); setPlan(null); setBooks([]); return trade; })
      .catch(e => { setError(e instanceof Error ? e.message : 'Falha ao acompanhar plano.'); return null; })
      .finally(() => setBusy(false));
  }

  async function cancelWatching(id: string) {
    setBusy(true); setError('');
    try {
      await api.paperEvent(id, {
        request_id: crypto.randomUUID(), action: 'cancel', source: 'Cancelamento pela mesa de operações',
        note: 'Cancelado no cockpit; plano não foi executado.', as_of: new Date().toISOString(), quotes: [],
      });
      refreshOps();
    } catch (e) { setError(e instanceof Error ? e.message : 'Falha ao cancelar.'); } finally { setBusy(false); }
  }

  const bandPos = (t: OperatorTrade) => {
    const last = t.last?.underlying;
    if (!last || last == null) return null;
    const lo = Math.min(t.exit.invalidation, t.exit.target), hi = Math.max(t.exit.invalidation, t.exit.target);
    return Math.max(0, Math.min(100, ((last - lo) / (hi - lo)) * 100));
  };
  const daysLeft = (closeBy: string) => Math.round((new Date(closeBy).getTime() - Date.now()) / 864e5);

  const openTrades = ops?.trades.filter(t => t.status === 'open') ?? [];
  const watching = ops?.trades.filter(t => t.status === 'watching') ?? [];
  const done = ops?.trades.filter(t => t.status === 'closed' || t.status === 'cancelled') ?? [];

  return <Stack spacing={3} sx={{ maxWidth: 1200, mx: 'auto' }}>
    <Box>
      <Chip label="Mesa de operações · piloto sem ordens reais" size="small" />
      <Typography variant="h4" component="h1" sx={{ mt: 2 }}>Operar é decidir menos coisas — e ver todas juntas.</Typography>
      <Typography color="text.secondary">
        O que exige atenção hoje, quando entrar e quando sair. As cotações das pernas continuam sendo
        declaradas por você; nada aqui envia ordens.
      </Typography>
    </Box>

    {/* ── Estado do mercado ── */}
    <Card><CardContent>
      <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" alignItems="center">
        {regime?.regime && <Chip color={regime.kill_switch?.armed ? 'error' : 'default'}
          label={regime.kill_switch?.armed ? `Regime: ${regime.regime} · KILL SWITCH ARMADO` : `Regime: ${regime.regime}`} />}
        <Chip label={`Abertas: ${ops?.aggregate.open_count ?? '—'}`} />
        <Chip label={`Aguardando gatilho: ${ops?.aggregate.watching_count ?? '—'}`} />
        <Chip label={`Risco reservado: ${ops ? money(ops.aggregate.reserved_risk_brl) : '—'}`} />
        <Box sx={{ flexGrow: 1 }} />
        <Button component={Link} to="/sources" size="small">Fontes de dados</Button>
        <Button component={Link} to="/regime" size="small">Detalhe dos regimes</Button>
      </Stack>
    </CardContent></Card>

    {error && <Alert severity="error">{error}</Alert>}
    {!getAccessToken() && <Alert severity="info">Faça login para ver suas operações.</Alert>}

    {/* ── A. O que exige atenção agora ── */}
    <Typography variant="h5">Agora</Typography>
    {!ops && <LinearProgress />}
    {ops && !ops.trades.length && <Typography color="text.secondary">
      Nenhuma operação. Monte um plano abaixo — o primeiro acompanhamento nasce “aguardando entrada”.</Typography>}

    {watching.map(t => {
      const expired = new Date(t.entry.quote_valid_until).getTime() < Date.now();
      return <Card key={t.id} sx={{ borderLeft: 4, borderColor: expired ? 'warning.main' : 'info.main' }}><CardContent>
        <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" alignItems="center">
          <strong>{t.ticker}</strong><Chip size="small" label={statusLabels[t.status]} />
          <Chip size="small" label={strategyLabels[t.strategy] ?? t.strategy} variant="outlined" />
          {t.provenance === 'synthetic' && <Chip size="small" color="warning" label="Fictício" />}
        </Stack>
        <Typography sx={{ mt: 1 }}>
          Entrar quando o ativo {t.entry.comparison === '>=' ? 'estiver em' : 'cair até'} <strong>{money(t.entry.trigger)}</strong> ·
          invalidação {money(t.exit.invalidation)} · alvo {money(t.exit.target)} · sair até {t.close_by} (vence em {t.expiry})
        </Typography>
        {expired && <Alert severity="warning" sx={{ mt: 1 }}>
          Validade da cotação expirou ({new Date(t.entry.quote_valid_until).toLocaleString('pt-BR')}). Gere um plano novo abaixo ou cancele o acompanhamento.</Alert>}
        <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mt: 1 }}>
          <Button size="small" component={Link} to={`/paper-trades?id=${t.id}`} variant="outlined">Registrar entrada no diário</Button>
          <Button size="small" disabled={busy} onClick={() => cancelWatching(t.id)}>Cancelar</Button>
          <Button size="small" component={Link} to="/derivatives" variant="text">Reimportar livros</Button>
        </Stack>
      </CardContent></Card>;
    })}

    {openTrades.map(t => {
      const pos = bandPos(t); const dl = daysLeft(t.close_by);
      return <Card key={t.id} sx={{ borderLeft: 4, borderColor: t.last?.alerts?.length ? 'warning.main' : 'success.main' }}><CardContent>
        <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" alignItems="center">
          <strong>{t.ticker}</strong><Chip size="small" color="success" label={statusLabels[t.status]} />
          <Chip size="small" label={strategyLabels[t.strategy] ?? t.strategy} variant="outlined" />
          {t.last?.alerts?.map(a => <Chip key={a} size="small" color="warning" label={a} />)}
        </Stack>
        {pos !== null && <>
          <Box sx={{ mt: 2, mb: 1 }}>
            <LinearProgress variant="determinate" value={pos}
              sx={{ height: 8, borderRadius: 4, '& .MuiLinearProgress-bar': { backgroundColor: 'primary.main' } }} />
            <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 0.5 }}>
              <Typography variant="caption">🔴 Invalidação {money(t.exit.invalidation)}</Typography>
              <Typography variant="caption">🟡 Entrada {money(t.entry.trigger)}</Typography>
              <Typography variant="caption">🟢 Alvo {money(t.exit.target)}</Typography>
            </Box>
            <Typography variant="body2">Último preço registrado: {money(t.last?.underlying ?? 0)} ({new Date(t.last?.as_of ?? Date.now()).toLocaleString('pt-BR')})</Typography>
          </Box>
        </>}
        {pos === null && <Typography color="text.secondary" sx={{ mt: 1 }}>Sem cotação do ativo-objeto registrada ainda — atualize no diário.</Typography>}
        <Stack direction="row" spacing={3} useFlexGap flexWrap="wrap" sx={{ mt: 1 }}>
          {typeof t.last?.net_pnl_brl === 'number' && <Typography><strong>{t.last.pnl_kind === 'realized_simulated' ? 'Realizado' : 'Estimado se encerrar'}:</strong> {money(t.last.net_pnl_brl)}</Typography>}
          <Typography><strong>Reserva de risco:</strong> {money(t.reserved_risk_brl ?? 0)} / orçamento {money(t.risk_budget_brl)}</Typography>
          <Typography color={dl <= 0 ? 'error' : dl <= 2 ? 'warning.main' : 'text.secondary'}>
            <strong>Sair até</strong> {t.close_by}{dl <= 2 ? ` · ${dl <= 0 ? 'PRAZO HOJE/ESTOURADO' : `faltam ${dl} d`}` : ` · faltam ${dl} d`}
          </Typography>
          <Typography><strong>Pernas:</strong> {t.legs.join(' · ')}</Typography>
        </Stack>
        <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mt: 1 }}>
          <Button size="small" component={Link} to={`/paper-trades?id=${t.id}`} variant="contained">Atualizar / encerrar no diário</Button>
          <Button size="small" component={Link} to="/regime" variant="text">Conferir regime antes de agir</Button>
        </Stack>
      </CardContent></Card>;
    })}

    {done.length > 0 && <>
      <Divider />
      <Typography variant="h6">Encerradas recentemente</Typography>
      <Table size="small"><TableBody>
        {done.map(t => <TableRow key={t.id}>
          <TableCell>{t.ticker}</TableCell><TableCell>{statusLabels[t.status]}</TableCell>
          <TableCell>{t.last?.net_pnl_brl !== undefined && t.last?.net_pnl_brl !== null ? money(t.last.net_pnl_brl) : '—'}</TableCell>
          <TableCell><Button size="small" component={Link} to={`/paper-trades?id=${t.id}`}>Histórico</Button></TableCell>
        </TableRow>)}
      </TableBody></Table>
    </>}

    {/* ── B. Nova operação ── */}
    <Divider />
    <Typography variant="h5">Nova operação (B3 · opções)</Typography>
    <Alert severity="info">
      Fluxo v1: B3 com ciclo completo de plano e diário. Para cripto (Binance) e EUA, use os dashboards das
      respectivas páginas — diário simulado de perp entra em revisão. O livro de opções é declarado por
      você (bid/ask do seu provedor); o ATOM apenas seleciona estruturas e dimensiona risco. Sem ordens reais.
    </Alert>

    <Card><CardContent><Stack spacing={2}>
      <Typography variant="h6">1. Mercado e ativo</Typography>
      <Stack direction="row" spacing={1} alignItems="center" useFlexGap flexWrap="wrap">
        <TextField label="Ativo-objeto (ex.: PETR4)" size="small" value={ticker}
          onChange={e => setTicker(e.target.value.toUpperCase())} sx={{ width: 200 }} disabled={busy} />
        <Button variant="outlined" disabled={busy || !ticker.trim()} onClick={fetchQuote}>Buscar cotação</Button>
      </Stack>
      {quote && <>
        <Stack direction="row" spacing={2} useFlexGap flexWrap="wrap" alignItems="baseline">
          <Typography variant="h5">{money(spot)}</Typography>
          {typeof quote.change_pct === 'number' && <Chip size="small" color={quote.change_pct >= 0 ? 'success' : 'error'}
            label={`${quote.change_pct >= 0 ? '+' : ''}${quote.change_pct.toFixed(2)}%`} />}
          <Typography color="text.secondary">{quote.name ?? ticker}</Typography>
        </Stack>
        <Button size="small" onClick={() => { setEntry(String(spot || '')); }} disabled={busy}>Prefill entrada na cotação atual</Button>
      </>}
    </Stack></CardContent></Card>

    <Card><CardContent><Stack spacing={2}>
      <Typography variant="h6">2. Tese (compra condicional — o plano nasce “aguardando gatilho”)</Typography>
      <ToggleButtonGroup exclusive value={direction} onChange={(_, v) => { if (v) setDirection(v); }}>
        <ToggleButton value="bullish">Alta</ToggleButton>
        <ToggleButton value="bearish">Baixa</ToggleButton>
      </ToggleButtonGroup>
      <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(160px,1fr))', gap: 2 }}>
        <TextField label="Entrada (gatilho)" type="number" size="small" value={entry} onChange={e => setEntry(e.target.value)} disabled={busy} />
        <TextField label="Invalidação (sair se tocar)" type="number" size="small" value={invalidation} onChange={e => setInvalidation(e.target.value)} disabled={busy} />
        <TextField label="Alvo (premissa, não previsão)" type="number" size="small" value={target} onChange={e => setTarget(e.target.value)} disabled={busy} />
        <TextField label="Prazo (dias corridos)" type="number" size="small" value={holdingDays} inputProps={{ min: 2, max: 180 }} onChange={e => setHoldingDays(+e.target.value)} disabled={busy} />
      </Box>
      <TextField label="Tese — hipótese econômica e por que agora (mín. 30 caracteres)" multiline minRows={2}
        value={rationale} onChange={e => setRationale(e.target.value)} disabled={busy} />
      <Stack direction="row" spacing={2} useFlexGap flexWrap="wrap" alignItems="center">
        <FormControlLabel control={<Checkbox checked={eventsChecked} onChange={e => setEventsChecked(e.target.checked)} disabled={busy} />}
          label={<Typography variant="body2">Calendário de eventos conferido (resultados, dividendos, macro) — horizonte livre de eventos</Typography>} />
        <TextField label="Próximo evento (opcional)" type="date" size="small" value={nextEvent}
          onChange={e => setNextEvent(e.target.value)} disabled={busy} sx={{ width: 200 }} />
      </Stack>
      <Divider />
      <Typography variant="h6">3. Orçamento (por plano)</Typography>
      <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(160px,1fr))', gap: 2 }}>
        <TextField label="Capital (R$)" type="number" size="small" value={capital} onChange={e => setCapital(+e.target.value)} disabled={busy} />
        <TextField label="Risco por operação (%)" type="number" size="small" value={riskPct} inputProps={{ min: 0.1, max: 5, step: 0.1 }} onChange={e => setRiskPct(+e.target.value)} disabled={busy} />
        <TextField label="Risco agregado (%)" type="number" size="small" value={totalRiskPct} inputProps={{ min: 0.1, max: 10, step: 0.1 }} onChange={e => setTotalRiskPct(+e.target.value)} disabled={busy} />
        <TextField label="Risco já comprometido (R$)" type="number" size="small" value={existingRisk} onChange={e => setExistingRisk(+e.target.value)} disabled={busy} />
        <TextField label="Taxa por contrato/lado (R$)" type="number" size="small" value={fee} inputProps={{ step: 0.01 }} onChange={e => setFee(+e.target.value)} disabled={busy} />
      </Box>
    </Stack></CardContent></Card>

    <Card><CardContent><Stack spacing={2}>
      <Typography variant="h6">4. Livro de opções (você declara)</Typography>
      <Typography variant="body2" color="text.secondary">
        Bid/ask e quantidade do livro do seu provedor (OPLAB/CEDRO/broker). Sem livro não há plano —
        é o que impede o motor de inventar liquidez.
      </Typography>
      <Button size="small" disabled={busy || !spot} onClick={suggestBooks}>
        Sugerir strikes ao redor da cotação (bid/ask continuam vazios para você preencher)
      </Button>
      <Box sx={{ overflowX: 'auto' }}>
        <Table size="small">
          <TableHead><TableRow>
            {['Contrato', 'Tipo', 'Strike', 'Vencimento', 'Bid', 'Ask', 'Q bid', 'Q ask', 'Mult.', 'Lote', ''].map(h => <TableCell key={h}>{h}</TableCell>)}
          </TableRow></TableHead>
          <TableBody>
            {books.map((b, i) => <TableRow key={i}>
              <TableCell><TextField size="small" value={b.symbol} onChange={e => setBooks(p => p.map((x, j) => j === i ? { ...x, symbol: e.target.value } : x))} placeholder="PETRC55" sx={{ width: 130 }} disabled={busy} /></TableCell>
              <TableCell>
                <ToggleButtonGroup exclusive size="small" value={b.kind} onChange={(_, v) => v && setBooks(p => p.map((x, j) => j === i ? { ...x, kind: v } : x))}>
                  <ToggleButton value="call">C</ToggleButton><ToggleButton value="put">P</ToggleButton>
                </ToggleButtonGroup>
              </TableCell>
              <TableCell><TextField size="small" type="number" value={b.strike} onChange={e => setBooks(p => p.map((x, j) => j === i ? { ...x, strike: e.target.value } : x))} sx={{ width: 90 }} disabled={busy} /></TableCell>
              <TableCell><TextField size="small" type="date" value={b.expiry} onChange={e => setBooks(p => p.map((x, j) => j === i ? { ...x, expiry: e.target.value } : x))} sx={{ width: 150 }} disabled={busy} /></TableCell>
              {(['bid', 'ask', 'bid_size', 'ask_size'] as const).map(field => <TableCell key={field}>
                <TextField size="small" type="number" value={b[field]} onChange={e => setBooks(p => p.map((x, j) => j === i ? { ...x, [field]: e.target.value } : x))} sx={{ width: 90 }} disabled={busy} />
              </TableCell>)}
              <TableCell><TextField size="small" type="number" value={b.multiplier} onChange={e => setBooks(p => p.map((x, j) => j === i ? { ...x, multiplier: e.target.value } : x))} sx={{ width: 70 }} disabled={busy} /></TableCell>
              <TableCell><TextField size="small" type="number" value={b.lot_size} onChange={e => setBooks(p => p.map((x, j) => j === i ? { ...x, lot_size: e.target.value } : x))} sx={{ width: 70 }} disabled={busy} /></TableCell>
              <TableCell><Button size="small" color="error" disabled={busy} onClick={() => setBooks(p => p.filter((_, j) => j !== i))}>×</Button></TableCell>
            </TableRow>)}
          </TableBody>
        </Table>
      </Box>
      <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
        <Button size="small" disabled={busy} onClick={() => setBooks(p => [...p, emptyBook(direction === 'bullish' ? 'call' : 'put', Math.round(spot * 100) / 100 || 100, new Date(Date.now() + 45 * 864e5).toISOString().slice(0, 10))])}>
          + perna
        </Button>
        <Button variant="contained" disabled={busy || !spot || !books.length} onClick={mountPlans}>
          {busy ? 'Processando…' : 'Comparar estruturas e montar planos'}
        </Button>
      </Stack>
      <Typography variant="body2" color="text.secondary">
        Regras do motor: livro até 15 min de idade, spread ≤ 15%, saída ≥ 7 dias antes do vencimento,
        ganho no cenário-alvo ≥ risco. Saída por +50%/−40% líquido, invalidação, alvo ou prazo — o que ocorrer primeiro.
      </Typography>
    </Stack></CardContent></Card>

    {plan && <>
      <Typography variant="h5">Planos montados · {plan.status === 'no_trade' ? 'não operar com estas condições' : plan.status === 'simulation' ? 'SIMULAÇÃO' : 'condicionais — revise dados e tese'}</Typography>
      {plan.rejected.map((r, i) => <Alert severity="info" key={i}>{r.ticker}: {r.reason}</Alert>)}
      {plan.plans.map((p, i) => <Card key={p.ticker}><CardContent><Stack spacing={1}>
        <Typography variant="h6">{i + 1}. {p.ticker} · {strategyLabels[p.strategy] ?? p.strategy}</Typography>
        <Typography><strong>Entrada:</strong> ação {p.entry.comparison} {money(p.entry.underlying_trigger)} — o plano fica “aguardando gatilho”; revalide o livro antes.</Typography>
        <Typography><strong>Saída:</strong> invalidação {money(p.exit.underlying_invalidation)}, alvo {money(p.exit.underlying_target)}, +{money(p.exit.take_profit_net_brl)} / −{money(p.exit.stop_loss_net_brl)} líquido ou {p.close_by}.</Typography>
        <Typography><strong>Capital:</strong> prêmio {money(p.premium_outlay_brl)} + taxas {money(p.fees_reserved_brl)} · perda máxima modelada {money(p.modeled_max_loss_brl)} · razão no cenário-alvo {p.target_scenario_reward_risk}×</Typography>
        <Stack direction="row" spacing={1}>
          <Button variant="contained" disabled={busy} onClick={() => void track(i)}>Acompanhar como operação simulada</Button>
          <Button size="small" component={Link} to="/derivatives">Fluxo completo com importação</Button>
        </Stack>
        <Typography variant="caption">Cotação válida para entrada até {new Date(p.entry.quote_valid_until).toLocaleString('pt-BR')}.</Typography>
      </Stack></CardContent></Card>)}
      {plan.plans.length > 0 && <Alert severity="success">Ao acompanhar, a operação aparece em “Agora”, aguardando o gatilho da tese.</Alert>}
    </>}

    <Divider />
    <Typography variant="body2" color="text.secondary">
      Doutrina em uma linha: entrada por gatilho declarado, saída por invalidação, alvo, limite líquido
      ou prazo — registrado no diário imutável, sem envio de ordens, sem monitoramento automático.
    </Typography>
  </Stack>;
}
