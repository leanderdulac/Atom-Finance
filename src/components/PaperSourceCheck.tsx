import {useEffect, useRef, useState} from 'react';
import {Link} from 'react-router-dom';
import {Alert, Button, Card, CardContent, MenuItem, Stack, TextField, Typography} from '@mui/material';
import {api} from '../services/api';
import type {SourceCheck, SourceSnapshotSummary} from '../types/paperTrading';

export default function PaperSourceCheck({tradeId,ticker}:{tradeId:string;ticker:string}) {
  const [snapshots,setSnapshots]=useState<SourceSnapshotSummary[]>([]);
  const [selected,setSelected]=useState('');
  const [report,setReport]=useState<SourceCheck|null>(null);
  const [error,setError]=useState('');
  const [loading,setLoading]=useState(true);
  const [busy,setBusy]=useState(false);
  const mounted=useRef(false);
  useEffect(()=>{
    mounted.current=true;
    let active=true;
    api.sourceSnapshots(ticker).then(rows=>{if(active){setSnapshots(rows);setSelected(rows[0]?.snapshot_id||'');}})
      .catch(e=>{if(active)setError(e.message);}).finally(()=>{if(active)setLoading(false);});
    return()=>{active=false;mounted.current=false;};
  },[ticker]);
  async function check(){
    setBusy(true);setError('');setReport(null);
    try {const result=await api.paperSourceCheck(tradeId,selected);if(mounted.current)setReport(result);}
    catch(e){if(mounted.current)setError(e instanceof Error?e.message:'Falha na conferência.');}
    finally{if(mounted.current)setBusy(false);}
  }
  function download(){
    if(!report)return;
    const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));
    const a=document.createElement('a');a.href=url;a.download=`atom-conferencia-${report.snapshot_id}.json`;a.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  return <Card><CardContent><Stack spacing={2}>
    <Typography variant="h6">Conferir dados da fonte para esta operação</Typography>
    <Typography color="text.secondary">Compare os contratos do plano com um snapshot salvo. A conferência preserva o horário original e não preenche nem registra uma observação.</Typography>
    {/^[A-Z]{4}[0-9]{1,2}$/.test(ticker)?<Button component={Link} to={`/sources?ticker=${encodeURIComponent(ticker)}`}>Consultar e salvar dados da fonte</Button>:<Typography variant="body2">Este código não corresponde ao formato de ação B3 aceito pelos conectores.</Typography>}
    {loading&&<Typography role="status">Carregando snapshots…</Typography>}
    {error&&<Alert severity="error">{error}</Alert>}
    {!loading&&!error&&!snapshots.length&&<Typography>Nenhum snapshot salvo para {ticker}. Consulte uma fonte e retorne a esta operação.</Typography>}
    {snapshots.length>0&&<>
      <TextField select label="Snapshot para conferência" value={selected} disabled={busy} onChange={e=>{setSelected(e.target.value);setReport(null);}}>
        {snapshots.map(row=><MenuItem key={row.snapshot_id} value={row.snapshot_id}>{row.provider} · recebido em {new Date(row.fetched_at).toLocaleString('pt-BR')} · {row.snapshot_id.slice(0,8)}</MenuItem>)}
      </TextField>
      <Button variant="outlined" disabled={busy||!selected} onClick={check}>{busy?'Conferindo…':'Conferir contratos e qualidade'}</Button>
    </>}
    {report&&<>
      <Alert severity="warning">Snapshot sem autorização para alimentar observações. Conferido em {new Date(report.checked_at).toLocaleString('pt-BR')}.</Alert>
      {report.blockers.map(message=><Typography key={message}>• {message}</Typography>)}
      {report.legs.map(leg=><Stack key={leg.symbol} spacing={1}>
        <Typography fontWeight={600}>{leg.symbol}</Typography>
        <Typography variant="body2">Cotação original: {leg.observed_at?new Date(leg.observed_at).toLocaleString('pt-BR'):'não informada'}.</Typography>
        {leg.issues.length?leg.issues.map(issue=><Alert severity="warning" key={issue}>{issue}</Alert>):<Alert severity="info">Estrutura e livro passaram nas verificações; os bloqueios da fonte continuam aplicáveis.</Alert>}
      </Stack>)}
      <Typography variant="caption">{report.note}</Typography>
      <Button onClick={download}>Exportar diagnóstico com referência ao snapshot</Button>
    </>}
  </Stack></CardContent></Card>;
}
