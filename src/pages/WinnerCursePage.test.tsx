import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import WinnerCursePage from './WinnerCursePage';

const deskWinnersCurseSimulate = vi.fn();
const deskWinnersCurseDeflate = vi.fn();

vi.mock('../services/api', () => ({
  api: {
    deskWinnersCurseSimulate: (...args: unknown[]) => deskWinnersCurseSimulate(...args),
    deskWinnersCurseDeflate: (...args: unknown[]) => deskWinnersCurseDeflate(...args),
  },
}));

describe('WinnerCursePage', () => {
  beforeEach(() => {
    deskWinnersCurseDeflate.mockReset();
    deskWinnersCurseSimulate.mockReset().mockResolvedValue({
      n_strategies: 400,
      t_is: 504,
      t_oos: 252,
      true_sharpe: 0,
      winner_is: 1.95,
      winner_oos: -0.21,
      is_oos_corr: 0.02,
      expected_max: { expected_max_sqrt_2lnN: 2.45, expected_max_blp: 2.31, se: 0.71 },
      dsr: {
        deflated_sharpe_prob: 0.31,
        sr_star: 2.31,
        significant_at_95: false,
        haircut: -0.36,
      },
      cloud: [
        { is: 0.4, oos: -0.1, winner: false },
        { is: 1.95, oos: -0.21, winner: true },
      ],
      math: 'True E[r]=0 for every trial.',
      what_broke: ['Trials are modelled as independent'],
      eligible_for_live_trading: false,
    });
  });

  it('runs the zero-edge lottery and shows the champion haircut', async () => {
    render(<WinnerCursePage />);
    expect(screen.getByText(/maldição do vencedor/i)).toBeInTheDocument();
    expect(await screen.findByText('+1,95')).toBeInTheDocument();
    expect(screen.getByText('−0,21')).toBeInTheDocument();
    expect(screen.getByText(/campeão de/i)).toBeInTheDocument();
    expect(screen.getByText(/não passa de 95%/i)).toBeInTheDocument();
    expect(deskWinnersCurseSimulate).toHaveBeenCalledWith({
      n_strategies: 400, t_is: 504, t_oos: 252, seed: 7,
    });
  });

  it('deflates a pasted Sharpe after asking how many candidates it beat', async () => {
    deskWinnersCurseDeflate.mockResolvedValue({
      observed_sharpe: 2.96,
      sr_star: 2.45,
      deflated_sharpe_prob: 0.72,
      significant_at_95: false,
      haircut: 0.51,
      n_trials: 400,
      n_obs: 504,
      math: 'DSR',
    });
    const user = userEvent.setup();
    render(<WinnerCursePage />);
    await screen.findByText('+1,95');
    await user.click(screen.getByRole('button', { name: /descontar o sharpe/i }));
    expect(deskWinnersCurseDeflate).toHaveBeenCalledWith({
      observed_sharpe: 2.96, n_trials: 400, n_obs: 504,
    });
    expect(await screen.findByText(/ainda parece sorte/i)).toBeInTheDocument();
  });
});
