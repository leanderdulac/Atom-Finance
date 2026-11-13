import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { useAuth } from './AuthContext';

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

const OPERATOR_MODE_KEY = 'atom.operatorMode';

interface OperatorModeValue {
  canOperate: boolean;
  showDesk: boolean;
  enterOperatorMode: () => void;
  exitOperatorMode: () => void;
}

const OperatorModeContext = createContext<OperatorModeValue>({
  canOperate: false,
  showDesk: false,
  enterOperatorMode: () => {},
  exitOperatorMode: () => {},
});

export function OperatorModeProvider({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  const cfg = useClientConfig();
  const canOperate = isOperatorRole(user?.role, cfg.operator_roles);
  const [flag, setFlag] = useState(() => {
    try {
      return localStorage.getItem(OPERATOR_MODE_KEY) === '1';
    } catch {
      return false;
    }
  });
  const enterOperatorMode = useCallback(() => {
    try { localStorage.setItem(OPERATOR_MODE_KEY, '1'); } catch { /* ignore */ }
    setFlag(true);
  }, []);
  const exitOperatorMode = useCallback(() => {
    try { localStorage.removeItem(OPERATOR_MODE_KEY); } catch { /* ignore */ }
    setFlag(false);
  }, []);
  const value = useMemo(
    () => ({ canOperate, showDesk: Boolean(canOperate && flag), enterOperatorMode, exitOperatorMode }),
    [canOperate, flag, enterOperatorMode, exitOperatorMode],
  );
  return <OperatorModeContext.Provider value={value}>{children}</OperatorModeContext.Provider>;
}

export function useOperatorMode() {
  return useContext(OperatorModeContext);
}
