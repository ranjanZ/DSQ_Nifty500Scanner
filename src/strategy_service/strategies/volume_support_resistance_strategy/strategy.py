import pandas as pd
import numpy as np
from typing import Dict, Any, List, Tuple
from scipy.stats import gaussian_kde
from scipy.signal import find_peaks
from datetime import datetime, timedelta
from ...strategy_base import TradingStrategy


class VolumeSupportResistanceStrategy(TradingStrategy):
    """
    Support/Resistance Strategy using ALL available historical data.
    Generates signals on the same candle when price breaks resistance
    with volume confirmation.
    """

    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'volume_ema_period': 20,
            'volume_threshold': 1.3,
            'kde_bandwidth': 0.2,
            'num_levels': 10,
            'level_tolerance': 0.02,
            'use_pivot_points': True,
            'min_touch_count': 1,
            'merge_tolerance': 0.005,
            'max_history_days': None,
            'min_history_candles': 2,
            'adaptive_kde': True,
            'exponential_weighting': True,
            'weight_decay_factor': 0.99
        }

        if params:
            default_params.update(params)

        super().__init__(name="VolumeSupportResistance", params=default_params)

    def calculate_pivot_points(self, df: pd.DataFrame) -> Tuple[List[float], List[float]]:
        if len(df) < 5:
            return [], []

        high = df['high'].values
        low = df['low'].values
        pivot_highs = []
        pivot_lows = []

        for i in range(2, len(df) - 2):
            if (high[i] > high[i-1] and high[i] > high[i-2] and
                high[i] > high[i+1] and high[i] > high[i+2]):
                pivot_highs.append(high[i])

            if (low[i] < low[i-1] and low[i] < low[i-2] and
                low[i] < low[i+1] and low[i] < low[i+2]):
                pivot_lows.append(low[i])

        return pivot_lows, pivot_highs

    def get_weighted_price_points(self, df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        price_points = []
        weights = []
        n = len(df)

        for idx, (_, row) in enumerate(df.iterrows()):
            weight = (self.params['weight_decay_factor'] ** (n - idx - 1)
                      if self.params['exponential_weighting'] else 1.0)

            price_points.extend([row['open'], row['high'], row['low'], row['close']])
            weights.extend([weight, weight, weight, weight])

            price_points.extend([row['close'], row['close']])
            weights.extend([weight * 1.5, weight * 1.5])

        return np.array(price_points), np.array(weights)

    def merge_similar_levels(self, levels: List[float], tolerance: float = 0.005) -> List[float]:
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
        historical_df = df.iloc[:current_idx]

        if len(historical_df) < self.params['min_history_candles']:
            return [], []

        if self.params['max_history_days'] and len(historical_df) > 0:
            date_col = 'date' if 'date' in historical_df.columns else 'timestamp'
            if date_col in historical_df.columns:
                cutoff_date = historical_df[date_col].iloc[-1] - timedelta(days=self.params['max_history_days'])
                historical_df = historical_df[historical_df[date_col] >= cutoff_date]

        price_points, weights = self.get_weighted_price_points(historical_df)
        kde_bandwidth = self.params['kde_bandwidth']

        if self.params['adaptive_kde']:
            data_points = len(price_points)
            if data_points > 1000:
                kde_bandwidth *= 0.8
            elif data_points < 200:
                kde_bandwidth *= 1.5

        try:
            kde = gaussian_kde(price_points, bw_method=kde_bandwidth, weights=weights)
            price_min, price_max = price_points.min(), price_points.max()
            price_range = np.linspace(price_min, price_max, min(1000, len(price_points)))
            density = kde(price_range)

            peaks, _ = find_peaks(density,
                                  height=np.percentile(density, 75),
                                  distance=max(1, len(price_range) // 100))

            if len(peaks) > 0:
                kde_levels = price_range[peaks]
                peak_heights = density[peaks]
                strong_peaks = kde_levels[np.argsort(peak_heights)[-self.params['num_levels']:]]
            else:
                strong_peaks = np.array([])
        except Exception:
            strong_peaks = np.array([])

        pivot_lows, pivot_highs = self.calculate_pivot_points(historical_df)

        recent_period = min(50, len(historical_df))
        recent_df = historical_df.tail(recent_period)
        recent_highs = recent_df['high'].nlargest(3).values
        recent_lows = recent_df['low'].nsmallest(3).values

        all_time_high = historical_df['high'].max()
        all_time_low = historical_df['low'].min()
        recent_high = historical_df['high'].iloc[-1] if len(historical_df) > 0 else 0
        recent_low = historical_df['low'].iloc[-1] if len(historical_df) > 0 else 0

        all_support = list(pivot_lows) + list(recent_lows) + [all_time_low, recent_low]
        all_resistance = list(pivot_highs) + list(recent_highs) + [all_time_high, recent_high]

        if len(strong_peaks) > 0:
            current_price = df['close'].iloc[current_idx] if current_idx < len(df) else df['close'].iloc[-1]
            for level in strong_peaks:
                if level < current_price:
                    all_support.append(level)
                else:
                    all_resistance.append(level)

        support_levels = self.merge_similar_levels(all_support, self.params['merge_tolerance'])
        resistance_levels = self.merge_similar_levels(all_resistance, self.params['merge_tolerance'])

        support_levels = sorted(support_levels, reverse=True)
        resistance_levels = sorted(resistance_levels)

        return support_levels[:self.params['num_levels']], resistance_levels[:self.params['num_levels']]

    def is_at_resistance(self, candle: pd.Series, resistance_levels: List[float]) -> Tuple[bool, float]:
        if not resistance_levels:
            return False, None

        for level in resistance_levels:
            close_diff = abs(candle['close'] - level) / level
            high_diff = abs(candle['high'] - level) / level

            if close_diff <= self.params['level_tolerance'] or high_diff <= self.params['level_tolerance']:
                return True, level

        return False, None

    def calculate_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()

        df['volume_ema'] = df['volume'].ewm(span=self.params['volume_ema_period'], adjust=False).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ema']

        df['candle_size'] = df['high'] - df['low']
        df['body_size'] = abs(df['close'] - df['open'])
        df['is_green'] = df['close'] > df['open']
        df['upper_wick'] = df['high'] - df[['open', 'close']].max(axis=1)
        df['lower_wick'] = df[['open', 'close']].min(axis=1) - df['low']

        support_levels_list = []
        resistance_levels_list = []

        for i in range(len(df)):
            if i >= self.params['min_history_candles']:
                support_levels, resistance_levels = self.calculate_support_resistance(df, i)
            else:
                support_levels, resistance_levels = [], []

            support_levels_list.append(support_levels)
            resistance_levels_list.append(resistance_levels)

        df['support_levels'] = support_levels_list
        df['resistance_levels'] = resistance_levels_list
        df['num_support'] = df['support_levels'].apply(len)
        df['num_resistance'] = df['resistance_levels'].apply(len)

        return df

    def generate_signals(self, data: pd.DataFrame, num_back_signals: int = None) -> pd.DataFrame:
        df = self.calculate_indicators(data)
        df['signal'] = 0
        df['signal_strength'] = 0.0

        volume_threshold = self.params['volume_threshold']
        start_idx = self.params['min_history_candles']

        if num_back_signals is not None and len(df) > 0:
            start_idx = max(0, len(df) - num_back_signals)

        for i in range(start_idx, len(df)):
            current_candle = df.iloc[i]

            is_at_res, res_level = self.is_at_resistance(
                current_candle, current_candle['resistance_levels']
            )

            if not is_at_res:
                continue

            condition1 = current_candle['is_green']
            condition2 = current_candle['volume'] > (volume_threshold * current_candle['volume_ema'])
            condition3 = current_candle['body_size'] > 0.5 * current_candle['candle_size']
            condition4 = current_candle['upper_wick'] < 0.3 * current_candle['candle_size']

            if condition1 and condition2:
                df.loc[df.index[i], 'signal'] = 1

                signal_strength = 0.5
                if condition3:
                    signal_strength += 0.2
                if condition4:
                    signal_strength += 0.3
                df.loc[df.index[i], 'signal_strength'] = min(signal_strength, 1.0)
                df.loc[df.index[i], 'signal_resistance'] = res_level
                df.loc[df.index[i], 'volume_ratio'] = current_candle['volume'] / current_candle['volume_ema']

        return df