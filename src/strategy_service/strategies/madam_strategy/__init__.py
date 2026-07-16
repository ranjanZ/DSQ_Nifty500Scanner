import pandas as pd
import numpy as np
from typing import Dict, Any, List, Tuple
from scipy.stats import gaussian_kde
from scipy.signal import find_peaks
from datetime import datetime, timedelta
from ...strategy_base import TradingStrategy  


class SupportResistanceStrategy(TradingStrategy):
    """
    Support/Resistance Strategy using ALL available historical data
    Generates signals on the same candle
    """

    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'volume_ema_period': 20,     # Period for volume EMA
            'volume_threshold': 1.3,     # Volume multiplier threshold
            'kde_bandwidth': 0.2,        # Bandwidth for KDE smoothing
            'num_levels': 10,             # Number of S/R levels to identify
            'level_tolerance': 0.02,     # 2% tolerance for level matching
            'use_pivot_points': True,    # Use pivot points for level detection
            'min_touch_count': 1,        # Minimum touches to validate level
            'merge_tolerance': 0.005,    # Merge similar levels within 0.5%
            'max_history_days': None,    # Optional: max days to look back (None = all)
            'min_history_candles': 2,   # Minimum candles needed to calculate levels
            'adaptive_kde': True,        # Adjust KDE bandwidth based on data size
            'exponential_weighting': True, # Give more weight to recent data
            'weight_decay_factor': 0.99  # Decay factor for exponential weighting
        }

        if params:
            default_params.update(params)
        
        super().__init__(name="SupportResistance", params=default_params)
    
    def calculate_pivot_points(self, df: pd.DataFrame) -> Tuple[List[float], List[float]]:
        """
        Calculate pivot points from ALL price action
        Returns: (support_levels, resistance_levels)
        """
        if len(df) < 5:  # Need at least 5 candles for pivot detection
            return [], []
        
        high = df['high'].values
        low = df['low'].values
        
        pivot_highs = []
        pivot_lows = []
        
        # Find pivot highs and lows across entire history
        for i in range(2, len(df)-2):
            # Pivot High
            if (high[i] > high[i-1] and high[i] > high[i-2] and 
                high[i] > high[i+1] and high[i] > high[i+2]):
                pivot_highs.append(high[i])
            
            # Pivot Low
            if (low[i] < low[i-1] and low[i] < low[i-2] and 
                low[i] < low[i+1] and low[i] < low[i+2]):
                pivot_lows.append(low[i])
        
        return pivot_lows, pivot_highs
    
    def get_weighted_price_points(self, df: pd.DataFrame) -> np.ndarray:
        """
        Get price points with exponential weighting (more weight to recent prices)
        """
        price_points = []
        weights = []
        
        n = len(df)
        
        for idx, (_, row) in enumerate(df.iterrows()):
            # Calculate weight based on position (exponential decay)
            if self.params['exponential_weighting']:
                weight = self.params['weight_decay_factor'] ** (n - idx - 1)
            else:
                weight = 1.0
            
            # Add multiple price points from each candle with weight
            # Basic price points (each gets full weight)
            price_points.extend([row['open'], row['high'], row['low'], row['close']])
            weights.extend([weight, weight, weight, weight])
            
            # Extra weight to close prices
            price_points.append(row['close'])
            price_points.append(row['close'])
            weights.extend([weight * 1.5, weight * 1.5])  # Higher weight for close prices
        
        return np.array(price_points), np.array(weights)
    
    def merge_similar_levels(self, levels: List[float], tolerance: float = 0.005) -> List[float]:
        """Merge similar price levels"""
        if not levels:
            return []
        
        levels = sorted(levels)
        merged = []
        
        current_group = [levels[0]]
        for price in levels[1:]:
            if abs(price - np.mean(current_group)) / np.mean(current_group) <= tolerance:
                current_group.append(price)
            else:
                merged.append(np.mean(current_group))
                current_group = [price]
        
        if current_group:
            merged.append(np.mean(current_group))
        
        return merged
    
    def calculate_support_resistance(self, df: pd.DataFrame, current_idx: int) -> Tuple[List[float], List[float]]:
        """
        Calculate support and resistance levels using ALL previous candles
        current_idx: Index of current candle for which we're calculating levels
        """
        # Use ALL previous candles up to current_idx
        historical_df = df.iloc[:current_idx]  # All candles before current
        
        if len(historical_df) < self.params['min_history_candles']:
            # Not enough data yet
            return [], []
        
        # Apply max history days filter if specified
        if self.params['max_history_days'] and len(historical_df) > 0:
            if 'date' in historical_df.columns or 'timestamp' in historical_df.columns:
                date_col = 'date' if 'date' in historical_df.columns else 'timestamp'
                cutoff_date = historical_df[date_col].iloc[-1] - timedelta(days=self.params['max_history_days'])
                historical_df = historical_df[historical_df[date_col] >= cutoff_date]
        
        # Method 1: KDE on all historical price points
        price_points, weights = self.get_weighted_price_points(historical_df)
        
        # Adjust KDE bandwidth based on data size if adaptive
        kde_bandwidth = self.params['kde_bandwidth']
        if self.params['adaptive_kde']:
            # Smaller bandwidth for more data, larger for less data
            data_points = len(price_points)
            if data_points > 1000:
                kde_bandwidth = self.params['kde_bandwidth'] * 0.8
            elif data_points < 200:
                kde_bandwidth = self.params['kde_bandwidth'] * 1.5
        
        try:
            # Create weighted KDE
            kde = gaussian_kde(price_points, bw_method=kde_bandwidth, weights=weights)
            
            # Evaluate on price range of historical data
            price_min, price_max = price_points.min(), price_points.max()
            price_range = np.linspace(price_min, price_max, min(1000, len(price_points)))
            density = kde(price_range)
            
            # Find peaks (potential S/R levels)
            peaks, properties = find_peaks(density, 
                                          height=np.percentile(density, 75),
                                          distance=max(1, len(price_range) // 100))  # Adaptive distance
            
            if len(peaks) > 0:
                kde_levels = price_range[peaks]
                # Get strongest peaks
                peak_heights = density[peaks]
                strong_peaks = kde_levels[np.argsort(peak_heights)[-self.params['num_levels']:]]
            else:
                strong_peaks = np.array([])
        except:
            strong_peaks = np.array([])
        
        # Method 2: Pivot points from all history
        pivot_lows, pivot_highs = self.calculate_pivot_points(historical_df)
        
        # Method 3: Recent highs and lows (but using all history)
        # We'll take more recent data for these
        recent_period = min(50, len(historical_df))
        recent_df = historical_df.tail(recent_period)
        recent_highs = recent_df['high'].nlargest(3).values
        recent_lows = recent_df['low'].nsmallest(3).values
        
        # Method 4: Significant historical levels (all-time highs/lows)
        all_time_high = historical_df['high'].max()
        all_time_low = historical_df['low'].min()
        recent_high = historical_df['high'].iloc[-1] if len(historical_df) > 0 else 0
        recent_low = historical_df['low'].iloc[-1] if len(historical_df) > 0 else 0
        
        significant_highs = [all_time_high, recent_high]
        significant_lows = [all_time_low, recent_low]
        
        # Combine all levels
        all_support = list(pivot_lows) + list(recent_lows) + list(significant_lows)
        all_resistance = list(pivot_highs) + list(recent_highs) + list(significant_highs)
        
        # Add KDE levels
        if len(strong_peaks) > 0:
            current_price = df['close'].iloc[current_idx] if current_idx < len(df) else df['close'].iloc[-1]
            for level in strong_peaks:
                if level < current_price:
                    all_support.append(level)
                else:
                    all_resistance.append(level)
        
        # Merge similar levels
        support_levels = self.merge_similar_levels(all_support, self.params['merge_tolerance'])
        resistance_levels = self.merge_similar_levels(all_resistance, self.params['merge_tolerance'])
        
        # Sort and return
        support_levels = sorted(support_levels, reverse=True)  # Highest support first
        resistance_levels = sorted(resistance_levels)  # Lowest resistance first
        
        return support_levels[:self.params['num_levels']], resistance_levels[:self.params['num_levels']]
    
    def is_at_resistance(self, candle: pd.Series, resistance_levels: List[float]) -> Tuple[bool, float]:
        """
        Check if candle is at resistance level
        Consider: close near resistance OR high touches resistance
        """
        if not resistance_levels:
            return False, None
        
        for level in resistance_levels:
            # Check if close is near resistance
            close_diff = abs(candle['close'] - level) / level
            # Check if high touched resistance
            high_diff = abs(candle['high'] - level) / level
            
            if close_diff <= self.params['level_tolerance'] or high_diff <= self.params['level_tolerance']:
                return True, level
        
        return False, None
    
    def calculate_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        """Calculate all indicators using all historical data"""
        df = data.copy()
        
        # Volume EMA
        df['volume_ema'] = df['volume'].ewm(
            span=self.params['volume_ema_period'], 
            adjust=False
        ).mean()
        
        # Candle properties
        df['candle_size'] = df['high'] - df['low']
        df['body_size'] = abs(df['close'] - df['open'])
        df['is_green'] = df['close'] > df['open']
        df['upper_wick'] = df['high'] - df[['open', 'close']].max(axis=1)
        df['lower_wick'] = df[['open', 'close']].min(axis=1) - df['low']
        
        # Calculate S/R levels for each candle using ALL previous data
        support_levels_list = []
        resistance_levels_list = []
        
        for i in range(len(df)):
            # Use ALL candles before current one
            if i >= self.params['min_history_candles']:
                support_levels, resistance_levels = self.calculate_support_resistance(df, i)
            else:
                support_levels, resistance_levels = [], []
            
            support_levels_list.append(support_levels)
            resistance_levels_list.append(resistance_levels)
        
        df['support_levels'] = support_levels_list
        df['resistance_levels'] = resistance_levels_list
        
        # Track number of levels found (for analysis)
        df['num_support'] = df['support_levels'].apply(len)
        df['num_resistance'] = df['resistance_levels'].apply(len)
        
        return df
    
    def generate_signals(self, data: pd.DataFrame, num_back_signals: int = None) -> pd.DataFrame:
        """
        Generate signals on SAME candle when conditions are met
        Indicators computed for ALL data, signals only for recent candles
        
        Args:
            data: OHLCV dataframe with 'time' column
            last_n_days: Only generate signals for last N days (None = all)
        
        Returns:
            DataFrame with signal and signal_strength columns
        """
        # Calculate indicators for ALL data (for accurate support/resistance levels)
        df = self.calculate_indicators(data)
        df['signal'] = 0
        df['signal_strength'] = 0.0
        
        volume_threshold = self.params['volume_threshold']
        
        # Determine range for signal generation
        start_idx = self.params['min_history_candles']
        
        if num_back_signals is not None and len(df) > 0:
            start_idx=max(0, len(df) - num_back_signals)  # Simple index-based approach if time column is unreliable

      
        # Generate signals only for specified range
        for i in range(start_idx, len(df)):
            current_candle = df.iloc[i]
            
            # Check if current candle is at resistance
            is_at_res, res_level = self.is_at_resistance(
                current_candle, 
                current_candle['resistance_levels']
            )
            
            if not is_at_res:
                continue
            
            # Condition 1: Green candle at resistance
            condition1 = current_candle['is_green']
            
            # Condition 2: High volume
            condition2 = current_candle['volume'] > (volume_threshold * current_candle['volume_ema'])
            
            # Condition 3: Strong candle (optional - body > 50% of range)
            condition3 = current_candle['body_size'] > 0.5 * current_candle['candle_size']
            
            # Condition 4: Small upper wick (price closed near high)
            condition4 = current_candle['upper_wick'] < 0.3 * current_candle['candle_size']
        
            # Generate buy signal if conditions met
            if condition1 and condition2:
                df.loc[df.index[i], 'signal'] = 1
                
                # Calculate signal strength (0 to 1)
                signal_strength = 0.5  # Base
                if condition3:
                    signal_strength += 0.2
                if condition4:
                    signal_strength += 0.3
                df.loc[df.index[i], 'signal_strength'] = min(signal_strength, 1.0)
                
                # Add metadata for analysis
                df.loc[df.index[i], 'signal_resistance'] = res_level
                df.loc[df.index[i], 'volume_ratio'] = current_candle['volume'] / current_candle['volume_ema']
        
        return df




# Example usage:
if __name__ == "__main__":
    # Example initialization with custom parameters
    # strategy_params = {
    #     'volume_ema_period': 20,
    #     'volume_threshold': 1.3,
    #     'kde_bandwidth': 0.2,
    #     'num_levels': 5,
    #     'level_tolerance': 0.015,
    #     'merge_tolerance': 0.005,
    #     'min_history_candles': 30,  # Minimum candles needed
    #     'max_history_days': 365,    # Optional: limit to 1 year history
    #     'exponential_weighting': True,
    #     'weight_decay_factor': 0.995
    # }
    
    strategy = SupportResistanceStrategy()
    
    # Assuming you have a DataFrame 'data' with OHLCV columns
    # signals = strategy.generate_signals(data)
    from src.data_pipeline.db_utils import get_table_content
    from src.utils.plot_chart import plot_signals
    end_date = datetime.now()
    start_date = end_date - timedelta(days=100)
    data=get_table_content(
                db_name='spot_db_anamika',
                table_name="aubank_eq",
                start_date=start_date,
                end_date=end_date
            )

    signals = strategy.generate_signals(data, num_back_signals=30)
    plot_signals(signals)


