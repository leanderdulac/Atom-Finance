import React, { useState } from "react";
import { 
  Box, 
  Typography, 
  Button, 
  Card, 
  CardContent, 
  Grid, 
  Chip, 
  CircularProgress, 
  Divider, 
  IconButton, 
  Tooltip,
  Paper,
  LinearProgress
} from "@mui/material";
import { 
  Psychology, 
  Search, 
  AutoFixHigh, 
  TrendingUp, 
  TrendingDown, 
  InfoOutlined, 
  ArrowForward,
  Assessment,
  Timeline,
  WarningAmber,
  CheckCircleOutline
} from "@mui/icons-material";
import { 
  AreaChart, 
  Area, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip as RechartsTooltip, 
  ResponsiveContainer,
  ReferenceLine
} from 'recharts';

interface OptionTrade {
  ticker: string;
  action: string;
  underlying_price: number;
  strike: number;
  strike_2?: number;
  expiry_days: number;
  iv: number;
  delta: number;
  theta: number;
  cost_brl: number;
  max_profit?: number;
  max_loss?: number;
  prob_success: number;
  reasoning: string;
  scenario_analysis: Record<string, number>;
}

interface ScanResult {
  timestamp: string;
  num_trades: number;
  trades: OptionTrade[];
  expert_narrative: string;
}

const OptionsExpertPage: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ScanResult | null>(null);
  const [selectedTrade, setSelectedTrade] = useState<OptionTrade | null>(null);

  const startScan = async () => {
    setLoading(true);
    try {
      const response = await fetch("/api/ai/options-expert/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ num_assets: 15, risk_profile: "Moderado" })
      });
      const data = await response.json();
      setResult(data);
      if (data.trades.length > 0) {
        setSelectedTrade(data.trades[0]);
      }
    } catch (error) {
      console.error("Scan failed:", error);
    } finally {
      setLoading(false);
    }
  };

  const getPayoffData = (trade: OptionTrade) => {
    const spot = trade.underlying_price;
    const strike = trade.strike;
    const data = [];
    const range = spot * 0.20;
    for (let i = spot - range; i <= spot + range; i += range / 10) {
        let profit = 0;
        if (trade.action.includes("CALL")) {
            profit = Math.max(0, i - strike) - trade.cost_brl;
        } else {
            profit = Math.max(0, strike - i) - trade.cost_brl;
        }
        data.push({ x: i.toFixed(2), y: profit.toFixed(2) });
    }
    return data;
  };

  return (
    <Box sx={{ p: 4, minHeight: "100vh", background: "linear-gradient(135deg, #0a0e17 0%, #05070a 100%)", color: "#e0e6ed" }}>
      {/* Header Section */}
      <Box sx={{ mb: 6, textAlign: "center" }}>
        <Typography variant="h3" sx={{ fontWeight: 800, mb: 1, letterSpacing: "-1px" }}>
          Especialista em <span style={{ color: "#00d4ff" }}>Opções IA</span>
        </Typography>
        <Typography variant="body1" sx={{ color: "#8a99af", mb: 4 }}>
          Rede neural treinada em dinâmica de derivativos. Escaneando distorções de volatilidade na B3 em tempo real.
        </Typography>
        
        <Button 
          variant="contained" 
          size="large" 
          onClick={startScan}
          disabled={loading}
          startIcon={loading ? <CircularProgress size={20} color="inherit" /> : <Search />}
          sx={{ 
            px: 6, 
            py: 2, 
            borderRadius: "12px", 
            background: "linear-gradient(90deg, #00d4ff 0%, #0055ff 100%)",
            boxShadow: "0 8px 16px rgba(0, 212, 255, 0.2)",
            textTransform: "none",
            fontSize: "1.1rem",
            fontWeight: 700
          }}
        >
          {loading ? "Escaneando B3..." : "Iniciar Escaneamento de Mercado"}
        </Button>
      </Box>

      {loading && (
        <Box sx={{ width: '100%', maxWidth: 600, mx: 'auto', mt: 4 }}>
          <LinearProgress sx={{ borderRadius: 4, height: 8 }} />
          <Typography variant="caption" sx={{ mt: 2, display: "block", textAlign: "center", color: "#5c6d84" }}>
            Analisando Gregas, Skew de Volatilidade e Momentum de 30 tickers selecionados...
          </Typography>
        </Box>
      )}

      {result && (
        <Grid container spacing={4}>
          {/* Left Column: Recommendations */}
          <Grid size={{ xs: 12, md: 4 }}>
            <Typography variant="h6" sx={{ mb: 2, fontWeight: 700, display: "flex", alignItems: "center", gap: 1 }}>
              <CheckCircleOutline sx={{ color: "#00ff88" }} /> Recomendações do Dia
            </Typography>
            <Box sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
              {result.trades.map((trade, idx) => (
                <Card 
                  key={idx}
                  onClick={() => setSelectedTrade(trade)}
                  sx={{ 
                    cursor: "pointer",
                    background: selectedTrade?.ticker === trade.ticker ? "#111b2d" : "#0d1421",
                    border:  selectedTrade?.ticker === trade.ticker ? "1px solid #00d4ff" : "1px solid #1e293b",
                    borderRadius: "12px",
                    transition: "0.2s",
                    "&:hover": { background: "#111b2d" }
                  }}
                >
                  <CardContent sx={{ p: 2, "&:last-child": { pb: 2 } }}>
                    <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", mb: 1 }}>
                      <Typography variant="h6" sx={{ fontWeight: 800 }}>{trade.ticker}</Typography>
                      <Chip 
                        label={trade.action} 
                        size="small" 
                        color={trade.action.includes("BUY") ? "success" : "warning"} 
                        sx={{ fontWeight: 700, fontSize: "0.7rem" }}
                      />
                    </Box>
                    <Box sx={{ display: "flex", gap: 2, color: "#8a99af", fontSize: "0.85rem" }}>
                      <Typography variant="body2" sx={{ fontSize: "inherit" }}>
                        Prob: <span style={{ color: "#00ff88", fontWeight: 700 }}>{trade.prob_success}%</span>
                      </Typography>
                      <Typography variant="body2" sx={{ fontSize: "inherit" }}>
                        Spot: R$ {trade.underlying_price.toFixed(2)}
                      </Typography>
                    </Box>
                  </CardContent>
                </Card>
              ))}
            </Box>

            <Paper sx={{ mt: 4, p: 3, background: "#101625cc", borderRadius: "16px", border: "1px solid #2d3b50" }}>
              <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1, color: "#00d4ff", display: "flex", alignItems: "center", gap: 1 }}>
                <Psychology fontSize="small" /> Insights do Especialista
              </Typography>
              <Typography variant="body2" sx={{ color: "#cbd5e1", lineHeight: 1.6, fontStyle: "italic" }}>
                "{result.expert_narrative}"
              </Typography>
            </Paper>
          </Grid>

          {/* Right Column: Deep Analysis */}
          <Grid size={{ xs: 12, md: 8 }}>
            {selectedTrade && (
              <Box>
                <Card sx={{ background: "#0d1421", borderRadius: "16px", border: "1px solid #1e293b", p: 2 }}>
                  <CardContent>
                    <Grid container spacing={3}>
                      <Grid size={{ xs: 12, md: 6 }}>
                        <Typography variant="h4" sx={{ fontWeight: 800, mb: 1 }}>{selectedTrade.ticker} — {selectedTrade.action}</Typography>
                        <Typography variant="body1" sx={{ color: "#8a99af", mb: 3 }}>
                          {selectedTrade.reasoning}
                        </Typography>
                        
                        <Grid container spacing={2}>
                          <Grid size={{ xs: 4 }}>
                            <Typography variant="caption" sx={{ color: "#5c6d84", display: "block" }}>STRIKE</Typography>
                            <Typography variant="h6">R$ {selectedTrade.strike.toFixed(2)}</Typography>
                          </Grid>
                          <Grid size={{ xs: 4 }}>
                            <Typography variant="caption" sx={{ color: "#5c6d84", display: "block" }}>CUSTO</Typography>
                            <Typography variant="h6">R$ {selectedTrade.cost_brl.toFixed(2)}</Typography>
                          </Grid>
                          <Grid size={{ xs: 4 }}>
                            <Typography variant="caption" sx={{ color: "#5c6d84", display: "block" }}>IV</Typography>
                            <Typography variant="h6">{(selectedTrade.iv * 100).toFixed(1)}%</Typography>
                          </Grid>
                        </Grid>
                      </Grid>

                      <Grid size={{ xs: 12, md: 6 }}>
                        <Box sx={{ height: 260, width: "100%" }}>
                          <Typography variant="subtitle2" sx={{ mb: 1, color: "#8a99af", textAlign: "center" }}>Simulação de Payoff no Vencimento</Typography>
                          <ResponsiveContainer width="100%" height="100%">
                            <AreaChart data={getPayoffData(selectedTrade)}>
                              <defs>
                                <linearGradient id="colorY" x1="0" y1="0" x2="0" y2="1">
                                  <stop offset="5%" stopColor="#00d4ff" stopOpacity={0.3}/>
                                  <stop offset="95%" stopColor="#00d4ff" stopOpacity={0}/>
                                </linearGradient>
                              </defs>
                              <XAxis dataKey="x" hide />
                              <YAxis hide domain={['auto', 'auto']} />
                              <RechartsTooltip 
                                contentStyle={{ backgroundColor: "#111b2d", border: "1px solid #1e293b" }}
                                labelStyle={{ color: "#8a99af" }}
                              />
                              <ReferenceLine y={0} stroke="#5c6d84" strokeDasharray="3 3" />
                              <Area type="monotone" dataKey="y" stroke="#00d4ff" fillOpacity={1} fill="url(#colorY)" />
                            </AreaChart>
                          </ResponsiveContainer>
                        </Box>
                      </Grid>
                    </Grid>

                    <Divider sx={{ my: 3, borderColor: "#1e293b" }} />

                    <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <Box sx={{ display: "flex", gap: 3 }}>
                           <Box>
                              <Typography variant="caption" sx={{ color: "#5c6d84", display: "block" }}>DELTA</Typography>
                              <Typography variant="body1" sx={{ fontWeight: 700 }}>{selectedTrade.delta.toFixed(3)}</Typography>
                           </Box>
                           <Box>
                              <Typography variant="caption" sx={{ color: "#5c6d84", display: "block" }}>THETA (DIA)</Typography>
                              <Typography variant="body1" sx={{ fontWeight: 700, color: "#ff6b6b" }}>{selectedTrade.theta.toFixed(4)}</Typography>
                           </Box>
                        </Box>
                        <Button 
                          variant="outlined" 
                          endIcon={<ArrowForward />}
                          sx={{ borderColor: "#00d4ff", color: "#00d4ff", borderRadius: "8px" }}
                        >
                          Ir para Home-Broker
                        </Button>
                    </Box>
                  </CardContent>
                </Card>
              </Box>
            )}
          </Grid>
        </Grid>
      )}
    </Box>
  );
};

export default OptionsExpertPage;
