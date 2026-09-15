import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';

// AuthContext calls fetch('/api/auth/me') on mount when a token is stored;
// with none stored it resolves synchronously without hitting the network.
describe('App routing', () => {
  beforeEach(() => {
    localStorage.clear();
    window.history.pushState({}, '', '/');
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders the landing page at the root path', async () => {
    render(<App />);
    await waitFor(() =>
      expect(screen.getByText(/pesquisa quantitativa/i)).toBeInTheDocument()
    );
  });

  it('renders the login page at /login', async () => {
    window.history.pushState({}, '', '/login');
    render(<App />);
    await waitFor(() => expect(screen.getByRole('button', { name: /entrar/i })).toBeInTheDocument());
  });

  it('redirects an unauthenticated visit to a protected route back to /login', async () => {
    window.history.pushState({}, '', '/dashboard');
    render(<App />);
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /entrar/i })).toBeInTheDocument()
    );
    expect(window.location.pathname).toBe('/login');
  });

  it('redirects an unauthenticated visit to a tool route back to /login', async () => {
    window.history.pushState({}, '', '/pricing');
    render(<App />);
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /entrar/i })).toBeInTheDocument()
    );
    expect(window.location.pathname).toBe('/login');
  });

  it('redirects an unauthenticated visit to /desk back to /login', async () => {
    window.history.pushState({}, '', '/desk');
    render(<App />);
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /entrar/i })).toBeInTheDocument()
    );
    expect(window.location.pathname).toBe('/login');
  });

  it('redirects an unauthenticated visit to /winners-curse back to /login', async () => {
    window.history.pushState({}, '', '/winners-curse');
    render(<App />);
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /entrar/i })).toBeInTheDocument()
    );
    expect(window.location.pathname).toBe('/login');
  });

  it('redirects an unauthenticated visit to /forward-test back to /login', async () => {
    window.history.pushState({}, '', '/forward-test');
    render(<App />);
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /entrar/i })).toBeInTheDocument()
    );
    expect(window.location.pathname).toBe('/login');
  });

  it('redirects an unauthenticated visit to /target-choice back to /login', async () => {
    window.history.pushState({}, '', '/target-choice');
    render(<App />);
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /entrar/i })).toBeInTheDocument()
    );
    expect(window.location.pathname).toBe('/login');
  });

  it('redirects an unauthenticated visit to /quant-doctrine back to /login', async () => {
    window.history.pushState({}, '', '/quant-doctrine');
    render(<App />);
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /entrar/i })).toBeInTheDocument()
    );
    expect(window.location.pathname).toBe('/login');
  });
});
