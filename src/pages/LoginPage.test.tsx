import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import LoginPage from './LoginPage';

const login = vi.fn();

vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ login, register: vi.fn() }),
}));

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

function renderLoginAt(path: string, state?: unknown) {
  const entries = state === undefined ? [path] : [{ pathname: path, state }];
  return render(
    <MemoryRouter initialEntries={entries}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('LoginPage redirect-back', () => {
  beforeEach(() => {
    login.mockReset().mockResolvedValue(undefined);
  });

  it('returns to the protected page after login', async () => {
    const user = userEvent.setup();
    renderLoginAt('/login', { from: '/ml' });
    await user.type(screen.getByLabelText(/usuário/i), 'ana');
    await user.type(screen.getByLabelText(/^senha$/i), 'twelve-chars-pw');
    await user.click(screen.getByRole('button', { name: /entrar/i }));
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/ml'));
  });

  it('falls back to the dashboard without a destination', async () => {
    const user = userEvent.setup();
    renderLoginAt('/login');
    await user.type(screen.getByLabelText(/usuário/i), 'ana');
    await user.type(screen.getByLabelText(/^senha$/i), 'twelve-chars-pw');
    await user.click(screen.getByRole('button', { name: /entrar/i }));
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/dashboard'));
  });

  it('rejects absolute-URL destinations (open redirect)', async () => {
    const user = userEvent.setup();
    renderLoginAt('/login', { from: '//evil.example/phish' });
    await user.type(screen.getByLabelText(/usuário/i), 'ana');
    await user.type(screen.getByLabelText(/^senha$/i), 'twelve-chars-pw');
    await user.click(screen.getByRole('button', { name: /entrar/i }));
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/dashboard'));
  });
});
