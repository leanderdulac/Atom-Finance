import React, { Suspense, lazy, useState } from 'react';
import { BrowserRouter, Routes, Route, useNavigate, useLocation } from 'react-router-dom';
import {
  Box, Drawer, List, ListItemButton, ListItemIcon, ListItemText,
  AppBar, Toolbar, Typography, IconButton, Divider, Tooltip, Chip, useMediaQuery,
  CircularProgress,
} from '@mui/material';
import {
  ShowChart, Assessment, AccountBalance, Psychology, Warning,
  Timeline, DarkMode, LightMode, Menu as MenuIcon, Waves, Terminal, AutoGraph,
  FindInPage, Functions, TrendingUp, MonetizationOn, CallMerge, RocketLaunch, AutoFixHigh,
  CurrencyExchange, Logout, Science, Percent, MenuBook,
} from '@mui/icons-material';
import { ThemeProvider, useThemeMode } from './theme/ThemeProvider';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import DisclaimerBanner from './components/DisclaimerBanner';

// Pages — lazy-loaded so each route ships its own chunk instead of one
// multi-megabyte bundle for the whole app (30+ pages were previously eager).
const LoginPage = lazy(() => import('./pages/LoginPage'));
const LandingPage = lazy(() => import('./pages/LandingPage'));
const ExperimentsPage = lazy(() => import('./pages/ExperimentsPage'));
const PricingPage = lazy(() => import('./pages/PricingPage'));
const RiskPage = lazy(() => import('./pages/RiskPage'));
const PortfolioPage = lazy(() => import('./pages/PortfolioPage'));
const MLPage = lazy(() => import('./pages/MLPage'));
const BlackSwanPage = lazy(() => import('./pages/BlackSwanPage'));
const BacktestingPage = lazy(() => import('./pages/BacktestingPage'));
const StrategiesPage = lazy(() => import('./pages/StrategiesPage'));
const NeuralSDEPage = lazy(() => import('./pages/NeuralSDEPage'));
const TerminalPage = lazy(() => import('./pages/TerminalPage'));
const AIReportPage = lazy(() => import('./pages/AIReportPage'));
const SimulacaoB3Page = lazy(() => import('./pages/SimulacaoB3Page'));
const PerfilInvestidorPage = lazy(() => import('./pages/PerfilInvestidorPage'));
const IbovespaDashboard = lazy(() => import('./pages/IbovespaDashboard'));
const ResearchPage = lazy(() => import('./pages/ResearchPage'));
const PaperCrawlerPage = lazy(() => import('./pages/PaperCrawlerPage'));
const CSQAPage = lazy(() => import('./pages/CSQAPage'));
const SPYIntradayPage = lazy(() => import('./pages/SPYIntradayPage'));
const ClientOptionsHub = lazy(() => import('./pages/ClientOptionsHub'));
const AlphaCombinationPage = lazy(() => import('./pages/AlphaCombinationPage'));
const DerivativesPage = lazy(() => import('./pages/DerivativesPage'));
const SourcesPage = lazy(() => import('./pages/SourcesPage'));
const PaperTradesPage = lazy(() => import('./pages/PaperTradesPage'));
const AIAlphaScreener = lazy(() => import('./pages/AIAlphaScreener'));
const AutopilotPage = lazy(() => import('./pages/AutopilotPage'));
const BinanceDashboard = lazy(() => import('./pages/BinanceDashboard'));
const EarningsPredictionPage = lazy(() => import('./pages/EarningsPredictionPage'));
const DeskLabPage = lazy(() => import('./pages/DeskLabPage'));
const RegimePage = lazy(() => import('./pages/RegimePage'));
const WinnerCursePage = lazy(() => import('./pages/WinnerCursePage'));
const ForwardTestPage = lazy(() => import('./pages/ForwardTestPage'));
const TargetChoicePage = lazy(() => import('./pages/TargetChoicePage'));
const QuantDoctrinePage = lazy(() => import('./pages/QuantDoctrinePage'));

function RouteFallback() {
  return (
    <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '40vh' }}>
      <CircularProgress size={32} />
    </Box>
  );
}

const DRAWER_WIDTH = 260;

// Split by what a page promises, not by how well it is implemented: anything
// that offers a prediction, a pick or an edge belongs under "Exploratórias",
// because docs/RESEARCH-POLICY.md makes /api/ml/evaluate the only route allowed
// to speak about evidence. Borderline pages default to exploratory.
const toolItems = [
  { label: 'Options Pricing', path: '/pricing', icon: <ShowChart /> },
  { label: 'Strategies', path: '/strategies', icon: <Timeline /> },
  { label: 'Risk Analysis', path: '/risk', icon: <Assessment /> },
  { label: 'Portfolio', path: '/portfolio', icon: <AccountBalance /> },
  { label: 'Tail Risk', path: '/black-swan', icon: <Warning /> },
  { label: 'Backtesting', path: '/backtesting', icon: <Timeline /> },
  { label: 'Quant Terminal', path: '/terminal', icon: <Terminal /> },
  { label: 'Binance Crypto', path: '/binance', icon: <CurrencyExchange /> },
];

const exploratoryItems = [
  { label: 'Cenários teóricos de opções', path: '/autopilot', icon: <RocketLaunch /> },
  { label: 'B3 AI Alpha Screener', path: '/ai-screener', icon: <AutoFixHigh /> },
  { label: 'Especialista em Opções', path: '/options-expert', icon: <Psychology /> },
  { label: 'Earnings Predictor', path: '/earnings-predictor', icon: <Assessment /> },
  { label: 'Alpha Engine', path: '/alpha-engine', icon: <CallMerge /> },
  { label: 'Simulador Cliente (Opções)', path: '/client-options', icon: <MonetizationOn /> },
  { label: 'SPY Intraday', path: '/spy-momentum', icon: <TrendingUp /> },
  { label: 'CSQA Math Engine', path: '/csqa', icon: <Functions /> },
  { label: 'Paper Crawler', path: '/paper-crawler', icon: <FindInPage /> },
  { label: 'Análise IA', path: '/ai-report', icon: <AutoGraph /> },
  { label: 'Simulação B3', path: '/simulacao-b3', icon: <ShowChart /> },
  { label: 'Perfil Investidor', path: '/perfil-investidor', icon: <AccountBalance /> },
  { label: 'Ibovespa 18 + RL', path: '/ibovespa', icon: <AutoGraph /> },
  { label: 'Neural SDE', path: '/neural-sde', icon: <Waves /> },
];

const coreItems = [
  { label: 'Doutrina da mesa', path: '/quant-doctrine', icon: <MenuBook /> },
  { label: 'Mesa de papers', path: '/desk', icon: <Functions /> },
  { label: 'Regimes', path: '/regime', icon: <Warning /> },
  { label: 'Maldição do vencedor', path: '/winners-curse', icon: <Timeline /> },
  { label: 'Teste sequencial', path: '/forward-test', icon: <Science /> },
  { label: 'Preço × retorno', path: '/target-choice', icon: <Percent /> },
  { label: 'Fontes de mercado', path: '/sources', icon: <AccountBalance /> },
  { label: 'Mesa de derivativos', path: '/derivatives', icon: <ShowChart /> },
  { label: 'Operações simuladas', path: '/paper-trades', icon: <Timeline /> },
  { label: 'Diário de pesquisa', path: '/dashboard', icon: <Assessment /> },
  { label: 'Novo experimento', path: '/ml', icon: <Psychology /> },
  { label: 'Biblioteca QuantMind', path: '/research', icon: <FindInPage /> },
];
function AppLayout() {
  const [showAdvanced, setShowAdvanced] = useState(false);
  const { mode, toggle } = useThemeMode();
  const compact = useMediaQuery('(max-width:900px)');
  const [drawerOpen, setDrawerOpen] = useState(false);
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
          <IconButton aria-label="Alternar navegação" edge="start" onClick={() => setDrawerOpen(!drawerOpen)} sx={{ mr: 2 }}>
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
              label="Research · piloto"
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
          <AuthStatusButton />
        </Toolbar>
      </AppBar>

      <Drawer
        variant={compact ? "temporary" : "persistent"}
        open={compact ? drawerOpen : !drawerOpen}
        onClose={() => setDrawerOpen(false)}
        sx={{
          width: compact ? 0 : !drawerOpen ? DRAWER_WIDTH : 0,
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
          {(() => {
            const renderItem = (item: { label: string; path: string; icon: React.ReactNode }) => (
              <ListItemButton
                key={item.path}
                selected={location.pathname === item.path}
                onClick={() => { navigate(item.path); if (compact) setDrawerOpen(false); }}
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
            );
            const groupLabel = (text: string, hint: string) => (
              <Box sx={{ px: 3, pt: 2, pb: 0.5 }}>
                <Typography variant="overline" color="text.secondary" sx={{ fontWeight: 700, letterSpacing: '0.08em' }}>
                  {text}
                </Typography>
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', lineHeight: 1.4 }}>
                  {hint}
                </Typography>
              </Box>
            );
            return (
              <List>
                {coreItems.map(renderItem)}
                {showAdvanced && (
                  <>
                    {groupLabel('Ferramentas', 'Cálculo sobre entradas que você fornece.')}
                    {toolItems.map(renderItem)}
                    {groupLabel('Exploratórias', 'Prometem previsão ou seleção. Sem validação fora da amostra — use o Laboratório Quant para evidência.')}
                    {exploratoryItems.map(renderItem)}
                  </>
                )}
              </List>
            );
          })()}
          <ListItemButton onClick={() => setShowAdvanced(!showAdvanced)} aria-expanded={showAdvanced}>
            <ListItemText primary={showAdvanced ? 'Ocultar ferramentas e exploratórias' : 'Ferramentas e exploratórias'} />
          </ListItemButton>
          <Divider sx={{ my: 1 }} />
          <Box sx={{ px: 2, py: 1 }}>
            <Typography variant="caption" color="text.secondary">
              ATOM Research · piloto local
            </Typography>
            <br />
            <Typography variant="caption" color="text.secondary">
              Pesquisa com evidência e rastreabilidade
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
        <Suspense fallback={<RouteFallback />}>
        <Routes>
          <Route path="/dashboard" element={<ProtectedRoute><ExperimentsPage /></ProtectedRoute>} />
          <Route path="/desk" element={<ProtectedRoute><DeskLabPage /></ProtectedRoute>} />
          <Route path="/regime" element={<ProtectedRoute><RegimePage /></ProtectedRoute>} />
          <Route path="/winners-curse" element={<ProtectedRoute><WinnerCursePage /></ProtectedRoute>} />
          <Route path="/forward-test" element={<ProtectedRoute><ForwardTestPage /></ProtectedRoute>} />
          <Route path="/target-choice" element={<ProtectedRoute><TargetChoicePage /></ProtectedRoute>} />
          <Route path="/quant-doctrine" element={<ProtectedRoute><QuantDoctrinePage /></ProtectedRoute>} />
          <Route path="/pricing" element={<ProtectedRoute><PricingPage /></ProtectedRoute>} />
          <Route path="/strategies" element={<ProtectedRoute><StrategiesPage /></ProtectedRoute>} />
          <Route path="/risk" element={<ProtectedRoute><RiskPage /></ProtectedRoute>} />
          <Route path="/portfolio" element={<ProtectedRoute><PortfolioPage /></ProtectedRoute>} />
          <Route path="/ml" element={<ProtectedRoute><MLPage /></ProtectedRoute>} />
          <Route path="/black-swan" element={<ProtectedRoute><BlackSwanPage /></ProtectedRoute>} />
          <Route path="/simulacao-b3" element={<ProtectedRoute><SimulacaoB3Page /></ProtectedRoute>} />
          <Route path="/perfil-investidor" element={<ProtectedRoute><PerfilInvestidorPage /></ProtectedRoute>} />
          <Route path="/ibovespa" element={<ProtectedRoute><IbovespaDashboard /></ProtectedRoute>} />
          <Route path="/neural-sde" element={<ProtectedRoute><NeuralSDEPage /></ProtectedRoute>} />
          <Route path="/backtesting" element={<ProtectedRoute><BacktestingPage /></ProtectedRoute>} />
          <Route path="/terminal" element={<ProtectedRoute><TerminalPage /></ProtectedRoute>} />
          <Route path="/ai-report"    element={<ProtectedRoute><AIReportPage /></ProtectedRoute>} />
          <Route path="/autopilot"    element={<ProtectedRoute><AutopilotPage /></ProtectedRoute>} />
          <Route path="/ai-screener"  element={<ProtectedRoute><AIAlphaScreener /></ProtectedRoute>} />
          <Route path="/research" element={<ProtectedRoute><ResearchPage /></ProtectedRoute>} />
          <Route path="/paper-crawler" element={<ProtectedRoute><PaperCrawlerPage /></ProtectedRoute>} />
          <Route path="/csqa" element={<ProtectedRoute><CSQAPage /></ProtectedRoute>} />
          <Route path="/spy-momentum" element={<ProtectedRoute><SPYIntradayPage /></ProtectedRoute>} />
          <Route path="/client-options" element={<ProtectedRoute><ClientOptionsHub /></ProtectedRoute>} />
          <Route path="/options-expert" element={<ProtectedRoute><DerivativesPage /></ProtectedRoute>} />
          <Route path="/sources" element={<ProtectedRoute><SourcesPage /></ProtectedRoute>} />
          <Route path="/paper-trades" element={<ProtectedRoute><PaperTradesPage /></ProtectedRoute>} />
          <Route path="/derivatives" element={<ProtectedRoute><DerivativesPage /></ProtectedRoute>} />
          <Route path="/earnings-predictor" element={<ProtectedRoute><EarningsPredictionPage /></ProtectedRoute>} />
          <Route path="/alpha-engine" element={<ProtectedRoute><AlphaCombinationPage /></ProtectedRoute>} />
          <Route path="/binance" element={<ProtectedRoute><BinanceDashboard /></ProtectedRoute>} />
        </Routes>
        </Suspense>
      </Box>
    </Box>
  );
}

function AuthStatusButton() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  if (!user) return null;
  return (
    <Tooltip title={`Sair (${user.username})`}>
      <IconButton onClick={() => { logout(); navigate('/login'); }} sx={{ color: 'text.secondary' }}>
        <Logout sx={{ fontSize: 20 }} />
      </IconButton>
    </Tooltip>
  );
}

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, loading } = useAuth();
  const navigate = useNavigate();
  React.useEffect(() => {
    if (!loading && !isAuthenticated) navigate('/login', { replace: true });
  }, [loading, isAuthenticated, navigate]);
  if (loading || !isAuthenticated) return null;
  return <>{children}</>;
}

function AppRouter() {
  const location = useLocation();
  
  // Show landing page on root path only
  if (location.pathname === '/') {
    return <Suspense fallback={<RouteFallback />}><LandingPage /></Suspense>;
  }

  if (location.pathname === '/login') {
    return <Suspense fallback={<RouteFallback />}><LoginPage /></Suspense>;
  }
  
  // Show app layout for all other routes
  return <AppLayout />;
}

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <BrowserRouter>
          <AppRouter />
          <DisclaimerBanner />
        </BrowserRouter>
      </AuthProvider>
    </ThemeProvider>
  );
}
