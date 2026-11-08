import React, { Suspense, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  AppBar, Box, Chip, Divider, Drawer, IconButton, List, ListItemButton,
  ListItemIcon, ListItemText, Toolbar, Tooltip, Typography, useMediaQuery,
} from '@mui/material';
import {
  AccountBalance, Assessment, AutoFixHigh, AutoGraph, CallMerge, CurrencyExchange,
  DarkMode, FindInPage, Functions, LightMode, Menu as MenuIcon, MenuBook,
  MonetizationOn, Percent, Psychology, RocketLaunch, Science, ShowChart,
  Terminal, Timeline, TrendingUp, Warning, Waves, Logout,
} from '@mui/icons-material';
import { useThemeMode } from '../../theme/ThemeProvider';
import { useAuth } from '../../contexts/AuthContext';
import LoadingState from '../LoadingState';

const DRAWER_WIDTH = 272;

type NavItem = { label: string; path: string; icon: React.ReactNode };

const coreGroups: { title: string; hint?: string; items: NavItem[] }[] = [
  {
    title: 'Doutrina',
    items: [{ label: 'Doutrina da mesa', path: '/quant-doctrine', icon: <MenuBook /> }],
  },
  {
    title: 'Mesa',
    hint: 'Papers e o relógio da evidência.',
    items: [
      { label: 'Mesa de papers', path: '/desk', icon: <Functions /> },
      { label: 'Regimes', path: '/regime', icon: <Warning /> },
      { label: 'Maldição do vencedor', path: '/winners-curse', icon: <Timeline /> },
      { label: 'Teste sequencial', path: '/forward-test', icon: <Science /> },
      { label: 'Preço × retorno', path: '/target-choice', icon: <Percent /> },
    ],
  },
  {
    title: 'Paper-trading',
    hint: 'Simulação à mão. Sem corretora.',
    items: [
      { label: 'Fontes de mercado', path: '/sources', icon: <AccountBalance /> },
      { label: 'Mesa de derivativos', path: '/derivatives', icon: <ShowChart /> },
      { label: 'Operações simuladas', path: '/paper-trades', icon: <Timeline /> },
    ],
  },
  {
    title: 'Pesquisa',
    items: [
      { label: 'Diário de pesquisa', path: '/dashboard', icon: <Assessment /> },
      { label: 'Novo experimento', path: '/ml', icon: <Psychology /> },
      { label: 'Biblioteca QuantMind', path: '/research', icon: <FindInPage /> },
    ],
  },
];

const toolItems: NavItem[] = [
  { label: 'Options Pricing', path: '/pricing', icon: <ShowChart /> },
  { label: 'Strategies', path: '/strategies', icon: <Timeline /> },
  { label: 'Risk Analysis', path: '/risk', icon: <Assessment /> },
  { label: 'Portfolio', path: '/portfolio', icon: <AccountBalance /> },
  { label: 'Tail Risk', path: '/black-swan', icon: <Warning /> },
  { label: 'Backtesting', path: '/backtesting', icon: <Timeline /> },
  { label: 'Quant Terminal', path: '/terminal', icon: <Terminal /> },
  { label: 'Binance Crypto', path: '/binance', icon: <CurrencyExchange /> },
];

const exploratoryItems: NavItem[] = [
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

function NavRow({ item, selected, onClick }: { item: NavItem; selected: boolean; onClick: () => void }) {
  return (
    <ListItemButton
      selected={selected}
      onClick={onClick}
      aria-current={selected ? 'page' : undefined}
      sx={{
        mx: 1,
        borderRadius: 'var(--atom-radius-sm)',
        mb: 0.25,
        py: 0.7,
        position: 'relative',
        '&.Mui-selected::before': {
          content: '""',
          position: 'absolute',
          left: 0,
          top: 8,
          bottom: 8,
          width: 2,
          borderRadius: 2,
          bgcolor: 'primary.main',
        },
      }}
    >
      <ListItemIcon sx={{ minWidth: 36, color: selected ? 'primary.main' : 'text.secondary' }}>
        {item.icon}
      </ListItemIcon>
      <ListItemText
        primary={item.label}
        slotProps={{ primary: { fontSize: '0.82rem', fontWeight: selected ? 600 : 500 } }}
      />
    </ListItemButton>
  );
}

function GroupLabel({ text, hint }: { text: string; hint?: string }) {
  return (
    <Box sx={{ px: 2.5, pt: 2, pb: 0.5 }}>
      <Typography variant="overline">{text}</Typography>
      {hint && (
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', lineHeight: 1.4 }}>
          {hint}
        </Typography>
      )}
    </Box>
  );
}

export default function AppShell({ children }: { children: React.ReactNode }) {
  const [showAdvanced, setShowAdvanced] = useState(false);
  const { mode, toggle } = useThemeMode();
  const compact = useMediaQuery('(max-width:900px)');
  const [drawerOpen, setDrawerOpen] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const { user, logout } = useAuth();

  const go = (path: string) => {
    navigate(path);
    if (compact) setDrawerOpen(false);
  };

  const drawer = (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <Toolbar />
      <Box sx={{ overflow: 'auto', py: 1, flexGrow: 1 }}>
        <List disablePadding>
          {coreGroups.map((group) => (
            <Box key={group.title}>
              <GroupLabel text={group.title} hint={group.hint} />
              {group.items.map((item) => (
                <NavRow
                  key={item.path}
                  item={item}
                  selected={location.pathname === item.path}
                  onClick={() => go(item.path)}
                />
              ))}
            </Box>
          ))}
          {showAdvanced && (
            <>
              <GroupLabel text="Ferramentas" hint="Cálculo sobre entradas que você fornece." />
              {toolItems.map((item) => (
                <NavRow
                  key={item.path}
                  item={item}
                  selected={location.pathname === item.path}
                  onClick={() => go(item.path)}
                />
              ))}
              <GroupLabel
                text="Exploratórias"
                hint="Prometem previsão ou seleção. Sem validação fora da amostra — use o Laboratório Quant para evidência."
              />
              {exploratoryItems.map((item) => (
                <NavRow
                  key={item.path}
                  item={item}
                  selected={location.pathname === item.path}
                  onClick={() => go(item.path)}
                />
              ))}
            </>
          )}
        </List>
        <ListItemButton
          onClick={() => setShowAdvanced(!showAdvanced)}
          aria-expanded={showAdvanced}
          sx={{ mx: 1, mt: 1, borderRadius: 'var(--atom-radius-sm)' }}
        >
          <ListItemText
            primary={showAdvanced ? 'Ocultar ferramentas e exploratórias' : 'Ferramentas e exploratórias'}
            slotProps={{ primary: { fontSize: '0.78rem', color: 'text.secondary' } }}
          />
        </ListItemButton>
      </Box>
      <Divider />
      <Box sx={{ px: 2.5, pt: 1.5, pb: 8 }}>
        <Typography variant="caption" sx={{ display: 'block', fontFamily: 'var(--atom-font-mono)', color: 'primary.main' }}>
          ATOM Research
        </Typography>
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', lineHeight: 1.45 }}>
          Piloto local · paper-trading primeiro
          <br />
          Sem execução ao vivo
        </Typography>
      </Box>
    </Box>
  );

  return (
    <Box sx={{ display: 'flex', minHeight: '100vh', bgcolor: 'background.default' }}>
      <AppBar
        position="fixed"
        elevation={0}
        sx={{
          zIndex: (t) => t.zIndex.drawer + 1,
          bgcolor: 'color-mix(in srgb, var(--atom-bg-elevated) 92%, transparent)',
          backgroundImage: 'none',
          backdropFilter: 'blur(16px)',
          borderBottom: '1px solid',
          borderColor: 'divider',
          boxShadow: 'inset 0 1px 0 color-mix(in srgb, var(--atom-accent) 35%, transparent)',
        }}
      >
        <Toolbar>
          <IconButton
            aria-label="Alternar navegação"
            edge="start"
            onClick={() => setDrawerOpen(!drawerOpen)}
            sx={{ mr: 1.5 }}
          >
            <MenuIcon />
          </IconButton>
          <Box
            onClick={() => navigate('/dashboard')}
            onKeyDown={(e) => { if (e.key === 'Enter') navigate('/dashboard'); }}
            role="link"
            tabIndex={0}
            sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 1.25,
              cursor: 'pointer',
              borderRadius: 1,
              '&:hover': { opacity: 0.85 },
              '&:focus-visible': { outline: '2px solid', outlineColor: 'primary.main', outlineOffset: 4 },
            }}
          >
            <Box
              component="img"
              src="/atom.svg"
              alt=""
              sx={{ width: 28, height: 28, filter: 'drop-shadow(0 0 8px var(--atom-accent-glow))' }}
            />
            <Typography variant="h6" sx={{ fontWeight: 700, letterSpacing: '-0.03em' }}>
              ATOM
            </Typography>
            <Chip
              label="Research · piloto"
              size="small"
              sx={{ height: 22, fontSize: '0.68rem', display: { xs: 'none', sm: 'inline-flex' } }}
            />
          </Box>
          <Box sx={{ flexGrow: 1 }} />
          <Tooltip title={mode === 'dark' ? 'Mudar para tema claro' : 'Mudar para tema escuro'}>
            <IconButton onClick={toggle} aria-label="Alternar tema" sx={{ color: 'text.primary' }}>
              {mode === 'dark' ? <LightMode /> : <DarkMode />}
            </IconButton>
          </Tooltip>
          {user && (
            <Tooltip title={`Sair (${user.username})`}>
              <IconButton
                aria-label={`Sair (${user.username})`}
                onClick={() => { logout(); navigate('/login'); }}
                sx={{ color: 'text.secondary' }}
              >
                <Logout sx={{ fontSize: 20 }} />
              </IconButton>
            </Tooltip>
          )}
        </Toolbar>
      </AppBar>

      <Drawer
        variant={compact ? 'temporary' : 'persistent'}
        open={compact ? drawerOpen : !drawerOpen}
        onClose={() => setDrawerOpen(false)}
        sx={{
          width: compact ? 0 : !drawerOpen ? DRAWER_WIDTH : 0,
          flexShrink: 0,
          '& .MuiDrawer-paper': {
            width: DRAWER_WIDTH,
            boxSizing: 'border-box',
            borderRight: '1px solid',
            borderColor: 'divider',
            bgcolor: 'var(--atom-bg-elevated)',
            backgroundImage: 'none',
          },
        }}
      >
        {drawer}
      </Drawer>

      <Box
        component="main"
        id="conteudo-principal"
        sx={{
          flexGrow: 1,
          p: { xs: 2, md: 3.5 },
          pb: 8,
          mt: '64px',
          maxWidth: '100%',
          overflow: 'hidden',
          minWidth: 0,
        }}
      >
        <Suspense fallback={<LoadingState label="Carregando a mesa…" />}>
          {children}
        </Suspense>
      </Box>
    </Box>
  );
}
