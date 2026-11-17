import { useState } from 'react';
import {
  Alert, Box, Button, Card, CardContent, Chip, CircularProgress,
  Slider, Stack, TextField, Typography,
} from '@mui/material';
import { api, type SimulateResult } from '../services/api';

type Props = {
  s0: number;
  direction: 'bullish' | 'bearish';
  entry: number;
  stop: number;
  target: number;
  horizonDays: number;
  horizonLabel: string;
  size: number;
  sizeNote?: string;
  measuredVol: number | null;
  costDefault: number | null;
  costMethod?: string;
  ccy: 'BRL' | 'USD';
};

const clampVolPct = (v: number) => Math.min(150, Math.max(5, Math.round(v)));

const money = (n: number, ccy: 'BRL' | 'USD') =>
  `${ccy === 'USD' ? 'US$' : 'R$'} ${n.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const pct1 = (n: number) => `${(n * 100).toFixed(1).replace('.', ',')}%`;

/** Honest Monte Carlo over the assembled levels: distributions, not promises. */
export default function SimulationCard(p: Props) {
  const measuredPct = p.measuredVol != null && Number.isFinite(p.measuredVol) && p.measuredVol > 0
    ? clampVolPct(p.measuredVol * 100)
    : null;
  const [volPct, setVolPct] = useState(measuredPct ?? 30);
  const [cost, setCost] = useState(p.costDefault != null && p.costDefault >= 0 ? String(p.costDefault) : '0');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [sim, setSim] = useState<SimulateResult | null>(null);
  // Never simulate an invented size: without a sized quantity there is no P&L.
  const sized = Number.isFinite(p.size) && p.size > 0;

  async function run() {
    setBusy(true);
    setError('');
    const costTotal = Number(String(cost).replace(',', '.'));
    try {
      const out = await api.clientSimulate({
        S0: p.s0,
        direction: p.direction === 'bullish' ? 'long' : 'short',
        entry: p.entry,
        stop: p.stop,
        target: p.target,
        horizon_days: p.horizonDays,
        vol_annual: volPct / 100,
        n_paths: 5000,
        seed: 7,
        size: p.size,
        cost_total: Number.isFinite(costTotal) && costTotal >= 0 ? costTotal : 0,
      });
      setSim(out);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Falha na simulação.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card variant="outlined" sx={{ mt: 2 }}>
      <CardContent>
        <Typography variant="subtitle1" fontWeight={700}>Simulação Monte Carlo</Typography>
        <Typography variant="body2" color="text.secondary">
          5.000 caminhos GBM sobre entrada, stop e alvo · {p.horizonLabel} · vol inicial medida
          no histórico{p.costMethod ? ` · custos: ${p.costMethod}` : ''}.
          Frequência em caminhos simulados — não é certeza sobre o mercado.
        </Typography>
        {!sized ? (
          <Alert severity="warning" sx={{ mt: 2 }}>
            Sem simulação: tamanho não dimensionado{p.sizeNote ? ` — ${p.sizeNote}` : '.'}
          </Alert>
        ) : (
          <>
            <Box sx={{ mt: 2, maxWidth: 420 }}>
              <Typography variant="body2">
                Vol anual: {volPct}%{measuredPct != null ? ` (medida ${measuredPct}%)` : ' (padrão 30%: sem medida)'}
              </Typography>
              <Slider
                aria-label="Volatilidade anual"
                value={volPct}
                min={5}
                max={150}
                onChange={(_, v) => setVolPct(v as number)}
              />
            </Box>
            <Box sx={{ mt: 1, maxWidth: 220 }}>
              <TextField
                fullWidth size="small" label={`Custos ida-volta (${p.ccy === 'USD' ? 'US$' : 'R$'})`}
                value={cost} onChange={(e) => setCost(e.target.value)}
                inputProps={{ inputMode: 'decimal' }}
              />
            </Box>
            <Button variant="outlined" onClick={run} disabled={busy} sx={{ mt: 1 }}>
              {busy ? <CircularProgress size={18} /> : 'Simular 5.000 caminhos'}
            </Button>
          </>
        )}
        {error && <Alert severity="error" sx={{ mt: 2 }}>{error}</Alert>}
        {sim && (
          <Box sx={{ mt: 2 }}>
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <Chip label={`P(lucro) ${pct1(sim.p_profit)}`} color="primary" />
              <Chip size="small" label={`stop ${pct1(sim.p_stop)}`} />
              <Chip size="small" label={`alvo ${pct1(sim.p_target)}`} />
              <Chip size="small" label={`vencimento ${pct1(sim.p_expiry)}`} />
              <Chip size="small" label={`P(entrada) ${pct1(sim.p_enter)}`} />
            </Stack>
            <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr 1fr', md: 'repeat(5, 1fr)' }, gap: 2, mt: 2 }}>
              {([['P5', sim.pnl_p5], ['P25', sim.pnl_p25], ['P50', sim.pnl_p50], ['P75', sim.pnl_p75], ['P95', sim.pnl_p95]] as [string, number][]).map(([label, v]) => (
                <Box key={label}>
                  <Typography variant="body2" color="text.secondary">{label}</Typography>
                  <Typography variant="h6">{money(v, p.ccy)}</Typography>
                </Box>
              ))}
            </Box>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
              Perda média no pior 5%: {money(sim.expected_shortfall_95, p.ccy)}
              {` · ${sim.median_holding_days} dias até a saída (mediana)`}
              {` · GBM vol ${volPct}%, drift zero, preenchimento no toque.`}
            </Typography>
            <Box component="ul" sx={{ pl: 2, mb: 0, mt: 1 }}>
              {sim.what_broke.map((w) => (
                <li key={w}><Typography variant="caption" color="text.secondary">{w}</Typography></li>
              ))}
            </Box>
          </Box>
        )}
      </CardContent>
    </Card>
  );
}
