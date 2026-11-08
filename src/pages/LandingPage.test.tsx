import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import LandingPage from './LandingPage';
import { ThemeProvider } from '../theme/ThemeProvider';

function renderLanding() {
  return render(
    <ThemeProvider>
      <MemoryRouter>
        <LandingPage />
      </MemoryRouter>
    </ThemeProvider>
  );
}

describe('LandingPage', () => {
  it('states what ATOM is and that there is no live trading', () => {
    renderLanding();
    expect(screen.getByRole('heading', { name: /mesa de pesquisa quantitativa/i })).toBeInTheDocument();
    expect(screen.getAllByText(/pesquisa quantitativa/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/paper-trading primeiro/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/sem execução ao vivo/i).length).toBeGreaterThan(0);
    expect(screen.queryByText(/rentabilidade futura/i)).toBeInTheDocument();
  });

  it('lists the model families and the layered harness', () => {
    renderLanding();
    expect(screen.getByText(/stat arb e cointegração/i)).toBeInTheDocument();
    expect(screen.getByText(/avellaneda–stoikov/i)).toBeInTheDocument();
    expect(screen.getByText(/heston e derivativos/i)).toBeInTheDocument();
    expect(screen.getByText(/^regimes$/i)).toBeInTheDocument();
    expect(screen.getByText(/evt e cisne negro/i)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /um harness em camadas/i })).toBeInTheDocument();
  });
});
