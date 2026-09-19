import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ErrorMaximizerPage from './ErrorMaximizerPage';

const deskErrorMaximizer = vi.fn();

vi.mock('../services/api', () => ({
  api: {
    deskErrorMaximizer: (...args: unknown[]) => deskErrorMaximizer(...args),
  },
}));

describe('ErrorMaximizerPage', () => {
  beforeEach(() => {
    deskErrorMaximizer.mockReset().mockResolvedValue({
      n_assets: 80,
      t_is: 252,
      t_oos: 63,
      gmv: {
        formula: 'w* = Σ⁻¹ 1 / (1′ Σ⁻¹ 1)',
        sample: { l1: 4.2, max_abs: 0.81, hhi: 0.4, n_short: 31, sum: 1 },
        ledoit_wolf: { l1: 1.6, max_abs: 0.12, hhi: 0.05, n_short: 8, sum: 1 },
      },
      covariance: {
        sample_condition: 4800,
        lw_condition: 42,
        sample_min_eig: 0.04,
        lw_min_eig: 0.31,
        ledoit_wolf: { alpha: 0.62, r_bar: 0.21 },
      },
      marchenko_pastur: {
        q: 0.317, lambda_minus: 0.19, lambda_plus: 2.13, n_sample_eigs_below_bulk: 12,
      },
      spectrum: { sample: [3.1, 0.2, 0.04], ledoit_wolf: [2.4, 0.8, 0.31] },
      oos: { vol_sample: 0.22, vol_ledoit_wolf: 0.14, vol_equal_weight: 0.16 },
      turnover: { sample: 0.45, ledoit_wolf: 0.11, rebalance_every: 21 },
      math: 'Inverting crushed eigenvalues is the error maximizer.',
      what_broke: ['Constant-correlation F is a structured guess'],
      eligible_for_live_trading: false,
    });
  });

  it('shows sample GMV as the error maximizer against Ledoit–Wolf', async () => {
    render(<MemoryRouter><ErrorMaximizerPage /></MemoryRouter>);
    expect(screen.getByText(/maximizadora de erros/i)).toBeInTheDocument();
    expect(await screen.findByText('4.800')).toBeInTheDocument();
    expect(screen.getAllByText(/ledoit/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/eligible_for_live_trading: false/i)).toBeInTheDocument();
    expect(deskErrorMaximizer).toHaveBeenCalledWith({
      n_assets: 80, t_is: 252, t_oos: 63, seed: 7,
    });
  });
});
