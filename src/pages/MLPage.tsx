import { useState } from 'react';
import {
  Alert, Box, Button, Card, CardContent, Checkbox, Chip, FormControlLabel,
  MenuItem, Stack, Table, TableBody, TableCell, TableHead, TableRow, TextField, Typography,
} from '@mui/material';
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api, type QuantExperiment } from '../services/api';
import MarketTickerAutocomplete from '../components/MarketTickerAutocomplete';

type Dataset = { prices: number[]; dates: string[]; source: string; ticker: string };
function demoData(): Dataset {
  const prices: number[] = [], dates: string[] = [];
  const day = new Date(); day.setUTCDate(day.getUTCDate() - 1300);
  let price = 100, seed = 42;
  for (let i = 0; i < 1250; i++) {
    day.setUTCDate(day.getUTCDate() + 1);
    if ([0, 6].includes(day.getUTCDay())) continue;
    seed = (seed * 16807) % 2147483647;
    price *= Math.exp((seed / 2147483647 - 0.5) * 0.035);
    prices.push(price); dates.push(day.toISOString().slice(0, 10));
  }
  return { prices, dates, source: 'synthetic_demo', ticker: 'DEMO' };
}
const labels: Record<string, string> = { ridge: 'Ridge', random_forest: 'Random Forest', zero: 'Previsão zero / caixa', momentum: 'Momentum simples', buy_hold: 'Buy & hold' };

export default function MLPage() {
  const [ticker, setTicker] = useState('PETR4.SA');
  const [data, setData] = useState<Dataset | null>(null);
  const [hypothesis, setHypothesis] = useState('');
  const [model, setModel] = useState<'ridge' | 'random_forest'>('ridge');
  const [commission, setCommission] = useState(5);
  const [slippage, setSlippage] = useState(5);
  const [targetVol, setTargetVol] = useState(10);
  const [maxDrawdown, setMaxDrawdown] = useState(20);
  const [adjusted, setAdjusted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<QuantExperiment | null>(null);

  function invalidate() { setResult(null); }
  async function load() {
    setBusy(true); setError(''); setData(null); setAdjusted(false); invalidate();
    try {
      const history = await api.researchMarketHistory(ticker);
      const source = history.provider || history.source || 'unverified';
      if (source.toLowerCase().includes('synthetic') || history.source?.toLowerCase().includes('synthetic')) {
        throw new Error('O provedor retornou dados sintéticos. Use a demonstração explicitamente ou tente outra fonte.');
      }
      if (history.close.length < 400 || history.dates.length !== history.close.length) throw new Error('É preciso um histórico diário datado de pelo menos 400 observações (~18 meses).');
      setData({ prices: history.close, dates: history.dates, source, ticker });
    } catch (e) { setError(e instanceof Error ? e.message : 'Falha ao carregar dados.'); }
    finally { setBusy(false); }
  }
  async function evaluate(event: React.FormEvent) {
    event.preventDefault(); if (!data) return;
    setBusy(true); setError(''); invalidate();
    try {
      setResult(await api.quantEvaluate({ prices: data.prices, dates: data.dates, data_source: `${data.source}:${data.ticker}`,
        hypothesis: hypothesis.trim(), model, price_basis: adjusted ? 'adjusted' : 'unverified',
        commission_bps: commission, slippage_bps: slippage, target_volatility: targetVol / 100, max_drawdown: maxDrawdown / 100 }));
    } catch (e) { setError(e instanceof Error ? e.message : 'Falha na avaliação.'); }
    finally { setBusy(false); }
  }
  function download() {
    if (!result) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' }));
    const link = document.createElement('a'); link.href = url; link.download = `atom-research-${result.experiment_id.slice(0, 12)}.json`;
    link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const selected = result?.results[result.config.model];
  const curve = result && selected ? selected.equity.map((value, i) => ({ day: i, net: value, baseline: result.results.momentum.equity[i] })) : [];

  return <Stack spacing={3} sx={{ maxWidth: 1200, mx: 'auto' }}>
    <Box><Typography variant="h4" component="h1">Laboratório Quant</Typography>
      <Typography color="text.secondary">Hipótese econômica → features causais → validação temporal → resultado líquido.</Typography></Box>
    <Alert severity="info">Complexidade precisa justificar seu custo. Resultados são de pesquisa e nunca autorizam negociação automática. O teste usa grupos mensais, purga de rótulos e um mês de intervalo antes de cada janela.</Alert>
    {error && <Alert severity="error">{error}</Alert>}
    <Card component="form" onSubmit={evaluate}><CardContent><Stack spacing={2}>
      <Typography variant="h6">1. Dados e hipótese</Typography>
      <MarketTickerAutocomplete label="Ativo" value={ticker} onChange={value => { setTicker(value || ''); setData(null); setAdjusted(false); invalidate(); }} />
      <Stack direction="row" spacing={2} useFlexGap flexWrap="wrap">
        <Button onClick={load} disabled={busy} variant="outlined">Carregar histórico de 5 anos</Button>
        <Button onClick={() => { setData(demoData()); setAdjusted(false); setError(''); invalidate(); }} disabled={busy}>Usar dados sintéticos de demonstração</Button>
      </Stack>
      {data && <Chip sx={{ alignSelf: 'flex-start' }} label={`${data.ticker} · ${data.source} · ${data.prices.length} observações`} />}
      <TextField label="Hipótese econômica e condição que a refutaria" multiline minRows={3} value={hypothesis}
        onChange={e => { setHypothesis(e.target.value); invalidate(); }} disabled={busy} required
        helperText="Explique por que as features poderiam carregar sinal, em quais regimes e como o teste pode rejeitar essa ideia. Mínimo de 30 caracteres." inputProps={{ minLength: 30, maxLength: 2000 }} />
      <FormControlLabel control={<Checkbox checked={adjusted} disabled={busy || !data || data.source.includes('synthetic')}
        onChange={e => { setAdjusted(e.target.checked); invalidate(); }} />} label="Verifiquei que a série está ajustada por eventos corporativos" />
      <Typography variant="h6">2. Modelo e premissas definidas antes do teste</Typography>
      <TextField select label="Modelo" value={model} disabled={busy} onChange={e => { setModel(e.target.value as 'ridge' | 'random_forest'); invalidate(); }}>
        <MenuItem value="ridge">Ridge — baseline linear regularizado</MenuItem>
        <MenuItem value="random_forest">Random Forest — candidato não linear</MenuItem>
      </TextField>
      <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 2 }}>
        <TextField label="Comissão (bps por lado)" type="number" value={commission} disabled={busy} inputProps={{ min: 0, max: 100, step: 1 }} onChange={e => { setCommission(+e.target.value); invalidate(); }} />
        <TextField label="Slippage (bps por lado)" type="number" value={slippage} disabled={busy} inputProps={{ min: 0, max: 100, step: 1 }} onChange={e => { setSlippage(+e.target.value); invalidate(); }} />
        <TextField label="Alvo de volatilidade anual (%)" type="number" value={targetVol} disabled={busy} inputProps={{ min: 1, max: 50 }} onChange={e => { setTargetVol(+e.target.value); invalidate(); }} />
        <TextField label="Limite de drawdown (%)" type="number" value={maxDrawdown} disabled={busy} inputProps={{ min: 1, max: 50 }} onChange={e => { setMaxDrawdown(+e.target.value); invalidate(); }} />
      </Box>
      <Typography variant="body2" color="text.secondary">1 bp = 0,01%. Estratégia comprada ou em caixa, sem alavancagem. Sinal após o fechamento, execução no fechamento seguinte. Custos incluem rebalanceamentos e saída final.</Typography>
      <Button type="submit" variant="contained" disabled={busy || !data || hypothesis.trim().length < 30}>{busy ? 'Processando…' : 'Avaliar fora da amostra'}</Button>
    </Stack></CardContent></Card>
    {result && selected && <>
      <Alert severity="warning"><strong>{result.assessment === 'insufficient_evidence' ? 'Evidência insuficiente' : 'Candidato a revisão independente'}</strong> — uso exclusivamente de pesquisa.</Alert>
      {result.reasons.map(reason => <Typography key={reason}>• {reason}</Typography>)}
      <Card><CardContent><Typography variant="h6">3. Comparação fora da amostra — mesmos períodos e custos</Typography>
        <Box sx={{ overflowX: 'auto' }}><Table size="small"><TableHead><TableRow>
          {['Modelo', 'Retorno bruto %', 'Retorno líquido %', 'Sharpe líquido', 'Vol. anual %', 'Drawdown %', 'Turnover ×', 'Custo / capital %', 'MSE OOS'].map(h => <TableCell key={h}>{h}</TableCell>)}
        </TableRow></TableHead><TableBody>{Object.entries(result.results).map(([name, metrics]) => <TableRow key={name} selected={name === result.config.model}>
          <TableCell>{labels[name]}</TableCell>{[metrics.gross_return_pct, metrics.net_return_pct, metrics.sharpe_net, metrics.annualized_volatility_pct, metrics.max_drawdown_pct, metrics.turnover_total, metrics.cost_paid_pct_initial].map((v, i) => <TableCell key={i}>{v.toFixed(2)}</TableCell>)}<TableCell>{metrics.mse_oos?.toExponential(2) || '—'}</TableCell>
        </TableRow>)}</TableBody></Table></Box>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>Patrimônio normalizado; capital inicial = 1. O eixo conta observações OOS. Buy & hold mantém exposição integral; os modelos usam alvo de volatilidade.</Typography>
        <Box sx={{ height: 260 }}><ResponsiveContainer width="100%" height="100%"><LineChart data={curve}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="day" /><YAxis domain={['auto', 'auto']} /><Tooltip /><Line type="linear" dataKey="net" name="Modelo líquido" stroke="#7c83ff" dot={false} /><Line type="linear" dataKey="baseline" name="Momentum líquido" stroke="#40ba8d" dot={false} /></LineChart></ResponsiveContainer></Box>
      </CardContent></Card>
      <Card><CardContent><Typography variant="h6">Janelas temporais e estabilidade</Typography><Box sx={{ overflowX: 'auto' }}><Table size="small"><TableHead><TableRow>{['Janela', 'Treino até', 'Último rótulo de treino', 'Teste de', 'Teste até', 'N teste', 'Retorno líquido %'].map(h => <TableCell key={h}>{h}</TableCell>)}</TableRow></TableHead><TableBody>{result.folds.map(f => <TableRow key={f.fold}><TableCell>{f.fold}</TableCell><TableCell>{f.train_end}</TableCell><TableCell>{f.last_train_label_end}</TableCell><TableCell>{f.test_start}</TableCell><TableCell>{f.test_end}</TableCell><TableCell>{f.test_count}</TableCell><TableCell>{f.net_return_pct.toFixed(2)}</TableCell></TableRow>)}</TableBody></Table></Box></CardContent></Card>
      <Card><CardContent><Typography variant="h6">Limitações que acompanham o resultado</Typography>{result.limitations.map(item => <Typography key={item} variant="body2" sx={{ mt: 1 }}>• {item}</Typography>)}</CardContent></Card>
      <Button onClick={download} variant="outlined">Exportar relatório auditável (JSON)</Button>
      <Typography variant="caption" sx={{ overflowWrap: 'anywhere' }}>{result.policy_version} · Experimento {result.experiment_id}</Typography>
    </>}
  </Stack>;
}
