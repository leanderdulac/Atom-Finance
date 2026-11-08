/**
 * ATOM design tokens — single source of truth for palette, type and spacing.
 * CSS variables in tokens.css mirror these values for raw CSS and charts.
 */
export const fonts = {
  sans: '"Inter", "Helvetica Neue", Helvetica, Arial, sans-serif',
  mono: '"JetBrains Mono", "SFMono-Regular", ui-monospace, Menlo, monospace',
} as const;

export const space = {
  1: 4,
  2: 8,
  3: 12,
  4: 16,
  5: 20,
  6: 24,
  8: 32,
  10: 40,
  12: 48,
  16: 64,
} as const;

export const radii = {
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
} as const;

/** One accent: teal. Used for CTAs, focus, selection, key numbers. */
export const dark = {
  bg: '#07090f',
  bgElevated: '#0c1018',
  surface: '#11161f',
  surfaceHover: '#171d28',
  border: 'rgba(148, 163, 184, 0.14)',
  borderStrong: 'rgba(148, 163, 184, 0.28)',
  accent: '#3ee0c5',
  accentHover: '#6aebd4',
  accentMuted: 'rgba(62, 224, 197, 0.12)',
  accentGlow: 'rgba(62, 224, 197, 0.32)',
  onAccent: '#04110e',
  text: '#e8edf5',
  textMuted: '#8b98ad',
  textFaint: '#5c6a80',
  danger: '#f07178',
  warning: '#e4b363',
  success: '#3ee0c5',
  info: '#8aa4ff',
  overlay: 'rgba(7, 9, 15, 0.72)',
} as const;

export const light = {
  bg: '#f3f5f8',
  bgElevated: '#ffffff',
  surface: '#ffffff',
  surfaceHover: '#eef1f6',
  border: 'rgba(15, 23, 42, 0.10)',
  borderStrong: 'rgba(15, 23, 42, 0.18)',
  accent: '#0f766e',
  accentHover: '#0d9488',
  accentMuted: 'rgba(15, 118, 110, 0.10)',
  accentGlow: 'rgba(15, 118, 110, 0.18)',
  onAccent: '#f4fffd',
  text: '#0c1222',
  textMuted: '#4b5872',
  textFaint: '#7a869c',
  danger: '#b42318',
  warning: '#b45309',
  success: '#0f766e',
  info: '#3554d1',
  overlay: 'rgba(243, 245, 248, 0.8)',
} as const;

export type PaletteTokens = {
  [K in keyof typeof dark]: string;
};
