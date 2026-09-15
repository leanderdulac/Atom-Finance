import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ForwardTestPage from './ForwardTestPage';

const deskForwardTest = vi.fn();

vi.mock('../services/api', () => ({
  api: {
    deskForwardTest: (...args: unknown[]) => deskForwardTest(...args),
  },
}));

function renderPage() {
  return render(
    <MemoryRouter>
      <ForwardTestPage />
    </MemoryRouter>,
  );
}

describe('ForwardTestPage', () => {
  beforeEach(() => {
    deskForwardTest.mockReset().mockResolvedValue({
      n_prices: 756,
      n_candidates: 20,
      locked: { sharpe: 0.12, hit_rate: 0.49, ic: 0.01, same_bar_sharpe: 0.4, n_active: 700 },
      mined_delayed: { sharpe: 1.1, hit_rate: 0.54, ic: 0.06, fast: 8, slow: 50 },
      mined_same_bar: { sharpe: 1.8, hit_rate: 0.58, ic: 0.09, fast: 5, slow: 30 },
      walk_forward: { sharpe: 0.2, hit_rate: 0.5, ic: 0.02, n_refits: 24 },
      buy_hold: { sharpe: -0.05 },
      dsr_mined: { deflated_sharpe_prob: 0.22, significant_at_95: false, n_trials: 20 },
      today_signal: {
        price: 100,
        fast_sma: 101,
        slow_sma: 99,
        position: 1,
        side: 'long',
        note: 'Sinal gerado no último fechamento. O retorno que o avalia ainda não conhecido neste arquivo.',
      },
      equity: {
        locked: [1, 1.01],
        mined_delayed: [1, 1.04],
        walk_forward: [1, 1.02],
        buy_hold: [1, 0.99],
      },
      math: 'Decisão no fechamento t.',
      what_broke: ['Synthetic GBM is a clock, not a market'],
    });
  });

  it('runs the sequential clock and refuses to treat the mined Sharpe as proof', async () => {
    renderPage();
    expect(screen.getByText(/teste sequencial/i)).toBeInTheDocument();
    expect(await screen.findByText(/comprado/i)).toBeInTheDocument();
    expect(screen.getByText(/não passa de 95%/i)).toBeInTheDocument();
    expect(screen.getAllByText(/spec travada/i).length).toBeGreaterThan(0);
    expect(deskForwardTest).toHaveBeenCalledWith({});
  });

  it('re-runs the clock from the button', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/comprado/i);
    await user.click(screen.getByRole('button', { name: /relógio sequencial/i }));
    expect(deskForwardTest.mock.calls.length).toBeGreaterThanOrEqual(2);
  });
});
