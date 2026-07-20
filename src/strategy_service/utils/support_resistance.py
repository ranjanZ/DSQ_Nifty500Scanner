"""
utils/support_resistance.py
===========================
Robust S/R utility with multiple fallback layers.
Never returns empty lists for valid OHLCV data.
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
    role: str


class SupportResistanceCalculator:
    """
    Detects S/R levels from price action using fractal pivots + clustering.
    Falls back to simpler methods if clustering fails.
    """

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        self.params = {
            'lookback_window': 300,
            'pivot_window': 2,
            'min_touch_count': 2,
            'level_atr_multiple': 0.3,
            'num_levels': 5,
            'max_age_candles': 100,
            'broken_level_cooldown': 20,
            'fallback_tolerance_pct': 0.005,   # 0.5% of price if ATR is useless
        }
        if params:
            self.params.update(params)

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def calculate(self, df: pd.DataFrame, current_idx: int, current_atr: float) -> Tuple[List[float], List[float]]:
        """
        Return (support_prices, resistance_prices) using only data[:current_idx].
        Guaranteed non-empty for any valid data with >= 2 rows.
        """
        hist = df.iloc[:current_idx].copy()

        if len(hist) == 0:
            return [], []

        # --- Layer 0: Ultra-minimal data (2-4 candles) -----------------
        if len(hist) < 5:
            return self._ultra_fallback(hist)

        # --- Layer 1: Normal pivot clustering ------------------------
        window = self.params['lookback_window']
        if len(hist) > window:
            hist = hist.iloc[-window:].copy()

        if current_atr <= 0 or np.isnan(current_atr):
            current_atr = (hist['high'].max() - hist['low'].min()) * 0.01

        # Ensure minimum tolerance (ATR can be tiny on low-volatility stocks)
        tolerance = max(
            self.params['level_atr_multiple'] * current_atr,
            hist['close'].iloc[-1] * self.params['fallback_tolerance_pct']
        )

        pivot_highs, high_indices = self._find_pivot_highs(hist)
        pivot_lows, low_indices = self._find_pivot_lows(hist)
        hist_start_idx = current_idx - len(hist)

        high_clusters = self._cluster_levels(pivot_highs, high_indices, tolerance, hist_start_idx)
        low_clusters = self._cluster_levels(pivot_lows, low_indices, tolerance, hist_start_idx)

        # Try strict min_touch_count first
        support, resistance = self._process_clusters(
            hist, high_clusters, low_clusters, current_idx, current_atr, tolerance,
            strict=True
        )

        # --- Layer 2: Relax min_touch_count if strict yields nothing ---
        if not support or not resistance:
            support, resistance = self._process_clusters(
                hist, high_clusters, low_clusters, current_idx, current_atr, tolerance,
                strict=False
            )

        # --- Layer 3: Raw pivots if clustering failed entirely ---
        if not support:
            support = self._raw_pivot_fallback(pivot_lows, hist_start_idx, current_idx, 'support')
        if not resistance:
            resistance = self._raw_pivot_fallback(pivot_highs, hist_start_idx, current_idx, 'resistance')

        # --- Layer 4: Recent extremes if absolutely nothing else -------
        if not support:
            support = self._extreme_fallback(hist, 'low')
        if not resistance:
            resistance = self._extreme_fallback(hist, 'high')

        # Sort and truncate
        support = sorted(support, reverse=True)[:self.params['num_levels']]
        resistance = sorted(resistance)[:self.params['num_levels']]

        return support, resistance

    # ------------------------------------------------------------------ #
    #  Fallback Layers
    # ------------------------------------------------------------------ #

    def _ultra_fallback(self, hist: pd.DataFrame) -> Tuple[List[float], List[float]]:
        """For 2-4 candles: just return min(low) and max(high)."""
        return [hist['low'].min()], [hist['high'].max()]

    def _raw_pivot_fallback(self, pivots: np.ndarray, hist_start_idx: int,
                            current_idx: int, role: str) -> List[float]:
        """Use individual pivot points if clustering failed."""
        if len(pivots) == 0:
            return []
        # Take most recent 3 pivots
        prices = pivots[-3:] if len(pivots) > 3 else pivots
        return [float(p) for p in prices]

    def _extreme_fallback(self, hist: pd.DataFrame, col: str) -> List[float]:
        """Use recent extremes as last resort."""
        if len(hist) == 0:
            return []
        recent = hist.tail(20)
        return [
            recent[col].min(),
            recent[col].quantile(0.10),
            hist[col].min(),
        ]

    # ------------------------------------------------------------------ #
    #  Core Methods
    # ------------------------------------------------------------------ #

    def _find_pivot_highs(self, hist: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
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
                       atr: float, tolerance_mult: float,
                       cluster_indices: List[int]) -> str:
        tol = atr * tolerance_mult
        support_touches = 0
        resistance_touches = 0

        first_idx = min(cluster_indices) if cluster_indices else 0
        relevant = hist.loc[hist.index >= first_idx]

        for _, row in relevant.iterrows():
            low, high, close = row['low'], row['high'], row['close']
            if abs(low - price) <= tol and close > price:
                support_touches += 1
            elif abs(high - price) <= tol and close < price:
                resistance_touches += 1

        if support_touches > resistance_touches:
            return 'support'
        elif resistance_touches > support_touches:
            return 'resistance'
        return 'neutral'

    def _is_broken(self, hist: pd.DataFrame, price: float,
                   role: str, atr: float, tolerance_mult: float,
                   last_idx: int) -> bool:
        if len(hist) == 0:
            return False

        tol = atr * tolerance_mult
        level_hist = hist.loc[hist.index >= last_idx]
        if len(level_hist) == 0:
            return False

        recent = level_hist.tail(self.params['broken_level_cooldown'])

        if role == 'support':
            return (recent['close'] < (price - tol)).any()
        elif role == 'resistance':
            return (recent['close'] > (price + tol)).any()
        return False

    def _process_clusters(self, hist: pd.DataFrame,
                          high_clusters: List[Dict], low_clusters: List[Dict],
                          current_idx: int, atr: float, tolerance: float,
                          strict: bool = True) -> Tuple[List[float], List[float]]:
        support_levels: List[float] = []
        resistance_levels: List[float] = []

        min_touch = self.params['min_touch_count'] if strict else 1

        all_clusters = [(c, 'high') for c in high_clusters] + [(c, 'low') for c in low_clusters]

        for cluster, origin in all_clusters:
            price = cluster['price']
            count = cluster['count']
            last_idx = cluster['last_idx']
            indices = cluster['indices']

            if (current_idx - last_idx) > self.params['max_age_candles']:
                continue
            if count < min_touch:
                continue

            role = self._classify_role(hist, price, atr, self.params['level_atr_multiple'], indices)

            if role == 'neutral':
                role = 'resistance' if origin == 'high' else 'support'

            if self._is_broken(hist, price, role, atr, self.params['level_atr_multiple'], last_idx):
                continue

            if role == 'support':
                support_levels.append(price)
            else:
                resistance_levels.append(price)

        return support_levels, resistance_levels


# ==================================================================== #
#  TEST RUNNER — verifies 20 random stocks never return empty
# ==================================================================== #
if __name__ == "__main__":
    import random

    def make_random_stock(seed: int, n: int = 500) -> pd.DataFrame:
        np.random.seed(seed)
        returns = np.random.normal(0.0005, 0.015, n)
        close = 100 * np.exp(np.cumsum(returns))
        noise = np.random.uniform(0.005, 0.015, n)
        return pd.DataFrame({
            'open': close * (1 - np.random.uniform(0, 0.005, n)),
            'high': close * (1 + noise),
            'low': close * (1 - noise),
            'close': close,
            'volume': np.random.randint(1_000_000, 10_000_000, n),
        })

    calc = SupportResistanceCalculator()

    print("Testing 20 random synthetic stocks …\n")
    failures = 0

    for seed in range(20):
        df = make_random_stock(seed, n=random.randint(50, 500))

        # Real ATR
        hl = df['high'] - df['low']
        hc = (df['high'] - df['close'].shift()).abs()
        lc = (df['low'] - df['close'].shift()).abs()
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        atr = tr.ewm(span=14, adjust=False).mean().iloc[-1]
        if pd.isna(atr) or atr <= 0:
            atr = (df['high'].max() - df['low'].min()) * 0.01

        support, resistance = calc.calculate(df, current_idx=len(df), current_atr=atr)

        ok = len(support) > 0 and len(resistance) > 0
        status = "✅" if ok else "❌"
        print(f"{status} Seed {seed:2d} | n={len(df):3d} | ATR={atr:.2f} | "
              f"Support:{len(support)} Resistance:{len(resistance)}")

        if not ok:
            failures += 1

    print(f"\n{'='*50}")
    print(f"Results: {20 - failures}/20 passed")
    if failures == 0:
        print("🎉 All stocks returned valid S/R levels!")
    else:
        print(f"⚠️  {failures} stocks returned empty levels — check above.")