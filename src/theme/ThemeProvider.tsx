import React, { createContext, useContext, useMemo, useState } from 'react';
import { ThemeProvider as MUIThemeProvider, createTheme, CssBaseline } from '@mui/material';

type ThemeMode = 'dark' | 'light';

interface ThemeContextType {
  mode: ThemeMode;
  toggle: () => void;
}

const ThemeContext = createContext<ThemeContextType>({ mode: 'dark', toggle: () => {} });

export const useThemeMode = () => useContext(ThemeContext);

export const ThemeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [mode, setMode] = useState<ThemeMode>('dark');
  const toggle = () => setMode((m) => (m === 'dark' ? 'light' : 'dark'));

  const theme = useMemo(
    () =>
      createTheme({
        palette: {
          mode,
          primary: { main: '#6366f1', light: '#818cf8', dark: '#4f46e5' },
          secondary: { main: '#06b6d4', light: '#22d3ee', dark: '#0891b2' },
          ...(mode === 'dark'
            ? {
                background: { default: '#0a0e1a', paper: '#111827' },
                text: { primary: '#f1f5f9', secondary: '#94a3b8' },
                error: { main: '#ef4444' },
                warning: { main: '#f59e0b' },
                success: { main: '#10b981' },
              }
            : {
                background: { default: '#f8fafc', paper: '#ffffff' },
                error: { main: '#dc2626' },
                warning: { main: '#d97706' },
                success: { main: '#059669' },
              }),
        },
        typography: {
          fontFamily: '"Inter", "Helvetica", "Arial", sans-serif',
          h4: { fontWeight: 700, letterSpacing: '-0.02em' },
          h5: { fontWeight: 600, letterSpacing: '-0.01em' },
          h6: { fontWeight: 600 },
          subtitle1: { fontWeight: 500 },
          body2: { color: mode === 'dark' ? '#94a3b8' : '#64748b' },
        },
        shape: { borderRadius: 12 },
        components: {
          MuiCard: {
            styleOverrides: {
              root: {
                backgroundImage: 'none',
                border: `1px solid ${mode === 'dark' ? '#1e293b' : '#e2e8f0'}`,
                transition: 'border-color 0.2s, box-shadow 0.2s',
                '&:hover': {
                  borderColor: mode === 'dark' ? '#334155' : '#cbd5e1',
                  boxShadow: mode === 'dark' ? '0 4px 24px rgba(0,0,0,0.3)' : '0 4px 24px rgba(0,0,0,0.08)',
                },
              },
            },
          },
          MuiButton: {
            styleOverrides: {
              root: {
                textTransform: 'none',
                fontWeight: 600,
                borderRadius: 8,
              },
            },
          },
          MuiTextField: {
            defaultProps: { size: 'small', variant: 'outlined' },
          },
          MuiPaper: {
            styleOverrides: {
              root: { backgroundImage: 'none' },
            },
          },
        },
      }),
    [mode]
  );

  return (
    <ThemeContext.Provider value={{ mode, toggle }}>
      <MUIThemeProvider theme={theme}>
        <CssBaseline />
        {children}
      </MUIThemeProvider>
    </ThemeContext.Provider>
  );
};
