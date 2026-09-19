import type { PaperRecord, PaperSummary, SourceCheck, SourceSnapshotSummary } from '../types/paperTrading';
const API_BASE = '/api';

// The access token is short-lived and kept ONLY in memory. It is never written
// to localStorage/sessionStorage, so a stored-XSS vector cannot steal a usable
// credential. Sessions are restored/refreshed through the HttpOnly refresh cookie
// (/auth/refresh), which JS cannot read.
let accessToken: string | null = null;
let refreshPromise: Promise<boolean> | null = null;

export function getAccessToken(): string | null { return accessToken; }
export function setAccessToken(token: string | null): void { accessToken = token; }

async function refreshAccessToken(): Promise<boolean> {
  if (refreshPromise) return refreshPromise;
  refreshPromise = (async () => {
    try {
      const res = await fetch(`${API_BASE}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // the HttpOnly refresh cookie is sent automatically (same-origin, SameSite=Lax)
      });
      if (!res.ok) { accessToken = null; return false; }
      const data = await res.json();
      accessToken = data.access_token ?? null;
      return accessToken !== null;
    } catch {
      accessToken = null;
      return false;
    }
  })().finally(() => { refreshPromise = null; });
  return refreshPromise;
}

function getAuthHeader(): Record<string, string> {
  return accessToken ? { Authorization: `Bearer ${accessToken}` } : {};
}

// Endpoints where a 401 is a genuine "bad credentials/session" answer, not an
// expired access token, so we must NOT auto-refresh on them.
const NO_REFRESH = new Set(['/auth/login', '/auth/register', '/auth/refresh', '/auth/logout']);

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const doFetch = () => fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...getAuthHeader() },
    ...options,
  });
  let res = await doFetch();
  if (res.status === 401 && !NO_REFRESH.has(path)) {
    if (await refreshAccessToken()) {
      res = await doFetch();
    } else {
      setAccessToken(null);
    }
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(Array.isArray(err.detail) ? err.detail.map((item: { msg: string }) => item.msg).join('; ') : (err.detail || 'API Error'));
  }
  return res.json();
}

export interface ResearchPaper {
  id: string;
  root_node_id: string;
  nodes: Record<string, { node_id: string; title: string; summary: string; content?: string; citations: { source_id: string; quote?: string; page?: number }[] }>;
  authors: string[];
  asset_classes: string[];
  as_of: string;
}
export interface ResearchSummary { id: string; title: string; created_at: string }

export interface QuantMetrics {
  gross_return_pct: number; net_return_pct: number; sharpe_net: number;
  annualized_volatility_pct: number; max_drawdown_pct: number; turnover_total: number;
  cost_paid_pct_initial: number; mse_oos?: number; equity: number[];
}
export interface QuantExperiment {
  run_id?: string; experiment_id: string; policy_version: string; assessment: string;
  config: { model: string }; reasons: string[]; limitations: string[];
  results: Record<string, QuantMetrics>;
  folds: { fold: number; train_end: string; last_train_label_end: string; test_start: string; test_end: string; test_count: number; net_return_pct: number }[];
}
export interface ExperimentSummary { id: string; created_at: string; status: string; input_hash: string; error: string | null; hypothesis: string; data_source: string; model: string; assessment: string | null }
export interface ExperimentDetail {
  id: string; created_at: string; status: string; input_hash: string; error: string | null;
  inputs: { hypothesis: string; data_source: string; prices: number[]; dates: string[]; price_basis: string; commission_bps: number; slippage_bps: number; target_volatility: number; max_drawdown: number };
  result: QuantExperiment | null;
  reviews: { id: string; created_at: string; decision: string; rationale: string }[];
}
export const api = {
  sourceSnapshots: (ticker:string) => request<SourceSnapshotSummary[]>(`/sources/snapshots?ticker=${encodeURIComponent(ticker)}`),
  paperSourceCheck: (id:string,snapshotId:string) => request<SourceCheck>(`/paper-trades/${encodeURIComponent(id)}/source-check/${encodeURIComponent(snapshotId)}`),
  sourceStatus: () => request<Record<string,{configured?:boolean;access?:string;data_mode?:string}>>('/sources/status'),
  sourceExpirations: (ticker:string) => request<{expirations:string[]}>(`/sources/expirations?ticker=${encodeURIComponent(ticker)}`),
  sourceChain: (provider:string,ticker:string,expiry:string) => request<unknown>(`/sources/chain?provider=${provider}&ticker=${encodeURIComponent(ticker)}${expiry?'&expiry='+encodeURIComponent(expiry):''}`),
  sourceSnapshot: (id:string) => request<unknown>(`/sources/snapshots/${encodeURIComponent(id)}`),
  sourceSelic: () => request<{value:number;observed_date:string;annualized_252_pct:number;note:string}>('/sources/selic'),
  sourceCvm: (kind:string) => request<{dataset:string;note:string;resources:{name:string;url:string;format:string}[]}>(`/sources/cvm?kind=${kind}`),
  paperTrack: (plan_id:string,plan_index:number) => request<PaperRecord>('/paper-trades', {method:'POST',body:JSON.stringify({plan_id,plan_index})}),
  paperHistory: () => request<PaperSummary[]>('/paper-trades'),
  paperRecord: (id:string) => request<PaperRecord>(`/paper-trades/${encodeURIComponent(id)}`),
  paperEvent: (id:string,data:object) => request<PaperRecord>(`/paper-trades/${encodeURIComponent(id)}/events`, {method:'POST',body:JSON.stringify(data)}),
  derivativePlan: (data: object) => request<unknown>('/derivatives/plan', { method: 'POST', body: JSON.stringify(data) }),
  derivativeHistory: () => request<{id: string; created_at: string}[]>('/derivatives/plans'),
  derivativeRecord: (id: string) => request<{inputs: unknown; result: unknown}>(`/derivatives/plans/${encodeURIComponent(id)}`),
  experiments: (offset = 0) => request<{items: ExperimentSummary[]; total: number}>(`/ml/experiments?offset=${offset}`),
  experiment: (id: string) => request<ExperimentDetail>(`/ml/experiments/${encodeURIComponent(id)}`),
  reviewExperiment: (id: string, decision: string, rationale: string) => request<ExperimentDetail>(`/ml/experiments/${encodeURIComponent(id)}/reviews`, { method: 'POST', body: JSON.stringify({ decision, rationale }) }),
  researchMarketHistory: (ticker: string) => request<{close: number[]; dates: string[]; provider?: string; source?: string}>(`/market-data/history/${encodeURIComponent(ticker)}?days=1825&period=5y&provider=yfinance`),
  quantEvaluate: (data: object) => request<QuantExperiment>('/ml/evaluate', { method: 'POST', body: JSON.stringify(data) }),
  screenerTopPicks: () => request<any[]>('/screener/top-picks'),
  autopilotGenerate: (data: { capital: number; horizon_days: number }) =>
    request<any>('/autopilot/generate', { method: 'POST', body: JSON.stringify(data) }),
  researchHistory: () => request<ResearchSummary[]>('/research/papers'),
  researchPaper: (id: string) => request<ResearchPaper>(`/research/papers/${encodeURIComponent(id)}`),
  researchExtract: (kind: 'text' | 'arxiv', content: string) => request<ResearchPaper>('/research/papers', { method: 'POST', body: JSON.stringify({ kind, content }) }),
  // Health & auth
  health: () => request<{ status: string }>('/health'),
  login: (username: string, password: string) =>
    request<{ access_token: string; username: string; role: string; refresh_cookie_set?: boolean }>(
      '/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) },
    ),
  register: (username: string, email: string, password: string) =>
    request<{ message: string }>('/auth/register', { method: 'POST', body: JSON.stringify({ username, email, password }) }),
  refresh: () => refreshAccessToken(),
  logout: () => request<{ message: string }>('/auth/logout', { method: 'POST', body: '{}' }),
  me: () => request<{ username: string; email?: string; role?: string }>('/auth/me'),

  // Pricing
  blackScholes: (data: any) => request('/pricing/black-scholes', { method: 'POST', body: JSON.stringify(data) }),
  monteCarlo: (data: any) => request('/pricing/monte-carlo', { method: 'POST', body: JSON.stringify(data) }),
  binomial: (data: any) => request('/pricing/binomial', { method: 'POST', body: JSON.stringify(data) }),
  finiteDifference: (data: any) => request('/pricing/finite-difference', { method: 'POST', body: JSON.stringify(data) }),
  impliedVolatility: (data: any) => request('/pricing/implied-volatility', { method: 'POST', body: JSON.stringify(data) }),
  volSurface: (data: any) => request('/pricing/volatility-surface', { method: 'POST', body: JSON.stringify(data) }),
  compareModels: (data: any) => request('/pricing/compare', { method: 'POST', body: JSON.stringify(data) }),
  strategy: (data: any) => request('/pricing/strategy', { method: 'POST', body: JSON.stringify(data) }),
  straddle: (data: any) => request(`/pricing/strategy/straddle?strike=${data.strike}`, { method: 'POST', body: JSON.stringify(data) }),
  ironCondor: (data: any) => request('/pricing/strategy/iron-condor', { method: 'POST', body: JSON.stringify(data) }),
  butterfly: (data: any) => request('/pricing/strategy/butterfly', { method: 'POST', body: JSON.stringify(data) }),

  // Risk
  var: (data: any) => request('/risk/var', { method: 'POST', body: JSON.stringify(data) }),
  varAll: (data: any) => request('/risk/var/all-methods', { method: 'POST', body: JSON.stringify(data) }),
  stressTest: (data: any) => request('/risk/stress-test', { method: 'POST', body: JSON.stringify(data) }),
  garch: (data: any) => request('/risk/garch', { method: 'POST', body: JSON.stringify(data) }),
  heston: (data: any) => request('/risk/heston', { method: 'POST', body: JSON.stringify(data) }),

  // Portfolio
  efficientFrontier: (data: any) => request('/portfolio/efficient-frontier', { method: 'POST', body: JSON.stringify(data) }),
  maxSharpe: (data: any) => request('/portfolio/max-sharpe', { method: 'POST', body: JSON.stringify(data) }),
  riskParity: (data: any) => request('/portfolio/risk-parity', { method: 'POST', body: JSON.stringify(data) }),
  blackLitterman: (data: any) => request('/portfolio/black-litterman', { method: 'POST', body: JSON.stringify(data) }),

  // Tail risk
  tailRisk: (data: any) => request('/black-swan/tail-risk', { method: 'POST', body: JSON.stringify(data) }),
  regimeChange: (data: any) => request('/black-swan/regime-change', { method: 'POST', body: JSON.stringify(data) }),
  blackSwanFull: (data: any) => request('/black-swan/full-analysis', { method: 'POST', body: JSON.stringify(data) }),
  blackSwanDemo: () => request('/black-swan/demo'),

  // Market Data
  marketProviders: () => request('/market-data/providers'),
  quote: (ticker: string, provider = 'auto') => request(`/market-data/quote/${ticker}?provider=${provider}`),
  history: (ticker: string, days?: number, provider = 'auto') => request(`/market-data/history/${ticker}?days=${days || 252}&provider=${provider}`),
  profile: (ticker: string) => request(`/market-data/profile/${ticker}`),
  search: (query: string) => request(`/market-data/search?query=${encodeURIComponent(query)}`),
  optionsChain: (ticker: string, provider = 'auto') => request(`/market-data/options-chain/${ticker}?provider=${provider}`),
  volatility: (ticker: string) => request(`/market-data/volatility/${ticker}`),
  returns: (ticker: string, period = '1y') => request(`/market-data/returns/${ticker}?period=${period}`),

  // Backtesting
  backtest: (data: any) => request('/backtesting/run', { method: 'POST', body: JSON.stringify(data) }),

  // Neural SDE
  neuralSdeStatus: () => request('/neural-sde/status'),
  neuralSdeDemo: () => request('/neural-sde/demo'),
  neuralSdeSimulate: (data: any) => request('/neural-sde/simulate', { method: 'POST', body: JSON.stringify(data) }),

  // CAPM & Kelly
  capmDemo: () => request('/capm/demo'),
  capmBeta: (data: any) => request('/capm/beta', { method: 'POST', body: JSON.stringify(data) }),
  capmKelly: (data: any) => request('/capm/kelly', { method: 'POST', body: JSON.stringify(data) }),
  capmGbm: (data: any) => request('/capm/gbm', { method: 'POST', body: JSON.stringify(data) }),
  capmGbmMulti: (data: any) => request('/capm/gbm-multi', { method: 'POST', body: JSON.stringify(data) }),
  capmGbmMultiDemo: () => request('/capm/gbm-multi/demo'),

  // Ibovespa Dashboard (18 assets + RL CEM)
  ibovespaAssets: () => request('/ibovespa/assets'),
  ibovespaSimulate: (data: any) => request('/ibovespa/simulate', { method: 'POST', body: JSON.stringify(data) }),
  ibovespaRLOptimize: (data: any) => request('/ibovespa/rl-optimize', { method: 'POST', body: JSON.stringify(data) }),
  ibovespaDemo: () => request('/ibovespa/demo'),

  // AI Analysis Report
  aiAnalysis: (ticker: string) => request('/reports/ai-analysis', { method: 'POST', body: JSON.stringify({ ticker }) }),

  aiAnalysisStream: (
    ticker: string,
    onProgress: (step: number, total: number, message: string) => void,
    onResult: (data: any) => void,
    onError: (msg: string) => void,
  ): (() => void) => {
    const controller = new AbortController();
    fetch('/api/reports/ai-analysis/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...getAuthHeader() },
      body: JSON.stringify({ ticker }),
      signal: controller.signal,
    }).then(async (res) => {
      if (!res.ok) { onError('Erro ao iniciar análise'); return; }
      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split('\n\n');
        buffer = parts.pop() || '';
        for (const part of parts) {
          if (!part.trim()) continue;
          const lines = part.split('\n');
          let event = 'message', data = '';
          for (const line of lines) {
            if (line.startsWith('event: ')) event = line.slice(7);
            if (line.startsWith('data: ')) data = line.slice(6);
          }
          try {
            const parsed = JSON.parse(data);
            if (event === 'progress') onProgress(parsed.step, parsed.total, parsed.message);
            else if (event === 'result') onResult(parsed);
            else if (event === 'error') onError(parsed.message);
          // eslint-disable-next-line no-empty
          } catch {}
        }
      }
    }).catch((err) => { if (err.name !== 'AbortError') onError(String(err)); });
    return () => controller.abort();
  },

  // Binance Crypto
  binancePrice: (symbol: string) => request<any>(`/binance/price/${symbol}`),
  binanceTickers: () => request<any[]>('/binance/tickers'),
  binanceDepth: (symbol: string, limit = 100) => request<any>(`/binance/depth/${symbol}?limit=${limit}`),
  binanceKellySizing: (data: any) => request<any>('/binance/kelly-sizing', { method: 'POST', body: JSON.stringify(data) }),
  binanceFuturesAccount: () => request<any>('/binance/futures/account'),
  binanceFuturesPrice: (symbol: string) => request<any>(`/binance/futures/price/${symbol}`),

  // Report History
  reportHistory: (limit = 20) => request<any[]>(`/reports/history?limit=${limit}`),
  reportHistoryTicker: (ticker: string, limit = 10) => request<any[]>(`/reports/history/${ticker}?limit=${limit}`),
  reportDetail: (id: number) => request<any>(`/reports/history/detail/${id}`),

  // AI Proxy (Perplexity via backend — key never exposed to client)
  aiRefine: (code: string, instruction?: string) =>
    request<{ refined_code: string; model_used: string; tokens_used: number }>(
      '/ai/perplexity/refine',
      { method: 'POST', body: JSON.stringify({ code, instruction }) },
    ),

  // Earnings Directional Prediction (Kim et al., Schadner)
  earningsPrediction: (data: any) => request<{ analysis: string }>('/reports/earnings-prediction', { method: 'POST', body: JSON.stringify(data) }),

  // Fetch financials from ticker (yfinance)
  getTickerFinancials: (ticker: string) => request<{ current: any, previous: any }>(`/reports/ticker-financials/${ticker}`),

  deskHestonPrice: (data: object) => request<any>('/desk/heston/price', { method: 'POST', body: JSON.stringify(data) }),
  deskHestonCalibrate: (data: object) => request<any>('/desk/heston/calibrate', { method: 'POST', body: JSON.stringify(data) }),
  deskEngleGranger: (data: object) => request<any>('/desk/pairs/engle-granger', { method: 'POST', body: JSON.stringify(data) }),
  deskJohansen: (data: object) => request<any>('/desk/pairs/johansen', { method: 'POST', body: JSON.stringify(data) }),
  deskPairsBacktest: (data: object) => request<any>('/desk/pairs/backtest', { method: 'POST', body: JSON.stringify(data) }),
  deskMarketMaking: (data: object) => request<any>('/desk/market-making/quotes', { method: 'POST', body: JSON.stringify(data) }),
  deskFamaFrench: (data: object) => request<any>('/desk/fama-french/decompose', { method: 'POST', body: JSON.stringify(data) }),
  deskMeanReversion: (data: object) => request<any>('/desk/mean-reversion/scan', { method: 'POST', body: JSON.stringify(data) }),
  deskPerpArb: (data: object) => request<any>('/desk/perp-arb/scan', { method: 'POST', body: JSON.stringify(data) }),
  deskPerpLive: (symbol = 'BTCUSDT') => request<any>(`/desk/perp-arb/live?symbol=${encodeURIComponent(symbol)}`),
  deskInsiderClusters: (data: object) => request<any>('/desk/insider-clusters/detect', { method: 'POST', body: JSON.stringify(data) }),
  deskEdgar: (data: object) => request<any>('/desk/insider-clusters/edgar', { method: 'POST', body: JSON.stringify(data) }),
  deskRegime: (data: object) => request<any>('/desk/regime/evaluate', { method: 'POST', body: JSON.stringify(data) }),
  deskRegimeLive: (flatten = false) =>
    request<any>(`/desk/regime/live?flatten=${flatten ? 'true' : 'false'}`, { method: 'POST', body: '{}' }),
  deskWinnersCurseSimulate: (data: object) =>
    request<any>('/desk/winners-curse/simulate', { method: 'POST', body: JSON.stringify(data) }),
  deskWinnersCurseDeflate: (data: object) =>
    request<any>('/desk/winners-curse/deflate', { method: 'POST', body: JSON.stringify(data) }),
  deskForwardTest: (data: object) =>
    request<any>('/desk/forward-test/evaluate', { method: 'POST', body: JSON.stringify(data) }),
  deskTargetChoice: (data: object) =>
    request<any>('/desk/target-choice/evaluate', { method: 'POST', body: JSON.stringify(data) }),
  deskVectorize: (data: object) =>
    request<any>('/desk/vectorize/evaluate', { method: 'POST', body: JSON.stringify(data) }),
  deskDoctrine: () => request<any>('/desk/doctrine'),
};
