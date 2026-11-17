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

type Timing = {
  loop_mask_s: number;
  vec_mask_s: number;
  speedup_mask: number;
  loop_z_s: number;
  vec_z_s: number;
  speedup_z: number;
};

type Clock = { delayed_sharpe: number; same_bar_sharpe: number; note?: string };

type Result = {
  n_names: number;
  n_days: number;
  n_hits: number;
  z_max_abs_diff: number;
  timing: Timing;
  screen: Clock;
  index_bug: Clock;
  rejected_code: string;
  vectorized_code: string;
  equity: { t: number; delayed: number; same_bar: number }[];
  math: string;
  what_broke: string[];
};

const fmt = (x: number, digits = 1) => x.toFixed(digits).replace('.', ',');
const fmtS = (x: number) => `${(x * 1000).toFixed(2).replace('.', ',')} ms`;

export default function VectorizePage() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<Result | null>(null);

  const run = useCallback(async () => {
    setLoading(true); setError('');
    try { setResult(await api.deskVectorize({})); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { void run(); }, [run]);

  const chart = useMemo(() => result?.equity ?? [], [result]);

  return (
    <Box sx={{ maxWidth: 1040, mx: 'auto' }}>
      <Typography variant="h4" sx={{ fontWeight: 800, mb: 1, letterSpacing: '-0.03em' }}>
        Loops em série de preço
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        A primeira busca num desafio técnico de quant é quantas vezes `for` itera uma
        série de preço. `for i in range(len(df))` com `.iloc[i]` encerra a avaliação:
        Python interpretado é 50–100× mais lento que NumPy, i vs i-1 é look-ahead, e
        um backtest de 40 minutos vira 2 segundos. Vetorização não é estética — é 10
        vs 10.000 hipóteses por dia. Currículo: <Link to="/quant-doctrine">doutrina</Link>.
      </Typography>
      <Button variant="contained" disabled={loading} onClick={() => void run()} sx={{ mb: 2 }}>
        {loading ? 'Vetorizando…' : 'Comparar loop × broadcasting'}
      </Button>
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      {result && (
        <Stack spacing={2}>
          <Alert severity="warning">
            Painel {result.n_names} nomes × {result.n_days} dias. Máscara cheap×momentum:
            {result.n_hits} hits. Z-score loop vs broadcast diferem no máximo{' '}
            {result.z_max_abs_diff.toExponential(1)}. eligible_for_live_trading: false.
          </Alert>

          <Box
            sx={{
              display: 'grid',
              gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' },
              gap: 2,
            }}
          >
            <Card variant="outlined">
              <CardContent>
                <Typography variant="overline" color="error">Reprovado na mesa</Typography>
                <Typography
                  component="pre"
                  sx={{
                    whiteSpace: 'pre-wrap',
                    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
                    fontSize: 13,
                    m: 0,
                    mt: 1,
                  }}
                >
                  {result.rejected_code}
                </Typography>
              </CardContent>
            </Card>
            <Card variant="outlined">
              <CardContent>
                <Typography variant="overline" color="success.main">Broadcast</Typography>
                <Typography
                  component="pre"
                  sx={{
                    whiteSpace: 'pre-wrap',
                    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
                    fontSize: 13,
                    m: 0,
                    mt: 1,
                  }}
                >
                  {result.vectorized_code}
                </Typography>
              </CardContent>
            </Card>
          </Box>

          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Operação</TableCell>
                <TableCell>Loop Python</TableCell>
                <TableCell>NumPy</TableCell>
                <TableCell>Speedup</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              <TableRow>
                <TableCell>Máscara pe&lt;10 e mom&gt;0</TableCell>
                <TableCell>{fmtS(result.timing.loop_mask_s)}</TableCell>
                <TableCell>{fmtS(result.timing.vec_mask_s)}</TableCell>
                <TableCell>{fmt(result.timing.speedup_mask, 0)}×</TableCell>
              </TableRow>
              <TableRow>
                <TableCell>Z-score transversal (axis=0)</TableCell>
                <TableCell>{fmtS(result.timing.loop_z_s)}</TableCell>
                <TableCell>{fmtS(result.timing.vec_z_s)}</TableCell>
                <TableCell>{fmt(result.timing.speedup_z, 0)}×</TableCell>
              </TableRow>
            </TableBody>
          </Table>

          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Relógio</TableCell>
                <TableCell>Sharpe atrasado (t+1)</TableCell>
                <TableCell>Sharpe no mesmo bar (i)</TableCell>
                <TableCell>O que é</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              <TableRow>
                <TableCell>Tela PE × momentum 20d</TableCell>
                <TableCell>{fmt(result.screen.delayed_sharpe, 2)}</TableCell>
                <TableCell>{fmt(result.screen.same_bar_sharpe, 2)}</TableCell>
                <TableCell>
                  Sinal no close t, PnL no retorno seguinte. `.iloc[i]` no retorno
                  do mesmo i é o vazamento.
                </TableCell>
              </TableRow>
              <TableRow>
                <TableCell>Bug puro i vs i−1</TableCell>
                <TableCell>{fmt(result.index_bug.delayed_sharpe, 2)}</TableCell>
                <TableCell>{fmt(result.index_bug.same_bar_sharpe, 2)}</TableCell>
                <TableCell>{result.index_bug.note}</TableCell>
              </TableRow>
            </TableBody>
          </Table>

          <Box sx={{ height: 280 }}>
            <ResponsiveContainer>
              <LineChart data={chart} margin={{ top: 8, right: 12, bottom: 8, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="t" hide />
                <YAxis />
                <Tooltip />
                <Legend />
                <Line type="monotone" dataKey="delayed" name="Equity atrasada (t+1)" stroke="#6366f1" dot={false} />
                <Line type="monotone" dataKey="same_bar" name="Equity no mesmo bar (i)" stroke="#ef4444" dot={false} strokeDasharray="4 4" />
              </LineChart>
            </ResponsiveContainer>
          </Box>
          <Typography variant="caption" color="text.secondary">
            A linha vermelha não é alpha: é o retorno de hoje usado como se já existisse na decisão.
            O <Link to="/forward-test">teste sequencial</Link> é o mesmo relógio.
          </Typography>

          <Alert severity="info">{result.math}</Alert>
          <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap' }}>
            {result.what_broke.map((w) => <Chip key={w} size="small" label={w} />)}
          </Stack>
        </Stack>
      )}
    </Box>
  );
}
