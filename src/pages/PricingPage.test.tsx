import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import PricingPage from './PricingPage';

const blackScholes = vi.fn();

vi.mock('../services/api', () => ({
  api: {
    blackScholes: (...args: unknown[]) => blackScholes(...args),
    monteCarlo: vi.fn(),
    binomial: vi.fn(),
    finiteDifference: vi.fn(),
    compareModels: vi.fn(),
    quote: vi.fn(),
    volatility: vi.fn(),
  },
}));

describe('PricingPage flow', () => {
  beforeEach(() => {
    blackScholes.mockReset().mockResolvedValue({
      price: 10.4506, model: 'black_scholes',
      greeks: { delta: 0.6368, gamma: 0.0188, theta: -0.0176, vega: 0.3752, rho: 0.5323 },
    });
  });

  it('prices with Black-Scholes and shows price plus Greeks', async () => {
    const user = userEvent.setup();
    render(<PricingPage />);
    await user.click(screen.getByRole('button', { name: 'Black-Scholes' }));
    expect(blackScholes).toHaveBeenCalledWith(expect.objectContaining({
      spot: 100, strike: 100, maturity: 0.25, rate: 0.05, sigma: 0.2,
    }));
    expect(await screen.findByText(/10\.4506/)).toBeInTheDocument();
    await user.click(screen.getByRole('tab', { name: 'Greeks' }));
    expect(await screen.findByText(/0\.6368/)).toBeInTheDocument();
  });

  it('surfaces engine errors instead of hanging', async () => {
    const user = userEvent.setup();
    blackScholes.mockRejectedValueOnce(new Error('sigma must be positive'));
    render(<PricingPage />);
    await user.click(screen.getByRole('button', { name: 'Black-Scholes' }));
    expect(await screen.findByText(/sigma must be positive/i)).toBeInTheDocument();
  });
});
