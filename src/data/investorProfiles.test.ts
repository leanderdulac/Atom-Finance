import { describe, expect, it } from 'vitest';
import {
  profileFor,
  scoreProfile,
  recommendedProfile,
  tickersForSleeve,
  weightsForTickers,
  type ProfileId,
} from './investorProfiles';

const IDS: ProfileId[] = ['conservador', 'moderado', 'arrojado'];

describe('scoreProfile', () => {
  it.each([
    // horizon, drop, goal, expected — goal counts twice (retorno desejado)
    [0, 0, 0, 'conservador'],
    [0, 0, 1, 'conservador'],
    [0, 0, 2, 'moderado'],
    [0, 1, 0, 'conservador'],
    [0, 1, 1, 'moderado'],
    [0, 1, 2, 'moderado'],
    [0, 2, 0, 'conservador'],
    [0, 2, 1, 'moderado'],
    [0, 2, 2, 'arrojado'],
    [1, 0, 0, 'conservador'],
    [1, 0, 1, 'moderado'],
    [1, 0, 2, 'moderado'],
    [1, 1, 0, 'conservador'],
    [1, 1, 1, 'moderado'],
    [1, 1, 2, 'arrojado'], // print do Leandro: 1-3 anos + espera + maior retorno
    [1, 2, 0, 'moderado'],
    [1, 2, 1, 'moderado'],
    [1, 2, 2, 'arrojado'],
    [2, 0, 0, 'conservador'],
    [2, 0, 1, 'moderado'],
    [2, 0, 2, 'arrojado'],
    [2, 1, 0, 'moderado'],
    [2, 1, 1, 'moderado'],
    [2, 1, 2, 'arrojado'],
    [2, 2, 0, 'moderado'],
    [2, 2, 1, 'arrojado'],
    [2, 2, 2, 'arrojado'],
  ] as const)('horizon=%i drop=%i goal=%i → %s', (horizon, drop, goal, expected) => {
    expect(scoreProfile({ horizon, drop, goal })).toBe(expected);
    expect(IDS).toContain(expected);
  });

  it('does not pin every mixed answer to Moderado', () => {
    const labels = ([
      [0, 0, 0],
      [1, 1, 1],
      [1, 1, 2],
      [2, 2, 2],
    ] as const).map(([horizon, drop, goal]) => scoreProfile({ horizon, drop, goal }));
    expect(new Set(labels).size).toBe(3);
  });
});

describe('profileFor sleeve', () => {
  it('keeps B3 names on the equities sleeve', () => {
    const tickers = profileFor('moderado', 'equities').assets.map((row) => row.ticker);
    expect(tickers).toEqual(['ITUB4', 'PETR4', 'VALE3', 'WEGE3']);
    expect(tickers).not.toContain('ABEV3');
  });

  it('uses BTC/ETH/SOL when the client asked for crypto', () => {
    const tickers = profileFor('moderado', 'crypto').assets.map((row) => row.ticker);
    expect(tickers).toEqual(['BTC', 'ETH', 'SOL']);
    expect(tickersForSleeve('crypto')).toEqual(['BTC', 'ETH', 'SOL']);
  });

  it('mixes B3 and crypto on the mixed sleeve', () => {
    const tickers = profileFor('arrojado', 'mixed').assets.map((row) => row.ticker);
    expect(tickers).toContain('PETR4');
    expect(tickers).toContain('BTC');
    expect(tickers).toContain('SOL');
  });

  it('never cites ABEV3 on a B3 mix — it is not in the client universe', () => {
    const universe = ['PETR4', 'VALE3', 'ITUB4', 'BBDC4', 'WEGE3'];
    for (const id of IDS) {
      const tickers = profileFor(id, 'equities').assets.map((row) => row.ticker);
      expect(tickers.every((ticker) => universe.includes(ticker))).toBe(true);
      expect(tickers).not.toContain('ABEV3');
    }
  });

  it('maps Leandro’s print answers to Arrojado in crypto', () => {
    const profile = recommendedProfile({ horizon: 1, drop: 1, goal: 2 }, 'crypto');
    expect(profile.id).toBe('arrojado');
    expect(profile.label).toBe('Arrojado');
    expect(profile.assets.map((row) => row.ticker)).toEqual(['SOL', 'ETH', 'BTC']);
  });

  it('renormalizes mixed-profile weights when every marked ticker is in the book', () => {
    const profile = profileFor('moderado', 'mixed');
    expect(weightsForTickers(['PETR4', 'BTC'], profile)).toEqual([0.4, 0.6]);
  });

  it('uses equal weights when a marked ticker is outside the profile mix', () => {
    const profile = profileFor('moderado', 'mixed');
    expect(weightsForTickers(['PETR4', 'VALE3'], profile)).toEqual([0.5, 0.5]);
  });
});
