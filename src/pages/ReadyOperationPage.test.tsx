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
        { id: 'ETH', label: 'Ethereum', asset_class: 'crypto', instruments: ['spot', 'future'] },
        { id: 'SOL', label: 'Solana', asset_class: 'crypto', instruments: ['spot', 'future'] },
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

  it('shows the four client choices and no desk menu / meu plano link', () => {
    renderPage();
    expect(screen.getByText(/a operação vem pronta/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /ações \(b3\)/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^cripto$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /petrobras/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /à vista/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /algumas semanas/i })).toBeInTheDocument();
    expect(screen.getByText(/retorno desejado/i)).toBeInTheDocument();
    expect(screen.queryByText(/ver meu plano de investimento/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/mesa de operações/i)).not.toBeInTheDocument();
    expect(screen.getAllByText(/não recomendação/i).length).toBeGreaterThan(0);
  });

  it('suggests Arrojado and a crypto book when those answers + cripto are chosen', async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole('button', { name: /^cripto$/i }));
    await user.click(screen.getByRole('button', { name: /entre 1 e 3 anos/i }));
    await user.click(screen.getByRole('button', { name: /não mexeria e esperaria/i }));
    await user.click(screen.getByRole('button', { name: /buscar o maior retorno possível/i }));
    expect(screen.getByText('Perfil sugerido: Arrojado')).toBeInTheDocument();
    expect(screen.getByText('SOL')).toBeInTheDocument();
    expect(screen.getByText('ETH')).toBeInTheDocument();
    expect(screen.getByText('BTC')).toBeInTheDocument();
    expect(screen.queryByText('ITUB4')).not.toBeInTheDocument();
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
      sources: [{ title: 'Comunicado Copom', url: 'https://www.bcb.gov.br/copom', date: '2026-11-12' }],
      thermometer: {
        label: 'Clima do mercado para PETR4: otimista',
        tone: 'otimista',
        headlines: [{ title: 'Petrobras sobe com recorde', url: 'https://www.bcb.gov.br/noticia', date: '2026-11-12' }],
      },
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
    expect(screen.getByRole('link', { name: /comunicado copom/i })).toHaveAttribute(
      'href',
      'https://www.bcb.gov.br/copom',
    );
    expect(screen.getByText(/clima do mercado para petr4: otimista/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /petrobras sobe com recorde/i })).toHaveAttribute(
      'href',
      'https://www.bcb.gov.br/noticia',
    );
    expect(screen.getAllByText(/aguardando gatilho/i).length).toBeGreaterThan(0);
    expect(screen.queryByText(/eligible_for_live_trading/i)).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /registrar como operação paper/i }));
    expect(clientReadyPaper).toHaveBeenCalled();
    expect(await screen.findByText(/diário é o único escritor/i)).toBeInTheDocument();
  });

  it('assembles BTC when the client switches the asset', async () => {
    clientReadyOperation.mockResolvedValue({
      status: 'ready',
      ticker: 'BTC',
      label: 'Bitcoin',
      instrument: 'future',
      horizon_label: 'Algumas semanas',
      direction: 'bullish',
      structure: { strategy: 'long_perp', legs: [{ side: 'buy', symbol: 'BTC', strike: 95000, quantity: 0.01 }], expiry: '2026-12-01' },
      spot: 77640.12,
      entry: 77641.2,
      invalidation: 69185.36198,
      target: 86000.5,
      quantity: 0.01,
      suggested_size: { quantity: 0.01, risk_budget_brl: 100, can_register_paper: true },
      confidence: 'média',
      invalidation_reason: 'A tese cai se o preço cruzar 69.185,36.',
      why: 'Cenário de alta em Bitcoin. Simulação, não recomendação.',
      disclaimer: 'Cenário/simulação.',
      eligible_for_live_trading: false,
    });
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole('button', { name: /^cripto$/i }));
    await user.click(screen.getByRole('button', { name: /^bitcoin$/i }));
    await user.click(screen.getByRole('button', { name: /futuro \/ perpétuo/i }));
    expect(clientReadyOperation).toHaveBeenCalledWith({ ticker: 'BTC', instrument: 'future', horizon: 'weeks' });
    expect((await screen.findAllByText(/compra de perpétuo/i)).length).toBeGreaterThan(0);
    expect(screen.getByText('77.640,12')).toBeInTheDocument();
    expect(screen.getByText('69.185,36')).toBeInTheDocument();
    expect(screen.queryByText(/e\+0/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/69185,36198/)).not.toBeInTheDocument();
  });

  it('renders an option structure', async () => {
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
