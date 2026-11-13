import type { OperationsState, PaperRecord, PaperSummary, SourceCheck, SourceSnapshotSummary } from '../types/paperTrading';
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

// Centralized binary download: same 401-refresh contract as request(), plus a
// content-type guard so an expired session never saves a JSON error as a file.
export async function downloadBlob(path: string, body: unknown, expectedType: string): Promise<Blob> {
  const doFetch = () => fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeader() },
    body: JSON.stringify(body),
  });
  let res = await doFetch();
  if (res.status === 401 && await refreshAccessToken()) {
    res = await doFetch();
  }
  if (!res.ok) {
    const err = await res.json().catch(() => null) as { detail?: string } | null;
    throw new Error(err?.detail || `Download falhou (${res.status})`);
  }
  const ctype = res.headers.get('content-type') || '';
  if (!ctype.includes(expectedType)) {
    throw new Error(`Resposta inesperada do servidor (${ctype || 'sem content-type'})`);
  }
  return res.blob();
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

// ── Request/response contracts ──────────────────────────────────────────────
// These mirror the Pydantic models in backend/app/api/*.py — keep field names
// snake_case and optional exactly where the backend gives them defaults.
export type OptionType = 'call' | 'put';
export interface PricingRequest {
  spot: number; strike: number; maturity: number;
  rate?: number; sigma?: number; option_type?: OptionType; dividend_yield?: number;
}
export interface MonteCarloRequest extends PricingRequest { n_simulations?: number; n_steps?: number }
export interface BinomialRequest extends PricingRequest { american?: boolean; n_steps?: number }
export interface FiniteDiffRequest extends PricingRequest { american?: boolean; n_S?: number; n_t?: number }
export interface IVRequest { market_price: number; spot: number; strike: number; maturity: number; rate?: number; option_type?: OptionType }
export interface SurfaceRequest { spot: number; rate?: number; strikes?: number[]; maturities?: number[]; option_type?: OptionType }
export interface StrategyLeg { strike: number; type: OptionType; position: 'long' | 'short'; quantity?: number }
export interface StrategyRequest { spot: number; sigma?: number; rate?: number; maturity?: number; legs: StrategyLeg[] }
export interface PresetStrategyRequest { spot: number; sigma?: number; rate?: number; maturity?: number }
export interface Greeks { delta: number; gamma: number; theta: number; vega: number; rho: number }
export interface PricingResult { model: string; price: number; greeks: Greeks; inputs: Record<string, unknown> }
export interface EnginePricingResult {
  price?: number; model?: string; comparison?: Record<string, number>;
  greeks?: Record<string, number>; p1?: number; p2?: number;
  std_error?: number; confidence_95?: [number, number];
  arbitrage_violation?: boolean; limitations?: string[];
}

export interface VaRRequest {
  returns: number[]; confidence?: number; portfolio_value?: number; holding_period?: number;
  method?: 'historical' | 'parametric' | 'monte_carlo'; distribution?: 'normal' | 't';
}
export interface StressTestRequest { portfolio: Record<string, number>; scenario?: string | null; portfolio_value?: number }
export interface GARCHRequest { returns: number[]; forecast_horizon?: number }
export interface HestonRequest {
  S0?: number; v0?: number; mu?: number; kappa?: number; theta?: number;
  xi?: number; rho?: number; T?: number; n_paths?: number;
}

export interface PortfolioRequest {
  returns: number[][]; asset_names?: string[] | null; risk_free_rate?: number;
  allow_short?: boolean; shrinkage?: 'none' | 'ledoit_wolf';
}
export interface BlackLittermanRequest extends PortfolioRequest {
  views: Record<string, number>; market_weights?: Record<string, number> | null;
}

export interface TailRiskRequest { returns: number[] }

export interface BacktestRequest {
  prices: number[]; strategy?: 'sma_crossover' | 'mean_reversion' | 'momentum' | 'rsi';
  params?: Record<string, unknown> | null; initial_capital?: number;
  commission?: number; slippage?: number; data_source?: string;
}

export interface NeuralSDERequest {
  y0?: number; t_start?: number; t_end?: number; n_steps?: number; n_paths?: number;
  state_size?: number; hidden_size?: number; method?: 'euler' | 'milstein'; seed?: number | null;
}

export interface BetaRequest { asset_returns: number[]; market_returns: number[]; risk_free_rate?: number; market_premium?: number }
export interface KellyRequest { win_rate: number; payout_ratio: number; fraction?: number }
export interface GBMRequest { S0: number; mu?: number; sigma?: number; T?: number; n_steps?: number; n_paths?: number; seed?: number | null }
export interface GBMAsset { ticker: string; S0: number; mu?: number; sigma?: number }
export interface GBMMultiRequest {
  assets: GBMAsset[]; T?: number; n_steps?: number; n_paths?: number;
  corr_matrix?: number[][] | null; seed?: number | null;
}

export interface IbovespaSimulateRequest { n_paths?: number; T?: number; seed?: number | null }
export interface IbovespaRLRequest {
  profile?: 'conservador' | 'agressivo'; n_paths?: number; T?: number;
  n_iterations?: number; initial_capital?: number; seed?: number | null;
}

export interface KellyCryptoRequest { symbol: string; win_prob: number; payout_ratio: number; bankroll_override?: number | null; fraction?: number }
export interface BinanceTicker { symbol: string; price: string }
export interface BinanceKellySizing {
  kelly_full: number; kelly_frac: number; alocacao_dolares: number;
  current_price: number; symbol: string; asset_units: number;
}
export interface MarketHistory {
  ticker: string; dates: string[]; open: number[]; high: number[]; low: number[];
  close: number[]; volume: number[]; provider: string; source?: string;
}
export interface MarketQuote {
  ticker: string; price: number; change?: number; change_pct?: number;
  volume?: number; high?: number; low?: number; provider: string; source?: string;
}
export interface MarketVolatility {
  symbol: string; iv_call: number; iv_put: number; iv_avg: number;
  volatility_skew: number; timestamp: string;
}
export interface BetaResult {
  beta: number; alpha_daily: number; alpha_annual: number; r_squared: number;
  p_value: number; std_err: number; n_observations: number;
  capm?: {
    expected_return_annual: number; risk_free_rate: number;
    market_premium: number; formula: string;
  };
}
export interface KellyResult {
  kelly_full: number; kelly_fraction: number; edge: number;
  win_rate: number; payout_ratio: number; fraction_used: number;
}
export interface GBMResult {
  S0: number; mu: number; sigma: number; T: number; n_steps: number; n_paths: number;
  time: number[]; paths: number[][]; mean: number[]; p5: number[]; p95: number[];
  terminal: { mean: number; std: number; p5: number; p50: number; p95: number; prob_above_S0: number };
}
export interface VaRMethodResult {
  var_percentage: number; var_absolute: number;
  cvar_percentage: number; cvar_absolute: number;
}
export interface StressScenarioResult {
  scenario: string; portfolio_value: number; total_impact_pct: number;
  total_impact_abs: number; portfolio_after: number;
}
export interface GARCHFitResult {
  omega: number; alpha: number; beta: number; mu: number; persistence: number;
  long_run_variance: number; long_run_volatility: number | null;
  conditional_volatility: number[]; log_likelihood: number; converged: boolean;
}
export interface StrategyAnalysisResult {
  payoff_x?: number[]; payoff_y?: number[]; total_premium?: number;
  max_profit?: number | string; max_loss?: number;
  breakeven_points?: number[]; greeks?: Record<string, number>;
  strategy?: string;
}
export interface PortfolioOptimizeResult {
  expected_return?: number; volatility?: number; sharpe_ratio?: number;
  weights?: Record<string, number>;
  frontier?: { returns: number[]; volatilities: number[] };
  max_sharpe_portfolio?: Record<string, number>;
}
export interface GARCHForecastResult {
  forecast_volatility: number[];
  forecast_interval_95: { lower: number[]; upper: number[]; units: string };
  horizon_days: number;
}
export interface FullTailRiskResult {
  alert_level: string; combined_score: number;
  scores?: { market_score: number; regime_score: number };
  components?: {
    market_tail_risk?: {
      statistics?: Record<string, number>;
      tail_analysis?: Record<string, number>;
      risk_metrics?: Record<string, number>;
    };
  };
}
export interface BinanceDepth { bids: [string, string][]; asks: [string, string][] }

export interface AutopilotRequest { capital: number; horizon_days: number }

export interface FinancialPeriod {
  revenue: number; gross_profit: number; operating_income: number; interest_expense: number;
  net_income: number; cfo: number; cash_equivalents: number; current_assets: number;
  current_liabilities: number; inventory: number; accounts_receivable: number;
  total_assets: number; total_debt: number; total_equity: number;
}
export interface OptionsData { S: number; K: number; T: number; r: number; C: number }
export interface EarningsPredictionRequest { current_period: FinancialPeriod; previous_period: FinancialPeriod; options?: OptionsData | null }

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
  paperOperations: () => request<OperationsState>('/paper-trades/operations'),
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
  screenerTopPicks: <T = unknown[]>() => request<T>('/screener/top-picks'),
  autopilotGenerate: <T = unknown>(data: AutopilotRequest) =>
    request<T>('/autopilot/generate', { method: 'POST', body: JSON.stringify(data) }),
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
  clientConfig: () => request<{
    client_mode: boolean; universe: unknown[]; instruments: unknown[];
    horizons: unknown[]; disclaimer: string; eligible_for_live_trading: boolean;
  }>('/client/config'),
  clientReadyOperation: (data: { ticker: string; instrument: string; horizon: string }) =>
    request<unknown>('/client/ready-operation', { method: 'POST', body: JSON.stringify(data) }),
  clientReadyPaper: (data: { ticker: string; instrument: string; horizon: string }) =>
    request<unknown>('/client/ready-operation/paper', { method: 'POST', body: JSON.stringify(data) }),

  // Pricing
  blackScholes: (data: PricingRequest) => request<EnginePricingResult & { greeks: Record<string, number> }>('/pricing/black-scholes', { method: 'POST', body: JSON.stringify(data) }),
  monteCarlo: (data: MonteCarloRequest) => request<EnginePricingResult>('/pricing/monte-carlo', { method: 'POST', body: JSON.stringify(data) }),
  binomial: (data: BinomialRequest) => request<EnginePricingResult>('/pricing/binomial', { method: 'POST', body: JSON.stringify(data) }),
  finiteDifference: (data: FiniteDiffRequest) => request<EnginePricingResult>('/pricing/finite-difference', { method: 'POST', body: JSON.stringify(data) }),
  impliedVolatility: (data: IVRequest) => request<unknown>('/pricing/implied-volatility', { method: 'POST', body: JSON.stringify(data) }),
  volSurface: (data: SurfaceRequest) => request<unknown>('/pricing/volatility-surface', { method: 'POST', body: JSON.stringify(data) }),
  compareModels: (data: PricingRequest) => request<EnginePricingResult>('/pricing/compare', { method: 'POST', body: JSON.stringify(data) }),
  strategy: (data: StrategyRequest) => request<StrategyAnalysisResult>('/pricing/strategy', { method: 'POST', body: JSON.stringify(data) }),
  straddle: (data: PresetStrategyRequest & { strike: number }) => {
    const { strike, ...body } = data;
    return request<StrategyAnalysisResult>(`/pricing/strategy/straddle?strike=${strike}`, { method: 'POST', body: JSON.stringify(body) });
  },
  ironCondor: (data: PresetStrategyRequest & { k1: number; k2: number; k3: number; k4: number }) => {
    const { k1, k2, k3, k4, ...body } = data;
    return request<StrategyAnalysisResult>(`/pricing/strategy/iron-condor?k1=${k1}&k2=${k2}&k3=${k3}&k4=${k4}`, { method: 'POST', body: JSON.stringify(body) });
  },
  butterfly: (data: PresetStrategyRequest & { k1: number; k2: number; k3: number }) => {
    const { k1, k2, k3, ...body } = data;
    return request<StrategyAnalysisResult>(`/pricing/strategy/butterfly?k1=${k1}&k2=${k2}&k3=${k3}`, { method: 'POST', body: JSON.stringify(body) });
  },

  // Risk
  var: (data: VaRRequest) => request<unknown>('/risk/var', { method: 'POST', body: JSON.stringify(data) }),
  varAll: <T = unknown>(data: VaRRequest) => request<T>('/risk/var/all-methods', { method: 'POST', body: JSON.stringify(data) }),
  stressTest: (data: StressTestRequest) => request<{ scenarios: Record<string, StressScenarioResult> }>('/risk/stress-test', { method: 'POST', body: JSON.stringify(data) }),
  garch: (data: GARCHRequest) => request<{ fit: GARCHFitResult; forecast: GARCHForecastResult }>('/risk/garch', { method: 'POST', body: JSON.stringify(data) }),
  heston: (data: HestonRequest) => request<unknown>('/risk/heston', { method: 'POST', body: JSON.stringify(data) }),

  // Portfolio
  efficientFrontier: (data: PortfolioRequest) => request<PortfolioOptimizeResult>('/portfolio/efficient-frontier', { method: 'POST', body: JSON.stringify(data) }),
  maxSharpe: (data: PortfolioRequest) => request<PortfolioOptimizeResult>('/portfolio/max-sharpe', { method: 'POST', body: JSON.stringify(data) }),
  riskParity: (data: PortfolioRequest) => request<PortfolioOptimizeResult>('/portfolio/risk-parity', { method: 'POST', body: JSON.stringify(data) }),
  blackLitterman: (data: BlackLittermanRequest) => request<unknown>('/portfolio/black-litterman', { method: 'POST', body: JSON.stringify(data) }),

  // Tail risk
  tailRisk: (data: TailRiskRequest) => request<unknown>('/black-swan/tail-risk', { method: 'POST', body: JSON.stringify(data) }),
  regimeChange: (data: TailRiskRequest) => request<unknown>('/black-swan/regime-change', { method: 'POST', body: JSON.stringify(data) }),
  blackSwanFull: (data: TailRiskRequest) => request<FullTailRiskResult>('/black-swan/full-analysis', { method: 'POST', body: JSON.stringify(data) }),
  blackSwanDemo: () => request('/black-swan/demo'),

  // Market Data
  marketProviders: () => request('/market-data/providers'),
  quote: (ticker: string, provider = 'auto') => request<MarketQuote>(`/market-data/quote/${encodeURIComponent(ticker)}?provider=${encodeURIComponent(provider)}`),
  history: (ticker: string, days?: number, provider = 'auto') => request<MarketHistory>(`/market-data/history/${encodeURIComponent(ticker)}?days=${days || 252}&provider=${encodeURIComponent(provider)}`),
  profile: (ticker: string) => request(`/market-data/profile/${encodeURIComponent(ticker)}`),
  search: (query: string) => request(`/market-data/search?query=${encodeURIComponent(query)}`),
  optionsChain: (ticker: string, provider = 'auto') => request(`/market-data/options-chain/${encodeURIComponent(ticker)}?provider=${encodeURIComponent(provider)}`),
  volatility: (ticker: string) => request<MarketVolatility>(`/market-data/volatility/${encodeURIComponent(ticker)}`),
  returns: (ticker: string, period = '1y') => request(`/market-data/returns/${encodeURIComponent(ticker)}?period=${encodeURIComponent(period)}`),

  // Backtesting
  backtest: <T = unknown>(data: BacktestRequest) => request<T>('/backtesting/run', { method: 'POST', body: JSON.stringify(data) }),

  // Neural SDE
  neuralSdeStatus: () => request('/neural-sde/status'),
  neuralSdeDemo: <T = unknown>() => request<T>('/neural-sde/demo'),
  neuralSdeSimulate: <T = unknown>(data: NeuralSDERequest) => request<T>('/neural-sde/simulate', { method: 'POST', body: JSON.stringify(data) }),

  // CAPM & Kelly
  capmDemo: () => request('/capm/demo'),
  capmBeta: (data: BetaRequest) => request<BetaResult>('/capm/beta', { method: 'POST', body: JSON.stringify(data) }),
  capmKelly: (data: KellyRequest) => request<KellyResult>('/capm/kelly', { method: 'POST', body: JSON.stringify(data) }),
  capmGbm: (data: GBMRequest) => request<GBMResult>('/capm/gbm', { method: 'POST', body: JSON.stringify(data) }),
  capmGbmMulti: (data: GBMMultiRequest) => request<unknown>('/capm/gbm-multi', { method: 'POST', body: JSON.stringify(data) }),
  capmGbmMultiDemo: () => request('/capm/gbm-multi/demo'),

  // Ibovespa Dashboard (18 assets + RL CEM)
  ibovespaAssets: () => request('/ibovespa/assets'),
  ibovespaSimulate: (data: IbovespaSimulateRequest) => request<unknown>('/ibovespa/simulate', { method: 'POST', body: JSON.stringify(data) }),
  ibovespaRLOptimize: (data: IbovespaRLRequest) => request<unknown>('/ibovespa/rl-optimize', { method: 'POST', body: JSON.stringify(data) }),
  ibovespaDemo: () => request('/ibovespa/demo'),

  // AI Analysis Report
  aiAnalysis: (ticker: string) => request('/reports/ai-analysis', { method: 'POST', body: JSON.stringify({ ticker }) }),

  aiAnalysisStream: (
    ticker: string,
    onProgress: (step: number, total: number, message: string) => void,
    onResult: (data: Record<string, unknown>) => void,
    onError: (msg: string) => void,
  ): (() => void) => {
    const controller = new AbortController();
    const doStream = () => fetch('/api/reports/ai-analysis/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...getAuthHeader() },
      body: JSON.stringify({ ticker }),
      signal: controller.signal,
    });
    doStream().then(async (res) => {
      if (res.status === 401 && await refreshAccessToken()) {
        res = await doStream();
      }
      if (!res.ok) {
        const err = await res.json().catch(() => null) as { detail?: string } | null;
        onError(err?.detail || `Erro ao iniciar análise (${res.status})`);
        return;
      }
      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
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
  binancePrice: (symbol: string) => request<BinanceTicker>(`/binance/price/${encodeURIComponent(symbol)}`),
  binanceTickers: () => request<BinanceTicker[]>('/binance/tickers'),
  binanceDepth: (symbol: string, limit = 100) => request<BinanceDepth>(`/binance/depth/${encodeURIComponent(symbol)}?limit=${limit}`),
  binanceKellySizing: (data: KellyCryptoRequest) => request<BinanceKellySizing>('/binance/kelly-sizing', { method: 'POST', body: JSON.stringify(data) }),
  binanceFuturesAccount: () => request<unknown>('/binance/futures/account'),
  binanceFuturesPrice: (symbol: string) => request<BinanceTicker>(`/binance/futures/price/${encodeURIComponent(symbol)}`),

  // Report History
  reportHistory: (limit = 20) => request<unknown[]>(`/reports/history?limit=${limit}`),
  reportHistoryTicker: (ticker: string, limit = 10) => request<unknown[]>(`/reports/history/${encodeURIComponent(ticker)}?limit=${limit}`),
  reportDetail: (id: number) => request<unknown>(`/reports/history/detail/${id}`),

  // AI Proxy (Perplexity via backend — key never exposed to client)
  aiRefine: (code: string, instruction?: string) =>
    request<{ refined_code: string; model_used: string; tokens_used: number }>(
      '/ai/perplexity/refine',
      { method: 'POST', body: JSON.stringify({ code, instruction }) },
    ),

  // Earnings Directional Prediction (Kim et al., Schadner)
  earningsPrediction: (data: EarningsPredictionRequest) => request<{ analysis: string }>('/reports/earnings-prediction', { method: 'POST', body: JSON.stringify(data) }),

  // Fetch financials from ticker (yfinance)
  getTickerFinancials: (ticker: string) => request<{ current: FinancialPeriod | null, previous: FinancialPeriod | null }>(`/reports/ticker-financials/${encodeURIComponent(ticker)}`),

  deskHestonPrice: <T = unknown>(data: object) => request<T>('/desk/heston/price', { method: 'POST', body: JSON.stringify(data) }),
  deskHestonCalibrate: <T = unknown>(data: object) => request<T>('/desk/heston/calibrate', { method: 'POST', body: JSON.stringify(data) }),
  deskEngleGranger: <T = unknown>(data: object) => request<T>('/desk/pairs/engle-granger', { method: 'POST', body: JSON.stringify(data) }),
  deskJohansen: <T = unknown>(data: object) => request<T>('/desk/pairs/johansen', { method: 'POST', body: JSON.stringify(data) }),
  deskPairsBacktest: <T = unknown>(data: object) => request<T>('/desk/pairs/backtest', { method: 'POST', body: JSON.stringify(data) }),
  deskMarketMaking: <T = unknown>(data: object) => request<T>('/desk/market-making/quotes', { method: 'POST', body: JSON.stringify(data) }),
  deskFamaFrench: <T = unknown>(data: object) => request<T>('/desk/fama-french/decompose', { method: 'POST', body: JSON.stringify(data) }),
  deskMeanReversion: <T = unknown>(data: object) => request<T>('/desk/mean-reversion/scan', { method: 'POST', body: JSON.stringify(data) }),
  deskPerpArb: <T = unknown>(data: object) => request<T>('/desk/perp-arb/scan', { method: 'POST', body: JSON.stringify(data) }),
  deskPerpLive: <T = unknown>(symbol = 'BTCUSDT') => request<T>(`/desk/perp-arb/live?symbol=${encodeURIComponent(symbol)}`),
  deskInsiderClusters: <T = unknown>(data: object) => request<T>('/desk/insider-clusters/detect', { method: 'POST', body: JSON.stringify(data) }),
  deskEdgar: <T = unknown>(data: object) => request<T>('/desk/insider-clusters/edgar', { method: 'POST', body: JSON.stringify(data) }),
  deskRegime: <T = unknown>(data: object) => request<T>('/desk/regime/evaluate', { method: 'POST', body: JSON.stringify(data) }),
  deskRegimeLive: <T = unknown>(flatten = false) =>
    request<T>(`/desk/regime/live?flatten=${flatten ? 'true' : 'false'}`, { method: 'POST', body: '{}' }),
  deskWinnersCurseSimulate: <T = unknown>(data: object) =>
    request<T>('/desk/winners-curse/simulate', { method: 'POST', body: JSON.stringify(data) }),
  deskWinnersCurseDeflate: <T = unknown>(data: object) =>
    request<T>('/desk/winners-curse/deflate', { method: 'POST', body: JSON.stringify(data) }),
  deskForwardTest: <T = unknown>(data: object) =>
    request<T>('/desk/forward-test/evaluate', { method: 'POST', body: JSON.stringify(data) }),
  deskTargetChoice: <T = unknown>(data: object) =>
    request<T>('/desk/target-choice/evaluate', { method: 'POST', body: JSON.stringify(data) }),
  deskErrorMaximizer: <T = unknown>(data: object) =>
    request<T>('/desk/error-maximizer/evaluate', { method: 'POST', body: JSON.stringify(data) }),
  deskDoctrine: <T = unknown>() => request<T>('/desk/doctrine'),
};
