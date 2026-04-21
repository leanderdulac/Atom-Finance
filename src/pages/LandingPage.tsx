import React from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Container,
  Divider,
  Grid,
  Stack,
  Typography,
} from '@mui/material';
import { keyframes } from '@mui/system';
import {
  ArrowForward,
  AutoGraph,
  Bolt,
  CheckCircle,
  CrisisAlert,
  Domain,
  Hub,
  Insights,
  Layers,
  Lock,
  Psychology,
  QueryStats,
  RocketLaunch,
  Shield,
  Timeline,
  Water,
} from '@mui/icons-material';

const metrics = [
  { value: '9', label: 'Core analytics modules' },
  { value: '20+', label: 'Quant endpoints' },
  { value: 'OpenBB', label: 'Market data backbone' },
  { value: 'FastAPI', label: 'Execution-ready services' },
];

const modules = [
  {
    title: 'Pricing Engine',
    description: 'Black-Scholes, Monte Carlo, binomial trees and finite difference pricing with Greeks.',
    icon: <AutoGraph sx={{ fontSize: 34, color: '#7c3aed' }} />,
  },
  {
    title: 'Portfolio Lab',
    description: 'Markowitz, max Sharpe and risk parity workflows over live multi-asset histories.',
    icon: <Layers sx={{ fontSize: 34, color: '#2563eb' }} />,
  },
  {
    title: 'Risk Command',
    description: 'VaR, CVaR, stress testing and regime diagnostics for institutional risk visibility.',
    icon: <Shield sx={{ fontSize: 34, color: '#059669' }} />,
  },
  {
    title: 'Strategy Studio',
    description: 'Structured options workflows with payoff, premium and sensitivity analysis.',
    icon: <Timeline sx={{ fontSize: 34, color: '#f59e0b' }} />,
  },
  {
    title: 'ML Forecasting',
    description: 'Predictive modeling modules for signals, scenarios and comparative model research.',
    icon: <Psychology sx={{ fontSize: 34, color: '#ec4899' }} />,
  },
  {
    title: 'Microstructure Signals',
    description: 'Ghost liquidity and black swan detection to surface hidden fragility early.',
    icon: <Water sx={{ fontSize: 34, color: '#06b6d4' }} />,
  },
];

const pillars = [
  {
    title: 'Research infrastructure',
    description: 'A unified environment for market discovery, pricing, allocation, risk and validation.',
    icon: <Domain sx={{ fontSize: 30, color: '#7c3aed' }} />,
  },
  {
    title: 'Control and resilience',
    description: 'Provider routing, synthetic fallback and modular services for continuity under stress.',
    icon: <Lock sx={{ fontSize: 30, color: '#059669' }} />,
  },
  {
    title: 'Commercial readiness',
    description: 'Product language and interface quality aligned with startup pitches and institutional demos.',
    icon: <RocketLaunch sx={{ fontSize: 30, color: '#2563eb' }} />,
  },
];

const workflows = [
  'Search a symbol and pull live market context',
  'Price derivatives or build an options structure',
  'Measure portfolio concentration, stress and downside',
  'Backtest, compare outcomes and refine the thesis',
];

const useCases = [
  'Buy-side and sell-side derivatives research',
  'Portfolio committee scenario analysis',
  'Risk oversight and market surveillance workflows',
  'Investor demos for quant products and analytics startups',
];

const architectureBlocks = [
  {
    title: 'Data Layer',
    text: 'OpenBB and external providers with fallback routing, live quotes, historical series and ticker discovery.',
  },
  {
    title: 'Analytics Layer',
    text: 'Pricing, strategies, risk, optimization, ML and anomaly engines exposed through composable services.',
  },
  {
    title: 'Experience Layer',
    text: 'A React-based interface tailored for analysts, PMs, quants and decision-makers.',
  },
];

const quantFoundations = [
  {
    title: 'Stochastic calculus',
    description: 'Geometric Brownian motion and Itô calculus provide the continuous-time language behind asset paths, hedge ratios and dynamic state evolution.',
  },
  {
    title: 'Black-Scholes-Merton',
    description: 'Risk-neutral pricing and PDE-based valuation remain the reference layer for European options, Greeks and analytical benchmarking.',
  },
  {
    title: 'Extreme value theory',
    description: 'EVT and tail metrics improve the modeling of crashes, discontinuities and rare losses that standard Gaussian assumptions underestimate.',
  },
  {
    title: 'Monte Carlo engines',
    description: 'Path simulation scales valuation and scenario generation when products, payoff structures or risk systems become too complex for closed forms.',
  },
  {
    title: 'Machine learning and RL',
    description: 'Non-linear prediction, feature extraction and adaptive policies extend classical quant workflows into data-rich forecasting and execution regimes.',
  },
];

const convergenceThemes = [
  'Use AI to calibrate stochastic models and infer parameters from noisy market regimes.',
  'Feed EVT-based tail behavior into Monte Carlo scenario design for more realistic downside distributions.',
  'Model multi-factor dependence under stress through copula-style thinking and regime-aware diagnostics.',
  'Transfer the same architecture to climate derivatives, catastrophe insurance and systemic tipping-point analysis.',
];

const dataSources = ['OpenBB', 'Yahoo Finance', 'Synthetic fallback', 'FastAPI APIs', 'React dashboard'];

const heroSignals = [
  { label: 'AAPL', value: '+2.14%', tone: '#22c55e' },
  { label: 'NVDA', value: '+4.82%', tone: '#38bdf8' },
  { label: 'TSLA', value: '-1.06%', tone: '#f97316' },
];

const heroBars = [58, 72, 64, 88, 76, 94, 67, 81];

const heroPreviewRows = [
  { label: 'Live pricing', value: 'Black-Scholes / MC synced' },
  { label: 'Risk snapshot', value: 'VaR and tail alerts active' },
  { label: 'Portfolio state', value: 'Max Sharpe allocation loaded' },
];

const pulseGlow = keyframes`
  0%, 100% { transform: scale(1); opacity: 0.75; }
  50% { transform: scale(1.08); opacity: 1; }
`;

const floatCard = keyframes`
  0%, 100% { transform: translateY(0px) rotate(-6deg); }
  50% { transform: translateY(-10px) rotate(-4deg); }
`;

const breathe = keyframes`
  0%, 100% { transform: translateY(0px); box-shadow: 0 30px 100px rgba(2,6,23,0.48); }
  50% { transform: translateY(-6px); box-shadow: 0 36px 110px rgba(2,6,23,0.56); }
`;

const shimmer = keyframes`
  0%, 100% { opacity: 0.72; }
  50% { opacity: 1; }
`;

const LandingPage: React.FC = () => {
  const navigate = useNavigate();

  return (
    <Box sx={{ bgcolor: 'background.default', minHeight: '100vh' }}>
      <Box
        sx={{
          position: 'relative',
          overflow: 'hidden',
          background:
            'radial-gradient(circle at top left, rgba(99,102,241,0.35), transparent 28%), radial-gradient(circle at top right, rgba(6,182,212,0.28), transparent 24%), linear-gradient(180deg, rgba(15,23,42,1) 0%, rgba(10,14,30,1) 100%)',
          color: '#fff',
          pb: { xs: 8, md: 12 },
        }}
      >
        <Box
          sx={{
            position: 'absolute',
            inset: 0,
            backgroundImage:
              'linear-gradient(rgba(255,255,255,0.035) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.035) 1px, transparent 1px)',
            backgroundSize: '42px 42px',
            maskImage: 'linear-gradient(180deg, rgba(0,0,0,0.9), transparent)',
            opacity: 0.45,
          }}
        />
        <Box
          sx={{
            position: 'absolute',
            top: 120,
            right: -120,
            width: 380,
            height: 380,
            borderRadius: '50%',
            background: 'radial-gradient(circle, rgba(59,130,246,0.28) 0%, rgba(59,130,246,0) 70%)',
            filter: 'blur(30px)',
            animation: `${pulseGlow} 10s ease-in-out infinite`,
          }}
        />
        <Box
          sx={{
            position: 'absolute',
            top: 60,
            left: -80,
            width: 320,
            height: 320,
            borderRadius: '50%',
            background: 'radial-gradient(circle, rgba(124,58,237,0.24) 0%, rgba(124,58,237,0) 72%)',
            filter: 'blur(26px)',
            animation: `${pulseGlow} 12s ease-in-out infinite`,
          }}
        />
        <Container maxWidth="lg">
          <Box
            sx={{
              py: 2.5,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 2,
              flexWrap: 'wrap',
            }}
          >
            <Stack direction="row" spacing={1.5} alignItems="center">
              <Box component="img" src="/atom.svg" alt="ATOM" sx={{ width: 36, height: 36 }} />
              <Box>
                <Typography variant="h6" sx={{ fontWeight: 800, lineHeight: 1 }}>
                  ATOM
                </Typography>
                <Typography variant="caption" sx={{ opacity: 0.72 }}>
                  Advanced Trading & Options Modeler
                </Typography>
              </Box>
            </Stack>

            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
              <Button variant="text" sx={{ color: 'rgba(255,255,255,0.85)' }} onClick={() => navigate('/pricing')}>
                Pricing
              </Button>
              <Button variant="text" sx={{ color: 'rgba(255,255,255,0.85)' }} onClick={() => navigate('/portfolio')}>
                Portfolio
              </Button>
              <Button variant="contained" onClick={() => navigate('/dashboard')}>
                Open Platform
              </Button>
            </Stack>
          </Box>

          <Grid container spacing={4} sx={{ pt: { xs: 5, md: 8 }, alignItems: 'center' }}>
            <Grid size={{ xs: 12, md: 7 }}>
              <Chip
                icon={<Bolt />}
                label="Institutional-grade quant workflow for research, risk and decision support"
                sx={{
                  mb: 3,
                  color: '#fff',
                  bgcolor: 'rgba(255,255,255,0.08)',
                  border: '1px solid rgba(255,255,255,0.12)',
                  animation: `${shimmer} 6s ease-in-out infinite`,
                }}
              />

              <Typography
                variant="h1"
                sx={{
                  fontSize: { xs: '2.8rem', md: '4.4rem' },
                  lineHeight: 0.96,
                  fontWeight: 900,
                  letterSpacing: '-0.04em',
                  mb: 2,
                }}
              >
                Premium quant infrastructure for modern capital markets teams.
              </Typography>

              <Typography
                variant="h6"
                sx={{
                  maxWidth: 760,
                  color: 'rgba(255,255,255,0.78)',
                  fontWeight: 400,
                  lineHeight: 1.6,
                  mb: 4,
                }}
              >
                ATOM unifies derivatives pricing, portfolio optimization, backtesting, machine learning and market microstructure diagnostics in a product designed to look credible in front of investors, funds, desks and enterprise stakeholders.
              </Typography>

              <Grid container spacing={1.5} sx={{ mb: 4, maxWidth: 720 }}>
                {metrics.map((metric) => (
                  <Grid key={metric.label} size={{ xs: 6, sm: 3 }}>
                    <Box
                      sx={{
                        p: 1.75,
                        borderRadius: 3,
                        bgcolor: 'rgba(255,255,255,0.06)',
                        border: '1px solid rgba(255,255,255,0.08)',
                        backdropFilter: 'blur(6px)',
                      }}
                    >
                      <Typography variant="h6" sx={{ fontWeight: 900, mb: 0.25 }}>
                        {metric.value}
                      </Typography>
                      <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.68)', lineHeight: 1.4 }}>
                        {metric.label}
                      </Typography>
                    </Box>
                  </Grid>
                ))}
              </Grid>

              <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ mb: 4 }}>
                <Button
                  size="large"
                  variant="contained"
                  endIcon={<ArrowForward />}
                  onClick={() => navigate('/dashboard')}
                  sx={{ px: 3.5, py: 1.4, fontWeight: 700 }}
                >
                  Launch Dashboard
                </Button>
                <Button
                  size="large"
                  variant="outlined"
                  onClick={() => navigate('/strategies')}
                  sx={{
                    px: 3.5,
                    py: 1.4,
                    fontWeight: 700,
                    color: '#fff',
                    borderColor: 'rgba(255,255,255,0.28)',
                  }}
                >
                  Explore Strategies
                </Button>
              </Stack>

              <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                {['OpenBB integration', 'Live quotes', 'Risk engines', 'Backtesting', 'Options strategies'].map((item) => (
                  <Chip
                    key={item}
                    label={item}
                    sx={{
                      color: '#fff',
                      bgcolor: 'rgba(255,255,255,0.08)',
                      border: '1px solid rgba(255,255,255,0.08)',
                    }}
                  />
                ))}
              </Stack>
            </Grid>

            <Grid size={{ xs: 12, md: 5 }}>
              <Box sx={{ position: 'relative', minHeight: 560 }}>
                <Card
                  sx={{
                    position: 'relative',
                    zIndex: 2,
                    borderRadius: 5,
                    bgcolor: 'rgba(15,23,42,0.78)',
                    color: '#fff',
                    border: '1px solid rgba(255,255,255,0.08)',
                    boxShadow: '0 30px 100px rgba(2,6,23,0.48)',
                    backdropFilter: 'blur(14px)',
                    overflow: 'hidden',
                    animation: `${breathe} 8s ease-in-out infinite`,
                  }}
                >
                  <CardContent sx={{ p: 0 }}>
                    <Box sx={{ p: 2.5, borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
                      <Stack direction="row" justifyContent="space-between" alignItems="center">
                        <Box>
                          <Typography variant="overline" sx={{ letterSpacing: '0.12em', color: 'rgba(255,255,255,0.58)' }}>
                            Executive cockpit
                          </Typography>
                          <Typography variant="h5" sx={{ fontWeight: 800 }}>
                            Capital markets control layer
                          </Typography>
                        </Box>
                        <Chip
                          label="Live"
                          size="small"
                          sx={{ bgcolor: 'rgba(34,197,94,0.16)', color: '#86efac', fontWeight: 700 }}
                        />
                      </Stack>
                    </Box>

                    <Box sx={{ p: 2.5 }}>
                      <Grid container spacing={1.5} sx={{ mb: 2.5 }}>
                        {heroSignals.map((signal) => (
                          <Grid key={signal.label} size={{ xs: 4 }}>
                            <Box
                              sx={{
                                p: 1.5,
                                borderRadius: 3,
                                bgcolor: 'rgba(255,255,255,0.04)',
                                border: '1px solid rgba(255,255,255,0.06)',
                              }}
                            >
                              <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.6)' }}>
                                {signal.label}
                              </Typography>
                              <Typography sx={{ fontWeight: 800, color: signal.tone }}>
                                {signal.value}
                              </Typography>
                            </Box>
                          </Grid>
                        ))}
                      </Grid>

                      <Box
                        sx={{
                          p: 2.25,
                          borderRadius: 4,
                          background: 'linear-gradient(180deg, rgba(30,41,59,0.82) 0%, rgba(15,23,42,0.92) 100%)',
                          border: '1px solid rgba(255,255,255,0.06)',
                          mb: 2.5,
                        }}
                      >
                        <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 2 }}>
                          <Box>
                            <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.58)' }}>
                              Portfolio risk surface
                            </Typography>
                            <Typography variant="h6" sx={{ fontWeight: 800 }}>
                              Intraday regime monitor
                            </Typography>
                          </Box>
                          <QueryStats sx={{ color: '#a5b4fc' }} />
                        </Stack>

                        <Box sx={{ display: 'flex', alignItems: 'flex-end', gap: 1, height: 120 }}>
                          {heroBars.map((bar, index) => (
                            <Box
                              key={`${bar}-${index}`}
                              sx={{
                                flex: 1,
                                height: `${bar}%`,
                                borderRadius: 999,
                                background: index > 5
                                  ? 'linear-gradient(180deg, #22c55e 0%, rgba(34,197,94,0.15) 100%)'
                                  : 'linear-gradient(180deg, #60a5fa 0%, rgba(96,165,250,0.12) 100%)',
                                boxShadow: 'inset 0 -10px 18px rgba(15,23,42,0.18)',
                                transformOrigin: 'bottom',
                                animation: `${shimmer} ${3 + index * 0.25}s ease-in-out infinite`,
                              }}
                            />
                          ))}
                        </Box>
                      </Box>

                      <Box
                        sx={{
                          p: 2,
                          borderRadius: 4,
                          bgcolor: 'rgba(255,255,255,0.03)',
                          border: '1px solid rgba(255,255,255,0.06)',
                          mb: 2.5,
                        }}
                      >
                        <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1.5 }}>
                          <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.58)' }}>
                            Dashboard preview
                          </Typography>
                          <Chip label="Preview" size="small" sx={{ bgcolor: 'rgba(96,165,250,0.14)', color: '#93c5fd' }} />
                        </Stack>
                        <Stack spacing={1.2}>
                          {heroPreviewRows.map((row) => (
                            <Box
                              key={row.label}
                              sx={{
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'space-between',
                                gap: 2,
                                p: 1.25,
                                borderRadius: 2.5,
                                bgcolor: 'rgba(15,23,42,0.55)',
                                border: '1px solid rgba(255,255,255,0.04)',
                              }}
                            >
                              <Typography variant="body2" sx={{ color: 'rgba(255,255,255,0.62)' }}>
                                {row.label}
                              </Typography>
                              <Typography variant="body2" sx={{ fontWeight: 700 }}>
                                {row.value}
                              </Typography>
                            </Box>
                          ))}
                        </Stack>
                      </Box>

                      <Grid container spacing={1.5}>
                        <Grid size={{ xs: 7 }}>
                          <Box
                            sx={{
                              p: 2,
                              borderRadius: 3,
                              bgcolor: 'rgba(99,102,241,0.12)',
                              border: '1px solid rgba(99,102,241,0.24)',
                              height: '100%',
                            }}
                          >
                            <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.58)' }}>
                              Strategy status
                            </Typography>
                            <Typography variant="h6" sx={{ fontWeight: 800, mt: 0.5, mb: 0.75 }}>
                              Risk-on with volatility control
                            </Typography>
                            <Typography variant="body2" sx={{ color: 'rgba(255,255,255,0.72)', lineHeight: 1.7 }}>
                              Pricing, risk and portfolio modules aligned under a single research workflow.
                            </Typography>
                          </Box>
                        </Grid>
                        <Grid size={{ xs: 5 }}>
                          <Stack spacing={1.5}>
                            <Box
                              sx={{
                                p: 1.75,
                                borderRadius: 3,
                                bgcolor: 'rgba(255,255,255,0.04)',
                                border: '1px solid rgba(255,255,255,0.06)',
                              }}
                            >
                              <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.58)' }}>
                                Sharpe focus
                              </Typography>
                              <Typography variant="h6" sx={{ fontWeight: 900 }}>
                                1.84
                              </Typography>
                            </Box>
                            <Box
                              sx={{
                                p: 1.75,
                                borderRadius: 3,
                                bgcolor: 'rgba(255,255,255,0.04)',
                                border: '1px solid rgba(255,255,255,0.06)',
                              }}
                            >
                              <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.58)' }}>
                                Tail alert
                              </Typography>
                              <Typography variant="h6" sx={{ fontWeight: 900, color: '#fbbf24' }}>
                                Low
                              </Typography>
                            </Box>
                          </Stack>
                        </Grid>
                      </Grid>
                    </Box>
                  </CardContent>
                </Card>

                <Card
                  sx={{
                    position: 'absolute',
                    right: -12,
                    bottom: 28,
                    width: { xs: 220, md: 240 },
                    zIndex: 1,
                    borderRadius: 4,
                    transform: 'rotate(-6deg)',
                    bgcolor: 'rgba(8,15,30,0.78)',
                    color: '#fff',
                    border: '1px solid rgba(255,255,255,0.06)',
                    boxShadow: '0 24px 60px rgba(2,6,23,0.4)',
                    animation: `${floatCard} 9s ease-in-out infinite`,
                  }}
                >
                  <CardContent sx={{ p: 2 }}>
                    <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.58)' }}>
                      Executive summary
                    </Typography>
                    <Typography variant="h6" sx={{ fontWeight: 800, mb: 1.25 }}>
                      Portfolio upshift
                    </Typography>
                    <Stack spacing={1}>
                      {['Greeks synchronized', 'Risk within limits', 'Providers connected'].map((item) => (
                        <Box key={item} sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                          <CheckCircle sx={{ fontSize: 16, color: '#86efac' }} />
                          <Typography variant="body2" sx={{ color: 'rgba(255,255,255,0.72)' }}>
                            {item}
                          </Typography>
                        </Box>
                      ))}
                    </Stack>
                  </CardContent>
                </Card>
              </Box>
            </Grid>
          </Grid>
        </Container>
      </Box>

      <Container maxWidth="lg" sx={{ py: { xs: 6, md: 8 } }}>
        <Grid container spacing={3}>
          {pillars.map((pillar) => (
            <Grid key={pillar.title} size={{ xs: 12, md: 4 }}>
              <Card sx={{ height: '100%', borderRadius: 4, border: 1, borderColor: 'divider' }}>
                <CardContent sx={{ p: 3 }}>
                  <Box sx={{ mb: 1.5 }}>{pillar.icon}</Box>
                  <Typography variant="h6" sx={{ fontWeight: 800, mb: 1 }}>
                    {pillar.title}
                  </Typography>
                  <Typography color="text.secondary" sx={{ lineHeight: 1.8 }}>
                    {pillar.description}
                  </Typography>
                </CardContent>
              </Card>
            </Grid>
          ))}
        </Grid>
      </Container>

      <Container maxWidth="lg" sx={{ py: { xs: 2, md: 5 } }}>
        <Grid container spacing={2}>
          {metrics.map((metric) => (
            <Grid key={metric.label} size={{ xs: 6, md: 3 }}>
              <Card sx={{ height: '100%', borderRadius: 4, border: 1, borderColor: 'divider' }}>
                <CardContent>
                  <Typography variant="h4" sx={{ fontWeight: 900, mb: 0.5 }}>
                    {metric.value}
                  </Typography>
                  <Typography color="text.secondary">{metric.label}</Typography>
                </CardContent>
              </Card>
            </Grid>
          ))}
        </Grid>
      </Container>

      <Divider />

      <Container maxWidth="lg" sx={{ py: { xs: 7, md: 10 } }}>
        <Box sx={{ textAlign: 'center', mb: 5.5 }}>
          <Chip label="Quant foundations" color="primary" variant="outlined" sx={{ mb: 2 }} />
          <Typography variant="h3" sx={{ fontWeight: 900, mb: 2 }}>
            Mathematical infrastructure, not just interface polish
          </Typography>
          <Typography variant="body1" color="text.secondary" sx={{ maxWidth: 860, mx: 'auto', lineHeight: 1.8 }}>
            ATOM is being shaped around the actual spine of quantitative finance: stochastic calculus, Black-Scholes-Merton, tail-risk modeling, Monte Carlo simulation and machine learning workflows that can be reused beyond traditional markets.
          </Typography>
        </Box>

        <Grid container spacing={3} sx={{ mb: 3 }}>
          {quantFoundations.map((item) => (
            <Grid key={item.title} size={{ xs: 12, sm: 6, md: 4 }}>
              <Card sx={{ height: '100%', borderRadius: 4, border: 1, borderColor: 'divider' }}>
                <CardContent sx={{ p: 3 }}>
                  <Typography variant="h6" sx={{ fontWeight: 800, mb: 1.2 }}>
                    {item.title}
                  </Typography>
                  <Typography color="text.secondary" sx={{ lineHeight: 1.8 }}>
                    {item.description}
                  </Typography>
                </CardContent>
              </Card>
            </Grid>
          ))}
        </Grid>

        <Card sx={{ borderRadius: 4, border: 1, borderColor: 'divider' }}>
          <CardContent sx={{ p: { xs: 3, md: 3.5 } }}>
            <Typography variant="overline" color="text.secondary">
              Convergence layer
            </Typography>
            <Typography variant="h5" sx={{ fontWeight: 900, mb: 2 }}>
              EVT, AI and Monte Carlo belong in the same development roadmap
            </Typography>
            <Grid container spacing={2}>
              {convergenceThemes.map((item) => (
                <Grid key={item} size={{ xs: 12, md: 6 }}>
                  <Box sx={{ display: 'flex', gap: 1.25, alignItems: 'flex-start' }}>
                    <CheckCircle sx={{ color: 'success.main', fontSize: 20, mt: 0.2 }} />
                    <Typography color="text.secondary" sx={{ lineHeight: 1.8 }}>
                      {item}
                    </Typography>
                  </Box>
                </Grid>
              ))}
            </Grid>
          </CardContent>
        </Card>
      </Container>

      <Divider />

      <Container maxWidth="lg" sx={{ py: { xs: 7, md: 10 } }}>
        <Grid container spacing={4} alignItems="center">
          <Grid size={{ xs: 12, md: 5 }}>
            <Chip label="Positioning" color="secondary" variant="outlined" sx={{ mb: 2 }} />
            <Typography variant="h3" sx={{ fontWeight: 900, mb: 2 }}>
              Built to communicate maturity, not just functionality
            </Typography>
            <Typography color="text.secondary" sx={{ lineHeight: 1.9, mb: 3 }}>
              The product narrative, interface structure and modular architecture are shaped to support institutional demos, startup fundraising conversations and internal committees.
            </Typography>
            <Stack spacing={1.4}>
              {useCases.map((item) => (
                <Box key={item} sx={{ display: 'flex', alignItems: 'center', gap: 1.2 }}>
                  <CheckCircle sx={{ color: 'success.main', fontSize: 20 }} />
                  <Typography>{item}</Typography>
                </Box>
              ))}
            </Stack>
          </Grid>
          <Grid size={{ xs: 12, md: 7 }}>
            <Card sx={{ borderRadius: 4, border: 1, borderColor: 'divider' }}>
              <CardContent sx={{ p: 3.5 }}>
                <Typography variant="overline" color="text.secondary">
                  Operating architecture
                </Typography>
                <Grid container spacing={2} sx={{ mt: 0.5 }}>
                  {architectureBlocks.map((block, index) => (
                    <Grid key={block.title} size={{ xs: 12 }}>
                      <Box sx={{ display: 'flex', gap: 2, alignItems: 'flex-start' }}>
                        <Box
                          sx={{
                            width: 34,
                            height: 34,
                            borderRadius: 2,
                            bgcolor: 'primary.main',
                            color: '#fff',
                            display: 'grid',
                            placeItems: 'center',
                            fontWeight: 800,
                            flexShrink: 0,
                          }}
                        >
                          {index + 1}
                        </Box>
                        <Box>
                          <Typography variant="h6" sx={{ fontWeight: 800, mb: 0.4 }}>
                            {block.title}
                          </Typography>
                          <Typography color="text.secondary" sx={{ lineHeight: 1.8 }}>
                            {block.text}
                          </Typography>
                        </Box>
                      </Box>
                    </Grid>
                  ))}
                </Grid>
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      </Container>

      <Divider />

      <Container maxWidth="lg" sx={{ py: { xs: 7, md: 10 } }}>
        <Box sx={{ textAlign: 'center', mb: 6 }}>
          <Chip label="Modules" color="primary" variant="outlined" sx={{ mb: 2 }} />
          <Typography variant="h3" sx={{ fontWeight: 900, mb: 2 }}>
            A complete operating system for quantitative finance
          </Typography>
          <Typography variant="body1" color="text.secondary" sx={{ maxWidth: 760, mx: 'auto', lineHeight: 1.8 }}>
            Each module is designed to work independently and together, so the same research flow can move from market discovery to pricing, hedging, allocation and validation.
          </Typography>
        </Box>

        <Grid container spacing={3}>
          {modules.map((module) => (
            <Grid key={module.title} size={{ xs: 12, sm: 6, md: 4 }}>
              <Card sx={{ height: '100%', borderRadius: 4, border: 1, borderColor: 'divider' }}>
                <CardContent sx={{ p: 3 }}>
                  <Box sx={{ mb: 2 }}>{module.icon}</Box>
                  <Typography variant="h6" sx={{ fontWeight: 800, mb: 1.2 }}>
                    {module.title}
                  </Typography>
                  <Typography color="text.secondary" sx={{ lineHeight: 1.8 }}>
                    {module.description}
                  </Typography>
                </CardContent>
              </Card>
            </Grid>
          ))}
        </Grid>
      </Container>

      <Divider />

      <Container maxWidth="lg" sx={{ py: { xs: 7, md: 10 } }}>
        <Grid container spacing={4} alignItems="stretch">
          <Grid size={{ xs: 12, md: 6 }}>
            <Card sx={{ height: '100%', borderRadius: 4, border: 1, borderColor: 'divider' }}>
              <CardContent sx={{ p: 3.5 }}>
                <Chip label="Workflow" color="secondary" variant="outlined" sx={{ mb: 2 }} />
                <Typography variant="h4" sx={{ fontWeight: 900, mb: 2 }}>
                  From idea to validation
                </Typography>
                <Stack spacing={2.25}>
                  {workflows.map((step, index) => (
                    <Box key={step} sx={{ display: 'flex', gap: 2, alignItems: 'flex-start' }}>
                      <Box
                        sx={{
                          width: 32,
                          height: 32,
                          borderRadius: '50%',
                          bgcolor: 'primary.main',
                          color: '#fff',
                          display: 'grid',
                          placeItems: 'center',
                          fontWeight: 800,
                          flexShrink: 0,
                        }}
                      >
                        {index + 1}
                      </Box>
                      <Typography sx={{ pt: 0.4, lineHeight: 1.7 }}>{step}</Typography>
                    </Box>
                  ))}
                </Stack>
              </CardContent>
            </Card>
          </Grid>

          <Grid size={{ xs: 12, md: 6 }}>
            <Card sx={{ height: '100%', borderRadius: 4, border: 1, borderColor: 'divider' }}>
              <CardContent sx={{ p: 3.5 }}>
                <Chip label="Data stack" color="info" variant="outlined" sx={{ mb: 2 }} />
                <Typography variant="h4" sx={{ fontWeight: 900, mb: 2 }}>
                  Connected to real market inputs
                </Typography>
                <Typography color="text.secondary" sx={{ mb: 3, lineHeight: 1.8 }}>
                  ATOM supports real quotes and historical data through provider routing, with resilient fallback behavior to keep the platform usable during provider outages.
                </Typography>
                <Grid container spacing={1.5}>
                  {dataSources.map((item) => (
                    <Grid key={item} size={{ xs: 12, sm: 6 }}>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.25 }}>
                        <CheckCircle sx={{ color: 'success.main', fontSize: 20 }} />
                        <Typography>{item}</Typography>
                      </Box>
                    </Grid>
                  ))}
                </Grid>
                <Box
                  sx={{
                    mt: 3,
                    p: 2,
                    borderRadius: 3,
                    bgcolor: 'action.hover',
                    display: 'flex',
                    gap: 1.5,
                    alignItems: 'center',
                  }}
                >
                  <Hub color="primary" />
                  <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.7 }}>
                    OpenBB powers the market-data pipeline while the frontend exposes ticker search, provider switching and live prefilling across the core product surfaces.
                  </Typography>
                </Box>
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      </Container>

      <Divider />

      <Container maxWidth="lg" sx={{ py: { xs: 7, md: 10 } }}>
        <Grid container spacing={3}>
          <Grid size={{ xs: 12, md: 4 }}>
            <Card sx={{ height: '100%', borderRadius: 4, border: 1, borderColor: 'divider' }}>
              <CardContent sx={{ p: 3 }}>
                <Insights sx={{ color: '#7c3aed', fontSize: 32, mb: 1.5 }} />
                <Typography variant="h6" sx={{ fontWeight: 800, mb: 1.2 }}>
                  Analytics-first UX
                </Typography>
                <Typography color="text.secondary" sx={{ lineHeight: 1.8 }}>
                  Designed to move quickly between provider-backed inputs, raw outputs and reusable quantitative workflows.
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid size={{ xs: 12, md: 4 }}>
            <Card sx={{ height: '100%', borderRadius: 4, border: 1, borderColor: 'divider' }}>
              <CardContent sx={{ p: 3 }}>
                <CrisisAlert sx={{ color: '#ef4444', fontSize: 32, mb: 1.5 }} />
                <Typography variant="h6" sx={{ fontWeight: 800, mb: 1.2 }}>
                  Stress-ready engines
                </Typography>
                <Typography color="text.secondary" sx={{ lineHeight: 1.8 }}>
                  Built to assess downside, volatility regimes and fragility through dedicated black swan and risk modules.
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid size={{ xs: 12, md: 4 }}>
            <Card sx={{ height: '100%', borderRadius: 4, border: 1, borderColor: 'divider' }}>
              <CardContent sx={{ p: 3 }}>
                <QueryStats sx={{ color: '#06b6d4', fontSize: 32, mb: 1.5 }} />
                <Typography variant="h6" sx={{ fontWeight: 800, mb: 1.2 }}>
                  Research to execution loop
                </Typography>
                <Typography color="text.secondary" sx={{ lineHeight: 1.8 }}>
                  A single workspace for symbol discovery, derivative pricing, portfolio construction and strategy replay.
                </Typography>
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      </Container>

      <Divider />

      <Container maxWidth="lg" sx={{ py: { xs: 7, md: 10 } }}>
        <Card sx={{ borderRadius: 4, border: 1, borderColor: 'divider' }}>
          <CardContent sx={{ p: { xs: 3, md: 4 } }}>
            <Grid container spacing={3} alignItems="center">
              <Grid size={{ xs: 12, md: 8 }}>
                <Chip label="Institutional message" color="primary" variant="outlined" sx={{ mb: 2 }} />
                <Typography variant="h4" sx={{ fontWeight: 900, mb: 1.5 }}>
                  ATOM presents as a platform, not a prototype
                </Typography>
                <Typography color="text.secondary" sx={{ lineHeight: 1.9 }}>
                  The landing page, module framing and data integration now communicate a clearer startup/institutional identity: modern product, credible architecture and business-ready positioning.
                </Typography>
              </Grid>
              <Grid size={{ xs: 12, md: 4 }}>
                <Stack spacing={1.2}>
                  <Button variant="contained" size="large" onClick={() => navigate('/dashboard')} endIcon={<ArrowForward />}>
                    Enter Platform
                  </Button>
                  <Button variant="outlined" size="large" onClick={() => navigate('/portfolio')}>
                    View Portfolio Lab
                  </Button>
                </Stack>
              </Grid>
            </Grid>
          </CardContent>
        </Card>
      </Container>

      <Box sx={{ py: { xs: 8, md: 10 }, bgcolor: 'background.paper', borderTop: 1, borderColor: 'divider' }}>
        <Container maxWidth="md">
          <Card
            sx={{
              borderRadius: 5,
              border: 1,
              borderColor: 'divider',
              background: 'linear-gradient(135deg, rgba(99,102,241,0.08) 0%, rgba(6,182,212,0.08) 100%)',
            }}
          >
            <CardContent sx={{ p: { xs: 3, md: 5 }, textAlign: 'center' }}>
              <Typography variant="h3" sx={{ fontWeight: 900, mb: 1.5 }}>
                Ready to operate the full ATOM stack?
              </Typography>
              <Typography color="text.secondary" sx={{ mb: 3.5, lineHeight: 1.8 }}>
                Open the dashboard to access a modular quant stack built for research velocity and institutional presentation quality.
              </Typography>
              <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} justifyContent="center">
                <Button variant="contained" size="large" onClick={() => navigate('/dashboard')} endIcon={<ArrowForward />}>
                  Go to Dashboard
                </Button>
                <Button variant="outlined" size="large" onClick={() => navigate('/backtesting')}>
                  Run Backtests
                </Button>
              </Stack>
            </CardContent>
          </Card>

          <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center', mt: 4 }}>
            ATOM · Quantitative Finance Platform · Pricing, Risk, Portfolio, ML and Market Data
          </Typography>
        </Container>
      </Box>
    </Box>
  );
};

export default LandingPage;
