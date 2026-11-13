import React, { createContext, useContext, useEffect, useState } from 'react';

export type ClientInstrument = { id: string; label: string; hint: string };
export type ClientHorizon = { id: string; label: string; holding_days: number };
export type ClientAsset = { id: string; label: string; asset_class: string; instruments: string[] };

export interface ClientConfig {
  client_mode: boolean;
  universe: ClientAsset[];
  instruments: ClientInstrument[];
  horizons: ClientHorizon[];
  disclaimer: string;
  operator_roles: string[];
  eligible_for_live_trading: boolean;
}

const fallback: ClientConfig = {
  client_mode: false,
  universe: [],
  instruments: [],
  horizons: [],
  disclaimer: '',
  operator_roles: ['admin', 'operator'],
  eligible_for_live_trading: false,
};

const ClientModeContext = createContext<ClientConfig>(fallback);

export function ClientModeProvider({ children }: { children: React.ReactNode }) {
  const [config, setConfig] = useState<ClientConfig>(fallback);
  useEffect(() => {
    let cancelled = false;
    fetch('/api/client/config')
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!cancelled && data && typeof data.client_mode === 'boolean') {
          setConfig({ ...fallback, ...data });
        }
      })
      .catch(() => { /* landing works without the backend */ });
    return () => { cancelled = true; };
  }, []);
  return <ClientModeContext.Provider value={config}>{children}</ClientModeContext.Provider>;
}

export function useClientConfig() {
  return useContext(ClientModeContext);
}

export function isOperatorRole(role?: string, operatorRoles: string[] = fallback.operator_roles) {
  return operatorRoles.includes((role || '').toLowerCase());
}
