import type { CSSProperties } from 'react';

/** Shared Recharts styling — reads CSS tokens so charts follow the theme. */
export const chartTheme = {
  grid: 'var(--atom-border)',
  tick: 'var(--atom-text-muted)',
  axis: 'var(--atom-text-faint)',
  tooltipBg: 'var(--atom-surface)',
  tooltipBorder: 'var(--atom-border-strong)',
  tooltipRadius: 10,
  accent: 'var(--atom-accent)',
  mean: 'var(--atom-text)',
  band: 'var(--atom-info)',
  danger: 'var(--atom-danger)',
  mutedFill: 'color-mix(in srgb, var(--atom-accent) 50%, transparent)',
  dangerFill: 'color-mix(in srgb, var(--atom-danger) 50%, transparent)',
} as const;

export const chartTooltipStyle: CSSProperties = {
  background: 'var(--atom-surface)',
  border: '1px solid var(--atom-border-strong)',
  borderRadius: 10,
  fontFamily: 'var(--atom-font-sans)',
  fontSize: 12,
  color: 'var(--atom-text)',
  boxShadow: 'var(--atom-shadow-card)',
};
