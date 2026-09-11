import { useEffect, useState } from 'react';
import {useSearchParams} from 'react-router-dom';
import { Alert, Box, Button, Card, CardContent, MenuItem, Stack, Table, TableBody, TableCell, TableHead, TableRow, TextField, Typography } from '@mui/material';
import { api } from '../services/api';

type Contract = {symbol:string;kind:string;strike:number|null;expiry:string;exercise:string;bid:number|null;ask:number|null;close:number|null;bid_size:number|null;ask_size:number|null;observed_at:string|null};
type Chain = {snapshot_id:string;provider:string;data_mode:string;fetched_at:string;blockers:string[];contracts:Contract[]};
type Catalog = {dataset:string;note:string;resources:{name:string;url:string;format:string}[]};
export default function SourcesPage(){
  const [search]=useSearchParams();
  const [provider,setProvider]=useState('brapi');const [ticker,setTicker]=useState(()=>/^[A-Z]{4}[0-9]{1,2}$/.test(search.get('ticker')||'')?search.get('ticker')!:'PETR4');const [expiry,setExpiry]=useState('');const [expirations,setExpirations]=useState<string[]>([]);
  const [status,setStatus]=useState<Record<string,{configured?:boolean;access?:string;data_mode?:string}>|null>(null);
  const [chain,setChain]=useState<Chain|null>(null);const [selic,setSelic]=useState<{value:number;observed_date:string;annualized_252_pct:number;note:string}|null>(null);
  const [catalog,setCatalog]=useState<Catalog|null>(null);const [busy,setBusy]=useState(false);const [error,setError]=useState('');
  useEffect(()=>{let active=true;api.sourceStatus().then(s=>{if(active)setStatus(s);}).catch(e=>{if(active)setError(e.message);});return()=>{active=false;};},[]);
  async function run(action:()=>Promise<void>){setBusy(true);setError('');try{await action();}catch(e){setError(e instanceof Error?e.message:'Falha na fonte.');}finally{setBusy(false);}}
  function clear(){setChain(null);setExpiry('');setExpirations([]);}
  async function download(){if(!chain)return;await run(async()=>{const data=await api.sourceSnapshot(chain.snapshot_id);const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=`atom-fonte-${chain.snapshot_id}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});}
  const fmt=(n:number|null)=>n===null?'Não informado':n.toLocaleString('pt-BR',{maximumFractionDigits:4});
  return <Stack spacing={3} sx={{maxWidth:1250,mx:'auto'}}>
    <Box><Typography variant="h4" component="h1">Fontes de mercado</Typography><Typography color="text.secondary">Consulte os dados originais e verifique de quando são, antes de formular uma operação.</Typography></Box>
    {error&&<Alert severity="error">{error}</Alert>}
    <Alert severity="info">Dados de fechamento apoiam pesquisa. Não representam ofertas executáveis agora. Os conectores não preenchem quantidades ausentes nem presumem multiplicadores.</Alert>
    <Card><CardContent><Stack spacing={2}>
      <Typography variant="h6">Cadeia de opções B3</Typography>
      <TextField select label="Fonte" value={provider} disabled={busy} onChange={e=>{setProvider(e.target.value);clear();}}><MenuItem value="brapi">brapi · fechamento · PETR4 disponível sem token</MenuItem><MenuItem value="oplab">OpLab · requer token e usuário autorizado</MenuItem><MenuItem value="cedro">Cedro · requer sessão e homologação</MenuItem></TextField>
      {status&&<Typography variant="body2">{provider==='brapi'?status.brapi.access:status[provider]?.configured?'Credencial configurada para sua conta; cobertura e latência ainda precisam de homologação.':'Conector preparado; falta configurar acesso para sua conta no servidor.'}</Typography>}
      <TextField label="Ação B3" value={ticker} disabled={busy} onChange={e=>{setTicker(e.target.value.toUpperCase());clear();}} inputProps={{maxLength:6}} />
      {provider==='brapi'&&<><Button variant="outlined" disabled={busy||!/^\w{4}\d{1,2}$/.test(ticker)} onClick={()=>run(async()=>{const data=await api.sourceExpirations(ticker);setExpirations(data.expirations);setExpiry(data.expirations[0]||'');setChain(null);})}>Buscar vencimentos</Button>
      {expirations.length>0&&<TextField select label="Vencimento" value={expiry} disabled={busy} onChange={e=>{setExpiry(e.target.value);setChain(null);}}>{expirations.map(d=><MenuItem key={d} value={d}>{d}</MenuItem>)}</TextField>}</>}
      <Button variant="contained" disabled={busy||!ticker||(provider==='brapi'&&!expiry)} onClick={()=>run(async()=>{setChain(null);setChain(await api.sourceChain(provider,ticker,expiry) as Chain);})}>{busy?'Consultando…':'Consultar cadeia'}</Button>
    </Stack></CardContent></Card>
    {chain&&<Card><CardContent><Stack spacing={2}>
      <Typography variant="h6">{chain.provider} · {chain.data_mode==='eod'?'Fechamento (EOD)':'Latência não verificada'} · {chain.contracts.length} contratos</Typography>
      <Typography variant="body2">Recebido em {new Date(chain.fetched_at).toLocaleString('pt-BR')}. A data da cotação aparece em cada linha; não é a hora do recebimento.</Typography>
      {chain.blockers.map(b=><Alert severity="warning" key={b}>{b}</Alert>)}
      <Box sx={{maxHeight:480,overflow:'auto'}}><Table size="small" stickyHeader><TableHead><TableRow>{['Contrato','Tipo','Strike','Vencimento','Bid','Ask','Último/fechamento','Qtd. bid','Qtd. ask','Data da cotação'].map(h=><TableCell key={h}>{h}</TableCell>)}</TableRow></TableHead><TableBody>{chain.contracts.map((q,i)=><TableRow key={`${q.symbol}-${i}`}><TableCell>{q.symbol}</TableCell><TableCell>{q.kind}</TableCell><TableCell>{fmt(q.strike)}</TableCell><TableCell>{q.expiry}</TableCell><TableCell>{fmt(q.bid)}</TableCell><TableCell>{fmt(q.ask)}</TableCell><TableCell>{fmt(q.close)}</TableCell><TableCell>{fmt(q.bid_size)}</TableCell><TableCell>{fmt(q.ask_size)}</TableCell><TableCell>{q.observed_at?new Date(q.observed_at).toLocaleString('pt-BR'):'Não informada'}</TableCell></TableRow>)}</TableBody></Table></Box>
      <Button disabled={busy} onClick={download}>Exportar snapshot original e dados normalizados</Button>
      <Typography variant="caption">Snapshot {chain.snapshot_id}. Exportação de fonte para pesquisa; não é o arquivo de entrada do planejador.</Typography>
    </Stack></CardContent></Card>}
    <Card><CardContent><Typography variant="h6">Banco Central · Selic efetiva</Typography><Button disabled={busy} onClick={()=>run(async()=>{setSelic(null);setSelic(await api.sourceSelic());})}>Consultar última observação oficial</Button>{selic&&<Stack spacing={1}><Typography>{selic.observed_date} · {selic.value}% ao dia útil</Typography><Typography>Anualização derivada em 252 dias: {selic.annualized_252_pct}%</Typography><Typography color="text.secondary">{selic.note}</Typography></Stack>}</CardContent></Card>
    <Card><CardContent><Typography variant="h6">CVM · arquivos oficiais de demonstrações</Typography><Stack direction="row" spacing={1}>{['itr','dfp'].map(kind=><Button key={kind} disabled={busy} onClick={()=>run(async()=>{setCatalog(null);setCatalog(await api.sourceCvm(kind));})}>Consultar {kind.toUpperCase()}</Button>)}</Stack>{catalog&&<Stack spacing={1}><Typography>{catalog.note}</Typography>{catalog.resources.map(r=><Button key={r.url} component="a" href={r.url} target="_blank" rel="noopener noreferrer" sx={{justifyContent:'flex-start'}}>{r.name} · {r.format}</Button>)}</Stack>}</CardContent></Card>
  </Stack>;
}
