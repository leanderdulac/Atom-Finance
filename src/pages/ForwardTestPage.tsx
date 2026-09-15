import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Alert, Box, Button, Card, CardContent, Chip, Stack, Table, TableBody,
  TableCell, TableHead, TableRow, Typography,
} from '@mui/material';
import {
  CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { api } from '../services/api';

type Track = { sharpe: number; hit_rate: number; ic: number; fast?: number; slow?: number };

type Result = {
  n_prices: number;
  n_candidates: number;
  locked: Track & { same_bar_sharpe: number; n_active: number };
  mined_delayed: Track;
  mined_same_bar: Track;
  walk_forward: Track & { n_refits: number };
  buy_hold: { sharpe: number };
  dsr_mined: { deflated_sharpe_prob: number; significant_at_95: boolean; n_trials: number };
  today_signal: {
    price: number;
    fast_sma: number | null;
    slow_sma: number | null;
    position: number;
    side: string;
    note: string;
  };
  equity: {
    locked: number[];
    mined_delayed: number[];
    walk_forward: number[];
    buy_hold: number[];
  };
  math: string;
  what_broke: string[];
};

const fmt = (x: number, digits = 2) => {
  const sign = x > 0 ? '+' : x < 0 ? '−' : '';
  return `${sign}${Math.abs(x).toFixed(digits).replace('.', ',')}`;
};

export default function ForwardTestPage() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<Result | null>(null);

  const run = useCallback(async () => {
    setLoading(true); setError('');
    try { setResult(await api.deskForwardTest({})); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    void run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const chart = useMemo(() => {
    if (!result) return [];
    const n = Math.min(
      result.equity.locked.length,
      result.equity.mined_delayed.length,
      result.equity.walk_forward.length,
      result.equity.buy_hold.length,
    );
    return Array.from({ length: n }, (_, i) => ({
      t: i,
      locked: result.equity.locked[i],
      mined: result.equity.mined_delayed[i],
      wf: result.equity.walk_forward[i],
      bh: result.equity.buy_hold[i],
    }));
  }, [result]);

  const sideLabel = result?.today_signal.side === 'long'
    ? 'comprado' : result?.today_signal.side === 'short' ? 'vendido' : 'zerado';

  return (
    <Box sx={{ maxWidth: 1040, mx: 'auto' }}>
      <Typography variant="h4" sx={{ fontWeight: 800, mb: 1, letterSpacing: '-0.03em' }}>
        Teste sequencial
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        Backtest é ferramenta de pesquisa, não prova de edge. Quanto mais estratégias,
        parâmetros e sinais no mesmo histórico, maior o risco de transformar ruído em
        resultado aparentemente significativo.
        A evidência mais forte é executar a spec com disciplina: em cada instante, só a
        informação que já existia; o sinal de hoje é avaliado por um preço que ainda não
        conhecemos. Amanhã, de novo.
      </Typography>

      <Button variant="contained" disabled={loading} onClick={() => void run()} sx={{ mb: 2 }}>
        {loading ? 'Gerando a série…' : 'Rodar relógio sequencial'}
      </Button>
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      {result && (
        <Stack spacing={2}>
          <Card>
            <CardContent>
              <Typography variant="overline" color="text.secondary">Sinal de hoje (spec travada SMA 10/40)</Typography>
              <Typography variant="h4" sx={{ fontWeight: 800, textTransform: 'capitalize' }}>{sideLabel}</Typography>
              <Typography variant="body2" sx={{ mt: 1 }}>{result.today_signal.note}</Typography>
            </CardContent>
          </Card>

          <Box sx={{ height: 360 }}>
            <ResponsiveContainer>
              <LineChart data={chart} margin={{ top: 8, right: 12, bottom: 8, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="t" hide />
                <YAxis domain={['auto', 'auto']} />
                <Tooltip />
                <Legend />
                <Line type="monotone" dataKey="mined" name="TA minerada (atraso honesto, seleção não)" stroke="#ef4444" dot={false} strokeWidth={2} />
                <Line type="monotone" dataKey="locked" name="Spec travada (sequencial)" stroke="#6366f1" dot={false} strokeWidth={2} />
                <Line type="monotone" dataKey="wf" name="Walk-forward (rebusca em dados[:t])" stroke="#06b6d4" dot={false} />
                <Line type="monotone" dataKey="bh" name="Buy & hold" stroke="#94a3b8" dot={false} strokeDasharray="4 4" />
              </LineChart>
            </ResponsiveContainer>
          </Box>

          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Relógio</TableCell>
                <TableCell>Sharpe</TableCell>
                <TableCell>Acerto</TableCell>
                <TableCell>IC</TableCell>
                <TableCell>O que é</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              <TableRow>
                <TableCell>Spec travada</TableCell>
                <TableCell>{fmt(result.locked.sharpe)}</TableCell>
                <TableCell>{(result.locked.hit_rate * 100).toFixed(0)}%</TableCell>
                <TableCell>{fmt(result.locked.ic)}</TableCell>
                <TableCell>Parâmetros congelados no dia 0. Único relógio honesto desta spec.</TableCell>
              </TableRow>
              <TableRow>
                <TableCell>TA minerada, com atraso</TableCell>
                <TableCell>{fmt(result.mined_delayed.sharpe)}</TableCell>
                <TableCell>{(result.mined_delayed.hit_rate * 100).toFixed(0)}%</TableCell>
                <TableCell>{fmt(result.mined_delayed.ic)}</TableCell>
                <TableCell>Melhor de {result.n_candidates} pares SMA no mesmo histórico. Campeão de uma busca.</TableCell>
              </TableRow>
              <TableRow>
                <TableCell>TA minerada, mesmo bar</TableCell>
                <TableCell>{fmt(result.mined_same_bar.sharpe)}</TableCell>
                <TableCell>{(result.mined_same_bar.hit_rate * 100).toFixed(0)}%</TableCell>
                <TableCell>{fmt(result.mined_same_bar.ic)}</TableCell>
                <TableCell>Vazamento: o sinal usa o fechamento que já entra no retorno.</TableCell>
              </TableRow>
              <TableRow>
                <TableCell>Walk-forward</TableCell>
                <TableCell>{fmt(result.walk_forward.sharpe)}</TableCell>
                <TableCell>{(result.walk_forward.hit_rate * 100).toFixed(0)}%</TableCell>
                <TableCell>{fmt(result.walk_forward.ic)}</TableCell>
                <TableCell>{result.walk_forward.n_refits} refits só com dados[:t]. Mais honesto que o máximo global, ainda é busca.</TableCell>
              </TableRow>
              <TableRow>
                <TableCell>Buy & hold</TableCell>
                <TableCell>{fmt(result.buy_hold.sharpe)}</TableCell>
                <TableCell>—</TableCell>
                <TableCell>—</TableCell>
                <TableCell>Neste demo o GBM tem μ=0. Qualquer Sharpe alto é sorte.</TableCell>
              </TableRow>
            </TableBody>
          </Table>

          <Alert severity={result.dsr_mined.significant_at_95 ? 'warning' : 'error'}>
            A campeã da grade ({result.mined_delayed.fast}/{result.mined_delayed.slow}) foi o máximo de {result.n_candidates} testes.
            DSR = {(result.dsr_mined.deflated_sharpe_prob * 100).toFixed(1)}%
            {result.dsr_mined.significant_at_95
              ? ' — rejeita sorte a 95% neste modelo, ainda não autoriza live.'
              : ' — não passa de 95%. O backtest minerado ganhou o sorteio no mesmo histórico.'}
            {' '}Veja a <Link to="/winners-curse">maldição do vencedor</Link>.
            Evidência temporal com hipótese escrita: <Link to="/ml">Laboratório Quant</Link>.
            eligible_for_live_trading: false.
          </Alert>
          <Alert severity="info">{result.math}</Alert>
          <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap' }}>
            {result.what_broke.map((w) => <Chip key={w} size="small" label={w} />)}
          </Stack>
        </Stack>
      )}
    </Box>
  );
}
