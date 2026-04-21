import React, { useState } from 'react';
import {
  Box, Grid, Card, CardContent, Typography, Button, TextField,
  CircularProgress, Alert, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, Paper, Chip, LinearProgress,
} from '@mui/material';
import { api } from '../services/api';

export default function GhostLiquidityPage() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [monitorData, setMonitorData] = useState<any>(null);
  const [error, setError] = useState('');

  const [hftRate, setHftRate] = useState(0.7);
  const [duplication, setDuplication] = useState(0.3);

  const runAnalysis = async () => {
    setLoading(true); setError('');
    try {
      const res = await api.ghostLiquidity({
        bids: [], asks: [],
        hft_cancel_rate: hftRate,
        cross_venue_duplication: duplication,
      });
      setResult(res);
    } catch (e: any) { setError(e.message); }
    finally { setLoading(false); }
  };

  const runMonitor = async () => {
    setLoading(true); setError('');
    try {
      const res = await api.ghostMonitor(100);
      setMonitorData(res);
    } catch (e: any) { setError(e.message); }
    finally { setLoading(false); }
  };

  const riskColor = (level: string) =>
    level === 'HIGH' ? 'error' : level === 'MEDIUM' ? 'warning' : 'success';

  return (
    <Box>
      <Typography variant="h4" sx={{ mb: 0.5 }}>Ghost Liquidity</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Detect phantom liquidity from HFT, cross-venue duplication & flickering quotes
      </Typography>

      <Grid container spacing={2.5}>
        <Grid size={{ xs: 12, md: 4 }}>
          <Card>
            <CardContent>
              <Typography variant="h6" gutterBottom>Analysis Parameters</Typography>
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                <TextField label="HFT Cancel Rate" type="number" value={hftRate}
                  onChange={(e) => setHftRate(+e.target.value)}
                  inputProps={{ step: 0.05, min: 0, max: 1 }}
                  helperText="Rate of HFT order cancellations" fullWidth />
                <TextField label="Cross-Venue Duplication" type="number" value={duplication}
                  onChange={(e) => setDuplication(+e.target.value)}
                  inputProps={{ step: 0.05, min: 0, max: 1 }}
                  helperText="Duplicate order ratio across venues" fullWidth />
                <Button variant="contained" onClick={runAnalysis} disabled={loading} fullWidth>
                  {loading ? <CircularProgress size={20} /> : 'Analyze Order Book'}
                </Button>
                <Button variant="outlined" onClick={runMonitor} disabled={loading} fullWidth>
                  Monitor Over Time
                </Button>
              </Box>
            </CardContent>
          </Card>
        </Grid>

        <Grid size={{ xs: 12, md: 8 }}>
          {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

          {result && (
            <>
              <Card sx={{ mb: 2 }}>
                <CardContent>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                    <Typography variant="h6">Ghost Liquidity Analysis</Typography>
                    <Chip
                      label={`Risk: ${result.risk_level}`}
                      color={riskColor(result.risk_level) as any}
                      sx={{ fontWeight: 700 }}
                    />
                  </Box>

                  <Grid container spacing={2}>
                    <Grid size={{ xs: 6, sm: 3 }}>
                      <Box sx={{ textAlign: 'center', p: 1.5, border: 1, borderColor: 'divider', borderRadius: 2 }}>
                        <Typography variant="caption" color="text.secondary">Consolidated</Typography>
                        <Typography variant="h6" sx={{ fontFamily: 'monospace' }}>
                          {result.consolidated_liquidity?.toLocaleString()}
                        </Typography>
                      </Box>
                    </Grid>
                    <Grid size={{ xs: 6, sm: 3 }}>
                      <Box sx={{ textAlign: 'center', p: 1.5, border: 1, borderColor: 'divider', borderRadius: 2 }}>
                        <Typography variant="caption" color="text.secondary">Real Tradable</Typography>
                        <Typography variant="h6" sx={{ fontFamily: 'monospace', color: 'success.main' }}>
                          {result.estimated_real_liquidity?.toLocaleString()}
                        </Typography>
                      </Box>
                    </Grid>
                    <Grid size={{ xs: 6, sm: 3 }}>
                      <Box sx={{ textAlign: 'center', p: 1.5, border: 1, borderColor: 'divider', borderRadius: 2 }}>
                        <Typography variant="caption" color="text.secondary">Ghost</Typography>
                        <Typography variant="h6" sx={{ fontFamily: 'monospace', color: 'error.main' }}>
                          {result.ghost_liquidity?.toLocaleString()}
                        </Typography>
                      </Box>
                    </Grid>
                    <Grid size={{ xs: 6, sm: 3 }}>
                      <Box sx={{ textAlign: 'center', p: 1.5, border: 1, borderColor: 'divider', borderRadius: 2 }}>
                        <Typography variant="caption" color="text.secondary">Ghost Ratio</Typography>
                        <Typography variant="h6" sx={{ fontFamily: 'monospace', color: 'warning.main' }}>
                          {((result.ghost_ratio || 0) * 100).toFixed(1)}%
                        </Typography>
                      </Box>
                    </Grid>
                  </Grid>

                  {/* Liquidity Score Bar */}
                  <Box sx={{ mt: 2 }}>
                    <Typography variant="body2" color="text.secondary" gutterBottom>
                      Liquidity Score: {result.liquidity_score}/100
                    </Typography>
                    <LinearProgress
                      variant="determinate"
                      value={result.liquidity_score}
                      sx={{
                        height: 10, borderRadius: 5,
                        bgcolor: 'background.default',
                        '& .MuiLinearProgress-bar': {
                          bgcolor: result.liquidity_score > 60 ? 'success.main' :
                                   result.liquidity_score > 30 ? 'warning.main' : 'error.main',
                        },
                      }}
                    />
                  </Box>
                </CardContent>
              </Card>

              {/* Ghost Components */}
              <Card sx={{ mb: 2 }}>
                <CardContent>
                  <Typography variant="h6" gutterBottom>Ghost Liquidity Components</Typography>
                  <Table size="small">
                    <TableBody>
                      {result.ghost_components && Object.entries(result.ghost_components).map(([key, val]) => (
                        <TableRow key={key}>
                          <TableCell sx={{ textTransform: 'capitalize', fontWeight: 600 }}>
                            {key.replace(/_/g, ' ')}
                          </TableCell>
                          <TableCell align="right" sx={{ fontFamily: 'monospace' }}>
                            {(val as number).toLocaleString()} shares
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>

              {/* Market Quality */}
              {result.market_quality && (
                <Card>
                  <CardContent>
                    <Typography variant="h6" gutterBottom>Market Quality</Typography>
                    <Grid container spacing={2}>
                      {Object.entries(result.market_quality).map(([key, val]: [string, any]) => (
                        <Grid size={{ xs: 6, sm: 4, md: 2.4 }} key={key}>
                          <Box sx={{ textAlign: 'center' }}>
                            <Typography variant="caption" color="text.secondary" sx={{ textTransform: 'capitalize' }}>
                              {key.replace(/_/g, ' ')}
                            </Typography>
                            <Typography variant="body1" sx={{ fontFamily: 'monospace', fontWeight: 600 }}>
                              {typeof val === 'number' ? (val as number).toFixed(4) : val}
                            </Typography>
                          </Box>
                        </Grid>
                      ))}
                    </Grid>
                  </CardContent>
                </Card>
              )}
            </>
          )}

          {monitorData && (
            <Card sx={{ mt: 2 }}>
              <CardContent>
                <Typography variant="h6" gutterBottom>Liquidity Monitoring</Typography>
                <Alert severity="info">
                  Average Ghost Ratio: <strong>{((monitorData.average_ghost_ratio || 0) * 100).toFixed(2)}%</strong>
                  {' | '}Max: <strong>{((monitorData.max_ghost_ratio || 0) * 100).toFixed(2)}%</strong>
                  {' | '}{monitorData.timestamps?.length} snapshots
                </Alert>
              </CardContent>
            </Card>
          )}
        </Grid>
      </Grid>
    </Box>
  );
}
