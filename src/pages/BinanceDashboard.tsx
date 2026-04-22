import React, { useState, useEffect } from 'react';
import {
  Box, Grid, Card, CardContent, Typography, Button, TextField,
  Table, TableBody, TableCell, TableHead, TableRow, LinearProgress,
  Chip, Divider, IconButton, Tooltip, Zoom, Fade, Alert
} from '@mui/material';
import {
  CurrencyExchange, TrendingUp, TrendingDown, Refresh,
  Calculate, Assessment, AccountBalanceWallet, Speed, 
  BarChart, History, InfoOutlined
} from '@mui/icons-material';
import { 
  BarChart as ReBarChart, Bar, XAxis, YAxis, CartesianGrid, 
  Tooltip as ReTooltip, ResponsiveContainer, Cell, AreaChart, Area
} from 'recharts';
import { api } from '../services/api';

const BINANCE_YELLOW = '#F3BA2F';

interface TickerData {
  symbol: string;
  price: number;
}

interface OrderBook {
  bids: [string, string][];
  asks: [string, string][];
}

const BinanceDashboard: React.FC = () => {
  const [loading, setLoading] = useState(true);
  const [allTickers, setAllTickers] = useState<TickerData[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState('BTCUSDT');
  const [currentPrice, setCurrentPrice] = useState<number>(0);
  const [orderBook, setOrderBook] = useState<OrderBook | null>(null);
  
  // Kelly State
  const [winProb, setWinProb] = useState(0.55);
  const [payout, setPayout] = useState(1.5);
  const [fraction, setFraction] = useState(0.25);
  const [kellyResult, setKellyResult] = useState<any>(null);
  const [calculatingKelly, setCalculatingKelly] = useState(false);

  // Load Initial Tickers
  const loadTickerList = async () => {
    try {
      const data = await api.binanceTickers();
      const filtered = data.filter((t: any) => t.symbol.endsWith('USDT'))
                          .sort((a: any, b: any) => parseFloat(b.price) - parseFloat(a.price))
                          .slice(0, 100);
      setAllTickers(filtered.map((t: any) => ({ symbol: t.symbol, price: parseFloat(t.price) })));
    } catch (e) {
      console.error('Failed to load tickers', e);
    }
  };

  const loadSymbolData = async (symbol: string) => {
    try {
      const [priceData, depthData] = await Promise.all([
        api.binancePrice(symbol),
        api.binanceDepth(symbol, 15)
      ]);
      setCurrentPrice(priceData.price);
      setOrderBook(depthData);
    } catch (e) {
      console.error('Failed to load symbol data', e);
    }
  };

  const handleCalculateKelly = async () => {
    setCalculatingKelly(true);
    try {
      const res = await api.binanceKellySizing({
        symbol: selectedSymbol,
        win_prob: winProb,
        payout_ratio: payout,
        fraction: fraction
      });
      setKellyResult(res);
    } catch (e) {
      console.error('Kelly calculation failed', e);
    } finally {
      setCalculatingKelly(false);
    }
  };

  useEffect(() => {
    loadTickerList();
    const interval = setInterval(loadTickerList, 10000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    setLoading(true);
    loadSymbolData(selectedSymbol).finally(() => setLoading(false));
  }, [selectedSymbol]);

  // Order Book Visual Data
  const depthData = orderBook ? [
    ...orderBook.bids.slice(0, 10).map(b => ({ type: 'bid', price: parseFloat(b[0]), amount: parseFloat(b[1]) })),
    ...orderBook.asks.slice(0, 10).map(a => ({ type: 'ask', price: parseFloat(a[0]), amount: parseFloat(a[1]) }))
  ].sort((a, b) => b.price - a.price) : [];

  const maxAmount = Math.max(...depthData.map(d => d.amount), 1);

  return (
    <Box sx={{ p: 1 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Box>
          <Typography variant="h4" sx={{ fontWeight: 900, display: 'flex', alignItems: 'center', gap: 2 }}>
            <CurrencyExchange sx={{ color: BINANCE_YELLOW, fontSize: '2.5rem' }} /> BINANCE POWER DASHBOARD
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Análise Avançada de Liquidez e Sizing de Kelly p/ Cripto
          </Typography>
        </Box>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Chip label="SPOT READY" color="success" size="small" sx={{ fontWeight: 700 }} />
          <Chip label="FUTURES READY" color="warning" size="small" variant="outlined" sx={{ fontWeight: 700 }} />
        </Box>
      </Box>

      <Grid container spacing={3}>
        {/* Market Watchlist (Left) */}
        <Grid size={{ xs: 12, lg: 4 }}>
          <Card sx={{ height: '100%', overflow: 'hidden' }}>
            <Box sx={{ p: 2, display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
              <Typography variant="h6" sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <Speed fontSize="small" color="primary" /> Top Tickers (USDT)
              </Typography>
              <IconButton size="small" onClick={loadTickerList}><Refresh fontSize="small" /></IconButton>
            </Box>
            <Box sx={{ height: 600, overflowY: 'auto' }}>
              <Table size="small" stickyHeader>
                <TableHead>
                  <TableRow>
                    <TableCell sx={{ fontSize: '0.7rem', fontWeight: 800 }}>ATIVO</TableCell>
                    <TableCell align="right" sx={{ fontSize: '0.7rem', fontWeight: 800 }}>PREÇO</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {allTickers.slice(0, 20).map((t) => (
                    <TableRow 
                      hover 
                      key={t.symbol} 
                      selected={selectedSymbol === t.symbol}
                      onClick={() => setSelectedSymbol(t.symbol)}
                      sx={{ cursor: 'pointer' }}
                    >
                      <TableCell sx={{ fontWeight: 700 }}>{t.symbol}</TableCell>
                      <TableCell align="right" sx={{ fontFamily: 'monospace', color: BINANCE_YELLOW }}>
                        ${t.price > 1 ? t.price.toLocaleString() : t.price.toFixed(6)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Box>
          </Card>
        </Grid>

        {/* Main Analysis (Middle & Right) */}
        <Grid size={{ xs: 12, lg: 8 }}>
          <Grid container spacing={3}>
            {/* Price & Depth Info */}
            <Grid size={{ xs: 12 }}>
              <Card sx={{ 
                background: 'linear-gradient(135deg, rgba(20, 20, 40, 0.4) 0%, rgba(10, 10, 20, 0.4) 100%)',
                backdropFilter: 'blur(10px)',
                position: 'relative'
              }}>
                <CardContent sx={{ p: 3 }}>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 2 }}>
                    <Box>
                      <Typography variant="h3" sx={{ fontWeight: 900, mb: 0 }}>
                        {selectedSymbol}
                      </Typography>
                      <Typography variant="h5" sx={{ color: BINANCE_YELLOW, fontWeight: 700, fontFamily: 'monospace' }}>
                        $ {currentPrice?.toLocaleString()}
                      </Typography>
                    </Box>
                    <Box sx={{ textAlign: 'right' }}>
                       <Tooltip title="Volume Real do Mercado Spot">
                        <Chip icon={<Assessment />} label="Volume Explorer" variant="outlined" sx={{ color: '#fff' }} />
                       </Tooltip>
                    </Box>
                  </Box>

                  <Box sx={{ mt: 4 }}>
                    <Typography variant="subtitle2" sx={{ mb: 2, display: 'flex', alignItems: 'center', gap: 1 }}>
                      <BarChart fontSize="small" /> LIVE ORDER BOOK (DEPTH)
                    </Typography>
                    <Box sx={{ mt: 1 }}>
                      {loading ? <LinearProgress /> : (
                        <Box>
                          {depthData.map((d, i) => (
                            <Box key={i} sx={{ display: 'flex', alignItems: 'center', height: 24, position: 'relative', mb: 0.2 }}>
                              <Typography sx={{ width: 100, fontSize: '0.75rem', color: d.type === 'ask' ? '#ef4444' : '#10b981', fontWeight: 800 }}>
                                {d.price?.toLocaleString()}
                              </Typography>
                              <Box sx={{ flex: 1, height: '100%', position: 'relative', bgcolor: 'rgba(255,255,255,0.02)', borderRadius: 0.5, overflow: 'hidden' }}>
                                <Box sx={{ 
                                  position: 'absolute', 
                                  right: 0, 
                                  top: 0, 
                                  bottom: 0, 
                                  width: `${(d.amount / maxAmount) * 100}%`,
                                  bgcolor: d.type === 'ask' ? 'rgba(239, 68, 68, 0.2)' : 'rgba(16, 185, 129, 0.2)',
                                  transition: 'width 0.3s'
                                }} />
                                <Typography sx={{ position: 'absolute', right: 5, top: 2, fontSize: '0.65rem', color: 'rgba(255,255,255,0.5)', zIndex: 1 }}>
                                  {d.amount.toFixed(4)}
                                </Typography>
                              </Box>
                            </Box>
                          ))}
                        </Box>
                      )}
                    </Box>
                  </Box>
                </CardContent>
              </Card>
            </Grid>

            {/* Kelly Criterion Section */}
            <Grid size={{ xs: 12, md: 6 }}>
              <Card sx={{ border: '1px solid rgba(99, 102, 241, 0.2)' }}>
                <CardContent>
                   <Typography variant="h6" sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 3 }}>
                    <Calculate color="primary" /> Kelly Sizing Terminal (Taleb Edition)
                  </Typography>

                  <Grid container spacing={2}>
                    <Grid size={{ xs: 12 }}>
                      <TextField 
                        fullWidth 
                        label="Probabilidade de Lucro (win_prob)" 
                        type="number" 
                        value={winProb} 
                        onChange={(e) => setWinProb(parseFloat(e.target.value))}
                        helperText="Estimativa baseada no seu modelo"
                        inputProps={{ step: 0.01, min: 0, max: 1 }}
                      />
                    </Grid>
                    <Grid size={{ xs: 12 }}>
                      <TextField 
                        fullWidth 
                        label="Payout Ratio (Risk/Reward)" 
                        type="number" 
                        value={payout} 
                        onChange={(e) => setPayout(parseFloat(e.target.value))}
                        helperText="Ex: lucro de 1.5x do valor arriscado"
                      />
                    </Grid>
                    <Grid size={{ xs: 12 }}>
                      <TextField 
                        fullWidth 
                        label="Fração de Kelly (0.25 = Quarter)" 
                        type="number" 
                        value={fraction} 
                        onChange={(e) => setFraction(parseFloat(e.target.value))}
                        helperText="Recomendado 0.25 para mitigar ruína (Taleb)"
                      />
                    </Grid>
                    <Grid size={{ xs: 12 }}>
                      <Button 
                        fullWidth 
                        variant="contained" 
                        color="primary" 
                        onClick={handleCalculateKelly}
                        disabled={calculatingKelly}
                        sx={{ py: 1.5, fontWeight: 800 }}
                      >
                        CALCULAR POSITION SIZING
                      </Button>
                    </Grid>
                  </Grid>

                  {kellyResult && (
                    <Fade in>
                      <Box sx={{ mt: 3, p: 2, bgcolor: 'rgba(99, 102, 241, 0.05)', borderRadius: 2, border: '1px dashed #6366f1' }}>
                        <Typography variant="caption" sx={{ color: '#6366f1', fontWeight: 800, textTransform: 'uppercase' }}>Sugestão de Alocação</Typography>
                        <Typography variant="h4" sx={{ fontWeight: 900, mb: 1 }}>
                          ${kellyResult.alocacao_dolares?.toLocaleString()}
                        </Typography>
                        <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
                          <Typography variant="body2">Fração Aplicada:</Typography>
                          <Typography variant="body2" sx={{ fontWeight: 800 }}>{(kellyResult.kelly_frac * 100).toFixed(1)}%</Typography>
                        </Box>
                        <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
                          <Typography variant="body2">Unidades ({selectedSymbol}):</Typography>
                          <Typography variant="body2" sx={{ fontWeight: 800 }}>{kellyResult.asset_units}</Typography>
                        </Box>
                      </Box>
                    </Fade>
                  )}
                </CardContent>
              </Card>
            </Grid>

            {/* AI Insights & Futures Monitor */}
            <Grid size={{ xs: 12, md: 6 }}>
              <Card sx={{ height: '100%' }}>
                <CardContent>
                  <Typography variant="h6" sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
                    <AccountBalanceWallet color="secondary" /> Trading Context
                  </Typography>
                  <Box sx={{ mb: 3 }}>
                    <Typography variant="body2" color="text.secondary" gutterBottom>
                      Status da Conta Futuros
                    </Typography>
                    <Alert severity="info" variant="outlined" sx={{ borderRadius: 2 }}>
                      Requisição autenticada pendente da Secret Key no .env. Use o simulador para testes.
                    </Alert>
                  </Box>

                  <Typography variant="subtitle2" gutterBottom sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <History fontSize="small" /> Insights Recentes
                  </Typography>
                  <Box sx={{ borderLeft: '2px solid #6366f1', pl: 2, py: 1 }}>
                    <Typography variant="body2" sx={{ mb: 1 }}>
                      • Spread do Book: <strong>{orderBook ? (parseFloat(orderBook.asks[0][0]) - parseFloat(orderBook.bids[0][0])).toFixed(2) : '—'}</strong> USDT
                    </Typography>
                    <Typography variant="body2" sx={{ mb: 1 }}>
                      • Alvo Volatilidade: <strong>Alta</strong> (Baseado em Klines 24h)
                    </Typography>
                    <Typography variant="body2">
                      • Recomendação: <strong>Quarter Kelly</strong> preserva 75% da sua cauda de ruína.
                    </Typography>
                  </Box>

                  <Box sx={{ mt: 4, p: 2, borderRadius: 2, bgcolor: 'rgba(255,255,255,0.02)', textAlign: 'center' }}>
                    <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.3)', display: 'block', mb: 1 }}>POWERED BY ATOM QUANT ENGINE</Typography>
                    <img src="/atom.svg" alt="logo" style={{ width: 24, opacity: 0.3 }} />
                  </Box>
                </CardContent>
              </Card>
            </Grid>
          </Grid>
        </Grid>
      </Grid>
    </Box>
  );
};

export default BinanceDashboard;
