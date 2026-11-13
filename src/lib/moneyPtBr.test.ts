import { describe, expect, it } from 'vitest';
import { formatDatePtBr, formatPricePtBr } from './moneyPtBr';

describe('formatPricePtBr', () => {
  it('formats BTC, ETH and equities in pt-BR with two decimals', () => {
    expect(formatPricePtBr(77640.12)).toBe('77.640,12');
    expect(formatPricePtBr(2199)).toBe('2.199,00');
    expect(formatPricePtBr(44.7894)).toBe('44,79');
    expect(formatPricePtBr(69185.36198)).toBe('69.185,36');
  });

  it('never uses scientific notation', () => {
    const text = formatPricePtBr(7.764e4);
    expect(text).toBe('77.640,00');
    expect(text.toLowerCase()).not.toMatch(/e[+-]?\d/);
  });
});

describe('formatDatePtBr', () => {
  it('turns ISO into dd/mm/aaaa', () => {
    expect(formatDatePtBr('2026-12-04')).toBe('04/12/2026');
    expect(formatDatePtBr('2026-12-04T12:00:00Z')).toBe('04/12/2026');
  });
});
