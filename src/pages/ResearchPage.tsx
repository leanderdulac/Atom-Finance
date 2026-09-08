import { useEffect, useState } from 'react';
import { Alert, Box, Button, Chip, MenuItem, Paper, Stack, TextField, Typography } from '@mui/material';
import { api, type ResearchPaper, type ResearchSummary } from '../services/api';

export default function ResearchPage() {
  const [kind, setKind] = useState<'text' | 'arxiv'>('text');
  const [content, setContent] = useState('');
  const [history, setHistory] = useState<ResearchSummary[]>([]);
  const [paper, setPaper] = useState<ResearchPaper | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    api.researchHistory().then(items => { if (active) setHistory(items); })
      .catch((e: Error) => { if (active) setError(e.message); });
    return () => { active = false; };
  }, []);

  async function extract(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true); setError('');
    try {
      const result = await api.researchExtract(kind, content.trim());
      setPaper(result);
      setHistory(await api.researchHistory());
    } catch (e) { setError(e instanceof Error ? e.message : 'Falha na extração.'); }
    finally { setBusy(false); }
  }

  async function openPaper(id: string) {
    setBusy(true); setError('');
    try { setPaper(await api.researchPaper(id)); }
    catch (e) { setError(e instanceof Error ? e.message : 'Falha ao abrir artigo.'); }
    finally { setBusy(false); }
  }

  return <Stack spacing={3} sx={{ maxWidth: 1100, mx: 'auto' }}>
    <Box><Typography variant="h4" component="h1">Pesquisa QuantMind</Typography>
      <Typography color="text.secondary">Transforme artigos em resumos, metodologia e limitações com citações da fonte.</Typography></Box>
    {error && <Alert severity="error">{error}</Alert>}
    <Paper component="form" onSubmit={extract} sx={{ p: 3 }}>
      <Stack spacing={2}>
        <TextField select label="Fonte" value={kind} disabled={busy} onChange={e => setKind(e.target.value as 'text' | 'arxiv')}>
          <MenuItem value="text">Texto do artigo</MenuItem><MenuItem value="arxiv">Identificador arXiv</MenuItem>
        </TextField>
        <TextField label={kind === 'text' ? 'Cole o texto do artigo' : 'Identificador arXiv (ex.: 2401.12345)'}
          value={content} onChange={e => setContent(e.target.value)} multiline={kind === 'text'} minRows={kind === 'text' ? 6 : undefined}
          required disabled={busy} inputProps={{ maxLength: 80000 }} />
        <Typography variant="body2" color="text.secondary">A extração usa IA e pode levar até três minutos. Confira as conclusões nas fontes. O resultado fica salvo no seu histórico.</Typography>
        <Button type="submit" variant="contained" disabled={busy || !content.trim()}>{busy ? 'Processando…' : 'Extrair pesquisa'}</Button>
      </Stack>
    </Paper>
    {paper && <Stack spacing={2}>
      <Typography variant="h5">{paper.nodes[paper.root_node_id]?.title || 'Artigo'}</Typography>
      <Typography color="text.secondary">{paper.authors.join(', ')} · Data da informação: {new Date(paper.as_of).toLocaleDateString('pt-BR')}</Typography>
      <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">{paper.asset_classes.map(asset => <Chip key={asset} label={asset} />)}</Stack>
      {Object.values(paper.nodes).map(node => <Paper key={node.node_id} sx={{ p: 3 }}>
        <Typography variant="h6">{node.title}</Typography><Typography sx={{ whiteSpace: 'pre-wrap', mt: 1 }}>{node.summary}</Typography>
        {node.content && <Box component="details" sx={{ mt: 2 }}><summary>Texto da seção</summary><Typography sx={{ whiteSpace: 'pre-wrap' }}>{node.content}</Typography></Box>}
        {node.citations.map((citation, index) => <Typography key={index} variant="body2" color="text.secondary" sx={{ mt: 1 }}>Fonte: {citation.source_id}{citation.page ? `, p. ${citation.page}` : ''}{citation.quote ? ` — “${citation.quote}”` : ''}</Typography>)}
      </Paper>)}
    </Stack>}
    <Box><Typography variant="h5">Meu histórico</Typography>
      {!history.length && <Typography color="text.secondary">Nenhum artigo salvo ainda.</Typography>}
      {history.map(item => <Button key={item.id} onClick={() => openPaper(item.id)} disabled={busy} sx={{ display: 'block', textAlign: 'left', mt: 1 }}>{item.title} · {new Date(item.created_at).toLocaleDateString('pt-BR')}</Button>)}
    </Box>
  </Stack>;
}
