import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import SimulationCard from './SimulationCard';

const clientSimulate = vi.fn();

vi.mock('../services/api', () => ({
  api: { clientSimulate: (...args: unknown[]) => clientSimulate(...args) },
}));

const PROPS = {
  s0: 100, direction: 'bullish' as const, entry: 100, stop: 95, target: 110,
  horizonDays: 21, horizonLabel: 'Algumas semanas', size: 10, ccy: 'BRL' as const,
  measuredVol: null, costDefault: null,
};

describe('SimulationCard', () => {
  beforeEach(() => { clientSimulate.mockReset(); });

  it('sends assembled levels and shows the distribution', async () => {
    clientSimulate.mockResolvedValue({
      n_paths: 5000, n_entered: 5000, p_enter: 1, p_profit: 0.42,
      p_profit_given_entry: 0.42, p_stop: 0.5, p_target: 0.3, p_expiry: 0.2,
      pnl_p5: -50, pnl_p25: -10, pnl_p50: 5, pnl_p75: 40, pnl_p95: 90,
      pnl_mean: 8, expected_shortfall_95: 60, median_holding_days: 9,
      model: 'gbm_constant_vol', assumptions: {}, eligible_for_live_trading: false,
      what_broke: ['GBM com vol constante: sem saltos.'],
    });
    render(<SimulationCard {...PROPS} />);
    await userEvent.click(screen.getByRole('button', { name: /simular 5\.000 caminhos/i }));
    expect(clientSimulate).toHaveBeenCalledWith(expect.objectContaining({
      S0: 100, direction: 'long', entry: 100, stop: 95, target: 110,
      horizon_days: 21, vol_annual: 0.3, n_paths: 5000, size: 10,
    }));
    expect(await screen.findByText(/P\(lucro\) 42,0%/)).toBeInTheDocument();
    expect(screen.getByText(/stop 50,0%/)).toBeInTheDocument();
    expect(screen.getByText(/R\$ -50,00/)).toBeInTheDocument();
    expect(screen.getByText(/sem saltos/)).toBeInTheDocument();
  });

  it('refuses to simulate an unsized quantity', async () => {
    render(<SimulationCard {...PROPS} size={0} sizeNote="sem câmbio USD/BRL" />);
    expect(screen.getByText(/tamanho não dimensionado/)).toBeInTheDocument();
    expect(screen.getByText(/sem câmbio USD\/BRL/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /simular/i })).not.toBeInTheDocument();
    expect(clientSimulate).not.toHaveBeenCalled();
  });

  it('starts from measured vol and prefilled costs', async () => {
    clientSimulate.mockResolvedValue({
      n_paths: 5000, n_entered: 5000, p_enter: 1, p_profit: 0.5,
      p_profit_given_entry: 0.5, p_stop: 0.2, p_target: 0.2, p_expiry: 0.6,
      pnl_p5: 0, pnl_p25: 0, pnl_p50: 0, pnl_p75: 0, pnl_p95: 0,
      pnl_mean: 0, expected_shortfall_95: 0, median_holding_days: 1,
      model: 'gbm_constant_vol', assumptions: {}, eligible_for_live_trading: false,
      what_broke: [],
    });
    render(<SimulationCard {...PROPS} measuredVol={0.62} costDefault={4.5} />);
    expect(screen.getByText(/medida 62%/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /simular/i }));
    expect(clientSimulate).toHaveBeenCalledWith(expect.objectContaining({
      vol_annual: 0.62, cost_total: 4.5,
    }));
  });

  it('falls back to 30% vol and zero costs without measurements', async () => {
    clientSimulate.mockResolvedValue({
      n_paths: 5000, n_entered: 5000, p_enter: 1, p_profit: 0.5,
      p_profit_given_entry: 0.5, p_stop: 0.2, p_target: 0.2, p_expiry: 0.6,
      pnl_p5: 0, pnl_p25: 0, pnl_p50: 0, pnl_p75: 0, pnl_p95: 0,
      pnl_mean: 0, expected_shortfall_95: 0, median_holding_days: 1,
      model: 'gbm_constant_vol', assumptions: {}, eligible_for_live_trading: false,
      what_broke: [],
    });
    render(<SimulationCard {...PROPS} />);
    expect(screen.getByText(/padrão 30%: sem medida/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /simular/i }));
    expect(clientSimulate).toHaveBeenCalledWith(expect.objectContaining({
      vol_annual: 0.3, cost_total: 0,
    }));
  });

  it('maps bearish to short and surfaces backend errors', async () => {
    clientSimulate.mockRejectedValueOnce(new Error('stop < entry < target'));
    render(<SimulationCard {...PROPS} direction="bearish" />);
    await userEvent.click(screen.getByRole('button', { name: /simular/i }));
    expect(clientSimulate).toHaveBeenCalledWith(expect.objectContaining({ direction: 'short' }));
    expect(await screen.findByText(/stop < entry < target/)).toBeInTheDocument();
  });
});
