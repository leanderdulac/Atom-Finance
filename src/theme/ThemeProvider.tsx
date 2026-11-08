import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { ThemeProvider as MUIThemeProvider, createTheme, CssBaseline } from '@mui/material';
import { dark, fonts, light, radii, type PaletteTokens } from './tokens';

type ThemeMode = 'dark' | 'light';

interface ThemeContextType {
  mode: ThemeMode;
  toggle: () => void;
}

const ThemeContext = createContext<ThemeContextType>({ mode: 'dark', toggle: () => {} });

export const useThemeMode = () => useContext(ThemeContext);

function buildTheme(mode: ThemeMode, p: PaletteTokens) {
  return createTheme({
    palette: {
      mode,
      primary: {
        main: p.accent,
        light: p.accentHover,
        dark: p.accent,
        contrastText: p.onAccent,
      },
      secondary: {
        main: p.info,
        contrastText: p.text,
      },
      background: { default: p.bg, paper: p.surface },
      text: { primary: p.text, secondary: p.textMuted, disabled: p.textFaint },
      divider: p.border,
      error: { main: p.danger },
      warning: { main: p.warning },
      success: { main: p.success, contrastText: p.onAccent },
      info: { main: p.info },
    },
    typography: {
      fontFamily: fonts.sans,
      fontSize: 14,
      h1: { fontWeight: 700, letterSpacing: '-0.04em', lineHeight: 1.08 },
      h2: { fontWeight: 700, letterSpacing: '-0.03em', lineHeight: 1.15 },
      h3: { fontWeight: 600, letterSpacing: '-0.025em' },
      h4: { fontWeight: 600, letterSpacing: '-0.02em', fontSize: '1.75rem' },
      h5: { fontWeight: 600, letterSpacing: '-0.015em' },
      h6: { fontWeight: 600, letterSpacing: '-0.01em' },
      subtitle1: { fontWeight: 500 },
      subtitle2: { fontWeight: 600, letterSpacing: '0.04em', textTransform: 'uppercase', fontSize: '0.72rem', color: p.textMuted },
      body1: { lineHeight: 1.65 },
      body2: { color: p.textMuted, lineHeight: 1.6 },
      button: { fontWeight: 600, letterSpacing: '-0.01em' },
      caption: { color: p.textMuted },
      overline: {
        fontWeight: 700,
        letterSpacing: '0.14em',
        fontSize: '0.68rem',
        color: p.textFaint,
      },
    },
    shape: { borderRadius: radii.md },
    components: {
      MuiCssBaseline: {
        styleOverrides: {
          body: { backgroundColor: p.bg, color: p.text },
        },
      },
      MuiCard: {
        defaultProps: { elevation: 0 },
        styleOverrides: {
          root: {
            backgroundImage: `linear-gradient(180deg, ${p.surface} 0%, ${p.bgElevated} 100%)`,
            border: `1px solid ${p.border}`,
            borderRadius: radii.lg,
            boxShadow: 'var(--atom-shadow-card)',
            transition: 'border-color var(--atom-ease), transform var(--atom-ease), box-shadow var(--atom-ease)',
            '&:hover': {
              borderColor: p.borderStrong,
            },
          },
        },
      },
      MuiPaper: {
        defaultProps: { elevation: 0 },
        styleOverrides: {
          root: {
            backgroundImage: 'none',
            backgroundColor: p.surface,
            borderColor: p.border,
          },
        },
      },
      MuiButton: {
        defaultProps: { disableElevation: true },
        styleOverrides: {
          root: {
            textTransform: 'none',
            fontWeight: 600,
            borderRadius: radii.sm,
            paddingInline: 16,
            minHeight: 40,
            transition: 'background-color var(--atom-ease), box-shadow var(--atom-ease), border-color var(--atom-ease)',
          },
          containedPrimary: {
            boxShadow: `0 0 0 1px ${p.accentGlow}, 0 8px 24px ${p.accentGlow}`,
            '&:hover': {
              boxShadow: `0 0 0 1px ${p.accent}, 0 10px 28px ${p.accentGlow}`,
            },
          },
          outlined: {
            borderColor: p.borderStrong,
            '&:hover': { borderColor: p.accent, backgroundColor: p.accentMuted },
          },
        },
      },
      MuiIconButton: {
        styleOverrides: {
          root: {
            borderRadius: radii.sm,
            '&:hover': { backgroundColor: p.accentMuted },
          },
        },
      },
      MuiTextField: {
        defaultProps: { size: 'small', variant: 'outlined' },
      },
      MuiOutlinedInput: {
        styleOverrides: {
          root: {
            backgroundColor: p.bgElevated,
            '&:hover .MuiOutlinedInput-notchedOutline': { borderColor: p.borderStrong },
            '&.Mui-focused .MuiOutlinedInput-notchedOutline': { borderColor: p.accent, borderWidth: 1 },
          },
          notchedOutline: { borderColor: p.border },
        },
      },
      MuiChip: {
        styleOverrides: {
          root: {
            fontWeight: 600,
            borderRadius: 999,
            backgroundColor: p.accentMuted,
            color: p.accent,
            border: `1px solid ${p.border}`,
          },
          colorPrimary: {
            backgroundColor: p.accentMuted,
            color: p.accent,
          },
        },
      },
      MuiTableHead: {
        styleOverrides: {
          root: {
            '& .MuiTableCell-head': {
              color: p.textFaint,
              fontSize: '0.7rem',
              fontWeight: 700,
              letterSpacing: '0.08em',
              textTransform: 'uppercase',
              borderBottom: `1px solid ${p.border}`,
              backgroundColor: p.bgElevated,
            },
          },
        },
      },
      MuiTableCell: {
        styleOverrides: {
          root: {
            borderColor: p.border,
            fontVariantNumeric: 'tabular-nums',
          },
        },
      },
      MuiTableRow: {
        styleOverrides: {
          root: {
            transition: 'background-color var(--atom-ease)',
            '&:hover': { backgroundColor: p.surfaceHover },
          },
        },
      },
      MuiTabs: {
        styleOverrides: {
          indicator: {
            height: 2,
            borderRadius: 2,
            backgroundColor: p.accent,
          },
        },
      },
      MuiTab: {
        styleOverrides: {
          root: {
            textTransform: 'none',
            fontWeight: 600,
            minHeight: 44,
            color: p.textMuted,
            '&.Mui-selected': { color: p.accent },
          },
        },
      },
      MuiAlert: {
        styleOverrides: {
          root: {
            borderRadius: radii.md,
            border: `1px solid ${p.border}`,
            backgroundImage: 'none',
          },
        },
      },
      MuiTooltip: {
        styleOverrides: {
          tooltip: {
            backgroundColor: p.surface,
            color: p.text,
            border: `1px solid ${p.borderStrong}`,
            fontSize: '0.75rem',
            fontWeight: 500,
          },
        },
      },
      MuiDivider: {
        styleOverrides: { root: { borderColor: p.border } },
      },
      MuiListItemButton: {
        styleOverrides: {
          root: {
            borderRadius: radii.sm,
            '&.Mui-selected': {
              backgroundColor: p.accentMuted,
              color: p.accent,
              '&:hover': { backgroundColor: p.accentMuted },
              '& .MuiListItemIcon-root': { color: p.accent },
            },
          },
        },
      },
      MuiLinearProgress: {
        styleOverrides: {
          root: { borderRadius: 99, backgroundColor: p.accentMuted },
          bar: { borderRadius: 99 },
        },
      },
      MuiToggleButton: {
        styleOverrides: {
          root: {
            textTransform: 'none',
            fontWeight: 600,
            borderColor: p.border,
            '&.Mui-selected': {
              backgroundColor: p.accentMuted,
              color: p.accent,
              '&:hover': { backgroundColor: p.accentMuted },
            },
          },
        },
      },
    },
  });
}

export const ThemeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [mode, setMode] = useState<ThemeMode>('dark');
  const toggle = () => setMode((m) => (m === 'dark' ? 'light' : 'dark'));

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', mode);
  }, [mode]);

  const theme = useMemo(() => buildTheme(mode, mode === 'dark' ? dark : light), [mode]);

  return (
    <ThemeContext.Provider value={{ mode, toggle }}>
      <MUIThemeProvider theme={theme}>
        <CssBaseline />
        {children}
      </MUIThemeProvider>
    </ThemeContext.Provider>
  );
};
