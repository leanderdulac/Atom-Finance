import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import TargetChoicePage from './TargetChoicePage';

const deskTargetChoice = vi.fn();

vi.mock('../services/api', () => ({
  api: {
    deskTargetChoice: (...args: unknown[]) => deskTargetChoice(...args),
  },
}));

describe('TargetChoicePage', () => {
  beforeEach(() => {
    deskTargetChoice.mockReset().mockResolvedValue({
      scale: {
        move_brl: 500, petr4_last: 30, btc_last: 110000,
        petr4_move_pct: 16.67, btc_move_pct: 0.45,
      },
      stationarity: {
        adf_petr4_price: -1.2, adf_btc_price: -1.1, adf_returns: -8.4,
        critical_5pct: -2.86, price_rejects_unit_root: false, returns_reject_unit_root: true,
      },
      targets: {
        next_price_petr4: { r2: 0.99, rmse: 0.4, accuracy: 0.51, n: 200 },
        next_price_btc: { r2: 0.99, rmse: 1400, accuracy: 0.51, n: 200 },
        next_return: { r2: 0.01, rmse: 0.012, accuracy: 0.5, n: 200 },
        next_vol_regime: { r2: 0.2, rmse: 0.4, accuracy: 0.72, n: 180 },
      },
      transfer: {
        price_rmse_petr_model_on_btc: 80000,
        return_rmse_same_path: 0.012,
        price_rmse_ratio_btc_over_petr: 3500,
      },
      path: [{ t: 0, petr4_indexed: 1, btc_indexed: 1 }],
      math: 'PETR4 e BTC compartilham o mesmo caminho de log-retorno.',
      what_broke: ['Identical log-returns by construction'],
    });
  });

  it('shows that R$500 is not the same move and refuses price as the target', async () => {
    render(<MemoryRouter><TargetChoicePage /></MemoryRouter>);
    expect(screen.getByText(/preço não é alvo/i)).toBeInTheDocument();
    expect(await screen.findByText(/os retornos rejeitam raiz unitária/i)).toBeInTheDocument();
    expect(screen.getAllByText(/r\$\s*500/i).length).toBeGreaterThan(0);
    expect(deskTargetChoice).toHaveBeenCalledWith({});
  });
});
