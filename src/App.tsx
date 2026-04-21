import React, { useState } from 'react';
import { BrowserRouter, Routes, Route, useNavigate, useLocation } from 'react-router-dom';
import {
  Box, Drawer, List, ListItemButton, ListItemIcon, ListItemText,
  AppBar, Toolbar, Typography, IconButton, Divider, Tooltip, Chip,
} from '@mui/material';
import {
  ShowChart, Assessment, AccountBalance, Psychology, Water, Warning,
  Timeline, Speed, DarkMode, LightMode, Menu as MenuIcon, Waves, Terminal, AutoGraph,
  FindInPage, Functions, TrendingUp, MonetizationOn, CallMerge, RocketLaunch, AutoFixHigh,
  CurrencyExchange
} from '@mui/icons-material';
import { ThemeProvider, useThemeMode } from './theme/ThemeProvider';

// Pages
import LandingPage from './pages/LandingPage';
import Dashboard from './pages/Dashboard';
import PricingPage from './pages/PricingPage';
import RiskPage from './pages/RiskPage';
import PortfolioPage from './pages/PortfolioPage';
import MLPage from './pages/MLPage';
import GhostLiquidityPage from './pages/GhostLiquidityPage';
import BlackSwanPage from './pages/BlackSwanPage';
import BacktestingPage from './pages/BacktestingPage';
import StrategiesPage from './pages/StrategiesPage';
import NeuralSDEPage from './pages/NeuralSDEPage';
import TerminalPage from './pages/TerminalPage';
import AIReportPage from './pages/AIReportPage';
import SimulacaoB3Page from './pages/SimulacaoB3Page';
import PerfilInvestidorPage from './pages/PerfilInvestidorPage';
import IbovespaDashboard from './pages/IbovespaDashboard';
import PaperCrawlerPage from './pages/PaperCrawlerPage';
import CSQAPage from './pages/CSQAPage';
import SPYIntradayPage from './pages/SPYIntradayPage';
import ClientOptionsHub from './pages/ClientOptionsHub';
import AlphaCombinationPage from './pages/AlphaCombinationPage';
import OptionsExpertPage from './pages/OptionsExpertPage';
import AIAlphaScreener from './pages/AIAlphaScreener';
import AutopilotPage from './pages/AutopilotPage';
import BinanceDashboard from './pages/BinanceDashboard';

const DRAWER_WIDTH = 260;

const navItems = [
  { label: 'Binance Crypto', path: '/binance', icon: <CurrencyExchange /> },
  { label: 'AUTOPILOT', path: '/autopilot', icon: <RocketLaunch /> },
  { label: 'B3 AI Alpha Screener', path: '/ai-screener', icon: <AutoFixHigh /> },
  { label: 'Especialista em Opções', path: '/options-expert', icon: <Psychology /> },
  { label: 'Alpha Engine', path: '/alpha-engine', icon: <CallMerge /> },
  { label: 'Dashboard', path: '/dashboard', icon: <Speed /> },
  { label: 'Simulador Cliente (Opções)', path: '/client-options', icon: <MonetizationOn /> },
  { label: 'SPY Intraday', path: '/spy-momentum', icon: <TrendingUp /> },
  { label: 'CSQA Math Engine', path: '/csqa', icon: <Functions /> },
  { label: 'Paper Crawler', path: '/paper-crawler', icon: <FindInPage /> },
  { label: 'Análise IA', path: '/ai-report', icon: <AutoGraph /> },
  { label: 'Quant Terminal', path: '/terminal', icon: <Terminal /> },
  { label: 'Options Pricing', path: '/pricing', icon: <ShowChart /> },
  { label: 'Strategies', path: '/strategies', icon: <Timeline /> },
  { label: 'Risk Analysis', path: '/risk', icon: <Assessment /> },
  { label: 'Portfolio', path: '/portfolio', icon: <AccountBalance /> },
  { label: 'ML Predictions', path: '/ml', icon: <Psychology /> },
  { label: 'Simulação B3', path: '/simulacao-b3', icon: <ShowChart /> },
  { label: 'Perfil Investidor', path: '/perfil-investidor', icon: <AccountBalance /> },
  { label: 'Ibovespa 18 + RL', path: '/ibovespa', icon: <AutoGraph /> },
  { label: 'Neural SDE', path: '/neural-sde', icon: <Waves /> },
  { label: 'Ghost Liquidity', path: '/ghost-liquidity', icon: <Water /> },
  { label: 'Black Swan', path: '/black-swan', icon: <Warning /> },
  { label: 'Backtesting', path: '/backtesting', icon: <Timeline /> },
];

function AppLayout() {
  const { mode, toggle } = useThemeMode();
  const [drawerOpen, setDrawerOpen] = useState(true);
  const navigate = useNavigate();
  const location = useLocation();

  return (
    <Box sx={{ display: 'flex', minHeight: '100vh' }}>
      <AppBar
        position="fixed"
        elevation={0}
        sx={{
          zIndex: (t) => t.zIndex.drawer + 1,
          bgcolor: 'background.paper',
          borderBottom: 1,
          borderColor: 'divider',
        }}
      >
        <Toolbar>
          <IconButton edge="start" onClick={() => setDrawerOpen(!drawerOpen)} sx={{ mr: 2 }}>
            <MenuIcon />
          </IconButton>
          <Box
            onClick={() => navigate('/dashboard')}
            sx={{ display: 'flex', alignItems: 'center', gap: 1.5, cursor: 'pointer', '&:hover': { opacity: 0.8 } }}
          >
            <Box
              component="img"
              src="/atom.svg"
              sx={{ width: 32, height: 32 }}
            />
            <Typography variant="h6" sx={{ fontWeight: 700, letterSpacing: '-0.02em' }}>
              ATOM
            </Typography>
            <Chip
              label="Quant Finance"
              size="small"
              sx={{
                bgcolor: 'primary.main',
                color: '#fff',
                fontWeight: 600,
                fontSize: '0.7rem',
                height: 22,
              }}
            />
          </Box>
          <Box sx={{ flexGrow: 1 }} />
          <Tooltip title={`Switch to ${mode === 'dark' ? 'light' : 'dark'} mode`}>
            <IconButton onClick={toggle} sx={{ color: 'text.primary' }}>
              {mode === 'dark' ? <LightMode /> : <DarkMode />}
            </IconButton>
          </Tooltip>
        </Toolbar>
      </AppBar>

      <Drawer
        variant="persistent"
        open={drawerOpen}
        sx={{
          width: drawerOpen ? DRAWER_WIDTH : 0,
          flexShrink: 0,
          '& .MuiDrawer-paper': {
            width: DRAWER_WIDTH,
            boxSizing: 'border-box',
            borderRight: 1,
            borderColor: 'divider',
            bgcolor: 'background.paper',
          },
        }}
      >
        <Toolbar />
        <Box sx={{ overflow: 'auto', py: 1 }}>
          <List>
            {navItems.map((item) => (
              <ListItemButton
                key={item.path}
                selected={location.pathname === item.path}
                onClick={() => navigate(item.path)}
                sx={{
                  mx: 1,
                  borderRadius: 2,
                  mb: 0.5,
                  '&.Mui-selected': {
                    bgcolor: 'primary.main',
                    color: '#fff',
                    '&:hover': { bgcolor: 'primary.dark' },
                    '& .MuiListItemIcon-root': { color: '#fff' },
                  },
                }}
              >
                <ListItemIcon sx={{ minWidth: 40 }}>{item.icon}</ListItemIcon>
                <ListItemText
                  primary={item.label}
                  slotProps={{ primary: { fontSize: '0.875rem', fontWeight: 500 } }}
                />
              </ListItemButton>
            ))}
          </List>
          <Divider sx={{ my: 1 }} />
          <Box sx={{ px: 2, py: 1 }}>
            <Typography variant="caption" color="text.secondary">
              ATOM v1.0.0
            </Typography>
            <br />
            <Typography variant="caption" color="text.secondary">
              Quantitative Finance Platform
            </Typography>
          </Box>
        </Box>
      </Drawer>

      <Box
        component="main"
        sx={{
          flexGrow: 1,
          p: 3,
          marginLeft: 0,
          transition: 'margin 0.2s',
          mt: '64px',
          maxWidth: '100%',
          overflow: 'hidden',
        }}
      >
        <Routes>
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/pricing" element={<PricingPage />} />
          <Route path="/strategies" element={<StrategiesPage />} />
          <Route path="/risk" element={<RiskPage />} />
          <Route path="/portfolio" element={<PortfolioPage />} />
          <Route path="/ml" element={<MLPage />} />
          <Route path="/ghost-liquidity" element={<GhostLiquidityPage />} />
          <Route path="/black-swan" element={<BlackSwanPage />} />
          <Route path="/simulacao-b3" element={<SimulacaoB3Page />} />
          <Route path="/perfil-investidor" element={<PerfilInvestidorPage />} />
          <Route path="/ibovespa" element={<IbovespaDashboard />} />
          <Route path="/neural-sde" element={<NeuralSDEPage />} />
          <Route path="/backtesting" element={<BacktestingPage />} />
          <Route path="/terminal" element={<TerminalPage />} />
          <Route path="/ai-report" element={<AIReportPage />} />
          <Route path="/paper-crawler" element={<PaperCrawlerPage />} />
          <Route path="/csqa" element={<CSQAPage />} />
          <Route path="/spy-momentum" element={<SPYIntradayPage />} />
          <Route path="/client-options" element={<ClientOptionsHub />} />
          <Route path="/options-expert" element={<OptionsExpertPage />} />
          <Route path="/ai-screener" element={<AIAlphaScreener />} />
          <Route path="/autopilot" element={<AutopilotPage />} />
          <Route path="/alpha-engine" element={<AlphaCombinationPage />} />
          <Route path="/binance" element={<BinanceDashboard />} />
        </Routes>
      </Box>
    </Box>
  );
}

function AppRouter() {
  const location = useLocation();
  
  // Show landing page on root path only
  if (location.pathname === '/') {
    return <LandingPage />;
  }
  
  // Show app layout for all other routes
  return <AppLayout />;
}

export default function App() {
  return (
    <ThemeProvider>
      <BrowserRouter>
        <AppRouter />
      </BrowserRouter>
    </ThemeProvider>
  );
}
