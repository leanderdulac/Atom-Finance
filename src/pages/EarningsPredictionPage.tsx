import React, { useState } from 'react';
import {
  Box, Typography, Paper, TextField, Button, Grid, Switch, FormControlLabel,
  CircularProgress, Alert, Divider, useTheme, Tooltip, IconButton, InputAdornment
} from '@mui/material';
import { api } from '../services/api';
import { AutoFixHigh, Assessment, Search, HelpOutline } from '@mui/icons-material';

const glassStyle = {
  background: 'rgba(255, 255, 255, 0.03)',
  backdropFilter: 'blur(10px)',
  border: '1px solid rgba(255, 255, 255, 0.1)',
  borderRadius: 4,
  boxShadow: '0 8px 32px 0 rgba(0, 0, 0, 0.2)',
};

const initialPeriod = {
  revenue: '', gross_profit: '', operating_income: '', interest_expense: '',
  net_income: '', cfo: '', cash_equivalents: '', current_assets: '',
  current_liabilities: '', inventory: '', accounts_receivable: '',
  total_assets: '', total_debt: '', total_equity: ''
};

const initialOptions = { S: '', K: '', T: '', r: '', C: '' };

const labels: Record<string, { label: string, hint: string }> = {
  revenue: { label: 'Receita Líquida', hint: 'Total de vendas menos devoluções e impostos.' },
  gross_profit: { label: 'Lucro Bruto', hint: 'Receita menos o Custo dos Produtos Vendidos (CPV).' },
  operating_income: { label: 'EBIT / Lucro Op.', hint: 'Lucro antes de juros e impostos.' },
  interest_expense: { label: 'Despesa com Juros', hint: 'Custo da dívida no período.' },
  net_income: { label: 'Lucro Líquido', hint: 'O "Bottom Line" após todas as despesas e impostos.' },
  cfo: { label: 'Fluxo Cx. Operacional', hint: 'Caixa gerado pelas atividades core (CFO).' },
  cash_equivalents: { label: 'Caixa e Equiv.', hint: 'Dinheiro disponível e aplicações imediatas.' },
  current_assets: { label: 'Ativo Circulante', hint: 'Bens conversíveis em dinheiro em < 1 ano.' },
  current_liabilities: { label: 'Passivo Circulante', hint: 'Obrigações a pagar em < 1 ano.' },
  inventory: { label: 'Estoques', hint: 'Valor dos produtos em estoque.' },
  accounts_receivable: { label: 'Contas a Receber', hint: 'Vendas a prazo já realizadas.' },
  total_assets: { label: 'Ativo Total', hint: 'Soma de todos os bens e direitos.' },
  total_debt: { label: 'Dívida Total', hint: 'Soma de empréstimos e financiamentos.' },
  total_equity: { label: 'Patrimônio Líquido', hint: 'Capital próprio dos acionistas.' }
};

const groups = [
  { name: 'DRE (Resultados)', keys: ['revenue', 'gross_profit', 'operating_income', 'interest_expense', 'net_income'] },
  { name: 'Fluxo de Caixa', keys: ['cfo'] },
  { name: 'Balanço (Ativos)', keys: ['cash_equivalents', 'current_assets', 'inventory', 'accounts_receivable', 'total_assets'] },
  { name: 'Balanço (Passivo/PL)', keys: ['current_liabilities', 'total_debt', 'total_equity'] }
];

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export default function EarningsPredictionPage() {
  const theme = useTheme();
  const isDark = theme.palette.mode === 'dark';

  const [current, setCurrent] = useState<Record<string, string>>({ ...initialPeriod });
  const [previous, setPrevious] = useState<Record<string, string>>({ ...initialPeriod });
  const [options, setOptions] = useState<Record<string, string>>({ ...initialOptions });
  
  const [ticker, setTicker] = useState('');
  const [fetchingTicker, setFetchingTicker] = useState(false);
  const [useOptions, setUseOptions] = useState(false);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchFromTicker = async () => {
    if (!ticker) return;
    setFetchingTicker(true);
    setError(null);
    try {
      const res = await api.getTickerFinancials(ticker);
      if (res.current) {
        const fmt = (o: any) => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, (v as number).toFixed(0)]));
        setCurrent(fmt(res.current));
        setPrevious(fmt(res.previous));
      }
    } catch (err: any) {
      setError('Não foi possível buscar dados para este ticker. Tente formatar como PETR4.SA ou AAPL.');
    } finally {
      setFetchingTicker(false);
    }
  };

  const fillTestData = () => {
    setPrevious({
      revenue: '100000', gross_profit: '40000', operating_income: '20000', interest_expense: '2000',
      net_income: '14000', cfo: '15000', cash_equivalents: '10000', current_assets: '50000',
      current_liabilities: '30000', inventory: '15000', accounts_receivable: '20000',
      total_assets: '150000', total_debt: '60000', total_equity: '60000'
    });
    setCurrent({
      revenue: '105000', gross_profit: '38000', operating_income: '18000', interest_expense: '2500',
      net_income: '12000', cfo: '11000', cash_equivalents: '8000', current_assets: '52000',
      current_liabilities: '35000', inventory: '18000', accounts_receivable: '24000',
      total_assets: '155000', total_debt: '65000', total_equity: '55000'
    });
    setOptions({ S: '34.50', K: '35.00', T: '0.08', r: '0.1075', C: '1.20' });
    setUseOptions(true);
  };

  const handleRun = async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const parseObj = (obj: any) => Object.fromEntries(Object.entries(obj).map(([k, v]) => [k, parseFloat(v as string) || 0]));
      const payload: any = {
        current_period: parseObj(current),
        previous_period: parseObj(previous)
      };
      if (useOptions) payload.options = parseObj(options);
      const res = await api.earningsPrediction(payload);
      setResult(res.analysis);
    } catch (err: any) {
      setError(err.message || 'Erro ao comunicar com o motor de análise.');
    } finally {
      setLoading(false);
    }
  };

  const renderGroupedInputs = (data: any, setter: any, title: string) => (
    <Box>
      <Typography variant="h6" fontWeight={700} gutterBottom sx={{ color: 'primary.main', mb: 2, textAlign: 'center', fontSize: '1rem' }}>
        {title}
      </Typography>
      {groups.map((group) => (
        <Box key={group.name} sx={{ mb: 2 }}>
          <Typography variant="overline" fontWeight={700} color="text.secondary" sx={{ display: 'block', mb: 0.5, opacity: 0.7 }}>
            {group.name}
          </Typography>
          <Grid container spacing={1}>
            {group.keys.map((k) => (
              <Grid size={{ xs: 6 }} key={k}>
                <TextField
                  label={labels[k].label}
                  value={data[k]}
                  onChange={(e) => setter({ ...data, [k]: e.target.value })}
                  fullWidth size="small" type="number" variant="outlined"
                  sx={{ '& .MuiInputBase-root': { fontSize: '0.85rem' } }}
                  InputProps={{
                    endAdornment: (
                      <InputAdornment position="end">
                        <Tooltip title={labels[k].hint}>
                          <HelpOutline sx={{ fontSize: 14, cursor: 'help', opacity: 0.3 }} />
                        </Tooltip>
                      </InputAdornment>
                    ),
                  }}
                />
              </Grid>
            ))}
          </Grid>
        </Box>
      ))}
    </Box>
  );

  return (
    <Box sx={{ p: 1, maxWidth: 1400, mx: 'auto' }}>
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 3, gap: 2 }}>
        <Assessment color="primary" sx={{ fontSize: 40 }} />
        <Box>
          <Typography variant="h4" fontWeight={900} sx={{ background: 'linear-gradient(45deg, #1976d2, #64b5f6)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
            Earnings Predictor
          </Typography>
          <Typography variant="subtitle2" color="text.secondary" sx={{ opacity: 0.8 }}>
            Inteligência Quantitativa para Previsão de Lucros & Volatilidade Analítica
          </Typography>
        </Box>
      </Box>

      <Paper sx={{ ...glassStyle, p: 3, mb: 4, bgcolor: isDark ? 'rgba(20,25,35,0.6)' : 'rgba(255,255,255,0.8)' }}>
        <Grid container spacing={2} alignItems="center" sx={{ mb: 4 }}>
          <Grid size={{ xs: 12, sm: 6, md: 5 }} >
            <TextField
              fullWidth
              label="Autocompletar via Ticker"
              placeholder="Ex: PETR4, VALE3, ITUB4, AAPL, NVDA"
              value={ticker}
              onChange={(e) => setTicker(e.target.value.toUpperCase())}
              disabled={fetchingTicker}
              onKeyPress={(e) => e.key === 'Enter' && fetchFromTicker()}
              InputProps={{
                startAdornment: <Search sx={{ mr: 1, opacity: 0.5 }} />,
                endAdornment: (
                  <InputAdornment position="end">
                    <Button 
                      variant="contained" 
                      size="small" 
                      onClick={fetchFromTicker} 
                      disabled={fetchingTicker || !ticker}
                      sx={{ borderRadius: 1 }}
                    >
                      {fetchingTicker ? <CircularProgress size={16} color="inherit" /> : 'Buscar'}
                    </Button>
                  </InputAdornment>
                ),
              }}
            />
          </Grid>
          <Grid size={{ xs: 12, sm: 6, md: 7 }} sx={{ textAlign: 'right' }}>
            <Button variant="outlined" color="inherit" onClick={fillTestData} startIcon={<AutoFixHigh />} sx={{ opacity: 0.7 }}>
              Dados de Simulação
            </Button>
          </Grid>
        </Grid>

        <Grid container spacing={4}>
          <Grid size={{ xs: 12, md: 6 }} >
            {renderGroupedInputs(previous, setPrevious, "Ano Anterior (T-1)")}
          </Grid>
          <Grid size={{ xs: 12, md: 6 }} >
            {renderGroupedInputs(current, setCurrent, "Trimestre Atual (T-0)")}
          </Grid>
        </Grid>

        <Divider sx={{ my: 4, opacity: 0.1 }} />

        <Box sx={{ mb: 3 }}>
          <FormControlLabel
            control={<Switch checked={useOptions} onChange={(e) => setUseOptions(e.target.checked)} color="primary" />}
            label={<Typography variant="subtitle1" fontWeight={700}>Análise de Volatilidade de Opções (Opcional)</Typography>}
          />
        </Box>

        {useOptions && (
          <Grid container spacing={2} sx={{ mb: 4 }}>
            {Object.keys(initialOptions).map((k) => (
              <Grid size={{ xs: 6, sm: 4, md: 2.4 }} key={k}>
                <TextField
                  label={optionsLabels[k]}
                  value={options[k]}
                  onChange={(e) => setOptions({ ...options, [k]: e.target.value })}
                  fullWidth size="small" type="number" variant="outlined"
                  helperText={optionsHints[k]}
                />
              </Grid>
            ))}
          </Grid>
        )}

        <Box sx={{ textAlign: 'center', mt: 4 }}>
          <Button
            variant="contained"
            color="primary"
            size="large"
            onClick={handleRun}
            disabled={loading}
            startIcon={loading ? <CircularProgress size={24} color="inherit" /> : <Assessment />}
            sx={{ 
              px: 10, py: 2, borderRadius: 3, fontWeight: 800, fontSize: '1.1rem',
              boxShadow: '0 10px 30px rgba(25, 118, 210, 0.4)',
              '&:hover': { transform: 'translateY(-2px)', boxShadow: '0 15px 40px rgba(25, 118, 210, 0.5)' },
              transition: 'all 0.2s'
            }}
          >
            {loading ? 'Processando Modelos Quantitativos...' : 'Gerar Veredito de Lucros'}
          </Button>
        </Box>
      </Paper>

      {error && (
        <Alert severity="error" sx={{ mb: 4, borderRadius: 2 }}>{error}</Alert>
      )}

      {result && (
        <Paper 
          sx={{ 
            p: 4, 
            ...glassStyle,
            bgcolor: isDark ? 'rgba(0,0,0,0.5)' : 'rgba(255,255,255,0.9)',
            borderLeft: '10px solid',
            borderLeftColor: result.includes('Increase') || result.includes('Aumentar') ? '#00e676' : '#ff1744'
          }}
        >
          <Typography variant="h5" fontWeight={900} gutterBottom sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 3 }}>
            <Assessment sx={{ fontSize: 30 }} />
            Relatório de Previsão Direcional
          </Typography>
          
          <Box className="markdown-body" sx={{ 
            color: 'text.primary',
            '& h3': { color: 'primary.main', mt: 3, mb: 2, fontWeight: 700, borderBottom: '1px solid rgba(0,0,0,0.1)' },
            '& p': { mb: 2, lineHeight: 1.7 },
            '& strong': { color: 'primary.light' },
            '& ul': { mb: 2, pl: 3 },
            '& li': { mb: 1 }
          }}>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {result}
            </ReactMarkdown>
          </Box>
        </Paper>
      )}
    </Box>
  );
}

const optionsLabels: Record<string, string> = {
  S: 'Preço Ativo', K: 'Strike', T: 'Anos', r: 'Taxa Juros', C: 'Prêmio'
};

const optionsHints: Record<string, string> = {
  S: 'Cotação atual', K: 'Preço exercício', T: 'Ex: 0.1 para 1 mês',
  r: 'Ex: 0.10 para 10%', C: 'Preço de mercado'
};
