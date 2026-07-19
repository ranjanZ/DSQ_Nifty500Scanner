"""
volume_support_resistance.py
============================
Buy signals generated when price bounces from a support level
with volume confirmation. Uses utils/support_resistance.py for
level detection.
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, List, Tuple

import sys
from pathlib import Path

_file = Path(__file__).resolve()
# Walk up to src/ : strategy.py -> strategy_folder -> strategies -> strategy_service -> src
_src_dir = _file.parent.parent.parent.parent
if _src_dir.name == "src" and str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

# Now absolute imports work regardless of how the file is loaded
from strategy_service.utils.support_resistance import SupportResistanceCalculator
from strategy_service.strategy_base import TradingStrategy



class VolumeSupportResistanceStrategy(TradingStrategy):
    """
    Support bounce strategy using rolling-window pivot clustering.
    """

    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'volume_ema_period': 20,
            'volume_threshold': 1.3,
            'lookback_window': 300,
            'pivot_window': 2,
            'min_touch_count': 2,
            'level_atr_multiple': 0.3,
            'num_levels': 5,
            'max_age_candles': 100,
            'broken_level_cooldown': 20,
            'min_history_candles': 10,
            'max_candle_size_atr': 2.0
        }

        if params:
            default_params.update(params)

        self.params = default_params
        self.name = "VolumeSupportResistance"
        self.sr_calc = SupportResistanceCalculator(self.params)

    # ------------------------------------------------------------------ #
    #  Indicators
    # ------------------------------------------------------------------ #

    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        high = df['high']
        low = df['low']
        close = df['close']
        prev_close = close.shift(1)

        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.ewm(span=period, adjust=False).mean()

    def calculate_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()

        # Volume
        df['volume_ema'] = df['volume'].ewm(span=self.params['volume_ema_period'], adjust=False).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ema']

        # ATR for dynamic tolerance
        df['atr'] = self._calculate_atr(df)

        # Candle features
        df['candle_size'] = df['high'] - df['low']
        df['body_size'] = (df['close'] - df['open']).abs()
        df['is_green'] = df['close'] > df['open']
        df['upper_wick'] = df['high'] - df[['open', 'close']].max(axis=1)
        df['lower_wick'] = df[['open', 'close']].min(axis=1) - df['low']

        # Support / Resistance levels
        support_levels_list = []
        resistance_levels_list = []

        min_hist = self.params['min_history_candles']

        for i in range(len(df)):
            if i >= min_hist:
                atr = df['atr'].iloc[i] if pd.notna(df['atr'].iloc[i]) else 0.0
                support, resistance = self.sr_calc.calculate(df, i, atr)
            else:
                support, resistance = [], []

            support_levels_list.append(support)
            resistance_levels_list.append(resistance)

        df['support_levels'] = support_levels_list
        df['resistance_levels'] = resistance_levels_list
        df['num_support'] = df['support_levels'].apply(len)
        df['num_resistance'] = df['resistance_levels'].apply(len)

        return df

    # ------------------------------------------------------------------ #
    #  Signal Logic
    # ------------------------------------------------------------------ #

    def is_at_support(self, candle: pd.Series, support_levels: List[float], atr: float) -> Tuple[bool, float]:
        """Check if price is testing a support level (low near level, close holding)."""
        if not support_levels or atr <= 0 or pd.isna(atr):
            return False, None

        tolerance = self.params['level_atr_multiple'] * atr

        for level in support_levels:
            # Low touched or dipped slightly below level, but close held above
            low_near = abs(candle['low'] - level) <= tolerance
            close_held = candle['close'] >= (level - tolerance)

            if low_near and close_held:
                return True, level

        return False, None

    def generate_signals(self, data: pd.DataFrame, num_back_signals: int = None) -> pd.DataFrame:
        df = self.calculate_indicators(data)

        df['signal'] = 0
        df['signal_strength'] = 0.0
        df['signal_support'] = np.nan

        volume_threshold = self.params['volume_threshold']
        start_idx = self.params['min_history_candles']

        if num_back_signals is not None and len(df) > 0:
            start_idx = max(0, len(df) - num_back_signals)

        for i in range(start_idx, len(df)):
            current_candle = df.iloc[i]
            atr = current_candle['atr'] if pd.notna(current_candle['atr']) else 0.0

            is_at_sup, sup_level = self.is_at_support(
                current_candle, current_candle['support_levels'], atr
            )
            if not is_at_sup:
                continue

            candle_atr_ratio = current_candle['candle_size'] / atr if atr > 0 else 999
            if candle_atr_ratio > self.params['max_candle_size_atr']:
                continue  # Candle too extended, skip



            # Support bounce conditions
            c1 = current_candle['is_green']                              # Bullish close
            c2 = current_candle['volume'] > (volume_threshold * current_candle['volume_ema'])
            c3 = current_candle['body_size'] > 0.5 * current_candle['candle_size']
            c4 = current_candle['lower_wick'] < 0.3 * current_candle['candle_size']  # Clean bounce

            if c1 and c2:
                df.loc[df.index[i], 'signal'] = 1

                strength = 0.5
                if c3:
                    strength += 0.2
                if c4:
                    strength += 0.3
                df.loc[df.index[i], 'signal_strength'] = min(strength, 1.0)
                df.loc[df.index[i], 'signal_support'] = sup_level
                df.loc[df.index[i], 'volume_ratio'] = current_candle['volume'] / current_candle['volume_ema']

        return df