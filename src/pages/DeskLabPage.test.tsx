import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import DeskLabPage from './DeskLabPage';

const deskHestonCalibrate = vi.fn();
const deskJohansen = vi.fn();
const deskPerpLive = vi.fn();
const deskEdgar = vi.fn();

vi.mock('../services/api', () => ({
  api: {
    deskHestonPrice: vi.fn(),
    deskHestonCalibrate: (...args: unknown[]) => deskHestonCalibrate(...args),
    deskEngleGranger: vi.fn(),
    deskJohansen: (...args: unknown[]) => deskJohansen(...args),
    deskPairsBacktest: vi.fn(),
    deskMarketMaking: vi.fn(),
    deskFamaFrench: vi.fn(),
    deskMeanReversion: vi.fn(),
    deskPerpArb: vi.fn(),
    deskPerpLive: (...args: unknown[]) => deskPerpLive(...args),
    deskInsiderClusters: vi.fn(),
    deskEdgar: (...args: unknown[]) => deskEdgar(...args),
  },
}));

describe('DeskLabPage', () => {
  beforeEach(() => {
    deskHestonCalibrate.mockReset().mockResolvedValue({
      rmse_price: 0.01,
      what_broke: ['unidentified'],
      math: 'least squares',
    });
    deskJohansen.mockReset().mockResolvedValue({ rank: 1, what_broke: ['lag'] });
    deskPerpLive.mockReset().mockResolvedValue({ live_books: true, what_broke: ['stale'] });
    deskEdgar.mockReset().mockResolvedValue({ n_events: 0, what_broke: ['UA'] });
  });

  it('exposes the round-5 desk tabs and runs calibrate', async () => {
    const user = userEvent.setup();
    render(<DeskLabPage />);
    expect(screen.getByText(/mesa de papers/i)).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /heston calibração/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /johansen/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /perp live/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /edgar form 4/i })).toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: /heston calibração/i }));
    await user.click(screen.getByRole('button', { name: /rodar demonstração/i }));
    expect(deskHestonCalibrate).toHaveBeenCalled();
    expect(await screen.findByText('unidentified')).toBeInTheDocument();
  });
});
