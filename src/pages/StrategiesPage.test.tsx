import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import StrategiesPage from './StrategiesPage';

const ironCondor = vi.fn();
const straddle = vi.fn();

vi.mock('../services/api', () => ({
  api: {
    straddle: (...args: unknown[]) => straddle(...args),
    ironCondor: (...args: unknown[]) => ironCondor(...args),
    butterfly: vi.fn(),
    strategy: vi.fn(),
  },
}));

describe('StrategiesPage flow', () => {
  beforeEach(() => {
    ironCondor.mockReset().mockResolvedValue({
      strategy: 'iron_condor', total_premium: 2.5,
      max_profit: 250, max_loss: -250, breakeven_points: [95, 115],
    });
    straddle.mockReset().mockResolvedValue({
      strategy: 'straddle', total_premium: 8.0,
      max_profit: 'unlimited', max_loss: -800, breakeven_points: [92, 108],
    });
  });

  it('sends condor strikes from the UI and shows the payoff summary', async () => {
    const user = userEvent.setup();
    render(<StrategiesPage />);
    await user.click(screen.getByRole('button', { name: /iron condor/i }));
    await user.click(screen.getByRole('button', { name: /analyze strategy/i }));
    expect(ironCondor).toHaveBeenCalledTimes(1);
    const payload = ironCondor.mock.calls[0][0] as Record<string, number>;
    expect(payload.k1).toBeLessThan(payload.k2);
    expect(await screen.findByText(/iron condor analysis/i)).toBeInTheDocument();
    expect(screen.getByText('$250.00')).toBeInTheDocument();
  });

  it('prices a straddle with the strike input', async () => {
    const user = userEvent.setup();
    render(<StrategiesPage />);
    await user.click(screen.getByRole('button', { name: /analyze strategy/i }));
    expect(straddle).toHaveBeenCalledWith(expect.objectContaining({ strike: 100 }));
    expect(await screen.findByText(/straddle analysis/i)).toBeInTheDocument();
  });
});
