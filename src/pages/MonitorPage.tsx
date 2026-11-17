import { useEffect, useState } from 'react';
import {
  Alert, Box, Button, Card, CardContent, Chip, CircularProgress, Grid,
  Stack, TextField, ToggleButton, ToggleButtonGroup, Typography,
} from '@mui/material';
import { api, type MonitorDetail, type MonitorSummary } from '../services/api';

const STATE_PT: Record<string, string> = {
  watching: 'Aguardando entrada', active: 'Ativa', stopped: 'Stop tocado',
  target_hit: 'Alvo tocado', expired: 'Vencida',
};
const pct1 = (n: number) => `${(n * 100).toFixed(1).replace('.', ',')}%`;

const num = (v: string, fallback: number) => {
  const n = Number(String(v).replace(',', '.'));
  return Number.isFinite(n) ? n : fallback;
};

export default function MonitorPage() {
  const [items, setItems] = useState<MonitorSummary[]>([]);
  const [selected, setSelected] = useState<MonitorDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState('');
  const [form, setForm] = useState({
    ticker: 'PETR4', direction: 'long', entry: '38', stop: '36', target: '41',
    horizon_days: '21', vol_pct: '30', size: '20', note: '',
  });
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  async function refreshList(): Promise<MonitorSummary[]> {
    const res = await api.monitorsList();
    setItems(res.monitors);
    return res.monitors;
  }

  useEffect(() => {
    refreshList().catch((e: unknown) =>
      setError(e instanceof Error ? e.message : 'Falha ao listar monitores.'));
  }, []);

  async function open(id: string) {
    setError('');
    try {
      setSelected(await api.monitorsGet(id));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Falha ao abrir monitor.');
    }
  }

  async function declare() {
    setBusy(true);
    setError('');
    try {
      const created = await api.monitorsDeclare({
        ticker: form.ticker.trim().toUpperCase(),
        direction: form.direction as 'long' | 'short',
        entry: num(form.entry, 0), stop: num(form.stop, 0), target: num(form.target, 0),
        horizon_days: Math.round(num(form.horizon_days, 21)),
        size: num(form.size, 1), vol_annual: num(form.vol_pct, 30) / 100,
        note: form.note.trim(),
      });
      await refreshList();
      await open(created.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Falha ao declarar monitor.');
    } finally {
      setBusy(false);
    }
  }

  async function checkNow() {
    if (!selected) return;
    setChecking(true);
    setError('');
    try {
      await api.monitorsCheck(selected.id);
      await open(selected.id);
      await refreshList();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Falha na verificação.');
    } finally {
      setChecking(false);
    }
  }

  async function remove(id: string) {
    setError('');
    try {
      await api.monitorsDelete(id);
      if (selected?.id === id) setSelected(null);
      await refreshList();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Falha ao excluir.');
    }
  }

  return (
    <Box sx={{ maxWidth: 1100, mx: 'auto' }}>
      <Typography variant="h5" gutterBottom>Monitores de tese</Typography>
      <Typography color="text.secondary" sx={{ mb: 3 }}>
        Declare a operação paper (ativo, direção, entrada, stop, alvo, horizonte).
        Cada verificação lê o oráculo e avalia a tese — toques entre verificações passam despercebidos.
      </Typography>
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Typography variant="subtitle1" fontWeight={700} gutterBottom>Declarar operação</Typography>
          <Grid container spacing={2}>
            <Grid size={{ xs: 6, md: 3 }}>
              <TextField fullWidth label="Ativo" value={form.ticker} onChange={set('ticker')} />
            </Grid>
            <Grid size={{ xs: 6, md: 3 }}>
              <ToggleButtonGroup
                exclusive fullWidth value={form.direction}
                onChange={(_, v) => v && setForm((f) => ({ ...f, direction: v }))} aria-label="Direção"
              >
                <ToggleButton value="long">Alta</ToggleButton>
                <ToggleButton value="short">Baixa</ToggleButton>
              </ToggleButtonGroup>
            </Grid>
            {[['entry', 'Entrada'], ['stop', 'Stop'], ['target', 'Alvo']].map(([k, label]) => (
              <Grid size={{ xs: 4, md: 2 }} key={k}>
                <TextField
                  fullWidth label={label} value={form[k as keyof typeof form]}
                  onChange={set(k as keyof typeof form)} inputProps={{ inputMode: 'decimal' }}
                />
              </Grid>
            ))}
            <Grid size={{ xs: 4, md: 2 }}>
              <TextField fullWidth label="Horizonte (dias)" value={form.horizon_days} onChange={set('horizon_days')} inputProps={{ inputMode: 'numeric' }} />
            </Grid>
            <Grid size={{ xs: 4, md: 2 }}>
              <TextField fullWidth label="Vol anual %" value={form.vol_pct} onChange={set('vol_pct')} inputProps={{ inputMode: 'decimal' }} />
            </Grid>
            <Grid size={{ xs: 4, md: 2 }}>
              <TextField fullWidth label="Tamanho" value={form.size} onChange={set('size')} inputProps={{ inputMode: 'decimal' }} />
            </Grid>
            <Grid size={{ xs: 12 }}>
              <TextField fullWidth label="Nota de tese (opcional)" value={form.note} onChange={set('note')} />
            </Grid>
          </Grid>
          <Button variant="contained" onClick={declare} disabled={busy} sx={{ mt: 2 }}>
            {busy ? <CircularProgress size={18} /> : 'Declarar e simular base'}
          </Button>
        </CardContent>
      </Card>

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, md: 5 }}>
          <Typography variant="subtitle1" fontWeight={700} gutterBottom>
            Meus monitores ({items.length})
          </Typography>
          <Stack spacing={1}>
            {items.map((m) => (
              <Card key={m.id} variant="outlined">
                <CardContent sx={{ py: 1.5, '&:last-child': { pb: 1.5 } }}>
                  <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                    <Typography fontWeight={700}>{m.ticker}</Typography>
                    <Chip size="small" label={m.direction === 'long' ? 'Alta' : 'Baixa'} />
                    <Chip size="small" color={m.state === 'active' ? 'success' : m.state === 'watching' ? 'default' : 'warning'} label={STATE_PT[m.state] || m.state} />
                  </Stack>
                  <Typography variant="body2" color="text.secondary">
                    {`entrada ${m.entry} · stop ${m.stop} · alvo ${m.target} · ${m.horizon_days}d`}
                    {m.last_spot != null ? ` · última ${m.last_spot}` : ''}
                  </Typography>
                  <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
                    <Button size="small" onClick={() => open(m.id)}>Abrir</Button>
                    <Button size="small" color="error" onClick={() => remove(m.id)}>Excluir</Button>
                  </Stack>
                </CardContent>
              </Card>
            ))}
            {!items.length && <Typography color="text.secondary">Nenhum monitor declarado.</Typography>}
          </Stack>
        </Grid>
        <Grid size={{ xs: 12, md: 7 }}>
          {!selected ? (
            <Typography color="text.secondary">Selecione um monitor para ver a base e o histórico.</Typography>
          ) : (
            <Card>
              <CardContent>
                <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                  <Typography variant="h6">{selected.ticker}</Typography>
                  <Chip size="small" label={STATE_PT[selected.state] || selected.state} />
                  <Box sx={{ flexGrow: 1 }} />
                  <Button
                    variant="outlined" size="small" onClick={checkNow} disabled={checking}
                  >
                    {checking ? <CircularProgress size={16} /> : 'Verificar agora'}
                  </Button>
                </Stack>
                {selected.baseline && (
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                    {`Base na declaração: P(lucro) ${pct1(selected.baseline.p_profit)} · P5 ${selected.baseline.pnl_p5} · P50 ${selected.baseline.pnl_p50} · P95 ${selected.baseline.pnl_p95}`}
                  </Typography>
                )}
                <Stack spacing={1} sx={{ mt: 2 }}>
                  {selected.checks.map((c) => (
                    <Box key={c.checked_at} sx={{ p: 1.5, border: '1px solid', borderColor: 'divider', borderRadius: 1 }}>
                      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                        <Typography variant="body2" fontWeight={700}>{c.spot}</Typography>
                        <Chip size="small" label={STATE_PT[c.state] || c.state} />
                        {!c.oracle_usable && <Chip size="small" color="warning" label="oráculo falho" />}
                        <Typography variant="caption" color="text.secondary">
                          {new Date(c.checked_at).toLocaleString('pt-BR')}
                        </Typography>
                      </Stack>
                      {c.alerts.map((a) => (
                        <Alert key={a.kind + a.text} severity={a.kind === 'state_changed' ? 'info' : 'warning'} sx={{ mt: 1 }}>
                          {a.text}
                        </Alert>
                      ))}
                    </Box>
                  ))}
                  {!selected.checks.length && (
                    <Typography color="text.secondary">Sem verificações — use “Verificar agora”.</Typography>
                  )}
                </Stack>
              </CardContent>
            </Card>
          )}
        </Grid>
      </Grid>
    </Box>
  );
}
