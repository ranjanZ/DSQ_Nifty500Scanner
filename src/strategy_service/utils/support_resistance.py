"""
utils/support_resistance.py
===========================
Pure utility for calculating support and resistance levels
using rolling-window pivot clustering with ATR-based tolerance.
No strategy logic — just level detection.
"""

import pandas as pd
import numpy as np
from typing import List, Tuple, Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class Level:
    price: float
    score: float
    touches: int
    last_idx: int
    role: str  # 'support' or 'resistance'


class SupportResistanceCalculator:
    """
    Detects S/R levels from price action using fractal pivots + clustering.
    """

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        self.params = {
            'lookback_window': 300,
            'pivot_window': 2,              # 2 bars each side = 5-bar fractal
            'min_touch_count': 2,
            'level_atr_multiple': 0.3,
            'num_levels': 5,
            'max_age_candles': 100,
            'broken_level_cooldown': 20,
        }
        if params:
            self.params.update(params)

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def calculate(self, df: pd.DataFrame, current_idx: int, current_atr: float) -> Tuple[List[float], List[float]]:
        """
        Return (support_prices, resistance_prices) using only data[:current_idx].
        """
        hist = df.iloc[:current_idx].copy()

        if len(hist) < 10:
            return [], []

        # Rolling window
        window = self.params['lookback_window']
        if len(hist) > window:
            hist = hist.iloc[-window:].copy()

        if len(hist) < 5:
            return [], []

        if current_atr <= 0 or np.isnan(current_atr):
            current_atr = (hist['high'].max() - hist['low'].min()) * 0.01

        tolerance = self.params['level_atr_multiple'] * current_atr

        # Find pivots
        pivot_highs, high_indices = self._find_pivot_highs(hist)
        pivot_lows, low_indices = self._find_pivot_lows(hist)

        # Map local indices back to global df indices for age checks
        hist_start_idx = current_idx - len(hist)

        # Cluster
        high_clusters = self._cluster_levels(pivot_highs, high_indices, tolerance, hist_start_idx)
        low_clusters = self._cluster_levels(pivot_lows, low_indices, tolerance, hist_start_idx)

        # Classify, filter, score
        support_levels, resistance_levels = self._process_clusters(
            hist, high_clusters, low_clusters, current_idx, current_atr, tolerance
        )

        # Sort by score, take top N
        support_levels = sorted(support_levels, key=lambda x: x.score, reverse=True)
        resistance_levels = sorted(resistance_levels, key=lambda x: x.score, reverse=True)

        support_prices = [l.price for l in support_levels[:self.params['num_levels']]]
        resistance_prices = [l.price for l in resistance_levels[:self.params['num_levels']]]

        return support_prices, resistance_prices

    # ------------------------------------------------------------------ #
    #  Internals
    # ------------------------------------------------------------------ #

    def _find_pivot_highs(self, hist: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        """Return (prices, local_indices) for swing highs."""
        high = hist['high'].values
        w = self.params['pivot_window']
        n = len(high)

        if n < 2 * w + 1:
            return np.array([]), np.array([])

        peaks = np.zeros(n, dtype=bool)
        for i in range(w, n - w):
            if all(high[i] > high[i - j] for j in range(1, w + 1)) and \
               all(high[i] > high[i + j] for j in range(1, w + 1)):
                peaks[i] = True

        indices = np.where(peaks)[0]
        return high[indices], indices

    def _find_pivot_lows(self, hist: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        """Return (prices, local_indices) for swing lows."""
        low = hist['low'].values
        w = self.params['pivot_window']
        n = len(low)

        if n < 2 * w + 1:
            return np.array([]), np.array([])

        troughs = np.zeros(n, dtype=bool)
        for i in range(w, n - w):
            if all(low[i] < low[i - j] for j in range(1, w + 1)) and \
               all(low[i] < low[i + j] for j in range(1, w + 1)):
                troughs[i] = True

        indices = np.where(troughs)[0]
        return low[indices], indices

    def _cluster_levels(self, prices: np.ndarray, indices: np.ndarray,
                        tolerance: float, hist_start_idx: int) -> List[Dict[str, Any]]:
        """Group nearby pivots into level clusters."""
        if len(prices) == 0:
            return []

        order = np.argsort(prices)
        prices = prices[order]
        indices = indices[order]

        clusters = []
        curr_prices = [prices[0]]
        curr_indices = [indices[0]]

        for p, idx in zip(prices[1:], indices[1:]):
            mean_p = np.mean(curr_prices)
            # Use absolute tolerance (ATR-based) instead of percentage
            if abs(p - mean_p) <= tolerance:
                curr_prices.append(p)
                curr_indices.append(idx)
            else:
                clusters.append({
                    'price': float(np.mean(curr_prices)),
                    'count': len(curr_prices),
                    'last_idx': hist_start_idx + max(curr_indices),
                    'indices': [hist_start_idx + i for i in curr_indices],
                })
                curr_prices = [p]
                curr_indices = [idx]

        clusters.append({
            'price': float(np.mean(curr_prices)),
            'count': len(curr_prices),
            'last_idx': hist_start_idx + max(curr_indices),
            'indices': [hist_start_idx + i for i in curr_indices],
        })
        return clusters

    def _classify_role(self, hist: pd.DataFrame, price: float,
                       atr: float, tolerance_mult: float) -> str:
        """Determine if level acted more as support or resistance historically."""
        tol = atr * tolerance_mult
        support_touches = 0
        resistance_touches = 0

        for _, row in hist.iterrows():
            low, high, close = row['low'], row['high'], row['close']

            # Bounced from below = support
            if abs(low - price) <= tol and close > price:
                support_touches += 1
            # Rejected from above = resistance
            elif abs(high - price) <= tol and close < price:
                resistance_touches += 1

        if support_touches > resistance_touches:
            return 'support'
        elif resistance_touches > support_touches:
            return 'resistance'
        return 'neutral'

    def _is_broken(self, hist: pd.DataFrame, price: float,
                   role: str, atr: float, tolerance_mult: float) -> bool:
        """Check if level was broken in recent history."""
        if len(hist) == 0:
            return False

        tol = atr * tolerance_mult
        recent = hist.tail(self.params['broken_level_cooldown'])

        if role == 'support':
            # Closed clearly below support
            return (recent['close'] < (price - tol)).any()
        elif role == 'resistance':
            # Closed clearly above resistance
            return (recent['close'] > (price + tol)).any()
        return False

    def _process_clusters(self, hist: pd.DataFrame,
                          high_clusters: List[Dict], low_clusters: List[Dict],
                          current_idx: int, atr: float, tolerance: float) -> Tuple[List[Level], List[Level]]:
        """Classify clusters, filter broken/old, score, and bucket into S/R."""
        support_levels: List[Level] = []
        resistance_levels: List[Level] = []

        all_clusters = [(c, 'high') for c in high_clusters] + [(c, 'low') for c in low_clusters]

        for cluster, origin in all_clusters:
            price = cluster['price']
            count = cluster['count']
            last_idx = cluster['last_idx']

            # Filter: age
            if (current_idx - last_idx) > self.params['max_age_candles']:
                continue

            # Filter: minimum touches
            if count < self.params['min_touch_count']:
                continue

            # Classify role from historical behavior
            role = self._classify_role(hist, price, atr, self.params['level_atr_multiple'])

            # If neutral, infer from origin
            if role == 'neutral':
                role = 'resistance' if origin == 'high' else 'support'

            # Filter: broken levels
            if self._is_broken(hist, price, role, atr, self.params['level_atr_multiple']):
                continue

            # Score: touches * recency_weight
            age = current_idx - last_idx
            recency = 1.0 - (age / self.params['max_age_candles'])
            recency = max(0.3, recency)
            score = count * recency

            level = Level(price=price, score=score, touches=count,
                          last_idx=last_idx, role=role)

            if role == 'support':
                support_levels.append(level)
            else:
                resistance_levels.append(level)

        return support_levels, resistance_levels