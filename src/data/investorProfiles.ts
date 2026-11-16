import type { ElementType } from 'react';
import { Shield, TrendingUp, Bolt } from '@mui/icons-material';

export interface AssetAlloc {
  ticker: string;
  S0: number;
  mu: number;
  sigma: number;
  weight: number;       // portfolio weight 0-1
}

export interface Profile {
  id: 'conservador' | 'moderado' | 'agressivo';
  label: string;
  description: string;
  color: string;
  bgColor: string;
  Icon: ElementType;
  assets: AssetAlloc[];
  expectedReturn: number;   // weighted mu
  expectedVol: number;      // approximate weighted sigma
}

// Synthetic allocations: fixed mu/sigma per asset, no correlations, no costs.
// They are scenario inputs, not forecasts (docs/PRODUCT-PILOT.md).
export const INVESTOR_PROFILES: Profile[] = [
  {
    id: 'conservador',
    label: 'Conservador',
    description: 'Prioriza preservação de capital. Ativos defensivos, alta previsibilidade de dividendos e menor oscilação.',
    color: '#22c55e',
    bgColor: '#22c55e18',
    Icon: Shield,
    assets: [
      { ticker: 'ABEV3', S0: 14.0, mu: 0.07, sigma: 0.20, weight: 0.40 },
      { ticker: 'ITUB4', S0: 35.0, mu: 0.09, sigma: 0.24, weight: 0.35 },
      { ticker: 'VALE3', S0: 65.0, mu: 0.08, sigma: 0.26, weight: 0.25 },
    ],
    expectedReturn: 0.0795,
    expectedVol: 0.232,
  },
  {
    id: 'moderado',
    label: 'Moderado',
    description: 'Equilíbrio entre crescimento e proteção. Mix de blue chips com exposição controlada a commodities.',
    color: '#f59e0b',
    bgColor: '#f59e0b18',
    Icon: TrendingUp,
    assets: [
      { ticker: 'ITUB4', S0: 35.0, mu: 0.10, sigma: 0.26, weight: 0.30 },
      { ticker: 'PETR4', S0: 40.0, mu: 0.11, sigma: 0.36, weight: 0.25 },
      { ticker: 'VALE3', S0: 65.0, mu: 0.10, sigma: 0.30, weight: 0.25 },
      { ticker: 'ABEV3', S0: 14.0, mu: 0.07, sigma: 0.20, weight: 0.20 },
    ],
    expectedReturn: 0.097,
    expectedVol: 0.286,
  },
  {
    id: 'agressivo',
    label: 'Agressivo',
    description: 'Maximiza retorno potencial aceitando alta volatilidade. Concentrado em commodities e ativos de alto beta.',
    color: '#ef4444',
    bgColor: '#ef444418',
    Icon: Bolt,
    assets: [
      { ticker: 'PETR4', S0: 40.0, mu: 0.14, sigma: 0.40, weight: 0.40 },
      { ticker: 'VALE3', S0: 65.0, mu: 0.12, sigma: 0.34, weight: 0.35 },
      { ticker: 'BBDC4', S0: 15.0, mu: 0.10, sigma: 0.30, weight: 0.25 },
    ],
    expectedReturn: 0.124,
    expectedVol: 0.368,
  },
];
