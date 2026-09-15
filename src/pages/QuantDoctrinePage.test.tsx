import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import QuantDoctrinePage from './QuantDoctrinePage';

const deskDoctrine = vi.fn();

vi.mock('../services/api', () => ({
  api: {
    deskDoctrine: (...args: unknown[]) => deskDoctrine(...args),
  },
}));

describe('QuantDoctrinePage', () => {
  beforeEach(() => {
    deskDoctrine.mockReset().mockResolvedValue({
      version: 'ATOM-QUANT-1.0',
      system: 'Você é a mesa de pesquisa ATOM. eligible_for_live_trading é sempre false.',
      tenets: [
        {
          id: 'winners_curse',
          title: 'O aleatório é a base do sinal',
          lab: '/winners-curse',
          summary: 'DSR antes de arriscar capital.',
        },
      ],
      eligible_for_live_trading: false,
      note: 'Isto não é fine-tune de pesos. É a constituição da mesa.',
    });
  });

  it('loads the desk constitution and refuses live trading', async () => {
    render(<MemoryRouter><QuantDoctrinePage /></MemoryRouter>);
    expect(screen.getByText(/doutrina da mesa/i)).toBeInTheDocument();
    expect(await screen.findByText('ATOM-QUANT-1.0')).toBeInTheDocument();
    expect(screen.getAllByText(/não é fine-tune/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/o aleatório é a base do sinal/i)).toBeInTheDocument();
    expect(screen.getByText(/eligible_for_live_trading = false/i)).toBeInTheDocument();
    expect(deskDoctrine).toHaveBeenCalled();
  });
});
