import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import VectorizePage from './VectorizePage';

const deskVectorize = vi.fn();

vi.mock('../services/api', () => ({
  api: {
    deskVectorize: (...args: unknown[]) => deskVectorize(...args),
  },
}));

describe('VectorizePage', () => {
  beforeEach(() => {
    deskVectorize.mockReset().mockResolvedValue({
      n_names: 80,
      n_days: 504,
      n_hits: 1200,
      z_max_abs_diff: 1e-15,
      timing: {
        loop_mask_s: 0.04, vec_mask_s: 0.0004, speedup_mask: 100,
        loop_z_s: 0.08, vec_z_s: 0.0008, speedup_z: 100,
      },
      screen: { delayed_sharpe: 0.2, same_bar_sharpe: 1.4 },
      index_bug: {
        delayed_sharpe: 0.05, same_bar_sharpe: 8.1,
        note: 'Sinal = 1{r_t>0}. Mesmo bar usa r_t; o relógio honesto usa r_{t+1}.',
      },
      rejected_code: "for i in range(len(df)):\n    if df['pe'].iloc[i] < 10:",
      vectorized_code: 'mask = (pe < 10) & (mom > 0)',
      equity: [{ t: 0, delayed: 1, same_bar: 1 }],
      math: 'Z-score transversal é broadcasting.',
      what_broke: ['Synthetic panel'],
    });
  });

  it('shows that iloc loops fail the desk screen', async () => {
    render(<MemoryRouter><VectorizePage /></MemoryRouter>);
    expect(screen.getByText(/loops em série de preço/i)).toBeInTheDocument();
    expect(await screen.findByText(/reprovado na mesa/i)).toBeInTheDocument();
    expect(screen.getAllByText(/for i in range/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/100×/).length).toBeGreaterThan(0);
    expect(deskVectorize).toHaveBeenCalledWith({});
  });
});
