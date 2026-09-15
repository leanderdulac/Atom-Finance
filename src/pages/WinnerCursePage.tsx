import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert, Box, Button, Card, CardContent, Chip, Stack, TextField, Typography,
} from '@mui/material';
import {
  CartesianGrid, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart,
  Tooltip as RTooltip, XAxis, YAxis,
} from 'recharts';
import { api } from '../services/api';

type CloudPoint = { is: number; oos: number; winner: boolean };

type SimResult = {
  n_strategies: number;
  t_is: number;
  t_oos: number;
  true_sharpe: number;
  winner_is: number;
  winner_oos: number;
  is_oos_corr: number;
  expected_max: { expected_max_sqrt_2lnN: number; expected_max_blp: number; se: number };
  dsr: {
    deflated_sharpe_prob: number;
    sr_star: number;
    significant_at_95: boolean;
    haircut: number;
  };
  cloud: CloudPoint[];
  math: string;
  what_broke: string[];
  eligible_for_live_trading: boolean;
};

type DeflateResult = {
  observed_sharpe: number;
  sr_star: number;
  deflated_sharpe_prob: number;
  significant_at_95: boolean;
  haircut: number;
  n_trials: number;
  n_obs: number;
  math: string;
};

const fmt = (x: number, digits = 2) => {
  const sign = x > 0 ? '+' : x < 0 ? '−' : '';
  return `${sign}${Math.abs(x).toFixed(digits).replace('.', ',')}`;
};

function HollowDot(props: { cx?: number; cy?: number }) {
  const { cx = 0, cy = 0 } = props;
  return <circle cx={cx} cy={cy} r={6} fill="none" stroke="#ef4444" strokeWidth={2} />;
}

export default function WinnerCursePage() {
  const [n, setN] = useState(400);
  const [tIs, setTIs] = useState(504);
  const [tOos, setTOos] = useState(252);
  const [seed, setSeed] = useState(7);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<SimResult | null>(null);

  const [obsSr, setObsSr] = useState('2.96');
  const [deflateN, setDeflateN] = useState('400');
  const [deflateT, setDeflateT] = useState('504');
  const [deflate, setDeflate] = useState<DeflateResult | null>(null);
  const [deflateErr, setDeflateErr] = useState('');

  const simulate = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const out = await api.deskWinnersCurseSimulate({
        n_strategies: n, t_is: tIs, t_oos: tOos, seed,
      });
      setResult(out);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [n, tIs, tOos, seed]);

  useEffect(() => {
    void simulate();
    // default lottery on first paint only
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const haircut = async () => {
    setDeflateErr('');
    try {
      const out = await api.deskWinnersCurseDeflate({
        observed_sharpe: Number(obsSr),
        n_trials: Number(deflateN),
        n_obs: Number(deflateT),
      });
      setDeflate(out);
    } catch (e) {
      setDeflateErr(e instanceof Error ? e.message : String(e));
    }
  };

  const display = useMemo(() => {
    if (!result) return { cloud: [] as CloudPoint[], winner: [] as CloudPoint[], naive: [] as { is: number; oos: number }[] };
    const others = result.cloud.filter((p) => !p.winner);
    const step = others.length > 400 ? Math.ceil(others.length / 400) : 1;
    const cloud = others.filter((_, i) => i % step === 0);
    const winner = result.cloud.filter((p) => p.winner);
    const naive = winner.length ? [{ is: winner[0].is, oos: winner[0].is }] : [];
    return { cloud, winner, naive };
  }, [result]);

  const domain = useMemo(() => {
    const pts = result?.cloud ?? [];
    if (!pts.length) return [-3, 3] as [number, number];
    const xs = pts.flatMap((p) => [p.is, p.oos, p.is]);
    const m = Math.max(3, Math.ceil(Math.max(...xs.map(Math.abs))));
    return [-m, m] as [number, number];
  }, [result]);

  const [lo, hi] = domain;
  const wIs = result?.winner_is ?? 0;
  const wOos = result?.winner_oos ?? 0;

  return (
    <Box sx={{ maxWidth: 1040, mx: 'auto' }}>
      <Typography variant="h4" sx={{ fontWeight: 800, mb: 1, letterSpacing: '-0.03em' }}>
        A maldição do vencedor
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        N estratégias sem edge nenhum: ruído iid, E[r]=0. O campeão é o máximo de N Sharpes
        amostrais — cresce como √(2·ln N) mesmo quando o valor verdadeiro é zero.
        Antes de arriscar capital, pergunte de quantos candidatos ele foi o campeão e
        desconte o Sharpe (Bailey &amp; López de Prado).
      </Typography>

      <Stack direction="row" spacing={1} sx={{ mb: 2, flexWrap: 'wrap', alignItems: 'center' }}>
        <TextField label="Candidatos (N)" type="number" value={n}
          onChange={(e) => setN(Number(e.target.value))} sx={{ width: 140 }}
          inputProps={{ min: 10, max: 2000 }} />
        <TextField label="Dias in-sample" type="number" value={tIs}
          onChange={(e) => setTIs(Number(e.target.value))} sx={{ width: 150 }} />
        <TextField label="Dias OOS" type="number" value={tOos}
          onChange={(e) => setTOos(Number(e.target.value))} sx={{ width: 130 }} />
        <TextField label="Semente" type="number" value={seed}
          onChange={(e) => setSeed(Number(e.target.value))} sx={{ width: 110 }} />
        <Button variant="contained" disabled={loading} onClick={() => void simulate()}>
          {loading ? 'Sorteando…' : 'Simular o sorteio'}
        </Button>
      </Stack>
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      {result && (
        <Stack spacing={2}>
          <Card>
            <CardContent>
              <Typography variant="overline" color="text.secondary">
                Sharpe da vencedora no backtest (in-sample)
              </Typography>
              <Typography variant="h3" sx={{ fontWeight: 800, color: '#ef4444', letterSpacing: '-0.04em' }}>
                {fmt(result.winner_is)}
              </Typography>
              <Stack direction="row" spacing={3} sx={{ mt: 1, flexWrap: 'wrap' }}>
                <Typography variant="body2">
                  fora da amostra: <strong>{fmt(result.winner_oos)}</strong>
                </Typography>
                <Typography variant="body2">
                  estratégias testadas: <strong>{result.n_strategies}</strong>
                </Typography>
                <Typography variant="body2">
                  correlação IS×OOS: <strong>{fmt(result.is_oos_corr)}</strong>
                </Typography>
              </Stack>
              <Box sx={{ height: 420, mt: 2 }}>
                <ResponsiveContainer>
                  <ScatterChart margin={{ top: 12, right: 16, bottom: 28, left: 8 }}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis type="number" dataKey="is" domain={domain} name="IS"
                      label={{ value: 'Sharpe no backtest (in-sample)', position: 'bottom', offset: 8 }} />
                    <YAxis type="number" dataKey="oos" domain={domain} name="OOS"
                      label={{ value: 'Sharpe fora da amostra', angle: -90, position: 'insideLeft' }} />
                    <RTooltip formatter={(v) => fmt(Number(v))} />
                    <ReferenceLine segment={[{ x: lo, y: lo }, { x: hi, y: hi }]} strokeDasharray="6 4" />
                    <ReferenceLine
                      segment={[{ x: wIs, y: wOos }, { x: wIs, y: wIs }]}
                      stroke="#ef4444" strokeDasharray="3 3"
                    />
                    <Scatter name="estratégias" data={display.cloud} fill="#94a3b8" fillOpacity={0.7} r={3} />
                    <Scatter name="vencedora" data={display.winner} fill="#ef4444" r={5} />
                    <Scatter name="replay ingênuo" data={display.naive} shape={<HollowDot />} />
                  </ScatterChart>
                </ResponsiveContainer>
              </Box>
              <Stack spacing={0.5} sx={{ mt: 1 }}>
                <Typography variant="caption">● Cada ponto: uma estratégia testada (edge verdadeiro = 0)</Typography>
                <Typography variant="caption">● Vencedora: melhor Sharpe no backtest (in-sample)</Typography>
                <Typography variant="caption">○ Se o backtest se repetisse (expectativa ingênua)</Typography>
                <Typography variant="caption">- - Reta y = x · Sharpe verdadeiro = 0</Typography>
              </Stack>
            </CardContent>
          </Card>

          <Alert severity="warning">
            Campeão de <strong>{result.n_strategies}</strong> candidatos.
            E[max SR | H0] ≈ {fmt(result.expected_max.expected_max_sqrt_2lnN)} (√(2 ln N)·σ_SR).
            Sharpe deflacionado DSR = {(result.dsr.deflated_sharpe_prob * 100).toFixed(1)}%
            {result.dsr.significant_at_95
              ? ' — rejeita sorte a 95% neste modelo, ainda não autoriza live.'
              : ' — não passa de 95%. O backtest ganhou o sorteio da rodada anterior.'}
            {' '}eligible_for_live_trading: false.
          </Alert>
          {result.math && <Alert severity="info">{result.math}</Alert>}
          <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap' }}>
            {result.what_broke.map((w) => <Chip key={w} size="small" label={w} />)}
          </Stack>
        </Stack>
      )}

      <Card sx={{ mt: 3 }}>
        <CardContent>
          <Typography variant="h6" sx={{ mb: 1 }}>Desconte a maldição (DSR)</Typography>
          <Typography variant="body2" sx={{ mb: 2 }}>
            Cole o Sharpe in-sample de uma estratégia e de quantos candidatos ela foi a campeã.
          </Typography>
          <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', mb: 2 }}>
            <TextField label="Sharpe observado" value={obsSr} onChange={(e) => setObsSr(e.target.value)} sx={{ width: 160 }} />
            <TextField label="Candidatos (N)" value={deflateN} onChange={(e) => setDeflateN(e.target.value)} sx={{ width: 150 }} />
            <TextField label="Observações (T)" value={deflateT} onChange={(e) => setDeflateT(e.target.value)} sx={{ width: 160 }} />
            <Button variant="outlined" onClick={() => void haircut()}>Descontar o Sharpe</Button>
          </Stack>
          {deflateErr && <Alert severity="error">{deflateErr}</Alert>}
          {deflate && (
            <Alert severity={deflate.significant_at_95 ? 'warning' : 'error'}>
              SR* (esperado do máximo) = {fmt(deflate.sr_star)}. Haircut = {fmt(deflate.haircut)}.
              DSR = {(deflate.deflated_sharpe_prob * 100).toFixed(1)}%
              {deflate.significant_at_95
                ? ' — rejeita H0 a 95% neste modelo gaussiano.'
                : ' — ainda parece sorte depois de pagar pela busca.'}
              {' '}Campeão de {deflate.n_trials} candidatos em {deflate.n_obs} observações.
            </Alert>
          )}
        </CardContent>
      </Card>
    </Box>
  );
}
