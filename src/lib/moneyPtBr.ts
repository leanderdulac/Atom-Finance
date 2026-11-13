/** Client-facing prices: 77.640,12 — never scientific notation, never extra cents. */
export function formatPricePtBr(value: number, decimals = 2): string {
  if (!Number.isFinite(value)) return '—';
  const neg = value < 0;
  const [whole, frac = ''] = Math.abs(value).toFixed(decimals).split('.');
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  const tail = decimals > 0 ? `,${frac}` : '';
  return `${neg ? '-' : ''}${grouped}${tail}`;
}

/** Client-facing dates: 04/12/2026 — never ISO, so the hyphen cannot wrap. */
export function formatDatePtBr(value?: string | null): string {
  if (!value) return '';
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value.trim());
  if (!match) return value;
  return `${match[3]}/${match[2]}/${match[1]}`;
}
