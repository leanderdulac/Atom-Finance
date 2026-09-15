import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthProvider, useAuth } from './AuthContext';
import { getAccessToken, setAccessToken } from '../services/api';

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

type Route = { ok?: boolean; status?: number; json: () => Promise<unknown> };

function mockFetch(routes: Record<string, Route>) {
  const fn = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : String(input);
    const route = routes[url] ?? { ok: false, status: 404, json: async () => ({ detail: 'no route' }) };
    return {
      ok: route.ok ?? false,
      status: route.status ?? (route.ok ? 200 : 401),
      json: route.json,
    };
  });
  vi.stubGlobal('fetch', fn);
  return fn;
}

const okJson = (body: unknown) => ({ ok: true, status: 200, json: async () => body });
const noSession = () => ({ ok: false, status: 401, json: async () => ({ detail: 'no session' }) });

describe('AuthContext', () => {
  beforeEach(() => {
    localStorage.clear();
    setAccessToken(null); // reset the shared in-memory access token between tests
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    setAccessToken(null);
  });

  it('starts unauthenticated when there is no refresh session', async () => {
    mockFetch({ '/api/auth/refresh': noSession() });
    renderProbe();
    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('false'));
    expect(screen.getByTestId('authenticated')).toHaveTextContent('false');
    expect(localStorage.getItem('atom_jwt')).toBeNull();
  });

  it('restores a session via the HttpOnly refresh cookie', async () => {
    const fetchMock = mockFetch({
      '/api/auth/refresh': okJson({ access_token: 'access-bob', expires_in: 1800 }),
      '/api/auth/me': okJson({ username: 'bob' }),
    });

    renderProbe();

    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('false'));
    expect(screen.getByTestId('authenticated')).toHaveTextContent('true');
    expect(screen.getByTestId('username')).toHaveTextContent('bob');
    expect(getAccessToken()).toBe('access-bob');
    // /me must be called with the freshly-rotated in-memory access token.
    const meCall = fetchMock.mock.calls.find(([u]) => u === '/api/auth/me');
    expect(meCall).toBeDefined();
  });

  it('stays logged out when the backend rejects the refresh', async () => {
    mockFetch({ '/api/auth/refresh': noSession() });
    renderProbe();
    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('false'));
    expect(screen.getByTestId('authenticated')).toHaveTextContent('false');
    expect(getAccessToken()).toBeNull();
  });

  it('login keeps the token in memory only (no localStorage)', async () => {
    mockFetch({
      '/api/auth/refresh': noSession(),
      '/api/auth/login': okJson({ access_token: 'new-token', username: 'alice', role: 'analyst' }),
    });

    const user = userEvent.setup();
    renderProbe();
    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('false'));

    await act(async () => { await user.click(screen.getByText('login')); });

    expect(screen.getByTestId('authenticated')).toHaveTextContent('true');
    expect(screen.getByTestId('username')).toHaveTextContent('alice');
    expect(screen.getByTestId('token')).toHaveTextContent('new-token');
    expect(localStorage.getItem('atom_jwt')).toBeNull();
    expect(getAccessToken()).toBe('new-token');
  });

  it('logout clears the in-memory token and session', async () => {
    mockFetch({
      '/api/auth/refresh': okJson({ access_token: 'access-bob' }),
      '/api/auth/me': okJson({ username: 'bob' }),
      '/api/auth/logout': okJson({ message: 'Logged out.' }),
    });

    const user = userEvent.setup();
    renderProbe();
    await waitFor(() => expect(screen.getByTestId('authenticated')).toHaveTextContent('true'));

    await act(async () => { await user.click(screen.getByText('logout')); });

    expect(screen.getByTestId('authenticated')).toHaveTextContent('false');
    expect(screen.getByTestId('token')).toHaveTextContent('');
    expect(getAccessToken()).toBeNull();
  });
});
