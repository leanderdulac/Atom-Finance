import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Alert, Box, Button, Card, CardContent, Chip, MenuItem, Stack, TextField, Typography } from '@mui/material';
import { api, type ExperimentDetail, type ExperimentSummary } from '../services/api';

const statusLabel: Record<string, string> = { running: 'Em processamento', failed: 'Falhou', completed: 'Concluído' };
export default function ExperimentsPage() {
  const navigate = useNavigate(); const [params, setParams] = useSearchParams();
  const id = params.get('id');
  const [items, setItems] = useState<ExperimentSummary[]>([]);
  const [total, setTotal] = useState(0); const [offset, setOffset] = useState(0);
  const [detail, setDetail] = useState<ExperimentDetail | null>(null);
  const [busy, setBusy] = useState(true); const [error, setError] = useState('');
  const [decision, setDecision] = useState<'discard' | 'investigate'>('investigate');
  const [rationale, setRationale] = useState(''); const [saving, setSaving] = useState(false);
  useEffect(() => {
    let active = true; setBusy(true); setError(''); setDetail(null); setRationale('');
    Promise.all([api.experiments(offset), id ? api.experiment(id) : Promise.resolve(null)])
      .then(([list, selected]) => { if (active) { setItems(list.items); setTotal(list.total); setDetail(selected); } })
      .catch(e => { if (active) setError(e.message); }).finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [id, offset]);
  async function saveReview() {
    if (!detail) return; setSaving(true); setError('');
    try { setDetail(await api.reviewExperiment(detail.id, decision, rationale.trim())); setRationale(''); }
    catch (e) { setError(e instanceof Error ? e.message : 'Falha ao registrar decisão.'); }
    finally { setSaving(false); }
  }
  function download() {
    if (!detail) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(detail, null, 2)], { type: 'application/json' }));
    const a = document.createElement('a'); a.href = url; a.download = `atom-${detail.id}.json`; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const report = detail?.result; const metrics = report?.results[report.config.model];
  return <Stack spacing={3} sx={{ maxWidth: 1150, mx: 'auto' }}>
    <Box><Chip label="ATOM Research · piloto local" size="small" sx={{ mb: 2 }} />
      <Typography variant="h4" component="h1">Da hipótese à evidência.</Typography>
      <Typography color="text.secondary" sx={{ mt: 1 }}>Seu diário de pesquisa quantitativa. Preserve cada tentativa e decida o que merece investigação.</Typography></Box>
    <Stack direction="row" spacing={2} useFlexGap flexWrap="wrap">
      <Button variant="contained" onClick={() => navigate('/ml')}>Novo experimento</Button>
      <Button variant="outlined" onClick={() => navigate('/research')}>Explorar um artigo</Button>
    </Stack>
    <Alert severity="info">Um resultado favorável ainda exige teste independente. O diário inclui falhas e repetições; escolher apenas o melhor teste pode produzir uma conclusão enganosa.</Alert>
    {error && <Alert severity="error">{error}</Alert>}
    {busy ? <Typography role="status">Carregando diário…</Typography> : !error && <>
      <Typography variant="h6">{total} tentativa{total === 1 ? '' : 's'} registrada{total === 1 ? '' : 's'}</Typography>
      {!total && <Card><CardContent><Typography variant="h6">Comece com uma pergunta que possa ser refutada</Typography>
        <Typography sx={{ my: 2 }}>Exemplo: momentum de 20 dias mantém resultado líquido positivo em diferentes janelas, após custos e controle de volatilidade?</Typography>
        <Typography color="text.secondary">No laboratório, use a demonstração sintética para conhecer o fluxo ou carregue uma série de mercado. Hipótese, dados e premissas são guardados antes do cálculo.</Typography>
      </CardContent></Card>}
      <Stack spacing={1}>{items.map(item => <Card key={item.id} variant="outlined" sx={{ borderColor: id === item.id ? 'primary.main' : 'divider' }}>
        <CardContent><Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mb: 1 }}><Chip size="small" label={statusLabel[item.status]} /><Chip size="small" label={item.data_source} /><Chip size="small" label={item.model} /></Stack>
          <Typography sx={{ overflowWrap: 'anywhere' }}>{item.hypothesis}</Typography>
          <Typography variant="caption" color="text.secondary">{new Date(item.created_at).toLocaleString('pt-BR')}</Typography>
          <Box><Button onClick={() => setParams({ id: item.id })}>Abrir registro</Button></Box>
        </CardContent></Card>)}</Stack>
      {total > 50 && <Stack direction="row" spacing={2}><Button disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 50))}>Anteriores</Button><Button disabled={offset + 50 >= total} onClick={() => setOffset(offset + 50)}>Próximos</Button></Stack>}
      {detail && <Card><CardContent><Stack spacing={2}>
        <Typography variant="h5" component="h2">Registro do experimento</Typography>
        <Typography>{detail.inputs.hypothesis}</Typography>
        <Typography variant="body2">Fonte: {detail.inputs.data_source} · {detail.inputs.prices.length} observações · Base de preços: {detail.inputs.price_basis}</Typography>
        <Typography variant="body2">Comissão: {detail.inputs.commission_bps} bps · Slippage: {detail.inputs.slippage_bps} bps · Alvo de volatilidade: {(detail.inputs.target_volatility * 100).toFixed(0)}% · Limite de drawdown: {(detail.inputs.max_drawdown * 100).toFixed(0)}%</Typography>
        {detail.status === 'running' && <Alert severity="info">Processamento iniciado. Se o servidor foi interrompido, esta tentativa pode permanecer pendente. Ela não representa um resultado concluído.</Alert>}
        {detail.error && <Alert severity="error">{detail.error}</Alert>}
        {report && metrics && <>
          <Alert severity="warning">{report.assessment === 'insufficient_evidence' ? 'Evidência insuficiente' : 'Candidato a revisão independente'} · Pesquisa, sem autorização de execução.</Alert>
          <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 2 }}>{[
            ['Retorno líquido OOS', `${metrics.net_return_pct.toFixed(2)}%`], ['Sharpe líquido', metrics.sharpe_net.toFixed(2)],
            ['Drawdown máximo', `${metrics.max_drawdown_pct.toFixed(2)}%`], ['Custo / capital inicial', `${metrics.cost_paid_pct_initial.toFixed(2)}%`],
          ].map(([label, value]) => <Box key={label}><Typography variant="body2" color="text.secondary">{label}</Typography><Typography variant="h5">{value}</Typography></Box>)}</Box>
          {report.reasons.map(reason => <Typography key={reason} variant="body2">• {reason}</Typography>)}
          <Typography variant="h6">Próxima decisão de pesquisa</Typography>
          <TextField select label="Decisão" value={decision} disabled={saving} onChange={e => setDecision(e.target.value as 'discard' | 'investigate')}><MenuItem value="investigate">Investigar com novos dados</MenuItem><MenuItem value="discard">Descartar esta hipótese</MenuItem></TextField>
          <TextField label="Justificativa e próximo teste" multiline minRows={2} value={rationale} disabled={saving} onChange={e => setRationale(e.target.value)} helperText="Mínimo de 20 caracteres. Novas decisões são acrescentadas ao histórico, sem apagar as anteriores." inputProps={{ maxLength: 2000 }} />
          <Button variant="outlined" disabled={saving || rationale.trim().length < 20} onClick={saveReview}>{saving ? 'Registrando…' : 'Registrar decisão'}</Button>
          {detail.reviews.map(review => <Box key={review.id}><Typography variant="subtitle2">{review.decision === 'discard' ? 'Descartar' : 'Investigar'} · {new Date(review.created_at).toLocaleString('pt-BR')}</Typography><Typography variant="body2">{review.rationale}</Typography></Box>)}
          <Typography variant="h6">Limitações</Typography>{report.limitations.map(item => <Typography variant="body2" key={item}>{item}</Typography>)}
        </>}
        <Button onClick={download}>Exportar dados, premissas, resultado e decisões (JSON)</Button>
        <Typography variant="caption" sx={{ overflowWrap: 'anywhere' }}>SHA-256 dos dados e premissas: {detail.input_hash}</Typography>
      </Stack></CardContent></Card>}
    </>}
  </Stack>;
}
