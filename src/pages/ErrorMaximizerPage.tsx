import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Alert, Box, Button, Card, CardContent, Chip, Stack, TextField, Typography,
} from '@mui/material';
import {
  CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer,
  Tooltip as RTooltip, XAxis, YAxis,
} from 'recharts';
import { api } from '../services/api';

type WeightStats = { l1: number; max_abs: number; hhi: number; n_short: number; sum: number };

type LabResult = {
  n_assets: number;
  t_is: number;
  t_oos: number;
  gmv: { formula: string; sample: WeightStats; ledoit_wolf: WeightStats };
  covariance: {
    sample_condition: number;
    lw_condition: number;
    sample_min_eig: number;
    lw_min_eig: number;
    ledoit_wolf: { alpha: number; r_bar: number };
  };
  marchenko_pastur: { q: number; lambda_minus: number; lambda_plus: number; n_sample_eigs_below_bulk: number };
  spectrum: { sample: number[]; ledoit_wolf: number[] };
  oos: { vol_sample: number; vol_ledoit_wolf: number; vol_equal_weight: number };
  turnover: { sample: number | null; ledoit_wolf: number | null; rebalance_every: number };
  math: string;
  what_broke: string[];
  eligible_for_live_trading: boolean;
};

const fmt = (x: number, digits = 2) =>
  x.toLocaleString('pt-BR', { minimumFractionDigits: digits, maximumFractionDigits: digits });
const pct = (x: number) => `${(x * 100).toFixed(1).replace('.', ',')}%`;

export default function ErrorMaximizerPage() {
  const [n, setN] = useState(80);
  const [tIs, setTIs] = useState(252);
  const [tOos, setTOos] = useState(63);
  const [seed, setSeed] = useState(7);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<LabResult | null>(null);

  const run = useCallback(async () => {
    setLoading(true); setError('');
    try {
      setResult(await api.deskErrorMaximizer({
        n_assets: n, t_is: tIs, t_oos: tOos, seed,
      }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [n, tIs, tOos, seed]);

  useEffect(() => {
    void run();
    // first paint only
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const spectrum = useMemo(() => {
    if (!result) return [];
    return result.spectrum.sample.map((v, i) => ({
      rank: i + 1,
      sample: v,
      lw: result.spectrum.ledoit_wolf[i],
    }));
  }, [result]);

  return (
    <Box sx={{ maxWidth: 1040, mx: 'auto' }}>
      <Typography variant="h4" sx={{ fontWeight: 800, mb: 1, letterSpacing: '-0.03em' }}>
        A maximizadora de erros
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        w* = Σ⁻¹ 1 / (1′ Σ⁻¹ 1) é a GMV analítica que todo curso ensina. Na amostra,
        Marchenko–Pastur rebaixa os menores autovalores por acaso; inverter Σ transforma
        esse ruído em pesos absurdos e giro que come o patrimônio. Buy-side encolhe
        antes de inverter: Σ_LW = α* F + (1 − α*) S (Ledoit–Wolf).
        Currículo: <Link to="/quant-doctrine">doutrina ATOM-QUANT-1.0</Link>.
      </Typography>

      <Stack direction="row" spacing={1} sx={{ mb: 2, flexWrap: 'wrap', alignItems: 'center' }}>
        <TextField label="Ativos (N)" type="number" value={n}
          onChange={(e) => setN(Number(e.target.value))} sx={{ width: 120 }}
          inputProps={{ min: 8, max: 100 }} />
        <TextField label="Dias in-sample" type="number" value={tIs}
          onChange={(e) => setTIs(Number(e.target.value))} sx={{ width: 150 }} />
        <TextField label="Dias OOS" type="number" value={tOos}
          onChange={(e) => setTOos(Number(e.target.value))} sx={{ width: 130 }} />
        <TextField label="Semente" type="number" value={seed}
          onChange={(e) => setSeed(Number(e.target.value))} sx={{ width: 110 }} />
        <Button variant="contained" disabled={loading} onClick={() => void run()}>
          {loading ? 'Invertendo…' : 'Comparar Σ amostral vs Ledoit–Wolf'}
        </Button>
      </Stack>
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      {result && (
        <Stack spacing={2}>
          <Box
            sx={{
              display: 'grid',
              gridTemplateColumns: { xs: '1fr', md: '1fr 1fr 1fr' },
              gap: 2,
            }}
          >
            <Card>
              <CardContent>
                <Typography variant="overline" color="text.secondary">Condicionamento κ(Σ)</Typography>
                <Typography variant="h5" sx={{ fontWeight: 800, color: '#ef4444' }}>
                  {fmt(result.covariance.sample_condition, 0)}
                </Typography>
                <Typography variant="body2">amostra · min λ = {fmt(result.covariance.sample_min_eig, 3)}</Typography>
                <Typography variant="h5" sx={{ fontWeight: 800, mt: 1 }}>
                  {fmt(result.covariance.lw_condition, 0)}
                </Typography>
                <Typography variant="body2">Ledoit–Wolf · min λ = {fmt(result.covariance.lw_min_eig, 3)}</Typography>
              </CardContent>
            </Card>
            <Card>
              <CardContent>
                <Typography variant="overline" color="text.secondary">Pesos GMV (L1 / máx |w|)</Typography>
                <Typography variant="h5" sx={{ fontWeight: 800, color: '#ef4444' }}>
                  {fmt(result.gmv.sample.l1)} / {fmt(result.gmv.sample.max_abs)}
                </Typography>
                <Typography variant="body2">
                  amostra · {result.gmv.sample.n_short} shorts
                </Typography>
                <Typography variant="h5" sx={{ fontWeight: 800, mt: 1 }}>
                  {fmt(result.gmv.ledoit_wolf.l1)} / {fmt(result.gmv.ledoit_wolf.max_abs)}
                </Typography>
                <Typography variant="body2">
                  Ledoit–Wolf · {result.gmv.ledoit_wolf.n_short} shorts · α* = {fmt(result.covariance.ledoit_wolf.alpha, 3)}
                </Typography>
              </CardContent>
            </Card>
            <Card>
              <CardContent>
                <Typography variant="overline" color="text.secondary">OOS vol / giro</Typography>
                <Typography variant="h5" sx={{ fontWeight: 800, color: '#ef4444' }}>
                  {pct(result.oos.vol_sample)}
                </Typography>
                <Typography variant="body2">
                  amostra · giro médio {result.turnover.sample == null ? '—' : pct(result.turnover.sample)}
                </Typography>
                <Typography variant="h5" sx={{ fontWeight: 800, mt: 1 }}>
                  {pct(result.oos.vol_ledoit_wolf)}
                </Typography>
                <Typography variant="body2">
                  Ledoit–Wolf · giro {result.turnover.ledoit_wolf == null ? '—' : pct(result.turnover.ledoit_wolf)}
                </Typography>
              </CardContent>
            </Card>
          </Box>

          <Card>
            <CardContent>
              <Typography variant="h6" sx={{ mb: 1 }}>Espectro da correlação amostral</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                q = N/T = {fmt(result.marchenko_pastur.q, 3)}. Bulk de Marchenko–Pastur
                [{fmt(result.marchenko_pastur.lambda_minus, 2)}, {fmt(result.marchenko_pastur.lambda_plus, 2)}].
                {' '}{result.marchenko_pastur.n_sample_eigs_below_bulk} autovalores amostrais abaixo de λ₋ —
                os que a inversa transforma em pesos gigantes.
              </Typography>
              <Box sx={{ height: 360 }}>
                <ResponsiveContainer>
                  <LineChart data={spectrum} margin={{ top: 12, right: 16, bottom: 28, left: 8 }}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="rank" label={{ value: 'Autovalor (maior → menor)', position: 'bottom', offset: 8 }} />
                    <YAxis label={{ value: 'λ', angle: -90, position: 'insideLeft' }} />
                    <RTooltip />
                    <Legend />
                    <ReferenceLine y={result.marchenko_pastur.lambda_minus} stroke="#ef4444" strokeDasharray="4 4" />
                    <ReferenceLine y={result.marchenko_pastur.lambda_plus} stroke="#94a3b8" strokeDasharray="4 4" />
                    <Line type="monotone" dataKey="sample" name="amostra" stroke="#ef4444" dot={false} strokeWidth={2} />
                    <Line type="monotone" dataKey="lw" name="Ledoit–Wolf" stroke="#0f766e" dot={false} strokeWidth={2} />
                  </LineChart>
                </ResponsiveContainer>
              </Box>
            </CardContent>
          </Card>

          <Alert severity="warning">
            Inverter a covariância amostral de {result.n_assets} ativos em {result.t_is} dias
            é a maximizadora de erros. κ cai de {fmt(result.covariance.sample_condition, 0)} para{' '}
            {fmt(result.covariance.lw_condition, 0)} com encolhimento. eligible_for_live_trading: false.
            Isto não é <code>POST /api/ml/evaluate</code>.
          </Alert>
          {result.math && <Alert severity="info">{result.math}</Alert>}
          <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap' }}>
            {result.what_broke.map((w) => <Chip key={w} size="small" label={w} />)}
          </Stack>
        </Stack>
      )}
    </Box>
  );
}
