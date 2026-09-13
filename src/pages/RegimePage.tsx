import React, { useState } from 'react';
import {
  Alert, Box, Button, Card, CardContent, Chip, Stack, Table, TableBody,
  TableCell, TableHead, TableRow, Typography,
} from '@mui/material';
import { api } from '../services/api';

type DemoKind = 'calm' | 'trending' | 'crisis';

const STATUS_COLOR: Record<string, 'success' | 'warning' | 'error' | 'default'> = {
  live: 'success',
  standby: 'warning',
  flatten: 'error',
};

export default function RegimePage() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<any>(null);
  const [kind, setKind] = useState<DemoKind | 'live'>('crisis');

  const run = async (demo: DemoKind) => {
    setKind(demo);
    setLoading(true); setError(''); setResult(null);
    try { setResult(await api.deskRegime({ demo })); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setLoading(false); }
  };

  const live = async (flatten: boolean) => {
    setKind('live');
    setLoading(true); setError(''); setResult(null);
    try { setResult(await api.deskRegimeLive(flatten)); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setLoading(false); }
  };

  const ks = result?.kill_switch;
  const armed = Boolean(ks?.armed);

  return (
    <Box sx={{ maxWidth: 1040, mx: 'auto' }}>
      <Typography variant="h4" sx={{ fontWeight: 800, mb: 1 }}>Regimes</Typography>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        Sinais públicos (Yahoo VIX/ações/UST + FRED HY OAS), percentil de 90 dias,
        P(regime) via softmax, holdout walk-forward, job de 4 h e flatten do livro
        <em> simulado</em> no último mark. Broker continua HTTP 410.
        Catálogo: <code>docs/strategy/signals.md</code>.
      </Typography>
      <Stack direction="row" spacing={1} sx={{ mb: 2, flexWrap: 'wrap' }}>
        <Button variant={kind === 'calm' ? 'contained' : 'outlined'} disabled={loading} onClick={() => run('calm')}>
          Demo calmo
        </Button>
        <Button variant={kind === 'trending' ? 'contained' : 'outlined'} disabled={loading} onClick={() => run('trending')}>
          Demo tendência
        </Button>
        <Button color="error" variant={kind === 'crisis' ? 'contained' : 'outlined'} disabled={loading} onClick={() => run('crisis')}>
          Demo crise
        </Button>
        <Button variant="outlined" disabled={loading} onClick={() => live(false)}>
          Livros públicos
        </Button>
        <Button color="error" variant="outlined" disabled={loading} onClick={() => live(true)}>
          Live + flatten paper
        </Button>
      </Stack>
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {result && (
        <Stack spacing={2}>
          <Alert severity={armed ? 'error' : 'info'}>
            Regime atual: <strong>{result.regime}</strong>
            {armed
              ? ' — kill switch ARMED (research_risk_off). Ordens no broker: 0. Paper flatten no último mark se você pediu.'
              : ' — kill switch em watch. Nada é executado no broker.'}
          </Alert>
          {result.math && <Alert severity="info">{result.math}</Alert>}
          {result.probs && (
            <Alert severity="info">
              P(regime): {Object.entries(result.probs).map(([k, v]) => `${k} ${(Number(v) * 100).toFixed(0)}%`).join(' · ')}
              {result.holdout?.n
                ? ` — holdout n=${result.holdout.n} acc=${result.holdout.accuracy} crisis-recall=${result.holdout.crisis_recall ?? 'n/a'}`
                : ''}
            </Alert>
          )}
          {result.what_broke && (
            <Alert severity="warning">
              <strong>What broke</strong>
              <ul style={{ margin: '8px 0 0', paddingLeft: 18 }}>
                {result.what_broke.map((w: string) => <li key={w}>{w}</li>)}
              </ul>
            </Alert>
          )}
          <Card>
            <CardContent>
              <Typography variant="h6" sx={{ mb: 1 }}>Sinais vs janela de 90 dias</Typography>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Sinal</TableCell>
                    <TableCell align="right">Valor</TableCell>
                    <TableCell align="right">Percentil</TableCell>
                    <TableCell>Flag</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {Object.entries(result.signals || {}).map(([name, meta]: [string, any]) => (
                    <TableRow key={name}>
                      <TableCell><code>{name}</code></TableCell>
                      <TableCell align="right">{Number(meta.value).toFixed(4)}</TableCell>
                      <TableCell align="right">{Number(meta.percentile).toFixed(0)}</TableCell>
                      <TableCell>
                        {meta.flag
                          ? <Chip size="small" color={meta.flag === 'high' ? 'error' : 'info'} label={meta.flag} />
                          : '—'}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
          <Card>
            <CardContent>
              <Typography variant="h6" sx={{ mb: 1 }}>Mapeamento (quando a estratégia pode estar live)</Typography>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Estratégia</TableCell>
                    <TableCell>Live em</TableCell>
                    <TableCell>Kill em</TableCell>
                    <TableCell>Status agora</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {(result.strategies || []).map((s: any) => (
                    <TableRow key={s.id}>
                      <TableCell>{s.name}</TableCell>
                      <TableCell>{(s.live_in || []).join(', ')}</TableCell>
                      <TableCell>{(s.kill_in || []).join(', ')}</TableCell>
                      <TableCell>
                        <Chip size="small" color={STATUS_COLOR[s.status] || 'default'} label={s.status} />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
          <Card>
            <CardContent>
              <Typography variant="h6" sx={{ mb: 1 }}>Resize (half-Kelly do regime, não ticket)</Typography>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Id</TableCell>
                    <TableCell align="right">Atual</TableCell>
                    <TableCell align="right">Alvo</TableCell>
                    <TableCell>Ação</TableCell>
                    <TableCell>Razão</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {(result.adjustments || []).map((a: any) => (
                    <TableRow key={a.id}>
                      <TableCell>{a.id}</TableCell>
                      <TableCell align="right">{a.current_weight}</TableCell>
                      <TableCell align="right">{a.target_weight}</TableCell>
                      <TableCell><Chip size="small" label={a.action} /></TableCell>
                      <TableCell>{a.reason}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
          {result.context?.['current-regime.md'] && (
            <Card>
              <CardContent>
                <Typography variant="h6" sx={{ mb: 1 }}>current-regime.md</Typography>
                <pre style={{ overflow: 'auto', fontSize: 12, maxHeight: 280, whiteSpace: 'pre-wrap' }}>
                  {result.context['current-regime.md']}
                </pre>
              </CardContent>
            </Card>
          )}
        </Stack>
      )}
    </Box>
  );
}
