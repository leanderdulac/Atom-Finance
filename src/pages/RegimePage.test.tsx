import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import RegimePage from './RegimePage';

const deskRegime = vi.fn();
const deskRegimeLive = vi.fn();

vi.mock('../services/api', () => ({
  api: {
    deskRegime: (...args: unknown[]) => deskRegime(...args),
    deskRegimeLive: (...args: unknown[]) => deskRegimeLive(...args),
  },
}));

describe('RegimePage', () => {
  beforeEach(() => {
    deskRegimeLive.mockReset();
    deskRegime.mockReset().mockResolvedValue({
      regime: 'crisis',
      math: 'percentile gate',
      what_broke: ['no broker'],
      probs: { crisis: 0.7, trending: 0.1, mean_reverting: 0.1, high_vol: 0.1 },
      holdout: { n: 80, accuracy: 0.4, crisis_recall: 0.6 },
      kill_switch: { armed: true, broker_orders_sent: 0 },
      signals: { credit_spread: { value: 780, percentile: 100, flag: 'high' } },
      strategies: [{ id: 'vol_selling', name: 'Short vol', live_in: ['mean_reverting'], kill_in: ['crisis'], status: 'flatten' }],
      adjustments: [{ id: 'vol_selling', current_weight: 0.08, target_weight: 0, action: 'flatten', reason: 'kill' }],
      context: { 'current-regime.md': '# Current regime\n- Regime: **crisis**' },
    });
  });

  it('runs the crisis demo and shows the research kill switch', async () => {
    const user = userEvent.setup();
    render(<RegimePage />);
    await user.click(screen.getByRole('button', { name: /demo crise/i }));
    expect(deskRegime).toHaveBeenCalledWith({ demo: 'crisis' });
    expect(await screen.findByText(/kill switch armed/i)).toBeInTheDocument();
    expect(screen.getByText(/ordens no broker: 0/i)).toBeInTheDocument();
    expect(screen.getAllByText('flatten').length).toBeGreaterThan(0);
  });

  it('requests live public books', async () => {
    deskRegimeLive.mockResolvedValue({
      regime: 'mean_reverting',
      live_books: true,
      kill_switch: { armed: false, broker_orders_sent: 0 },
      signals: {},
      strategies: [],
      adjustments: [],
    });
    const user = userEvent.setup();
    render(<RegimePage />);
    await user.click(screen.getByRole('button', { name: /livros públicos/i }));
    expect(deskRegimeLive).toHaveBeenCalledWith(false);
  });
});
