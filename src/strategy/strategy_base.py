"""
Trading Strategy Base Module
Designed for easy extension with custom strategies
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any,Tuple
import pandas as pd
import numpy as np


class TradingStrategy(ABC):
    """
    Abstract base class for trading strategies
    Implement this class to create custom strategies
    """
    
    def __init__(self, name: str = "BaseStrategy", params: Dict[str, Any] = None):
        self.name = name
        self.required_columns = ['open', 'high', 'low', 'close', 'volume']
        self.signals = {}
        self.params = params or {}
        
    def validate_data(self, data: pd.DataFrame) -> bool:
        """Validate if data has required columns"""
        missing_cols = [col for col in self.required_columns if col not in data.columns]
        if missing_cols:
            raise ValueError(f"Missing required columns: {missing_cols}")
        return True
    
    def calculate_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate technical indicators
        Override this method to add custom indicators
        """
        return data.copy()

    def calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """Calculate Relative Strength Index"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def calculate_sma(self, prices: pd.Series, period: int) -> pd.Series:
        """Calculate Simple Moving Average"""
        return prices.rolling(window=period).mean()

    def calculate_ema(self, prices: pd.Series, period: int) -> pd.Series:
        """Calculate Exponential Moving Average"""
        return prices.ewm(span=period, adjust=False).mean()

    def calculate_macd(self, prices: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple:
        """Calculate MACD indicator"""
        ema_fast = prices.ewm(span=fast, adjust=False).mean()
        ema_slow = prices.ewm(span=slow, adjust=False).mean()
        macd = ema_fast - ema_slow
        signal_line = macd.ewm(span=signal, adjust=False).mean()
        histogram = macd - signal_line
        return macd, signal_line, histogram

    def calculate_bollinger_bands(self, prices: pd.Series, period: int = 20, std_dev: int = 2) -> tuple:
        """Calculate Bollinger Bands"""
        sma = prices.rolling(window=period).mean()
        std = prices.rolling(window=period).std()
        upper_band = sma + (std * std_dev)
        lower_band = sma - (std * std_dev)
        return upper_band, sma, lower_band
    
    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Generate trading signals
        This method must be implemented by subclasses
        Returns DataFrame with signals
        """
        pass
    
    def get_signal_strength(self, data: pd.DataFrame) -> float:
        """
        Calculate signal strength (0-1)
        Override for custom signal strength calculation
        """
        return 1.0
    
    def get_parameters(self) -> Dict[str, Any]:
        """Get strategy parameters"""
        return {
            'name': self.name,
            'required_columns': self.required_columns,
            'parameters': self.params.copy()
        }

    def update_parameters(self, new_params: Dict[str, Any]):
        """Update strategy parameters"""
        self.params.update(new_params)



# #####################################################ALL strategy ###############################################
# class RSIStrategy(TradingStrategy):
#     """
#     RSI Strategy using oversold/overbought levels
#     """
    
#     def __init__(self, params: Dict[str, Any] = None):
#         default_params = {
#             'rsi_period': 14,
#             'oversold': 30,
#             'overbought': 70,
#             'use_volume': False
#         }
        
#         # Merge user params with defaults
#         if params:
#             default_params.update(params)
            
#         super().__init__(name="RSI_Strategy", params=default_params)
        
#     def calculate_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
#         """Calculate RSI indicator and additional technical indicators"""
#         df = data.copy()
        
#         # Calculate RSI
#         df['rsi'] = self.calculate_rsi(df['close'], self.params['rsi_period'])
        
#         # Optional volume-based indicator
#         if self.params.get('use_volume', False):
#             df['volume_sma'] = self.calculate_sma(df['volume'], 20)
            
#         return df
    
#     def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
#         """
#         Generate signals based on RSI levels
#         Returns: DataFrame with 'signal' column (-1, 0, 1)
#         """
#         self.validate_data(data)
#         df = self.calculate_indicators(data)
        
#         # Initialize signals
#         df['signal'] = 0
        
#         # Get parameters
#         oversold = self.params['oversold']
#         overbought = self.params['overbought']
        
#         # Generate signals
#         buy_signals = (df['rsi'] > oversold) & (df['rsi'].shift(1) <= oversold)
#         sell_signals = (df['rsi'] < overbought) & (df['rsi'].shift(1) >= overbought)
        
#         df.loc[buy_signals, 'signal'] = 1   # Buy signal
#         df.loc[sell_signals, 'signal'] = -1 # Sell signal
        
#         return df


# class MovingAverageCrossoverStrategy(TradingStrategy):
#     """
#     Moving Average Crossover Strategy
#     """
    
#     def __init__(self, params: Dict[str, Any] = None):
#         default_params = {
#             'fast_period': 20,
#             'slow_period': 50,
#             'use_volume_confirmation': False,
#             'volume_threshold': 1.2
#         }
        
#         if params:
#             default_params.update(params)
            
#         super().__init__(name="MA_Crossover_Strategy", params=default_params)
        
#     def calculate_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
#         """Calculate moving averages and additional indicators"""
#         df = data.copy()
        
#         # Calculate moving averages
#         df['sma_fast'] = self.calculate_sma(df['close'], self.params['fast_period'])
#         df['sma_slow'] = self.calculate_sma(df['close'], self.params['slow_period'])
        
#         # Volume confirmation if enabled
#         if self.params['use_volume_confirmation']:
#             df['volume_sma'] = self.calculate_sma(df['volume'], 20)
#             df['volume_ratio'] = df['volume'] / df['volume_sma']
            
#         return df
    
#     def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
#         """
#         Generate signals based on MA crossover
#         Returns: DataFrame with 'signal' column (-1, 0, 1)
#         """
#         self.validate_data(data)
#         df = self.calculate_indicators(data)
        
#         # Initialize signals
#         df['signal'] = 0
        
#         # Generate crossover signals
#         buy_signals = (df['sma_fast'] > df['sma_slow']) & (df['sma_fast'].shift(1) <= df['sma_slow'].shift(1))
#         sell_signals = (df['sma_fast'] < df['sma_slow']) & (df['sma_fast'].shift(1) >= df['sma_slow'].shift(1))
        
#         # Apply volume confirmation if enabled
#         if self.params['use_volume_confirmation']:
#             volume_condition = df['volume_ratio'] > self.params['volume_threshold']
#             buy_signals = buy_signals & volume_condition
#             sell_signals = sell_signals & volume_condition
        
#         df.loc[buy_signals, 'signal'] = 1   # Buy signal
#         df.loc[sell_signals, 'signal'] = -1 # Sell signal
        
#         return df


# class MACDStrategy(TradingStrategy):
#     """
#     MACD Crossover Strategy
#     """
    
#     def __init__(self, params: Dict[str, Any] = None):
#         default_params = {
#             'macd_fast': 12,
#             'macd_slow': 26,
#             'macd_signal': 9,
#             'use_histogram': True
#         }
        
#         if params:
#             default_params.update(params)
            
#         super().__init__(name="MACD_Strategy", params=default_params)
        
#     def calculate_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
#         """Calculate MACD indicator"""
#         df = data.copy()
        
#         macd, signal, histogram = self.calculate_macd(
#             df['close'], 
#             self.params['macd_fast'], 
#             self.params['macd_slow'], 
#             self.params['macd_signal']
#         )
        
#         df['macd'] = macd
#         df['macd_signal'] = signal
#         df['macd_histogram'] = histogram
        
#         return df
    
#     def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
#         """
#         Generate signals based on MACD crossover
#         Returns: DataFrame with 'signal' column (-1, 0, 1)
#         """
#         self.validate_data(data)
#         df = self.calculate_indicators(data)
        
#         # Initialize signals
#         df['signal'] = 0
        
#         if self.params['use_histogram']:
#             # Use histogram for signals (more sensitive)
#             buy_signals = (df['macd_histogram'] > 0) & (df['macd_histogram'].shift(1) <= 0)
#             sell_signals = (df['macd_histogram'] < 0) & (df['macd_histogram'].shift(1) >= 0)
#         else:
#             # Use MACD line crossover
#             buy_signals = (df['macd'] > df['macd_signal']) & (df['macd'].shift(1) <= df['macd_signal'].shift(1))
#             sell_signals = (df['macd'] < df['macd_signal']) & (df['macd'].shift(1) >= df['macd_signal'].shift(1))
        
#         df.loc[buy_signals, 'signal'] = 1   # Buy signal
#         df.loc[sell_signals, 'signal'] = -1 # Sell signal
        
#         return df

# ############################################


# class VolumePriceStrategy(TradingStrategy):
#     """
#     Volume-Price Strategy using statistical volume analysis and candle patterns
#     """

#     def __init__(self, params: Dict[str, Any] = None):
#         default_params = {
#             'volume_lookback_period': 20,
#             'volume_std_threshold': 2.0,  # Number of standard deviations for "high volume"
#             'mother_candle_ratio': 2.0,   # Minimum body to wick ratio for mother candle
#             'min_body_size': 0.001,       # Minimum candle body size (0.1% of price)
#         }

#         # Merge user params with defaults
#         if params:
#             default_params.update(params)

#         super().__init__(name="Volume_Price_Strategy", params=default_params)

#     def calculate_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
#         """Calculate volume statistics and candle patterns"""
#         df = data.copy()

#         # Calculate volume moving average and standard deviation
#         df['volume_sma'] = self.calculate_sma(df['volume'], self.params['volume_lookback_period'])
#         df['volume_std'] = df['volume'].rolling(window=self.params['volume_lookback_period']).std()
        
#         # Calculate if volume is statistically high
#         df['volume_zscore'] = (df['volume'] - df['volume_sma']) / df['volume_std']
#         df['high_volume'] = df['volume_zscore'] > self.params['volume_std_threshold']

#         # Calculate candle characteristics
#         df['candle_body'] = abs(df['close'] - df['open'])
#         df['candle_upper_wick'] = df['high'] - df[['open', 'close']].max(axis=1)
#         df['candle_lower_wick'] = df[['open', 'close']].min(axis=1) - df['low']
#         df['total_wick'] = df['candle_upper_wick'] + df['candle_lower_wick']
        
#         # Determine if candle is bullish or bearish
#         df['is_bullish'] = df['close'] > df['open']
#         df['is_bearish'] = df['close'] < df['open']
        
#         # Identify mother candles (large body relative to wicks)
#         df['body_wick_ratio'] = df['candle_body'] / (df['total_wick'] + 1e-9)  # Avoid division by zero
#         df['is_mother_candle'] = (
#             (df['body_wick_ratio'] > self.params['mother_candle_ratio']) & 
#             (df['candle_body'] > (df['close'] * self.params['min_body_size']))
#         )

#         return df

#     def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
#         """
#         Generate signals based on volume statistics and candle patterns
#         Returns: DataFrame with 'signal' column (-1, 0, 1)
#         """
#         self.validate_data(data)
#         df = self.calculate_indicators(data)

#         # Initialize signals
#         df['signal'] = 0

#         # Generate buy signals: High volume + Bullish candle + Mother candle confirmation
#         buy_signals = (
#             df['high_volume'] & 
#             df['is_bullish'] & 
#             df['is_mother_candle']
#         )

#         # Generate sell signals: High volume + Bearish candle + Mother candle confirmation
#         sell_signals = (
#             df['high_volume'] & 
#             df['is_bearish'] & 
#             df['is_mother_candle']
#         )

#         df.loc[buy_signals, 'signal'] = 1   # Buy signal
#         df.loc[sell_signals, 'signal'] = -1 # Sell signal

#         # Optional: Add filters to avoid whipsaws
#         df = self._apply_signal_filters(df)

#         return df

#     def _apply_signal_filters(self, df: pd.DataFrame) -> pd.DataFrame:
#         """Apply additional filters to improve signal quality"""
        
#         # Filter 1: Don't generate opposite signals immediately after a signal
#         for i in range(1, len(df)):
#             if df['signal'].iloc[i-1] != 0:
#                 df.loc[i, 'signal'] = 0

        
#         # Filter 2: Require minimum price movement for mother candle
#         min_price_move = df['close'] * 0.005  # 0.5% minimum move
#         df.loc[df['candle_body'] < min_price_move, 'signal'] = 0
        
#         return df

#     def calculate_sma(self, series: pd.Series, period: int) -> pd.Series:
#         """Calculate Simple Moving Average"""
#         return series.rolling(window=period).mean()

#     def validate_data(self, data: pd.DataFrame):
#         """Validate that required columns are present"""
#         required_columns = ['open', 'high', 'low', 'close', 'volume']
#         for col in required_columns:
#             if col not in data.columns:
#                 raise ValueError(f"Missing required column: {col}")



# class VolumePriceStrategy1(TradingStrategy):
#     """
#     Volume-Price Strategy using statistical volume analysis and candle patterns
#     with consolidation confirmation
#     """

#     def __init__(self, params: Dict[str, Any] = None):
#         default_params = {
#             'volume_lookback_period': 20,
#             'volume_std_threshold': 2.0,  # Number of standard deviations for "high volume"
#             'mother_candle_ratio': 2.0,   # Minimum body to wick ratio for mother candle
#             'min_body_size': 0.001,       # Minimum candle body size (0.1% of price)
#             'consolidation_lookback': 5,  # Look back 5 candles for signals
#             'consolidation_period': 3,    # Number of candles to check for consolidation
#             'consolidation_threshold': 0.03,  # 0.2% max price movement for consolidation
#         }

#         # Merge user params with defaults
#         if params:
#             default_params.update(params)

#         super().__init__(name="Volume_Price_Strategy", params=default_params)

#     def calculate_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
#         """Calculate volume statistics and candle patterns"""
#         df = data.copy()

#         # Calculate volume moving average and standard deviation
#         df['volume_sma'] = self.calculate_sma(df['volume'], self.params['volume_lookback_period'])
#         df['volume_std'] = df['volume'].rolling(window=self.params['volume_lookback_period']).std()

#         # Calculate if volume is statistically high
#         df['volume_zscore'] = (df['volume'] - df['volume_sma']) / df['volume_std']
#         df['high_volume'] = df['volume_zscore'] > self.params['volume_std_threshold']

#         # Calculate candle characteristics
#         df['candle_body'] = abs(df['close'] - df['open'])
#         df['candle_upper_wick'] = df['high'] - df[['open', 'close']].max(axis=1)
#         df['candle_lower_wick'] = df[['open', 'close']].min(axis=1) - df['low']
#         df['total_wick'] = df['candle_upper_wick'] + df['candle_lower_wick']

#         # Determine if candle is bullish or bearish
#         df['is_bullish'] = df['close'] > df['open']
#         df['is_bearish'] = df['close'] < df['open']

#         # Identify mother candles (large body relative to wicks)
#         df['body_wick_ratio'] = df['candle_body'] / (df['total_wick'] + 1e-9)  # Avoid division by zero
#         df['is_mother_candle'] = (
#             (df['body_wick_ratio'] > self.params['mother_candle_ratio']) &
#             (df['candle_body'] > (df['close'] * self.params['min_body_size']))
#         )

#         # Calculate price range for consolidation detection
#         df['price_range'] = (df['high'] - df['low']) / df['close']
        
#         return df

#     def is_consolidating(self, df: pd.DataFrame, current_index: int, signal_type: int) -> bool:
#         """
#         Check if candles after signal are consolidating
#         signal_type: 1 for buy, -1 for sell
#         """
#         if current_index >= len(df) - self.params['consolidation_period']:
#             return False
        
#         # Get the consolidation period candles
#         consolidation_candles = df.iloc[current_index:current_index + self.params['consolidation_period']]
        
#         # Check if all candles in consolidation period have small price range
#         is_small_range = all(
#             consolidation_candles['price_range'] <= self.params['consolidation_threshold']
#         )
        
#         # For buy signals, check if consolidation is above a support level
#         if signal_type == 1 and is_small_range:
#             signal_price = df.iloc[current_index]['close']
#             consolidation_lows = consolidation_candles['low'].min()
#             # Consolidation should not break below the signal candle
#             return consolidation_lows >= signal_price * 0.995  # Allow 0.5% slippage
        
#         # For sell signals, check if consolidation is below a resistance level
#         elif signal_type == -1 and is_small_range:
#             signal_price = df.iloc[current_index]['close']
#             consolidation_highs = consolidation_candles['high'].max()
#             # Consolidation should not break above the signal candle
#             return consolidation_highs <= signal_price * 1.005  # Allow 0.5% slippage
        
#         return False

#     def find_recent_signals(self, df: pd.DataFrame, current_index: int) -> List[Tuple[int, int]]:
#         """
#         Find signals within the last N candles
#         Returns list of (index, signal_type) tuples
#         """
#         recent_signals = []
#         lookback_start = max(0, current_index - self.params['consolidation_lookback'])
        
#         for i in range(lookback_start, current_index):
#             if df['signal'].iloc[i] != 0:
#                 recent_signals.append((i, df['signal'].iloc[i]))
        
#         return recent_signals

#     def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
#         """
#         Generate signals based on volume statistics and candle patterns
#         with consolidation confirmation
#         """
#         self.validate_data(data)
#         df = self.calculate_indicators(data)

#         # Initialize signals
#         df['signal'] = 0
#         df['raw_signal'] = 0  # Store raw signals before consolidation check

#         # Step 1: Generate raw signals
#         buy_signals = (
#             df['high_volume'] &
#             df['is_bullish'] &
#             df['is_mother_candle']
#         )

#         sell_signals = (
#             df['high_volume'] &
#             df['is_bearish'] &
#             df['is_mother_candle']
#         )

#         df.loc[buy_signals, 'raw_signal'] = 1   # Raw buy signal
#         df.loc[sell_signals, 'raw_signal'] = -1 # Raw sell signal

#         # Apply basic filters to raw signals
#         df = self._apply_signal_filters(df, signal_col='raw_signal')

#         # Step 2: Check for consolidation after recent signals
#         df['confirmed_signal'] = 0

#         for i in range(len(df)):
#             # Look for recent raw signals in the last N candles
#             recent_signals = self.find_recent_signals(df, i)
            
#             for signal_idx, signal_type in recent_signals:
#                 # Check if candles after the signal show consolidation
#                 if self.is_consolidating(df, signal_idx, signal_type):
#                     # Confirm the signal at current position
#                     df.loc[i, 'confirmed_signal'] = signal_type
#                     break  # Use the most recent confirmed signal

#         # Use confirmed signals as final signals
#         df['signal'] = df['confirmed_signal']

#         # Additional filter: Don't generate new signals while waiting for consolidation
#         df = self._prevent_signal_overlap(df)

#         return df

#     def _apply_signal_filters(self, df: pd.DataFrame, signal_col: str = 'signal') -> pd.DataFrame:
#         """Apply additional filters to improve signal quality"""
        
#         # Filter 1: Don't generate opposite signals immediately after a signal
#         for i in range(1, len(df)):
#             if df[signal_col].iloc[i-1] != 0:
#                 df.loc[df.index[i], signal_col] = 0

#         # Filter 2: Require minimum price movement for mother candle
#         min_price_move = df['close'] * 0.005  # 0.5% minimum move
#         df.loc[df['candle_body'] < min_price_move, signal_col] = 0

#         return df

#     def _prevent_signal_overlap(self, df: pd.DataFrame) -> pd.DataFrame:
#         """Prevent multiple signals from overlapping"""
#         for i in range(1, len(df)):
#             if df['signal'].iloc[i-1] != 0:
#                 # If previous candle had a signal, don't generate new one
#                 df.loc[df.index[i], 'signal'] = 0
                
#         return df

#     def calculate_sma(self, series: pd.Series, period: int) -> pd.Series:
#         """Calculate Simple Moving Average"""
#         return series.rolling(window=period).mean()

#     def validate_data(self, data: pd.DataFrame):
#         """Validate that required columns are present"""
#         required_columns = ['open', 'high', 'low', 'close', 'volume']
#         for col in required_columns:
#             if col not in data.columns:
#                 raise ValueError(f"Missing required column: {col}")






if __name__ == "__main__":
    # ------------------------------------------------------------
    # 1. Define a simple concrete strategy on the fly
    # ------------------------------------------------------------
    class SimplePriceVolumeStrategy(TradingStrategy):
        """
        A minimal strategy:
        - Buy when close > SMA(20) AND volume > 1.5 * SMA(volume)
        - Sell when close < SMA(20) AND volume > 1.5 * SMA(volume)
        """
        def __init__(self, params: dict = None):
            default_params = {
                'sma_period': 20,
                'volume_multiplier': 1.5,
                'volume_sma_period': 20
            }
            if params:
                default_params.update(params)
            super().__init__(name="SimplePriceVolume", params=default_params)

        def calculate_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
            df = data.copy()
            df['sma'] = self.calculate_sma(df['close'], self.params['sma_period'])
            df['volume_sma'] = self.calculate_sma(df['volume'], self.params['volume_sma_period'])
            df['volume_ratio'] = df['volume'] / df['volume_sma']
            return df

        def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
            self.validate_data(data)
            df = self.calculate_indicators(data)
            df['signal'] = 0

            buy_condition = (df['close'] > df['sma']) & (df['volume_ratio'] > self.params['volume_multiplier'])
            sell_condition = (df['close'] < df['sma']) & (df['volume_ratio'] > self.params['volume_multiplier'])

            df.loc[buy_condition, 'signal'] = 1
            df.loc[sell_condition, 'signal'] = -1
            return df

    # ------------------------------------------------------------
    # 2. Create sample data
    # ------------------------------------------------------------
    def create_sample_data():
        dates = pd.date_range(start='2023-01-01', end='2023-12-31', freq='D')
        np.random.seed(42)
        price = 100 + np.cumsum(np.random.randn(len(dates)) * 0.5)
        data = pd.DataFrame({
            'date': dates,
            'open': price + np.random.randn(len(dates)) * 0.2,
            'high': price + 0.5 + np.random.randn(len(dates)) * 0.2,
            'low': price - 0.5 + np.random.randn(len(dates)) * 0.2,
            'close': price,
            'volume': np.random.randint(1000, 10000, len(dates))
        })
        return data

    sample_data = create_sample_data()

    # ------------------------------------------------------------
    # 3. Test the strategy
    # ------------------------------------------------------------
    print("🔧 Trading Strategy Test (Using only Base Class)")
    print("=" * 70)

    # Create strategy with custom parameters
    strategy = SimplePriceVolumeStrategy(params={'sma_period': 15, 'volume_multiplier': 1.8})
    signals = strategy.generate_signals(sample_data)

    print(f"Strategy name: {strategy.name}")
    print(f"Parameters: {strategy.get_parameters()['parameters']}")
    print(f"Buy signals:  {(signals['signal'] == 1).sum()}")
    print(f"Sell signals: {(signals['signal'] == -1).sum()}")

    # Show first few signals
    signal_rows = signals[signals['signal'] != 0].head(5)
    if not signal_rows.empty:
        print("\nSample signals:")
        print(signal_rows[['date', 'close', 'sma', 'volume_ratio', 'signal']].round(2).to_string(index=False))
    else:
        print("\nNo signals generated (try adjusting parameters).")

    # ------------------------------------------------------------
    # 4. Test parameter update
    # ------------------------------------------------------------
    print("\n🔄 Updating parameters...")
    strategy.update_parameters({'sma_period': 10, 'volume_multiplier': 1.2})
    new_signals = strategy.generate_signals(sample_data)
    print(f"After update - Buy signals: {(new_signals['signal'] == 1).sum()}")
    print(f"After update - Sell signals: {(new_signals['signal'] == -1).sum()}")

    # ------------------------------------------------------------
    # 5. Demonstrate RSI helper method (inherited from base)
    # ------------------------------------------------------------
    print("\n📊 Testing base class helper: RSI")
    rsi_series = strategy.calculate_rsi(sample_data['close'], period=14)
    print(f"RSI range: [{rsi_series.min():.2f}, {rsi_series.max():.2f}]")
    print(f"Last 5 RSI values:\n{rsi_series.tail(5).round(2)}")

    # ------------------------------------------------------------
    # 6. Demonstrate signal strength placeholder
    # ------------------------------------------------------------
    print("\n⚡ Signal strength (default = 1.0 for all rows):")
    strength = strategy.get_signal_strength(sample_data)
    print(f"Signal strength value: {strength}")

    print("\n✅ All tests completed successfully!")
    print("=" * 70)