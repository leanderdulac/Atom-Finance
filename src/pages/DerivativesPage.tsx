import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Alert, Box, Button, Card, CardContent, Chip, Stack, Table, TableBody, TableCell, TableHead, TableRow, TextField, Typography } from '@mui/material';
import { api } from '../services/api';

type Snapshot = { source: string; provenance: 'synthetic' | 'user_supplied'; as_of: string; theses: unknown[] };
type Leg = { symbol: string; side: string; kind: string; strike: number; limit_reference: number; quantity: number; exercise: string };
type Plan = {
  ticker: string; direction: string; strategy: string; rationale: string; expiry: string; holding_days: number; close_by: string; calendar_basis: string;
  legs: Leg[]; premium_outlay_brl: number; fees_reserved_brl: number; modeled_max_loss_brl: number; modeled_max_profit_brl: number | null;
  breakeven_at_expiry: number; target_scenario_reward_risk: number;
  entry: { underlying_trigger: number; comparison: string; max_net_debit_per_unit: number; quote_valid_until: string; instruction: string };
  exit: { underlying_invalidation: number; underlying_target: number; take_profit_net_brl: number; stop_loss_net_brl: number; instruction: string };
};
type Report = { id: string; status: string; source: string; as_of: string; plans: Plan[]; rejected: {ticker: string; reason: string}[]; limitations: string[]; ranking_method: string };
const money = (v: number) => v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
const strategyLabels: Record<string, string> = { long_call: 'Compra de call', long_put: 'Compra de put', bull_call_spread: 'Trava de alta com calls', bear_put_spread: 'Trava de baixa com puts' };
function demo(): Snapshot {
  const expiry = new Date(); expiry.setDate(expiry.getDate() + 50);
  return { source: 'Demonstração fictícia; não são cotações de mercado', provenance: 'synthetic', as_of: new Date().toISOString(),
    theses: [{ ticker: 'DEMO', spot: 100, direction: 'bullish', rationale: 'Exemplo sintético: hipótese de continuação de alta acima de 101, invalidada abaixo de 95. O alvo de 115 é uma premissa, não uma previsão.',
      entry: 101, invalidation: 95, target: 115, holding_days: 15, events_checked: true, next_event: null,
      options: [100, 110].map((strike, i) => ({ symbol: `DEMO-C${strike}`, kind: 'call', strike, expiry: expiry.toISOString().slice(0,10), exercise: 'european', bid: i ? 4 : 4.9, ask: i ? 4.1 : 5, bid_size: 1000, ask_size: 1000, multiplier: 1, lot_size: 1 })) }] };
}
function download(value: unknown, name: string) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value,null,2)], { type: 'application/json' }));
  const a = document.createElement('a'); a.href=url; a.download=name; a.click(); setTimeout(()=>URL.revokeObjectURL(url),1000);
}
export default function DerivativesPage() {
  const navigate = useNavigate();
  async function track(index:number) { if(!report)return;setBusy(true);setError('');try{const trade=await api.paperTrack(report.id,index);navigate(`/paper-trades?id=${trade.id}`);}catch(e){setError(e instanceof Error?e.message:'Falha ao acompanhar plano.');}finally{setBusy(false);} }
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [capital, setCapital] = useState(10000); const [risk, setRisk] = useState(1); const [totalRisk, setTotalRisk] = useState(3);
  const [existingRisk, setExistingRisk] = useState(0); const [fee, setFee] = useState(.05);
  const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [report, setReport] = useState<Report | null>(null);
  const [history, setHistory] = useState<{id: string; created_at: string}[]>([]);
  const [record, setRecord] = useState<unknown>(null);
  useEffect(() => { let active=true; api.derivativeHistory().then(rows=>{if(active)setHistory(rows);}).catch(e=>{if(active)setError(e.message);});return()=>{active=false;}; }, []);
  async function importFile(file: File | undefined) {
    if (!file) return; setError(''); setReport(null); setSnapshot(null);
    try {
      if(file.size>2_000_000) throw new Error('Arquivo deve ter até 2 MB.');
      const data = JSON.parse(await file.text());
      if(!Array.isArray(data.theses)||typeof data.as_of!=='string'||typeof data.source!=='string'||!['synthetic','user_supplied'].includes(data.provenance)) throw new Error('Use o formato do modelo de importação.');
      setSnapshot(data);
    } catch(e) { setError(e instanceof Error?e.message:'Arquivo inválido.'); }
  }
  async function evaluate() {
    if(!snapshot)return;setBusy(true);setError('');setReport(null);
    try {
      const result=await api.derivativePlan({source:snapshot.source,provenance:snapshot.provenance,as_of:snapshot.as_of,theses:snapshot.theses,
        capital,risk_per_trade_pct:risk,total_risk_pct:totalRisk,existing_risk_brl:existingRisk,fee_per_contract_side:fee}) as Report;
      setReport(result);setRecord(await api.derivativeRecord(result.id));setHistory(await api.derivativeHistory());
    } catch(e){setError(e instanceof Error?e.message:'Falha ao montar plano.');}finally{setBusy(false);}
  }
  async function openRecord(id: string) { setBusy(true);setError('');setReport(null);try{const saved=await api.derivativeRecord(id);setRecord(saved);setReport(saved.result as Report);}catch(e){setError(e instanceof Error?e.message:'Falha ao abrir plano.');}finally{setBusy(false);} }
  return <Stack spacing={3} sx={{ maxWidth: 1200, mx: 'auto' }}>
    <Box><Chip label="Mesa de derivativos · planos condicionais" size="small" /><Typography variant="h4" component="h1" sx={{ mt: 2 }}>Uma operação completa, com risco definido.</Typography><Typography color="text.secondary">Compare ativos e contratos. Defina o que comprar ou vender, quando agir e quanto capital comprometer.</Typography></Box>
    <Alert severity="info">Conectores de consulta disponíveis em Fontes de mercado. Para planos, importe cotações e teses verificadas ou explore a demonstração. O ATOM seleciona estruturas entre os dados informados; alvos e duração ainda são premissas da tese. Não há execução automática.</Alert>
    <Button component={Link} to="/sources">Consultar fontes de mercado</Button>
    {error&&<Alert severity="error">{error}</Alert>}
    <Card><CardContent><Stack spacing={2}>
      <Typography variant="h6">1. Cotações e teses dos ativos</Typography>
      <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap"><Button variant="outlined" disabled={busy} onClick={()=>{setSnapshot(demo());setReport(null);setError('');}}>Carregar demonstração fictícia</Button><Button component="label" disabled={busy}>Importar snapshot JSON<input type="file" accept="application/json,.json" hidden onChange={e=>{void importFile(e.target.files?.[0]);e.target.value='';}} /></Button><Button onClick={()=>download(demo(),'atom-modelo-cotacoes.json')}>Baixar modelo de importação</Button></Stack>
      <Typography variant="body2" color="text.secondary">O arquivo inclui cada tese (direção, entrada, invalidação, alvo e prazo), calendário conferido e contratos com vencimento, exercício, bid/ask, quantidades, multiplicador e lote. Não substitua a hora original por uma hora recente em cotações antigas.</Typography>
      {snapshot&&<Alert severity={snapshot.provenance==='synthetic'?'warning':'info'}>{snapshot.source} · {snapshot.theses.length} ativo(s) · {new Date(snapshot.as_of).toLocaleString('pt-BR')}</Alert>}
      <Typography variant="h6">2. Orçamento de risco</Typography>
      <Box sx={{ display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(180px,1fr))',gap:2 }}>{[
        {label:'Capital disponível (R$)',value:capital,set:setCapital,min:1,max:100000000,step:100},
        {label:'Risco por operação (%)',value:risk,set:setRisk,min:.1,max:5,step:.1},
        {label:'Risco agregado máximo (%)',value:totalRisk,set:setTotalRisk,min:.1,max:10,step:.1},
        {label:'Risco já comprometido (R$)',value:existingRisk,set:setExistingRisk,min:0,max:100000000,step:1},
        {label:'Taxa por contrato por lado (R$)',value:fee,set:setFee,min:0,max:10000,step:.01},
      ].map(f=><TextField key={f.label} label={f.label} type="number" value={f.value} disabled={busy} inputProps={{min:f.min,max:f.max,step:f.step}} onChange={e=>{f.set(+e.target.value);setReport(null);}} />)}</Box>
      <Typography variant="body2">Regras iniciais: snapshot com até 15 minutos, spread de até 15%, saída pelo prazo da tese pelo menos 7 dias antes do vencimento, ganho no cenário-alvo ≥ risco. Saída por ganho líquido de 50% do prêmio ou perda de 40%, ou por invalidação/alvo/prazo — o que ocorrer primeiro. São parâmetros de pesquisa, não regras calibradas.</Typography>
      <Button variant="contained" disabled={busy||!snapshot} onClick={evaluate}>{busy?'Processando…':'Comparar e montar planos'}</Button>
    </Stack></CardContent></Card>
    {report&&<>
      <Alert severity="warning">{report.status==='no_trade'?'Não operar com estas condições':report.status==='simulation'?'SIMULAÇÃO — contratos fictícios':'Planos condicionais — exigem revisão dos dados e da tese'} · Registro {report.id}</Alert>
      <Typography variant="body2">{report.ranking_method}</Typography>
      {report.plans.map((p,i)=><Card key={p.ticker}><CardContent><Stack spacing={2}>
        <Typography variant="h5">{i+1}. {p.ticker} · {strategyLabels[p.strategy]}</Typography>
        <Chip sx={{alignSelf:'flex-start'}} label={p.direction==='long_bias'?'Tese de alta · long direcional':'Tese de baixa · short direcional via opções'} />
        <Typography>{p.rationale}</Typography>
        <Box sx={{overflowX:'auto'}}><Table size="small"><TableHead><TableRow>{['Perna','Contrato','Tipo','Strike','Preço de referência','Quantidade','Exercício'].map(h=><TableCell key={h}>{h}</TableCell>)}</TableRow></TableHead><TableBody>{p.legs.map(l=><TableRow key={l.symbol}><TableCell>{l.side==='buy'?'Comprar':'Vender'}</TableCell><TableCell>{l.symbol}</TableCell><TableCell>{l.kind.toUpperCase()}</TableCell><TableCell>{money(l.strike)}</TableCell><TableCell>{money(l.limit_reference)}</TableCell><TableCell>{l.quantity}</TableCell><TableCell>{l.exercise}</TableCell></TableRow>)}</TableBody></Table></Box>
        <Button variant="outlined" disabled={busy} onClick={()=>track(i)}>Acompanhar como operação simulada</Button>
        <Typography><strong>Entrada:</strong> ação {p.entry.comparison} {money(p.entry.underlying_trigger)}; débito líquido limite de {money(p.entry.max_net_debit_per_unit)} por unidade de cotação. {p.entry.instruction}</Typography>
        <Typography><strong>Prazo:</strong> até {p.holding_days} dias corridos, encerrar até {p.close_by}; opções vencem em {p.expiry}. {p.calendar_basis}.</Typography>
        <Typography><strong>Saída:</strong> invalidação na ação em {money(p.exit.underlying_invalidation)}, alvo em {money(p.exit.underlying_target)}, ganho líquido de {money(p.exit.take_profit_net_brl)} ou perda de {money(p.exit.stop_loss_net_brl)}. {p.exit.instruction}</Typography>
        <Typography><strong>Capital:</strong> prêmio {money(p.premium_outlay_brl)} + reserva de taxas {money(p.fees_reserved_brl)}. Perda máxima modelada {money(p.modeled_max_loss_brl)}.</Typography>
        <Typography><strong>No vencimento:</strong> equilíbrio em {money(p.breakeven_at_expiry)}; ganho máximo modelado {p.modeled_max_profit_brl===null?'sem teto teórico':money(p.modeled_max_profit_brl)}. Ganho no cenário-alvo / risco: {p.target_scenario_reward_risk.toFixed(2)}×.</Typography>
        <Typography variant="caption">Cotações devem ser renovadas após {new Date(p.entry.quote_valid_until).toLocaleString('pt-BR')}. O registro histórico não é uma indicação vigente de entrada.</Typography>
      </Stack></CardContent></Card>)}
      {report.rejected.map((r,i)=><Alert severity="info" key={i}>{r.ticker}: {r.reason}</Alert>)}
      <Card><CardContent><Typography variant="h6">Premissas e limites</Typography>{report.limitations.map(l=><Typography variant="body2" sx={{mt:1}} key={l}>{l}</Typography>)}</CardContent></Card>
      <Button onClick={()=>download(record,`atom-plano-${report.id}.json`)}>Exportar plano e dados originais</Button>
    </>}
    <Typography variant="h6">Últimos planos salvos</Typography>
    {!history.length&&<Typography color="text.secondary">Seu primeiro plano aparecerá aqui, mesmo se a decisão for não operar.</Typography>}
    {history.map(h=><Button key={h.id} disabled={busy} sx={{justifyContent:'flex-start'}} onClick={()=>openRecord(h.id)}>{new Date(h.created_at).toLocaleString('pt-BR')} · {h.id.slice(0,8)}</Button>)}
  </Stack>;
}
