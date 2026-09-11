import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthProvider, useAuth } from './AuthContext';

const TOKEN_KEY = 'atom_jwt';

function Probe() {
  const { user, token, isAuthenticated, loading, login, logout } = useAuth();
  return (
    <div>
      <span data-testid="loading">{String(loading)}</span>
      <span data-testid="authenticated">{String(isAuthenticated)}</span>
      <span data-testid="username">{user?.username ?? ''}</span>
      <span data-testid="token">{token ?? ''}</span>
      <button onClick={() => login('alice', 'hunter2')}>login</button>
      <button onClick={() => logout()}>logout</button>
    </div>
  );
}

function renderProbe() {
  return render(
    <AuthProvider>
      <Probe />
    </AuthProvider>
  );
}

describe('AuthContext', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('starts unauthenticated with no stored token', async () => {
    renderProbe();
    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('false'));
    expect(screen.getByTestId('authenticated')).toHaveTextContent('false');
  });

  it('restores the session when a valid token is already stored', async () => {
    localStorage.setItem(TOKEN_KEY, 'stored-token');
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ username: 'bob' }),
    });

    renderProbe();

    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('false'));
    expect(screen.getByTestId('authenticated')).toHaveTextContent('true');
    expect(screen.getByTestId('username')).toHaveTextContent('bob');
    expect(fetch).toHaveBeenCalledWith('/api/auth/me', {
      headers: { Authorization: 'Bearer stored-token' },
    });
  });

  it('clears a stored token that the backend rejects', async () => {
    localStorage.setItem(TOKEN_KEY, 'expired-token');
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ ok: false });

    renderProbe();

    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('false'));
    expect(screen.getByTestId('authenticated')).toHaveTextContent('false');
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
  });

  it('login stores the token and marks the user authenticated', async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ access_token: 'new-token', username: 'alice' }),
    });

    const user = userEvent.setup();
    renderProbe();
    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('false'));

    await act(async () => {
      await user.click(screen.getByText('login'));
    });

    expect(screen.getByTestId('authenticated')).toHaveTextContent('true');
    expect(screen.getByTestId('username')).toHaveTextContent('alice');
    expect(localStorage.getItem(TOKEN_KEY)).toBe('new-token');
  });

  it('logout clears the session and local storage', async () => {
    localStorage.setItem(TOKEN_KEY, 'stored-token');
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ username: 'bob' }),
    });

    const user = userEvent.setup();
    renderProbe();
    await waitFor(() => expect(screen.getByTestId('authenticated')).toHaveTextContent('true'));

    await act(async () => {
      await user.click(screen.getByText('logout'));
    });

    expect(screen.getByTestId('authenticated')).toHaveTextContent('false');
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
  });
});
