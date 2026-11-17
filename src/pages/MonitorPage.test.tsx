import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import MonitorPage from './MonitorPage';

const monitorsList = vi.fn();
const monitorsDeclare = vi.fn();
const monitorsGet = vi.fn();
const monitorsCheck = vi.fn();
const monitorsDelete = vi.fn();

vi.mock('../services/api', () => ({
  api: {
    monitorsList: (...a: unknown[]) => monitorsList(...a),
    monitorsDeclare: (...a: unknown[]) => monitorsDeclare(...a),
    monitorsGet: (...a: unknown[]) => monitorsGet(...a),
    monitorsCheck: (...a: unknown[]) => monitorsCheck(...a),
    monitorsDelete: (...a: unknown[]) => monitorsDelete(...a),
  },
}));

const ROW = {
  id: 'm1', ticker: 'PETR4', direction: 'long', entry: 38, stop: 36, target: 41,
  horizon_days: 21, state: 'watching', declared_at: '2026-01-05T12:00:00+00:00',
  last_spot: null, last_check: null,
};

const DETAIL = {
  ...ROW, size: 20, vol_annual: 0.3, entered_at: null, entry_px: null, note: '',
  baseline: { p_profit: 0.42, pnl_p5: -50, pnl_p50: 5, pnl_p95: 90 },
  checks: [],
};

describe('MonitorPage', () => {
  beforeEach(() => {
    monitorsList.mockReset().mockResolvedValue({ monitors: [] });
    monitorsDeclare.mockReset();
    monitorsGet.mockReset().mockResolvedValue(DETAIL);
    monitorsCheck.mockReset();
    monitorsDelete.mockReset().mockResolvedValue({ deleted: 'm1' });
  });

  function renderPage() {
    return render(<MemoryRouter><MonitorPage /></MemoryRouter>);
  }

  it('lists monitors and opens the detail with baseline', async () => {
    monitorsList.mockResolvedValue({ monitors: [ROW] });
    renderPage();
    expect(await screen.findByText('PETR4')).toBeInTheDocument();
    expect(screen.getByText('Aguardando entrada')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Abrir' }));
    expect(await screen.findByText(/P\(lucro\) 42,0%/)).toBeInTheDocument();
  });

  it('declares with mapped numbers and refreshes', async () => {
    monitorsDeclare.mockResolvedValue({ id: 'm2', state: 'watching', baseline: {} });
    monitorsList.mockResolvedValue({ monitors: [] });
    renderPage();
    await userEvent.click(screen.getByRole('button', { name: /declarar e simular base/i }));
    expect(monitorsDeclare).toHaveBeenCalledWith(expect.objectContaining({
      ticker: 'PETR4', direction: 'long', entry: 38, stop: 36, target: 41,
      horizon_days: 21, vol_annual: 0.3, size: 20,
    }));
    expect(await screen.findByText('Meus monitores (0)')).toBeInTheDocument();
  });

  it('checks the monitor and shows fresh alerts', async () => {
    monitorsList.mockResolvedValue({ monitors: [{ ...ROW, state: 'active' }] });
    monitorsGet.mockResolvedValue({
      ...DETAIL, state: 'active',
      checks: [{
        checked_at: '2026-01-06T12:00:00+00:00', spot: 36.2, oracle_usable: true,
        state: 'active', alerts: [{ kind: 'near_stop', text: 'Stop a 10% da distância inicial.' }],
        metrics: {},
      }],
    });
    monitorsCheck.mockResolvedValue({ id: 'm1', state: 'active' });
    renderPage();
    await userEvent.click(await screen.findByRole('button', { name: 'Abrir' }));
    await userEvent.click(screen.getByRole('button', { name: /verificar agora/i }));
    expect(monitorsCheck).toHaveBeenCalledWith('m1');
    expect(await screen.findByText(/Stop a 10%/)).toBeInTheDocument();
  });

  it('surfaces backend errors and deletes', async () => {
    monitorsDeclare.mockRejectedValueOnce(new Error('stop < entry < target'));
    renderPage();
    await userEvent.click(screen.getByRole('button', { name: /declarar e simular base/i }));
    expect(await screen.findByText(/stop < entry < target/)).toBeInTheDocument();
    monitorsList.mockResolvedValue({ monitors: [ROW] });
    renderPage();
    await userEvent.click(await screen.findByRole('button', { name: 'Excluir' }));
    expect(monitorsDelete).toHaveBeenCalledWith('m1');
  });
});
