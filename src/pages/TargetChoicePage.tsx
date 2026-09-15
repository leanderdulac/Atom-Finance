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

type Pack = { r2: number; rmse: number; accuracy: number; n: number };
type Result = {
  scale: {
    move_brl: number;
    petr4_last: number;
    btc_last: number;
    petr4_move_pct: number;
    btc_move_pct: number;
  };
  stationarity: {
    adf_petr4_price: number;
    adf_btc_price: number;
    adf_returns: number;
    critical_5pct: number;
    price_rejects_unit_root: boolean;
    returns_reject_unit_root: boolean;
  };
  targets: {
    next_price_petr4: Pack;
    next_price_btc: Pack;
    next_return: Pack;
    next_vol_regime: Pack;
  };
  transfer: {
    price_rmse_petr_model_on_btc: number;
    return_rmse_same_path: number;
    price_rmse_ratio_btc_over_petr: number;
  };
  path: { t: number; petr4_indexed: number; btc_indexed: number }[];
  math: string;
  what_broke: string[];
};

const fmt = (x: number, digits = 2) => x.toFixed(digits).replace('.', ',');
const fmtPct = (x: number, digits = 2) => `${fmt(x, digits)}%`;

export default function TargetChoicePage() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<Result | null>(null);

  const run = useCallback(async () => {
    setLoading(true); setError('');
    try { setResult(await api.deskTargetChoice({})); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    void run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const chart = useMemo(() => result?.path ?? [], [result]);

  return (
    <Box sx={{ maxWidth: 1040, mx: 'auto' }}>
      <Typography variant="h4" sx={{ fontWeight: 800, mb: 1, letterSpacing: '-0.03em' }}>
        Preço não é alvo
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        Prever o print já começa errado: R$ 500 no Bitcoin não é R$ 500 na PETR4, e o nível
        do preço não é estacionário. O mesmo caminho de log-retorno, dois níveis — o alvo
        honesto é o retorno (adimensional) ou o regime, não a cotação.
      </Typography>
      <Button variant="contained" disabled={loading} onClick={() => void run()} sx={{ mb: 2 }}>
        {loading ? 'Comparando alvos…' : 'Comparar preço × retorno × regime'}
      </Button>
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      {result && (
        <Stack spacing={2}>
          <Alert severity="warning">
            R$ {fmt(result.scale.move_brl, 0)} é {fmtPct(result.scale.petr4_move_pct)} da PETR4
            (último {fmt(result.scale.petr4_last)}) e só {fmtPct(result.scale.btc_move_pct, 4)} do BTC
            (último {fmt(result.scale.btc_last, 0)}). RMSE de um modelo de preço vive nessa unidade —
            não viaja entre ativos.
          </Alert>

          <Box sx={{ height: 280 }}>
            <ResponsiveContainer>
              <LineChart data={chart} margin={{ top: 8, right: 12, bottom: 8, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="t" hide />
                <YAxis />
                <Tooltip />
                <Legend />
                <Line type="monotone" dataKey="petr4_indexed" name="PETR4 indexada (P/P0)" stroke="#6366f1" dot={false} />
                <Line type="monotone" dataKey="btc_indexed" name="BTC indexado (P/P0)" stroke="#ef4444" dot={false} strokeDasharray="4 4" />
              </LineChart>
            </ResponsiveContainer>
          </Box>
          <Typography variant="caption" color="text.secondary">
            As duas linhas coincidem: é o mesmo retorno. Só a escala do print muda.
          </Typography>

          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Alvo</TableCell>
                <TableCell>R² walk-forward</TableCell>
                <TableCell>RMSE</TableCell>
                <TableCell>Acerto direcional / regime</TableCell>
                <TableCell>O que é</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              <TableRow>
                <TableCell>P_t+1 PETR4</TableCell>
                <TableCell>{fmt(result.targets.next_price_petr4.r2, 3)}</TableCell>
                <TableCell>{fmt(result.targets.next_price_petr4.rmse, 3)}</TableCell>
                <TableCell>{fmtPct(result.targets.next_price_petr4.accuracy * 100, 0)}</TableCell>
                <TableCell>R² alto porque o preço é I(1). Acerto de variação continua ruído.</TableCell>
              </TableRow>
              <TableRow>
                <TableCell>P_t+1 BTC</TableCell>
                <TableCell>{fmt(result.targets.next_price_btc.r2, 3)}</TableCell>
                <TableCell>{fmt(result.targets.next_price_btc.rmse, 0)}</TableCell>
                <TableCell>{fmtPct(result.targets.next_price_btc.accuracy * 100, 0)}</TableCell>
                <TableCell>Mesmo modelo, RMSE {fmt(result.transfer.price_rmse_ratio_btc_over_petr, 0)}× maior. A unidade comeu o erro.</TableCell>
              </TableRow>
              <TableRow>
                <TableCell>r_t+1</TableCell>
                <TableCell>{fmt(result.targets.next_return.r2, 3)}</TableCell>
                <TableCell>{fmt(result.targets.next_return.rmse, 4)}</TableCell>
                <TableCell>{fmtPct(result.targets.next_return.accuracy * 100, 0)}</TableCell>
                <TableCell>Adimensional. Transfere entre PETR4 e BTC. R² honesto, perto de zero.</TableCell>
              </TableRow>
              <TableRow>
                <TableCell>Regime de vol (próximos 20d)</TableCell>
                <TableCell>{fmt(result.targets.next_vol_regime.r2, 3)}</TableCell>
                <TableCell>—</TableCell>
                <TableCell>{fmtPct(result.targets.next_vol_regime.accuracy * 100, 0)}</TableCell>
                <TableCell>Estado, não print. Vol persiste; o Laboratório Quant rotula retorno, o <Link to="/regime">classificador</Link> rotula regime.</TableCell>
              </TableRow>
            </TableBody>
          </Table>

          <Alert severity={result.stationarity.returns_reject_unit_root ? 'info' : 'warning'}>
            ADF(1) preço PETR4 = {fmt(result.stationarity.adf_petr4_price, 2)}, BTC = {fmt(result.stationarity.adf_btc_price, 2)},
            retornos = {fmt(result.stationarity.adf_returns, 2)} (crítico 5% = {fmt(result.stationarity.critical_5pct, 2)}).
            {result.stationarity.returns_reject_unit_root
              ? ' Os retornos rejeitam raiz unitária; os preços, neste relógio, não.'
              : ' Relógio curto: ADF tem pouco poder — ainda assim o retorno é o alvo do protocolo.'}
            {' '}Coeficientes de preço da PETR4 aplicados ao BTC: RMSE {fmt(result.transfer.price_rmse_petr_model_on_btc, 0)}.
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
