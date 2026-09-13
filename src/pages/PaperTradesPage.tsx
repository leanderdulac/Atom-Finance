import {useEffect,useRef,useState} from 'react';
import {Link,useSearchParams} from 'react-router-dom';
import {Alert,Box,Button,Card,CardContent,Chip,Stack,Table,TableBody,TableCell,TableHead,TableRow,TextField,Typography} from '@mui/material';
import PaperSourceCheck from '../components/PaperSourceCheck';
import {api} from '../services/api';
import type {PaperRecord,PaperSummary} from '../types/paperTrading';

const labels:Record<string,string>={watching:'Aguardando entrada',open:'Aberta (simulação)',closed:'Encerrada (simulação)',cancelled:'Cancelada',mark:'Atualização',close:'Saída simulada',cancel:'Cancelamento'};
const strategies:Record<string,string>={bull_call_spread:'Trava de alta com calls',bear_put_spread:'Trava de baixa com puts',long_call:'Compra de call',long_put:'Compra de put'};
const money=(n:number)=>n.toLocaleString('pt-BR',{style:'currency',currency:'BRL'});
type QuoteForm={symbol:string;bid:string;ask:string;bid_size:string;ask_size:string};

export default function PaperTradesPage(){
  const [search,setSearch]=useSearchParams();const selected=search.get('id');
  const [rows,setRows]=useState<PaperSummary[]>([]);const [record,setRecord]=useState<PaperRecord|null>(null);
  const [error,setError]=useState('');const [busy,setBusy]=useState(false);const [loading,setLoading]=useState(false);
  const [source,setSource]=useState('');const [note,setNote]=useState('');const [asOf,setAsOf]=useState('');const [spot,setSpot]=useState('');
  const [quotes,setQuotes]=useState<QuoteForm[]>([]);
  const retry=useRef<{key:string;id:string}|null>(null);
  useEffect(()=>{let active=true;api.paperHistory().then(value=>{if(active)setRows(value);}).catch(e=>{if(active)setError(e.message);});return()=>{active=false;};},[]);
  useEffect(()=>{let active=true;setRecord(null);setError('');setLoading(Boolean(selected));
    if(selected)api.paperRecord(selected).then(value=>{if(!active)return;setRecord(value);setSource('');setNote('');setAsOf('');setSpot('');setQuotes(value.plan.legs.map(l=>({symbol:l.symbol,bid:'',ask:'',bid_size:'',ask_size:''})));retry.current=null;}).catch(e=>{if(active)setError(e.message);}).finally(()=>{if(active)setLoading(false);});
    return()=>{active=false;};},[selected]);
  function demo(){if(!record||record.context.provenance!=='synthetic')return;
    setSource('Exemplo fictício gerado para testar o acompanhamento');setNote('Observação sintética, sem consulta a mercado ou execução de ordens.');setAsOf(new Date().toISOString());setSpot(String(record.plan.entry.underlying_trigger));
    setQuotes(record.plan.legs.map(l=>({symbol:l.symbol,bid:String(l.side==='buy'?Math.max(0,l.limit_reference-.05):l.limit_reference),ask:String(l.side==='buy'?l.limit_reference:l.limit_reference+.05),bid_size:String(l.quantity),ask_size:String(l.quantity)})));
  }
  async function submit(action:'open'|'mark'|'close'|'cancel'){
    if(!record)return;setBusy(true);setError('');
    try{
      if(note.trim().length<10)throw new Error('Descreva o motivo com pelo menos 10 caracteres.');
      if(action!=='cancel'&&(!source||!asOf||!spot||quotes.some(q=>[q.bid,q.ask,q.bid_size,q.ask_size].some(v=>v.trim()===''))))throw new Error('Informe a fonte, o horário com fuso, o preço da ação e todas as cotações.');
      const payload={action,source:action==='cancel'?'Cancelamento manual':source,note,as_of:action==='cancel'?new Date().toISOString():asOf,
        underlying:action==='cancel'?record.plan.entry.underlying_trigger:Number(spot),quotes:action==='cancel'?[]:quotes.map(q=>({...q,bid:Number(q.bid),ask:Number(q.ask),bid_size:Number(q.bid_size),ask_size:Number(q.ask_size)}))};
      const key=JSON.stringify(payload);if(retry.current?.key!==key)retry.current={key,id:crypto.randomUUID()};
      const updated=await api.paperEvent(record.id,{...payload,request_id:retry.current.id});
      setRecord(updated);retry.current=null;setRows(previous=>previous.map(row=>row.id===updated.id?updated:row));
    }catch(e){setError(e instanceof Error?e.message:'Falha ao registrar evento.');}finally{setBusy(false);}
  }
  function download(){if(!record)return;const url=URL.createObjectURL(new Blob([JSON.stringify(record,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=`atom-simulacao-${record.id}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  return <Stack spacing={3} sx={{maxWidth:1150,mx:'auto'}}>
    <Box><Chip label="Acompanhamento manual · sem ordens reais"/><Typography variant="h4" component="h1" sx={{mt:2}}>Operações simuladas</Typography><Typography color="text.secondary">Registre o que aconteceu depois do plano: entrada, evolução e saída com custos.</Typography></Box>
    <Alert severity="info">Compra pelo ask e venda pelo bid, com as taxas previstas no plano. Os resultados são simulações baseadas nos dados informados; não comprovam execução nem desempenho fora da amostra. A atualização e o encerramento são manuais.</Alert>
    {error&&<Alert severity="error">{error}</Alert>}
    <Button component={Link} to="/derivatives">Criar plano na mesa de derivativos</Button>
    {!rows.length&&<Typography color="text.secondary">Na mesa, monte um plano e escolha “Acompanhar como operação simulada”. Planos sem operação elegível não geram posição.</Typography>}
    <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">{rows.map(row=><Button key={row.id} disabled={busy} variant={selected===row.id?'contained':'outlined'} onClick={()=>setSearch({id:row.id})}>{row.plan.ticker} · {labels[row.status]} · {row.id.slice(0,6)}</Button>)}</Stack>
    {loading&&<Typography role="status">Carregando operação…</Typography>}
    {record&&<>
      <Card><CardContent><Stack spacing={1}>
        <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap"><Chip label={labels[record.status]}/><Chip color={record.context.provenance==='synthetic'?'warning':'default'} label={record.context.provenance==='synthetic'?'Origem fictícia':'Dados declarados pelo usuário'}/></Stack>
        <Typography variant="h6">{record.plan.ticker} · {strategies[record.plan.strategy]||record.plan.strategy}</Typography>
        <Typography>Gatilho: {money(record.plan.entry.underlying_trigger)} · Encerrar até {record.plan.close_by} · Vencimento {record.plan.expiry}</Typography>
        {record.status==='watching'&&<Typography color="text.secondary">Plano válido para entrada até {new Date(record.plan.entry.quote_valid_until).toLocaleString('pt-BR')}. Se expirar, gere um novo plano.</Typography>}
        <Typography>Taxa estimada por contrato e lado: {money(record.context.fee_per_contract_side)}. Quantidades e estrutura permanecem as do plano original.</Typography>
        {record.status==='open'&&new Date().toISOString().slice(0,10)>=record.plan.close_by&&<Alert severity="warning">A data-limite foi alcançada. O sistema não encerra posições automaticamente.</Alert>}
        {record.events.length>0&&record.events[record.events.length - 1]?.result.net_pnl_brl!==undefined&&<Typography variant="h5">{record.status==='closed'?'Resultado líquido simulado':'Resultado estimado se encerrasse'}: {money(record.events[record.events.length - 1]!.result.net_pnl_brl!)}</Typography>}
        <Button onClick={download}>Exportar plano e histórico completo</Button>
      </Stack></CardContent></Card>
      <PaperSourceCheck key={`${record.id}-${record.status}`} tradeId={record.id} ticker={record.plan.ticker}/>
      {['watching','open'].includes(record.status)&&<Card><CardContent><Stack spacing={2}>
        <Typography variant="h6">Nova observação</Typography>
        {record.context.provenance==='synthetic'&&<Button onClick={demo} disabled={busy}>Preencher dados fictícios</Button>}
        <TextField label="Fonte das cotações" value={source} onChange={e=>setSource(e.target.value)} disabled={busy}/>
        <TextField label="Horário original com fuso (ISO 8601)" placeholder="2026-09-10T14:30:00-03:00" value={asOf} onChange={e=>setAsOf(e.target.value)} helperText="Não substitua o horário de uma cotação antiga pela hora atual." disabled={busy}/>
        <TextField label="Preço observado da ação (R$)" type="number" value={spot} onChange={e=>setSpot(e.target.value)} disabled={busy}/>
        {quotes.map((q,index)=><Box key={q.symbol}><Typography sx={{mb:1}}>{q.symbol} · {record.plan.legs[index].side==='buy'?'Perna comprada':'Perna vendida'} · {record.plan.legs[index].quantity} contratos</Typography><Box sx={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(150px,1fr))',gap:1}}>{(['bid','ask','bid_size','ask_size'] as const).map(field=><TextField key={field} label={{bid:'Bid (R$)',ask:'Ask (R$)',bid_size:'Quantidade no bid',ask_size:'Quantidade no ask'}[field]} type="number" value={q[field]} disabled={busy} onChange={e=>setQuotes(prev=>prev.map((item,i)=>i===index?{...item,[field]:e.target.value}:item))}/>)}</Box></Box>)}
        <TextField label="Motivo e observações" multiline minRows={2} value={note} onChange={e=>setNote(e.target.value)} disabled={busy}/>
        <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">{record.status==='watching'?<><Button variant="contained" disabled={busy} onClick={()=>submit('open')}>Registrar entrada simulada</Button><Button disabled={busy} onClick={()=>submit('cancel')}>Cancelar acompanhamento</Button></>:<><Button variant="outlined" disabled={busy} onClick={()=>submit('mark')}>Atualizar resultado simulado</Button><Button variant="contained" disabled={busy} onClick={()=>submit('close')}>Encerrar simulação</Button></>}</Stack>
      </Stack></CardContent></Card>}
      <Typography variant="h6">Histórico imutável</Typography>
      {!record.events.length&&<Typography>Nenhuma entrada registrada. Acompanhar um plano não abre uma posição.</Typography>}
      <Box sx={{overflowX:'auto'}}><Table size="small"><TableHead><TableRow>{['Registro','Evento','Fonte / observação','Resultado líquido'].map(h=><TableCell key={h}>{h}</TableCell>)}</TableRow></TableHead><TableBody>{record.events.map(event=><TableRow key={event.id}><TableCell>{new Date(event.created_at).toLocaleString('pt-BR')}</TableCell><TableCell>{event.kind==='open'?'Entrada simulada':labels[event.kind]}</TableCell><TableCell>{event.payload.source}<br/>{event.payload.note}{event.result.alerts.map(alert=><Alert severity="warning" key={alert}>{alert}</Alert>)}</TableCell><TableCell>{event.result.net_pnl_brl===undefined?'—':money(event.result.net_pnl_brl)}</TableCell></TableRow>)}</TableBody></Table></Box>
    </>}
  </Stack>;
}
