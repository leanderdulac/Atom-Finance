import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ReadyOperationPage from './ReadyOperationPage';

const clientReadyOperation = vi.fn();
const clientReadyPaper = vi.fn();

vi.mock('../services/api', () => ({
  api: {
    clientReadyOperation: (...args: unknown[]) => clientReadyOperation(...args),
    clientReadyPaper: (...args: unknown[]) => clientReadyPaper(...args),
  },
}));

vi.mock('../contexts/ClientModeContext', async () => {
  const actual = await vi.importActual<typeof import('../contexts/ClientModeContext')>('../contexts/ClientModeContext');
  return {
    ...actual,
    useClientConfig: () => ({
      client_mode: true,
      universe: [
        { id: 'PETR4', label: 'Petrobras (PETR4)', asset_class: 'equity_br', instruments: ['spot', 'option'] },
        { id: 'BTC', label: 'Bitcoin', asset_class: 'crypto', instruments: ['spot', 'future'] },
      ],
      instruments: [
        { id: 'spot', label: 'À vista (ação ou cripto)', hint: 'Compra ou venda simulada do próprio ativo.' },
        { id: 'option', label: 'Opção', hint: 'Livro com bid e ask.' },
        { id: 'future', label: 'Futuro / perpétuo', hint: 'Só cripto.' },
      ],
      horizons: [
        { id: 'days', label: 'Alguns dias', holding_days: 5 },
        { id: 'weeks', label: 'Algumas semanas', holding_days: 21 },
        { id: 'months', label: 'Alguns meses', holding_days: 63 },
      ],
      disclaimer: 'Cenário, não recomendação.',
      operator_roles: ['admin', 'operator'],
      eligible_for_live_trading: false,
    }),
  };
});

function renderPage() {
  return render(
    <MemoryRouter>
      <ReadyOperationPage />
    </MemoryRouter>,
  );
}

describe('ReadyOperationPage', () => {
  beforeEach(() => {
    clientReadyOperation.mockReset();
    clientReadyPaper.mockReset();
  });

  it('shows the three choices in plain language', () => {
    renderPage();
    expect(screen.getByText(/três escolhas/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /petrobras/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /à vista/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /algumas semanas/i })).toBeInTheDocument();
    expect(screen.getAllByText(/não recomendação/i).length).toBeGreaterThan(0);
  });

  it('renders a ready spot operation and registers paper', async () => {
    clientReadyOperation.mockResolvedValue({
      status: 'ready',
      ticker: 'PETR4',
      label: 'Petrobras (PETR4)',
      instrument: 'spot',
      horizon_label: 'Alguns dias',
      direction: 'bullish',
      structure: { strategy: 'long_stock', legs: [{ side: 'buy', symbol: 'PETR4', strike: 38, quantity: 20 }], expiry: '2026-12-01' },
      spot: 38.1,
      entry: 38.2,
      invalidation: 36,
      target: 41,
      quantity: 20,
      suggested_size: { quantity: 20, risk_budget_brl: 100, can_register_paper: true },
      confidence: 'média',
      invalidation_reason: 'A tese cai abaixo de 36.',
      why: 'Cenário de alta em PETR4 montado com cotação e volatilidade. Simulação, não recomendação.',
      disclaimer: 'Cenário/simulação. Não é recomendação.',
      eligible_for_live_trading: false,
    });
    clientReadyPaper.mockResolvedValue({
      message: 'Registrada como operação paper, aguardando gatilho. O diário é o único escritor.',
      status: 'watching',
    });
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole('button', { name: /montar operação/i }));
    expect(clientReadyOperation).toHaveBeenCalledWith({ ticker: 'PETR4', instrument: 'spot', horizon: 'weeks' });
    expect((await screen.findAllByText(/compra à vista/i)).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/aguardando gatilho/i).length).toBeGreaterThan(0);
    await user.click(screen.getByRole('button', { name: /registrar como operação paper/i }));
    expect(clientReadyPaper).toHaveBeenCalled();
    expect(await screen.findByText(/diário é o único escritor/i)).toBeInTheDocument();
  });

  it('renders an option structure with greeks', async () => {
    clientReadyOperation.mockResolvedValue({
      status: 'ready',
      ticker: 'PETR4',
      label: 'Petrobras (PETR4)',
      instrument: 'option',
      horizon_label: 'Alguns dias',
      direction: 'bullish',
      structure: {
        strategy: 'bull_call_spread',
        legs: [
          { side: 'buy', symbol: 'PETRC38', strike: 38, quantity: 1 },
          { side: 'sell', symbol: 'PETRC42', strike: 42, quantity: 1 },
        ],
        expiry: '2026-12-19',
      },
      spot: 38.1,
      entry: 38.2,
      invalidation: 36,
      target: 42,
      suggested_size: { quantity: 1, risk_budget_brl: 100, can_register_paper: true },
      greeks: { price: 1.2, delta: 0.55, gamma: 0.08, theta: -0.02, vega: 0.11 },
      confidence: 'média',
      invalidation_reason: 'A tese cai abaixo de 36.',
      why: 'Trava de alta montada pelo planner. Sem promessa de retorno.',
      disclaimer: 'Cenário/simulação.',
      eligible_for_live_trading: false,
    });
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole('button', { name: /^opção$/i }));
    await user.click(screen.getByRole('button', { name: /montar operação/i }));
    expect(clientReadyOperation).toHaveBeenCalledWith({ ticker: 'PETR4', instrument: 'option', horizon: 'weeks' });
    expect((await screen.findAllByText(/trava de alta com calls/i)).length).toBeGreaterThan(0);
    expect(screen.getByText(/gregas da perna comprada/i)).toBeInTheDocument();
  });

  it('says so when the arsenal has no book or signal', async () => {
    clientReadyOperation.mockResolvedValue({
      status: 'insufficient',
      reason: 'O arsenal não tem livro de opções utilizável para PETR4.',
      eligible_for_live_trading: false,
    });
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole('button', { name: /montar operação/i }));
    expect(await screen.findByText(/o arsenal não montou operação/i)).toBeInTheDocument();
    expect(screen.getByText(/não inventamos/i)).toBeInTheDocument();
  });
});
