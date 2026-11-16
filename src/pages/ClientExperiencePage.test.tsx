import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ClientExperiencePage from './ClientExperiencePage';

const capmGbmMulti = vi.fn();

vi.mock('../services/api', () => ({
  api: {
    capmGbmMulti: (...args: unknown[]) => capmGbmMulti(...args),
  },
}));

type AssetInput = { ticker: string; S0: number; mu: number; sigma: number };

function makeSim(assets: AssetInput[], days = 13) {
  const series = (factor: number) =>
    Array.from({ length: days }, (_, i) => factor * (i / (days - 1)));
  return {
    T: 1,
    n_steps: days - 1,
    n_paths: 500,
    time_days: Array.from({ length: days }, (_, i) => Math.round((i * 365) / (days - 1))),
    assets: assets.map((a) => ({
      ...a,
      mean: series(a.S0 * 1.08),
      p5: series(a.S0 * 0.95),
      p95: series(a.S0 * 1.12),
      terminal: {
        mean: a.S0 * 1.08,
        std: a.S0 * 0.1,
        p5: a.S0 * 0.95,
        p50: a.S0 * 1.06,
        p95: a.S0 * 1.12,
        prob_above_S0: 0.6,
        expected_return_pct: 8,
      },
    })),
  };
}

async function answerQuiz(user: ReturnType<typeof userEvent.setup>, labels: string[]) {
  for (const label of labels) {
    await user.click(screen.getByText(label));
  }
}

function renderPage() {
  return render(
    <MemoryRouter>
      <ClientExperiencePage />
    </MemoryRouter>,
  );
}

describe('ClientExperiencePage', () => {
  beforeEach(() => {
    capmGbmMulti.mockReset();
    capmGbmMulti.mockImplementation((payload: { assets: AssetInput[] }) =>
      Promise.resolve(makeSim(payload.assets)),
    );
  });

  it('suggests Arrojado for mid horizon, patience and max return', async () => {
    const user = userEvent.setup();
    renderPage();
    await answerQuiz(user, [
      'Entre 1 e 3 anos',
      'Não mexeria e esperaria',
      'Buscar o maior retorno possível',
    ]);
    expect(screen.getByText('Perfil sugerido: Arrojado')).toBeInTheDocument();
  });

  it('suggests the conservative profile for a short horizon and loss aversion', async () => {
    const user = userEvent.setup();
    renderPage();

    await answerQuiz(user, [
      'Em até 1 ano',
      'Venderia para parar a perda',
      'Proteger o que já tenho',
    ]);

    expect(screen.getByText('Perfil sugerido: Conservador')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /ver meu plano/i }));

    expect(screen.getByText(/quanto você quer simular/i)).toBeInTheDocument();
    expect(screen.getAllByText('Conservador').length).toBeGreaterThan(0);
  });

  it('runs the three profiles and shows the scenario in reais', async () => {
    const user = userEvent.setup();
    renderPage();

    await answerQuiz(user, [
      'Daqui a 3 anos ou mais',
      'Aproveitaria para comprar mais',
      'Buscar o maior retorno possível',
    ]);
    await user.click(screen.getByRole('button', { name: /ver meu plano/i }));
    await user.click(screen.getByRole('button', { name: /simular meu cenário/i }));

    expect(await screen.findAllByText(/cenário típico/i)).not.toHaveLength(0);
    expect(capmGbmMulti).toHaveBeenCalledTimes(3);

    const firstCall = capmGbmMulti.mock.calls[0][0];
    expect(firstCall.T).toBe(5);
    expect(firstCall.n_steps).toBe(1260);
    expect(firstCall.assets.map((a: AssetInput) => a.ticker)).toEqual(['WEGE3', 'ITUB4', 'VALE3']);

    // 10.000 invested, every asset ending at +8% -> R$ 10.800
    expect(screen.getAllByText(/10\.800/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/pior cenário \(10%\)/i).length).toBeGreaterThan(0);
  });

  it('blocks the simulation when the amount is below the minimum', async () => {
    const user = userEvent.setup();
    renderPage();

    await answerQuiz(user, [
      'Entre 1 e 3 anos',
      'Não mexeria e esperaria',
      'Crescer com equilíbrio',
    ]);
    await user.click(screen.getByRole('button', { name: /ver meu plano/i }));

    const amount = screen.getByLabelText(/valor inicial/i);
    await user.clear(amount);
    await user.type(amount, '50');

    expect(screen.getByRole('button', { name: /simular meu cenário/i })).toBeDisabled();
    expect(screen.getByText(/a partir de r\$ 100/i)).toBeInTheDocument();
  });
});
