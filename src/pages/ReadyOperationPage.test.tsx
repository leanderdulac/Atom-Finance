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
    expect(screen.getByText('WEGE3')).toBeInTheDocument();
    expect(screen.queryByText('ABEV3')).not.toBeInTheDocument();
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
      quote_currency: 'BRL',
      spot: 38.1,
      entry: 38.2,
      invalidation: 36,
      target: 41,
      quantity: 20,
      suggested_size: { quantity: 20, risk_budget_brl: 100, notional_brl: 764, can_register_paper: true },
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
    expect(clientReadyOperation).toHaveBeenCalledTimes(1);
    expect(clientReadyOperation.mock.calls[0][0]).toEqual({ ticker: 'PETR4', instrument: 'spot', horizon: 'weeks' });
    expect(clientReadyOperation.mock.calls[0][1]).toEqual(expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect((await screen.findAllByText(/compra à vista/i)).length).toBeGreaterThan(0);
    expect(screen.getByText(/risco máximo de R\$ 100,00/)).toBeInTheDocument();
    expect(screen.getByText(/nocional da posição R\$ 764,00/)).toBeInTheDocument();
    expect(screen.getByText('01/12/2026')).toBeInTheDocument();
    expect(screen.queryByText(/2026-12-01/)).not.toBeInTheDocument();
    expect(screen.queryByText(/orçamento paper/i)).not.toBeInTheDocument();
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
      quote_currency: 'USD',
      fx_usd_brl: { rate: 5.5, source: 'binance:USDTBRL' },
      spot: 77640.12,
      entry: 77641.2,
      invalidation: 69185.36198,
      target: 86000.5,
      quantity: 0.002,
      suggested_size: { quantity: 0.002, risk_budget_brl: 100, notional_brl: 854.05, notional_usd: 155.28, can_register_paper: true },
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
    expect(clientReadyOperation).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: /montar operação/i }));
    expect(clientReadyOperation).toHaveBeenCalledTimes(1);
    expect(clientReadyOperation.mock.calls[0][0]).toEqual({ ticker: 'BTC', instrument: 'future', horizon: 'weeks' });
    expect((await screen.findAllByText(/compra de perpétuo/i)).length).toBeGreaterThan(0);
    expect(screen.getByText(/US\$ 77\.640,12/)).toBeInTheDocument();
    expect(screen.getByText(/US\$ 69\.185,36/)).toBeInTheDocument();
    expect(screen.getByText(/nocional da posição R\$ 854,05/)).toBeInTheDocument();
    expect(screen.getByText(/câmbio USD\/BRL 5,5000/)).toBeInTheDocument();
    expect(screen.getByText('01/12/2026')).toBeInTheDocument();
    expect(screen.queryByText(/2026-12-01/)).not.toBeInTheDocument();
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
    expect(clientReadyOperation).toHaveBeenCalledTimes(1);
    expect(clientReadyOperation.mock.calls[0][0]).toEqual({ ticker: 'PETR4', instrument: 'option', horizon: 'weeks' });
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

  it('holds the explanation behind a loading state until the response arrives', async () => {
    let release!: (value: unknown) => void;
    const gate = new Promise((resolve) => { release = resolve; });
    clientReadyOperation.mockImplementation(async () => {
      await gate;
      return {
        status: 'ready',
        ticker: 'PETR4',
        label: 'Petrobras (PETR4)',
        instrument: 'spot',
        direction: 'bullish',
        structure: { strategy: 'long_stock', legs: [], expiry: '2026-12-01' },
        suggested_size: { quantity: 20, risk_budget_brl: 100, notional_brl: 764, can_register_paper: true },
        why: 'Texto final da IA. Simulação, não recomendação.',
        eligible_for_live_trading: false,
      };
    });
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole('button', { name: /montar operação/i }));
    expect(screen.getByText(/montando o cenário/i)).toBeInTheDocument();
    expect(screen.getByText(/texto final estiver pronto/i)).toBeInTheDocument();
    expect(screen.queryByText(/texto final da IA/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/compra à vista/i)).not.toBeInTheDocument();
    release(undefined);
    expect(await screen.findByText(/texto final da IA/i)).toBeInTheDocument();
    expect(screen.queryByText(/montando o cenário/i)).not.toBeInTheDocument();
  });

  it('sends one request per Montar click, aborts the previous, and ignores a stale ETH/PETR race', async () => {
    let releasePetr!: (value: unknown) => void;
    const petrGate = new Promise((resolve) => { releasePetr = resolve; });
    const petrBody = {
      status: 'ready',
      ticker: 'PETR4',
      label: 'Petrobras (PETR4)',
      instrument: 'spot',
      direction: 'bearish',
      structure: { strategy: 'short_stock', legs: [{ side: 'sell', symbol: 'PETR4', strike: 38, quantity: 20 }], expiry: '2026-12-01' },
      suggested_size: { quantity: 20, risk_budget_brl: 100, notional_brl: 764, can_register_paper: true },
      why: 'PETR antiga — não deveria aparecer.',
      eligible_for_live_trading: false,
    };
    const ethBody = {
      status: 'ready',
      ticker: 'ETH',
      label: 'Ethereum',
      instrument: 'future',
      direction: 'bearish',
      structure: { strategy: 'short_perp', legs: [{ side: 'sell', symbol: 'ETH', strike: 1956, quantity: 0.05 }], expiry: '2026-12-01' },
      suggested_size: { quantity: 0.05, risk_budget_brl: 100, notional_brl: 97.8, can_register_paper: true },
      why: 'ETH final. Simulação, não recomendação.',
      eligible_for_live_trading: false,
    };
    clientReadyOperation
      .mockImplementationOnce(async (_data: unknown, init?: { signal?: AbortSignal }) => {
        await petrGate;
        if (init?.signal?.aborted) {
          const err = new Error('The operation was aborted.');
          err.name = 'AbortError';
          throw err;
        }
        return petrBody;
      })
      .mockImplementationOnce(async () => ethBody);

    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole('button', { name: /montar operação/i }));
    expect(clientReadyOperation).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/montando o cenário/i)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /^cripto$/i }));
    await user.click(screen.getByRole('button', { name: /^ethereum$/i }));
    await user.click(screen.getByRole('button', { name: /futuro \/ perpétuo/i }));
    expect(clientReadyOperation).toHaveBeenCalledTimes(1);
    expect((clientReadyOperation.mock.calls[0][1] as { signal: AbortSignal }).signal.aborted).toBe(true);

    await user.click(screen.getByRole('button', { name: /montar operação/i }));
    expect(clientReadyOperation).toHaveBeenCalledTimes(2);
    expect(clientReadyOperation.mock.calls[1][0]).toEqual({ ticker: 'ETH', instrument: 'future', horizon: 'weeks' });

    releasePetr(undefined);
    expect(await screen.findByText(/ETH final/i)).toBeInTheDocument();
    expect(screen.queryByText(/PETR antiga/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/venda à vista/i)).not.toBeInTheDocument();
    expect(screen.getAllByText(/venda de perpétuo/i).length).toBeGreaterThan(0);
  });

  it('lets the mixed sleeve mark several assets and sends a weighted basket', async () => {
    clientReadyOperation.mockResolvedValue({
      status: 'ready',
      ticker: 'MIX',
      label: 'Carteira mista',
      basket: [
        {
          ticker: 'PETR4',
          label: 'Petrobras (PETR4)',
          status: 'ready',
          weight: 0.4,
          direction: 'bullish',
          instrument: 'spot',
          spot: 38,
          entry: 38.2,
          invalidation: 36,
          quote_currency: 'BRL',
          structure: { strategy: 'long_stock', legs: [{ side: 'buy', symbol: 'PETR4', strike: 38, quantity: 10 }] },
          suggested_size: { quantity: 10, risk_budget_brl: 40, can_register_paper: true },
        },
        {
          ticker: 'BTC',
          label: 'Bitcoin',
          status: 'ready',
          weight: 0.6,
          direction: 'bullish',
          instrument: 'spot',
          spot: 77640.12,
          entry: 78000,
          invalidation: 70000,
          quote_currency: 'USD',
          structure: { strategy: 'long_stock', legs: [{ side: 'buy', symbol: 'BTC', strike: 77640, quantity: 0.001 }] },
          suggested_size: { quantity: 0.001, risk_budget_brl: 60, can_register_paper: true },
        },
      ],
      structure: {
        strategy: 'mixed_book',
        legs: [
          { side: 'buy', symbol: 'PETR4', strike: 38, quantity: 10 },
          { side: 'buy', symbol: 'BTC', strike: 77640, quantity: 0.001 },
        ],
        expiry: '2026-12-01',
      },
      suggested_size: { quantity: 2, risk_budget_brl: 100, notional_brl: 900, can_register_paper: true },
      why: 'Carteira mista com Petrobras e Bitcoin. Simulação, não recomendação.',
      invalidation_reason: 'Cada perna cai no próprio stop.',
      confidence: 'média',
      horizon_label: 'Algumas semanas',
      eligible_for_live_trading: false,
    });
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole('button', { name: /^misto$/i }));
    const petr = screen.getByRole('button', { name: /petrobras/i });
    const btc = screen.getByRole('button', { name: /^bitcoin$/i });
    expect(petr).toHaveAttribute('aria-pressed', 'true');
    await user.click(btc);
    expect(petr).toHaveAttribute('aria-pressed', 'true');
    expect(btc).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText(/2 marcados/i)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /montar operação/i }));
    expect(clientReadyOperation).toHaveBeenCalledTimes(1);
    expect(clientReadyOperation.mock.calls[0][0]).toEqual({
      ticker: 'PETR4',
      tickers: ['PETR4', 'BTC'],
      instrument: 'spot',
      horizon: 'weeks',
      weights: [0.4, 0.6],
    });
    expect(await screen.findByText(/carteira mista com petrobras/i)).toBeInTheDocument();
    expect(screen.getByText(/peso 40,0%/)).toBeInTheDocument();
    expect(screen.getByText(/peso 60,0%/)).toBeInTheDocument();
    expect(screen.getByText(/risco máximo de R\$ 100,00/)).toBeInTheDocument();
    expect(screen.getByText(/carteira com/i)).toHaveTextContent(/2 pernas/);
    expect(screen.getAllByText(/carteira mista/i).length).toBeGreaterThan(0);
  });

  it('keeps B3 and crypto sleeves as a single exclusive asset', async () => {
    clientReadyOperation.mockResolvedValue({
      status: 'ready',
      ticker: 'ETH',
      label: 'Ethereum',
      instrument: 'spot',
      direction: 'bearish',
      structure: { strategy: 'short_stock', legs: [{ side: 'sell', symbol: 'ETH', strike: 1956, quantity: 0.05 }], expiry: '2026-12-01' },
      suggested_size: { quantity: 0.05, risk_budget_brl: 100, can_register_paper: true },
      why: 'ETH único. Simulação, não recomendação.',
      eligible_for_live_trading: false,
    });
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole('button', { name: /^cripto$/i }));
    await user.click(screen.getByRole('button', { name: /^bitcoin$/i }));
    await user.click(screen.getByRole('button', { name: /^ethereum$/i }));
    expect(screen.getByRole('button', { name: /^ethereum$/i })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: /^bitcoin$/i })).toHaveAttribute('aria-pressed', 'false');
    await user.click(screen.getByRole('button', { name: /montar operação/i }));
    expect(clientReadyOperation.mock.calls[0][0]).toEqual({ ticker: 'ETH', instrument: 'spot', horizon: 'weeks' });
    expect(clientReadyOperation.mock.calls[0][0]).not.toHaveProperty('tickers');
  });
});
