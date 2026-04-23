import React, { useState, useEffect } from 'react';
import { 
  Box, Typography, Grid, Card, CardContent, Chip, Button, 
  CircularProgress, LinearProgress, Divider, Fade, Zoom,
  Tooltip, IconButton
} from '@mui/material';
import { 
  AutoFixHigh, TrendingUp, TrendingDown, Info, 
  Refresh, Analytics, Shield, Search
} from '@mui/icons-material';
import axios from 'axios';

interface ScreenerResult {
  ticker: string;
  market_data: {
    price: number;
    change_pct: number;
    name: string;
  };
  model_scores: {
    bull_score: number;
  };
  recommendation: {
    action: string;
    action_en: string;
    color: string;
    emoji: string;
    suggested_strike: number;
    suggested_expiry_days: string;
    reasoning: string;
  };
  specialized_analysis: {
    news_monitoring_gemini: string;
    fundamental_claude: string;
    quant_strategy_gpt: string;
    pulse_grok: string;
    search_perplexity: string;
    bridgewise_b3: any;
  };
}

const AIAlphaScreener: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<ScreenerResult[]>([]);
  const [error, setError] = useState<string | null>(null);

  const fetchScreener = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await axios.get('/api/screener/top-picks');
      setResults(response.data);
    } catch (err) {
      setError('Falha ao processar screening multi-IA. Verifique as chaves de API.');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box sx={{ p: 4, minHeight: '100vh', background: 'radial-gradient(circle at 10% 20%, rgba(10, 10, 20, 1) 0%, rgba(20, 20, 40, 1) 90.2%)' }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 4 }}>
        <Box>
          <Typography variant="h4" sx={{ fontWeight: 900, color: '#fff', mb: 1, display: 'flex', alignItems: 'center', gap: 2 }}>
            <AutoFixHigh sx={{ color: '#fbbf24', fontSize: '2.5rem' }} /> B3 AI ALPHA SCREENER
          </Typography>
          <Typography variant="subtitle1" sx={{ color: 'rgba(255,255,255,0.6)' }}>
            Escaner de Elite: 6 especialistas de IA orquestrando os 18 ativos do Ibovespa
          </Typography>
        </Box>
        <Button 
          variant="contained" 
          onClick={fetchScreener} 
          disabled={loading}
          sx={{ 
            bgcolor: '#fbbf24', color: '#000', fontWeight: 800, px: 4,
            '&:hover': { bgcolor: '#f59e0b' },
            boxShadow: '0 0 20px rgba(251, 191, 36, 0.4)'
          }}
          startIcon={loading ? <CircularProgress size={20} color="inherit" /> : <Search />}
        >
          {loading ? 'PROCESSANDO 108 ANÁLISES...' : 'ESCANEAR MERCADO AGORA'}
        </Button>
      </Box>

      {loading && (
        <Box sx={{ mb: 4 }}>
          <LinearProgress sx={{ height: 10, borderRadius: 5, bgcolor: 'rgba(255,255,255,0.1)', '& .MuiLinearProgress-bar': { bgcolor: '#fbbf24' } }} />
          <Typography variant="caption" sx={{ mt: 1, display: 'block', textAlign: 'center', color: '#fbbf24', fontWeight: 700 }}>
            Orquestrando Claude, GPT-5, Gemini, Grok, Perplexity e Bridgewise para todos os ativos...
          </Typography>
        </Box>
      )}

      <Grid container spacing={3}>
        {results.map((res, idx) => (
          <Grid size={{ xs: 12, md: 6, lg: 4 }} key={res.ticker}>
            <Zoom in style={{ transitionDelay: `${idx * 100}ms` }}>
              <Card sx={{ 
                bgcolor: 'rgba(30, 30, 50, 0.8)', 
                backdropFilter: 'blur(10px)',
                border: `1px solid ${res.recommendation.action_en.includes('BUY') ? 'rgba(34, 197, 94, 0.3)' : 'rgba(239, 68, 68, 0.3)'}`,
                borderRadius: 4,
                overflow: 'visible',
                position: 'relative'
              }}>
                {idx < 3 && (
                  <Chip 
                    label="TOP PICK" 
                    sx={{ 
                      position: 'absolute', top: -12, right: 20, 
                      bgcolor: '#fbbf24', color: '#000', fontWeight: 900, fontSize: '0.65rem' 
                    }} 
                  />
                )}
                <CardContent sx={{ p: 3 }}>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 2 }}>
                    <Box>
                      <Typography variant="h5" sx={{ fontWeight: 900, color: '#fff' }}>{res.ticker}</Typography>
                      <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.5)' }}>{res.market_data.name}</Typography>
                    </Box>
                    <Box sx={{ textAlign: 'right' }}>
                      <Typography variant="h6" sx={{ color: '#fff', fontWeight: 800 }}>R$ {res.market_data.price.toFixed(2)}</Typography>
                      <Typography variant="body2" sx={{ color: res.market_data.change_pct >= 0 ? '#22c55e' : '#ef4444', fontWeight: 700 }}>
                        {res.market_data.change_pct >= 0 ? '+' : ''}{res.market_data.change_pct.toFixed(2)}%
                      </Typography>
                    </Box>
                  </Box>

                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 3 }}>
                    <Box sx={{ flex: 1 }}>
                      <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.4)', mb: 0.5, display: 'block' }}>CONFIDÊNCI AI CONSENSUS</Typography>
                      <LinearProgress 
                        variant="determinate" 
                        value={res.model_scores.bull_score} 
                        sx={{ height: 8, borderRadius: 4, bgcolor: 'rgba(255,255,255,0.1)', '& .MuiLinearProgress-bar': { bgcolor: res.recommendation.color === 'success' ? '#22c55e' : '#ef4444' } }}
                      />
                    </Box>
                    <Typography variant="h6" sx={{ fontWeight: 900, color: res.recommendation.color === 'success' ? '#22c55e' : '#ef4444' }}>
                      {res.model_scores.bull_score.toFixed(1)}
                    </Typography>
                  </Box>

                  <Divider sx={{ mb: 2, borderColor: 'rgba(255,255,255,0.05)' }} />

                  <Box sx={{ bgcolor: 'rgba(0,0,0,0.2)', p: 2, borderRadius: 2, mb: 2 }}>
                    <Typography variant="subtitle2" sx={{ color: '#fbbf24', fontWeight: 900, mb: 1, display: 'flex', alignItems: 'center', gap: 1 }}>
                      {res.recommendation.emoji} OPERAÇÃO SUGERIDA
                    </Typography>
                    <Typography variant="h6" sx={{ color: '#fff', fontWeight: 800, mb: 0.5 }}>
                      {res.recommendation.action}
                    </Typography>
                    <Typography variant="body2" sx={{ color: 'rgba(255,255,255,0.7)', fontSize: '0.8rem' }}>
                      STRIKE: <strong>R$ {res.recommendation.suggested_strike.toFixed(2)}</strong> | EXPIRY: <strong>{res.recommendation.suggested_expiry_days}</strong>
                    </Typography>
                  </Box>

                  <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                    <Tooltip title="News (Gemini)">
                      <Chip icon={<Analytics sx={{ fontSize: '1rem !important' }} />} label="Gemini" size="small" sx={{ bgcolor: 'rgba(100, 149, 237, 0.1)', color: '#6495ED', fontSize: '0.65rem' }} />
                    </Tooltip>
                    <Tooltip title="Quant (GPT-5)">
                      <Chip icon={<TrendingUp sx={{ fontSize: '1rem !important' }} />} label="GPT-5" size="small" sx={{ bgcolor: 'rgba(16, 185, 129, 0.1)', color: '#10B981', fontSize: '0.65rem' }} />
                    </Tooltip>
                    <Tooltip title="Fundamental (Claude)">
                      <Chip icon={<Shield sx={{ fontSize: '1rem !important' }} />} label="Claude" size="small" sx={{ bgcolor: 'rgba(249, 115, 22, 0.1)', color: '#F97316', fontSize: '0.65rem' }} />
                    </Tooltip>
                    <Tooltip title="Pulse (Grok)">
                      <Chip icon={<Refresh sx={{ fontSize: '1rem !important' }} />} label="Grok" size="small" sx={{ bgcolor: 'rgba(0, 242, 255, 0.1)', color: '#00f2ff', fontSize: '0.65rem' }} />
                    </Tooltip>
                  </Box>
                </CardContent>
              </Card>
            </Zoom>
          </Grid>
        ))}
      </Grid>

      {results.length === 0 && !loading && (
        <Box sx={{ textAlign: 'center', mt: 10 }}>
          <AutoFixHigh sx={{ fontSize: '5rem', color: 'rgba(255,255,255,0.05)', mb: 2 }} />
          <Typography variant="h6" sx={{ color: 'rgba(255,255,255,0.2)' }}>
            Clique em "Escanear" para processar o ecossistema Hexagonal de IA
          </Typography>
        </Box>
      )}
    </Box>
  );
};

export default AIAlphaScreener;
