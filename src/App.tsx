import React, { Suspense, lazy } from 'react';
import { BrowserRouter, Routes, Route, useNavigate, useLocation } from 'react-router-dom';
import { ThemeProvider } from './theme/ThemeProvider';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import DisclaimerBanner from './components/DisclaimerBanner';
import AppShell from './components/layout/AppShell';
import LoadingState from './components/LoadingState';

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

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, loading } = useAuth();
  const navigate = useNavigate();
  React.useEffect(() => {
    if (!loading && !isAuthenticated) navigate('/login', { replace: true });
  }, [loading, isAuthenticated, navigate]);
  if (loading) return <LoadingState label="Restaurando a sessão…" />;
  if (!isAuthenticated) return null;
  return <>{children}</>;
}

function AppLayout() {
  return (
    <AppShell>
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
        <Route path="/ai-report" element={<ProtectedRoute><AIReportPage /></ProtectedRoute>} />
        <Route path="/autopilot" element={<ProtectedRoute><AutopilotPage /></ProtectedRoute>} />
        <Route path="/ai-screener" element={<ProtectedRoute><AIAlphaScreener /></ProtectedRoute>} />
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
    </AppShell>
  );
}

function AppRouter() {
  const location = useLocation();

  if (location.pathname === '/') {
    return (
      <Suspense fallback={<LoadingState label="Carregando…" />}>
        <LandingPage />
      </Suspense>
    );
  }

  if (location.pathname === '/login') {
    return (
      <Suspense fallback={<LoadingState label="Carregando…" />}>
        <LoginPage />
      </Suspense>
    );
  }

  return <AppLayout />;
}

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <a className="atom-skip-link" href="#conteudo-principal">
          Ir para o conteúdo
        </a>
        <BrowserRouter>
          <AppRouter />
          <DisclaimerBanner />
        </BrowserRouter>
      </AuthProvider>
    </ThemeProvider>
  );
}
