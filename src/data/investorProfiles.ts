import type { ElementType } from 'react';
import { Shield, TrendingUp, Bolt } from '@mui/icons-material';

export type ProfileId = 'conservador' | 'moderado' | 'arrojado';
export type Sleeve = 'equities' | 'crypto' | 'mixed';

export interface AssetAlloc {
  ticker: string;
  S0: number;
  mu: number;
  sigma: number;
  weight: number;       // portfolio weight 0-1
}

export interface Profile {
  id: ProfileId;
  label: string;
  description: string;
  color: string;
  bgColor: string;
  Icon: ElementType;
  assets: AssetAlloc[];
  expectedReturn: number;   // weighted mu
  expectedVol: number;      // approximate weighted sigma
}

export type ProfileAnswers = {
  horizon: number | null;
  drop: number | null;
  goal: number | null;
};

export const PROFILE_QUESTIONS = [
  {
    id: 'horizon' as const,
    question: 'Quando você pretende usar esse dinheiro?',
    options: [
      { label: 'Em até 1 ano', value: 0, hint: 'Prazo curto: oscilação tem pouco tempo para se recuperar.' },
      { label: 'Entre 1 e 3 anos', value: 1, hint: 'Prazo médio: dá para atravessar um ciclo ruim.' },
      { label: 'Daqui a 3 anos ou mais', value: 2, hint: 'Prazo longo: o tempo trabalha a favor.' },
    ],
  },
  {
    id: 'drop' as const,
    question: 'Se a carteira caísse 20% em um mês, o que você faria?',
    options: [
      { label: 'Venderia para parar a perda', value: 0, hint: 'Perder no papel incomoda mais do que a chance de recuperar.' },
      { label: 'Não mexeria e esperaria', value: 1, hint: 'Aguenta a queda sem mudar o plano.' },
      { label: 'Aproveitaria para comprar mais', value: 2, hint: 'Queda é oportunidade, não motivo de saída.' },
    ],
  },
  {
    id: 'goal' as const,
    question: 'O que você quer desse investimento?',
    options: [
      { label: 'Proteger o que já tenho', value: 0, hint: 'Preservar vale mais que render.' },
      { label: 'Crescer com equilíbrio', value: 1, hint: 'Render, mas sem sustos grandes.' },
      { label: 'Buscar o maior retorno possível', value: 2, hint: 'Aceita oscilar muito para tentar render mais.' },
    ],
  },
] as const;

export const SLEEVES: { id: Sleeve; label: string; hint: string }[] = [
  { id: 'equities', label: 'Ações (B3)', hint: 'Carteira em papéis brasileiros que o arsenal já acompanha.' },
  { id: 'crypto', label: 'Cripto', hint: 'Bitcoin, Ethereum e Solana via feed público.' },
  { id: 'mixed', label: 'Misto', hint: 'Marque vários ativos (B3 e cripto). Uma perna por marcado; o risco total fica limitado e os pesos vêm do perfil.' },
];

const EQUITY = {
  WEGE3: { ticker: 'WEGE3', S0: 45.0, mu: 0.10, sigma: 0.28 },
  ITUB4: { ticker: 'ITUB4', S0: 35.0, mu: 0.09, sigma: 0.24 },
  VALE3: { ticker: 'VALE3', S0: 65.0, mu: 0.08, sigma: 0.26 },
  PETR4: { ticker: 'PETR4', S0: 40.0, mu: 0.11, sigma: 0.36 },
  BBDC4: { ticker: 'BBDC4', S0: 15.0, mu: 0.10, sigma: 0.30 },
} as const;

const CRYPTO = {
  BTC: { ticker: 'BTC', S0: 95000, mu: 0.12, sigma: 0.55 },
  ETH: { ticker: 'ETH', S0: 2000, mu: 0.14, sigma: 0.65 },
  SOL: { ticker: 'SOL', S0: 150, mu: 0.18, sigma: 0.85 },
} as const;

function w(base: { ticker: string; S0: number; mu: number; sigma: number }, weight: number): AssetAlloc {
  return { ...base, weight };
}

const SLEEVE_WEIGHTS: Record<Sleeve, Record<ProfileId, AssetAlloc[]>> = {
  equities: {
    conservador: [w(EQUITY.WEGE3, 0.40), w(EQUITY.ITUB4, 0.35), w(EQUITY.VALE3, 0.25)],
    moderado: [w(EQUITY.ITUB4, 0.30), w(EQUITY.PETR4, 0.25), w(EQUITY.VALE3, 0.25), w(EQUITY.WEGE3, 0.20)],
    arrojado: [w(EQUITY.PETR4, 0.40), w(EQUITY.VALE3, 0.35), w(EQUITY.BBDC4, 0.25)],
  },
  crypto: {
    conservador: [w(CRYPTO.BTC, 0.70), w(CRYPTO.ETH, 0.30)],
    moderado: [w(CRYPTO.BTC, 0.50), w(CRYPTO.ETH, 0.30), w(CRYPTO.SOL, 0.20)],
    arrojado: [w(CRYPTO.SOL, 0.40), w(CRYPTO.ETH, 0.35), w(CRYPTO.BTC, 0.25)],
  },
  mixed: {
    conservador: [w(EQUITY.ITUB4, 0.40), w(EQUITY.WEGE3, 0.30), w(CRYPTO.BTC, 0.30)],
    moderado: [w(EQUITY.ITUB4, 0.25), w(EQUITY.PETR4, 0.20), w(CRYPTO.BTC, 0.30), w(CRYPTO.ETH, 0.25)],
    arrojado: [w(EQUITY.PETR4, 0.25), w(EQUITY.VALE3, 0.20), w(CRYPTO.BTC, 0.25), w(CRYPTO.ETH, 0.15), w(CRYPTO.SOL, 0.15)],
  },
};

const META: Record<ProfileId, Omit<Profile, 'assets' | 'expectedReturn' | 'expectedVol'>> = {
  conservador: {
    id: 'conservador',
    label: 'Conservador',
    description: 'Prioriza preservação de capital. Menos oscilação, mais previsibilidade.',
    color: '#22c55e',
    bgColor: '#22c55e18',
    Icon: Shield,
  },
  moderado: {
    id: 'moderado',
    label: 'Moderado',
    description: 'Equilíbrio entre crescimento e proteção.',
    color: '#f59e0b',
    bgColor: '#f59e0b18',
    Icon: TrendingUp,
  },
  arrojado: {
    id: 'arrojado',
    label: 'Arrojado',
    description: 'Busca o maior retorno possível e aceita oscilar mais.',
    color: '#ef4444',
    bgColor: '#ef444418',
    Icon: Bolt,
  },
};

function finish(id: ProfileId, assets: AssetAlloc[]): Profile {
  const expectedReturn = assets.reduce((sum, row) => sum + row.weight * row.mu, 0);
  const expectedVol = assets.reduce((sum, row) => sum + row.weight * row.sigma, 0);
  return { ...META[id], assets, expectedReturn, expectedVol };
}

/** Goal (desired return) counts twice: that is the question the client is answering as «retorno desejado». */
export function scoreProfile(answers: { horizon: number; drop: number; goal: number }): ProfileId {
  const score = answers.horizon + answers.drop + 2 * answers.goal;
  if (score <= 2) return 'conservador';
  if (score <= 5) return 'moderado';
  return 'arrojado';
}

export function profileFor(id: ProfileId, sleeve: Sleeve = 'equities'): Profile {
  return finish(id, SLEEVE_WEIGHTS[sleeve][id]);
}

export function recommendedProfile(answers: ProfileAnswers, sleeve: Sleeve = 'equities'): Profile {
  return profileFor(scoreProfile({
    horizon: answers.horizon ?? 0,
    drop: answers.drop ?? 0,
    goal: answers.goal ?? 0,
  }), sleeve);
}

export function sleeveOfTicker(ticker: string): Sleeve {
  const key = ticker.toUpperCase();
  if (key in CRYPTO) return 'crypto';
  return 'equities';
}

export function tickersForSleeve(sleeve: Sleeve): string[] {
  if (sleeve === 'crypto') return ['BTC', 'ETH', 'SOL'];
  if (sleeve === 'equities') return ['PETR4', 'VALE3', 'ITUB4', 'BBDC4', 'WEGE3'];
  return ['PETR4', 'VALE3', 'ITUB4', 'BTC', 'ETH', 'SOL'];
}

/** Profile mix when every marked ticker is in the sleeve book; otherwise equal weights. */
export function weightsForTickers(tickers: string[], profile: Profile): number[] {
  if (!tickers.length) return [];
  const map = new Map(profile.assets.map((row) => [row.ticker, row.weight]));
  const raw = tickers.map((ticker) => map.get(ticker) ?? 0);
  const sum = raw.reduce((acc, weight) => acc + weight, 0);
  if (sum > 0 && raw.every((weight) => weight > 0)) {
    return raw.map((weight) => weight / sum);
  }
  return tickers.map(() => 1 / tickers.length);
}

/** Default sleeve = ações B3, used by the leftover «Meu plano» simulation. */
export const INVESTOR_PROFILES: Profile[] = [
  profileFor('conservador', 'equities'),
  profileFor('moderado', 'equities'),
  profileFor('arrojado', 'equities'),
];
