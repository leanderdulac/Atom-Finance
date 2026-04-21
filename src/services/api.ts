const API_BASE = '/api';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'API Error');
  }
  return res.json();
}

export const api = {
  // Health
  health: () => request<{ status: string }>('/health'),

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

  // ML
  predict: (data: any) => request('/ml/predict', { method: 'POST', body: JSON.stringify(data) }),

  // Ghost Liquidity
  ghostLiquidity: (data?: any) => request('/ghost-liquidity/analyze', { method: 'POST', body: JSON.stringify(data || {}) }),
  ghostMonitor: (n?: number) => request(`/ghost-liquidity/monitor?n_snapshots=${n || 100}`),
  ghostDemo: () => request('/ghost-liquidity/demo'),

  // Black Swan
  tailRisk: (data: any) => request('/black-swan/tail-risk', { method: 'POST', body: JSON.stringify(data) }),
  regimeChange: (data: any) => request('/black-swan/regime-change', { method: 'POST', body: JSON.stringify(data) }),
  newsSentiment: (data?: any) => request('/black-swan/news-sentiment', { method: 'POST', body: JSON.stringify(data || {}) }),
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
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ticker }),
      signal: controller.signal,
    }).then(async (res) => {
      if (!res.ok) { onError('Erro ao iniciar análise'); return; }
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
};
