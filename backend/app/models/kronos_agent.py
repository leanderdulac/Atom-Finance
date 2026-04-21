import logging
from typing import Optional, Dict

import pandas as pd
from datetime import timedelta

from app.services.data_fetcher import DataFetcher

logger = logging.getLogger(__name__)

class KronosAgent:
    _instance = None
    _predictor = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(KronosAgent, cls).__new__(cls)
        return cls._instance

    @classmethod
    def get_predictor(cls):
        if cls._predictor is None:
            logger.info("Initializing Kronos models from HuggingFace...")
            try:
                from app.models.kronos import Kronos, KronosTokenizer, KronosPredictor
                tokenizer = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
                model = Kronos.from_pretrained("NeoQuasar/Kronos-mini")
                cls._predictor = KronosPredictor(model, tokenizer, max_context=512)
                logger.info("Kronos models loaded successfully.")
            except Exception as e:
                logger.error(f"Error loading Kronos models: {e}")
                return None
        return cls._predictor

    @classmethod
    def predict(cls, symbol: str, pred_len: int = 30) -> Optional[Dict]:
        """
        Uses Kronos to predict the next `pred_len` days of price action for `symbol`.
        Retrieves the last year of data to feed up to 512 context tokens.
        """
        predictor = cls.get_predictor()
        if not predictor:
            return None

        # 1. Fetch historical data
        hist_df = DataFetcher.get_historical_data(symbol, period="1y", interval="1d")
        if hist_df is None or hist_df.empty:
            logger.warning(f"No historical data found for {symbol}")
            return None

        hist_df.reset_index(inplace=True)
        # Handle timezone timezone-aware datetimes
        if hist_df['Date'].dt.tz is not None:
             hist_df['Date'] = hist_df['Date'].dt.tz_localize(None)

        # 2. Map columns to what Kronos expects
        # Kronos expects lowercase cols: 'open', 'high', 'low', 'close', 'volume'
        # 'amount' is optional
        x_df = pd.DataFrame()
        x_df['timestamps'] = hist_df['Date']
        x_df['open'] = hist_df['Open']
        x_df['high'] = hist_df['High']
        x_df['low'] = hist_df['Low']
        x_df['close'] = hist_df['Close']
        x_df['volume'] = hist_df['Volume']

        # 3. Trim to max context (512)
        lookback = len(x_df)
        if lookback > 512:
            x_df = x_df.tail(512).reset_index(drop=True)
            lookback = 512

        x_timestamp = x_df['timestamps']
        
        # 4. Generate future timestamps for prediction (assuming business days roughly)
        last_date = x_timestamp.iloc[-1]
        future_dates = pd.date_range(start=last_date + timedelta(days=1), periods=pred_len, freq='B')
        y_timestamp = pd.Series(future_dates)

        # 5. Predict
        try:
            pred_df = predictor.predict(
                df=x_df[['open', 'high', 'low', 'close', 'volume']],
                x_timestamp=x_timestamp,
                y_timestamp=y_timestamp,
                pred_len=pred_len,
                T=1.0,
                top_p=0.9,
                sample_count=1
            )
            
            # 6. Analyze prediction
            start_price = x_df['close'].iloc[-1]
            end_price = pred_df['close'].iloc[-1]
            predicted_return_pct = ((end_price / start_price) - 1.0) * 100

            trend = "BULLISH" if predicted_return_pct > 0 else "BEARISH"

            return {
                "symbol": symbol,
                "current_price": float(start_price),
                "predicted_price": float(end_price),
                "predicted_return_pct": float(predicted_return_pct),
                "trend": trend,
                "prediction_df": pred_df,
                "lookback_days": lookback,
                "pred_len_days": pred_len
            }

        except Exception as e:
            logger.error(f"Error during Kronos prediction for {symbol}: {e}")
            return None
