import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import BacktestingPage from './BacktestingPage';

const renderPage = () => render(<MemoryRouter><BacktestingPage /></MemoryRouter>);

const backtest = vi.fn();

vi.mock('../services/api', () => ({
  api: {
    backtest: (...args: unknown[]) => backtest(...args),
    history: vi.fn(),
  },
}));

describe('BacktestingPage flow', () => {
  beforeEach(() => {
    backtest.mockReset().mockResolvedValue({
      strategy: 'sma_crossover',
      performance: { total_return_pct: 12.5, sharpe_ratio: 1.2, max_drawdown_pct: -8.0, final_value: 112500 },
    });
  });

  it('runs a backtest on synthetic demo data and shows performance', async () => {
    const user = userEvent.setup();
    renderPage();
    expect(screen.getByRole('button', { name: /run backtest/i })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: /demonstração sintética/i }));
    await user.click(screen.getByRole('button', { name: /run backtest/i }));
    expect(backtest).toHaveBeenCalledTimes(1);
    expect(await screen.findByText(/performance metrics/i)).toBeInTheDocument();
    expect(screen.getByText(/12\.50%/)).toBeInTheDocument();
  });

  it('surfaces backtest errors', async () => {
    const user = userEvent.setup();
    backtest.mockRejectedValueOnce(new Error('need at least 100 prices'));
    renderPage();
    await user.click(screen.getByRole('button', { name: /demonstração sintética/i }));
    await user.click(screen.getByRole('button', { name: /run backtest/i }));
    expect(await screen.findByText(/need at least 100 prices/i)).toBeInTheDocument();
  });
});
