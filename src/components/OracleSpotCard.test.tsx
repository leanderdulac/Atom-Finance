import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import OracleSpotCard from './OracleSpotCard';

const oracleSpot = vi.fn();

vi.mock('../services/api', () => ({
  api: { oracleSpot: (...args: unknown[]) => oracleSpot(...args) },
}));

describe('OracleSpotCard', () => {
  beforeEach(() => { oracleSpot.mockReset(); });

  it('shows price, source ages and disagreement warning', async () => {
    oracleSpot.mockResolvedValue({
      symbol: 'PETR4', asset_class: 'equity_br', usable: true, price: 38.1,
      method: 'median_fresh', disagreement_bps: 75.5,
      sources: [
        { provider: 'brapi', ok: true, price: 38.0, age_unknown: true, stale: false },
        { provider: 'yfinance', ok: true, price: 38.2, age_s: 400, stale: true },
      ],
      stale: ['yfinance'], blockers: ['yfinance: cotação velha (400s > 300s).'],
      fetched_at: '', eligible_for_live_trading: false,
    });
    render(<OracleSpotCard ticker="PETR4" />);
    expect(await screen.findByText(/Oráculo · PETR4/)).toBeInTheDocument();
    expect(screen.getByText(/brapi · idade\?/)).toBeInTheDocument();
    expect(screen.getByText(/yfinance · 400s · velha/)).toBeInTheDocument();
    expect(screen.getByText(/divergem 75,5 bps/)).toBeInTheDocument();
  });

  it('warns when the oracle has no quote and hides on transport failure', async () => {
    oracleSpot.mockResolvedValueOnce({
      symbol: 'XXX', usable: false, price: null, sources: [],
      disagreement_bps: null, stale: [], blockers: ['brapi: down'],
      fetched_at: '', eligible_for_live_trading: false,
    });
    const { unmount } = render(<OracleSpotCard ticker="XXX" />);
    expect(await screen.findByText(/sem cotação/)).toBeInTheDocument();
    unmount();
    oracleSpot.mockRejectedValueOnce(new Error('boom'));
    const { container } = render(<OracleSpotCard ticker="XXX" />);
    await waitFor(() => expect(oracleSpot).toHaveBeenCalledTimes(2));
    expect(container).toBeEmptyDOMElement();
  });
});
