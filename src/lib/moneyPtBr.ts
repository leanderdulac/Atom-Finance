/** Client-facing prices: 77.640,12 — never scientific notation, never extra cents. */
export function formatPricePtBr(value: number, decimals = 2): string {
  if (!Number.isFinite(value)) return '—';
  const neg = value < 0;
  const [whole, frac = ''] = Math.abs(value).toFixed(decimals).split('.');
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  const tail = decimals > 0 ? `,${frac}` : '';
  return `${neg ? '-' : ''}${grouped}${tail}`;
}
