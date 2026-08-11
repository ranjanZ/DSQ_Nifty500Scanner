"""
utils/support_resistance.py
===========================
Robust S/R utility. 
Returns ONLY a clean list of float prices for support and resistance.
Merges nearby levels and draws importance-based zones.
"""

import pandas as pd
import numpy as np
from typing import List, Tuple, Dict, Any, Optional


class SupportResistanceCalculator:
    def __init__(self, params: Optional[Dict[str, Any]] = None):
        self.params = {
            'lookback_window': 300,
            'pivot_window': 2,
            'min_touch_count': 2,
            'level_atr_multiple': 0.3,
            'num_levels': 5,
            'max_age_candles': 100,
            'broken_level_cooldown': 20,
            'fallback_tolerance_pct': 0.005,
            # --- FILTERING RULES ---
            'max_distance_pct': 0.15,       # Ignore levels > 15% away from current price
            'min_score_threshold': 3.0,     # Ignore weak levels
            'min_level_distance_pct': 0.02, # Merge levels closer than 2% (NEW!)
        }
        if params:
            self.params.update(params)

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def calculate(self, df: pd.DataFrame, current_idx: int, current_atr: float) -> Tuple[List[float], List[float]]:
        """
        Returns ONLY two lists of floats: (support_prices, resistance_prices).
        Nearby levels are automatically merged.
        """
        hist = df.iloc[:current_idx].copy().reset_index(drop=True)
        if len(hist) == 0:
            return [], []

        if 'volume' not in hist.columns:
            hist['volume'] = 1.0

        if len(hist) < 5:
            return [float(hist['low'].min())], [float(hist['high'].max())]

        window = self.params['lookback_window']
        if len(hist) > window:
            hist = hist.iloc[-window:].copy().reset_index(drop=True)

        if current_atr <= 0 or np.isnan(current_atr):
            current_atr = (hist['high'].max() - hist['low'].min()) * 0.01

        tolerance = max(
            self.params['level_atr_multiple'] * current_atr,
            hist['close'].iloc[-1] * self.params['fallback_tolerance_pct']
        )

        pivot_highs, high_indices = self._find_pivot_highs(hist)
        pivot_lows, low_indices = self._find_pivot_lows(hist)
        
        high_volumes = hist['volume'].values[high_indices] if len(high_indices) > 0 else np.array([])
        low_volumes = hist['volume'].values[low_indices] if len(low_indices) > 0 else np.array([])
        
        hist_start_idx = current_idx - len(hist)

        high_clusters = self._cluster_levels(pivot_highs, high_indices, high_volumes, tolerance, hist_start_idx)
        low_clusters = self._cluster_levels(pivot_lows, low_indices, low_volumes, tolerance, hist_start_idx)

        # 1. Try strict clustering
        support_levels, resistance_levels = self._process_clusters(
            hist, high_clusters, low_clusters, current_idx, current_atr, tolerance, strict=True
        )

        # 2. Relax rules if needed
        if not support_levels or not resistance_levels:
            sup_relax, res_relax = self._process_clusters(
                hist, high_clusters, low_clusters, current_idx, current_atr, tolerance, strict=False
            )
            if not support_levels: support_levels = sup_relax
            if not resistance_levels: resistance_levels = res_relax

        # 3. Fallback to raw pivots
        if not support_levels:
            support_levels = self._raw_pivot_fallback(pivot_lows, low_volumes, hist_start_idx, current_idx, 'support')
        if not resistance_levels:
            resistance_levels = self._raw_pivot_fallback(pivot_highs, high_volumes, hist_start_idx, current_idx, 'resistance')

        # 4. Fallback to extremes
        if not support_levels:
            support_levels = self._extreme_fallback(hist, 'low')
        if not resistance_levels:
            resistance_levels = self._extreme_fallback(hist, 'high')

        # Sort by strength (score) descending
        support_levels.sort(key=lambda x: x['score'], reverse=True)
        resistance_levels.sort(key=lambda x: x['score'], reverse=True)

        # ==================================================================== #
        #  STRICT FILTERING: Extract ONLY "Good" Float Prices
        # ==================================================================== #
        current_price = float(hist['close'].iloc[-1])
        max_dist = self.params['max_distance_pct']
        min_score = self.params['min_score_threshold']
        min_distance = self.params['min_level_distance_pct']

        good_supports = []
        for lvl in support_levels:
            price = lvl['price']
            if price > current_price * 1.02: continue
            if (current_price - price) / current_price > max_dist: continue
            if lvl['score'] < min_score: continue
            
            # Check if this price is too close to an already-added level
            if not any(abs(price - p) / p < min_distance for p in good_supports):
                good_supports.append(float(price))

        good_resistances = []
        for lvl in resistance_levels:
            price = lvl['price']
            if price < current_price * 0.98: continue
            if (price - current_price) / current_price > max_dist: continue
            if lvl['score'] < min_score: continue
            
            # Check if this price is too close to an already-added level
            if not any(abs(price - p) / p < min_distance for p in good_resistances):
                good_resistances.append(float(price))

        # ==================================================================== #
        #  GUARANTEE NON-EMPTY
        # ==================================================================== #
        if not good_supports and support_levels:
            good_supports = [float(support_levels[0]['price'])]
            
        if not good_resistances and resistance_levels:
            good_resistances = [float(resistance_levels[0]['price'])]

        # Final sort: Closest to current price first
        good_supports.sort(reverse=True)
        good_resistances.sort()

        return good_supports[:self.params['num_levels']], good_resistances[:self.params['num_levels']]

    # ------------------------------------------------------------------ #
    #  Additional Method: Get Rich Level Data for Visualization
    # ------------------------------------------------------------------ #
    
    def calculate_with_zones(self, df: pd.DataFrame, current_idx: int, current_atr: float) -> Tuple[List[dict], List[dict]]:
        """
        Returns level data with zone information for visualization.
        Each level includes: price, score, touches, zone_thickness (as % of price)
        """
        hist = df.iloc[:current_idx].copy().reset_index(drop=True)
        if len(hist) == 0:
            return [], []

        if 'volume' not in hist.columns:
            hist['volume'] = 1.0

        if len(hist) < 5:
            avg_vol = float(hist['volume'].mean())
            sup = {'price': float(hist['low'].min()), 'score': 1.0, 'touches': 1, 'avg_volume': avg_vol, 'zone_thickness_pct': 0.5}
            res = {'price': float(hist['high'].max()), 'score': 1.0, 'touches': 1, 'avg_volume': avg_vol, 'zone_thickness_pct': 0.5}
            return [sup], [res]

        window = self.params['lookback_window']
        if len(hist) > window:
            hist = hist.iloc[-window:].copy().reset_index(drop=True)

        if current_atr <= 0 or np.isnan(current_atr):
            current_atr = (hist['high'].max() - hist['low'].min()) * 0.01

        tolerance = max(
            self.params['level_atr_multiple'] * current_atr,
            hist['close'].iloc[-1] * self.params['fallback_tolerance_pct']
        )

        pivot_highs, high_indices = self._find_pivot_highs(hist)
        pivot_lows, low_indices = self._find_pivot_lows(hist)
        
        high_volumes = hist['volume'].values[high_indices] if len(high_indices) > 0 else np.array([])
        low_volumes = hist['volume'].values[low_indices] if len(low_indices) > 0 else np.array([])
        
        hist_start_idx = current_idx - len(hist)

        high_clusters = self._cluster_levels(pivot_highs, high_indices, high_volumes, tolerance, hist_start_idx)
        low_clusters = self._cluster_levels(pivot_lows, low_indices, low_volumes, tolerance, hist_start_idx)

        support_levels, resistance_levels = self._process_clusters(
            hist, high_clusters, low_clusters, current_idx, current_atr, tolerance, strict=True
        )

        if not support_levels or not resistance_levels:
            sup_relax, res_relax = self._process_clusters(
                hist, high_clusters, low_clusters, current_idx, current_atr, tolerance, strict=False
            )
            if not support_levels: support_levels = sup_relax
            if not resistance_levels: resistance_levels = res_relax

        if not support_levels:
            support_levels = self._raw_pivot_fallback(pivot_lows, low_volumes, hist_start_idx, current_idx, 'support')
        if not resistance_levels:
            resistance_levels = self._raw_pivot_fallback(pivot_highs, high_volumes, hist_start_idx, current_idx, 'resistance')

        if not support_levels:
            support_levels = self._extreme_fallback(hist, 'low')
        if not resistance_levels:
            resistance_levels = self._extreme_fallback(hist, 'high')

        # Sort by strength
        support_levels.sort(key=lambda x: x['score'], reverse=True)
        resistance_levels.sort(key=lambda x: x['score'], reverse=True)

        # Filter and merge nearby levels
        current_price = float(hist['close'].iloc[-1])
        max_dist = self.params['max_distance_pct']
        min_score = self.params['min_score_threshold']
        min_distance = self.params['min_level_distance_pct']

        def filter_and_merge(levels, is_support):
            result = []
            for lvl in levels:
                price = lvl['price']
                
                # Directional filter
                if is_support and price > current_price * 1.02: continue
                if not is_support and price < current_price * 0.98: continue
                
                # Distance filter
                if abs(price - current_price) / current_price > max_dist: continue
                
                # Score filter
                if lvl['score'] < min_score: continue
                
                # Calculate zone thickness based on score and volume
                # Higher score = thicker zone
                base_thickness = 0.3  # Base thickness %
                score_bonus = min(lvl['score'] * 0.1, 1.0)  # Up to 1% bonus
                zone_thickness_pct = base_thickness + score_bonus
                
                zone_data = {
                    'price': float(price),
                    'score': float(lvl['score']),
                    'touches': int(lvl['touches']),
                    'avg_volume': float(lvl['avg_volume']),
                    'zone_thickness_pct': zone_thickness_pct
                }
                
                # Merge if too close to existing level
                is_too_close = False
                for existing in result:
                    if abs(price - existing['price']) / existing['price'] < min_distance:
                        # Merge: keep the one with higher score
                        if lvl['score'] > existing['score']:
                            result.remove(existing)
                            result.append(zone_data)
                        is_too_close = True
                        break
                
                if not is_too_close:
                    result.append(zone_data)
            
            return result

        good_supports = filter_and_merge(support_levels, True)
        good_resistances = filter_and_merge(resistance_levels, False)

        # Guarantee non-empty
        if not good_supports and support_levels:
            good_supports = [{
                'price': float(support_levels[0]['price']),
                'score': float(support_levels[0]['score']),
                'touches': int(support_levels[0]['touches']),
                'avg_volume': float(support_levels[0]['avg_volume']),
                'zone_thickness_pct': 0.5
            }]
            
        if not good_resistances and resistance_levels:
            good_resistances = [{
                'price': float(resistance_levels[0]['price']),
                'score': float(resistance_levels[0]['score']),
                'touches': int(resistance_levels[0]['touches']),
                'avg_volume': float(resistance_levels[0]['avg_volume']),
                'zone_thickness_pct': 0.5
            }]

        # Sort
        good_supports.sort(key=lambda x: x['price'], reverse=True)
        good_resistances.sort(key=lambda x: x['price'])

        return good_supports[:self.params['num_levels']], good_resistances[:self.params['num_levels']]

    # ------------------------------------------------------------------ #
    #  Internal Helper Methods
    # ------------------------------------------------------------------ #

    def _raw_pivot_fallback(self, pivots: np.ndarray, volumes: np.ndarray, 
                            hist_start_idx: int, current_idx: int, role: str) -> List[dict]:
        if len(pivots) == 0: return []
        p_slice = pivots[-3:] if len(pivots) > 3 else pivots
        v_slice = volumes[-3:] if len(volumes) > 3 else volumes
        return [{'price': float(p), 'score': 1.0, 'touches': 1, 'last_idx': current_idx - 1, 'role': role, 'avg_volume': float(v)} for p, v in zip(p_slice, v_slice)]

    def _extreme_fallback(self, hist: pd.DataFrame, col: str) -> List[dict]:
        if len(hist) == 0: return []
        recent = hist.tail(20)
        avg_vol = float(hist['volume'].mean())
        role = 'support' if col == 'low' else 'resistance'
        return [
            {'price': float(recent[col].min()), 'score': 1.0, 'touches': 1, 'last_idx': len(hist)-1, 'role': role, 'avg_volume': avg_vol},
            {'price': float(recent[col].quantile(0.10)), 'score': 0.8, 'touches': 1, 'last_idx': len(hist)-1, 'role': role, 'avg_volume': avg_vol},
            {'price': float(hist[col].min()), 'score': 0.5, 'touches': 1, 'last_idx': len(hist)-1, 'role': role, 'avg_volume': avg_vol},
        ]

    def _find_pivot_highs(self, hist: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        high = hist['high']
        w = self.params['pivot_window']
        is_peak = pd.Series(True, index=hist.index)
        for i in range(1, w + 1):
            is_peak &= (high > high.shift(i)) & (high > high.shift(-i))
        is_peak = is_peak.fillna(False).values
        indices = np.where(is_peak)[0]
        return high.values[indices], indices

    def _find_pivot_lows(self, hist: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        low = hist['low']
        w = self.params['pivot_window']
        is_trough = pd.Series(True, index=hist.index)
        for i in range(1, w + 1):
            is_trough &= (low < low.shift(i)) & (low < low.shift(-i))
        is_trough = is_trough.fillna(False).values
        indices = np.where(is_trough)[0]
        return low.values[indices], indices

    def _cluster_levels(self, prices: np.ndarray, indices: np.ndarray, volumes: np.ndarray,
                        tolerance: float, hist_start_idx: int) -> List[Dict[str, Any]]:
        if len(prices) == 0: return []
        order = np.argsort(prices)
        prices, indices, volumes = prices[order], indices[order], volumes[order]

        clusters = []
        curr_prices, curr_indices, curr_volumes = [prices[0]], [indices[0]], [volumes[0]]

        for p, idx, v in zip(prices[1:], indices[1:], volumes[1:]):
            if abs(p - np.mean(curr_prices)) <= tolerance:
                curr_prices.append(p)
                curr_indices.append(idx)
                curr_volumes.append(v)
            else:
                clusters.append(self._make_cluster(curr_prices, curr_indices, curr_volumes, hist_start_idx))
                curr_prices, curr_indices, curr_volumes = [p], [idx], [v]

        clusters.append(self._make_cluster(curr_prices, curr_indices, curr_volumes, hist_start_idx))
        return clusters

    def _make_cluster(self, prices, indices, volumes, hist_start_idx):
        return {
            'price': float(np.mean(prices)), 'count': len(prices),
            'avg_volume': float(np.mean(volumes)), 'total_volume': float(np.sum(volumes)),
            'last_idx': hist_start_idx + max(indices),
            'indices': [hist_start_idx + i for i in indices],
        }

    def _classify_role(self, hist: pd.DataFrame, price: float, atr: float, 
                       tolerance_mult: float, cluster_indices: List[int]) -> str:
        tol = atr * tolerance_mult
        first_idx = min(cluster_indices) if cluster_indices else 0
        relevant = hist.loc[hist.index >= first_idx]
        if relevant.empty: return 'neutral'
            
        near_support = (relevant['low'] <= price + tol) & (relevant['low'] >= price - tol) & (relevant['close'] > price)
        near_resistance = (relevant['high'] <= price + tol) & (relevant['high'] >= price - tol) & (relevant['close'] < price)
        
        if near_support.sum() > near_resistance.sum(): return 'support'
        if near_resistance.sum() > near_support.sum(): return 'resistance'
        return 'neutral'

    def _is_broken(self, hist: pd.DataFrame, price: float, role: str, 
                   atr: float, tolerance_mult: float, last_idx: int) -> bool:
        if hist.empty: return False
        tol = atr * tolerance_mult
        level_hist = hist.loc[hist.index >= last_idx]
        if level_hist.empty: return False
        recent = level_hist.tail(self.params['broken_level_cooldown'])
        if recent.empty: return False
        
        if role == 'support': return (recent['close'] < (price - tol)).any()
        if role == 'resistance': return (recent['close'] > (price + tol)).any()
        return False

    def _process_clusters(self, hist: pd.DataFrame, high_clusters: List[Dict], low_clusters: List[Dict],
                          current_idx: int, atr: float, tolerance: float, strict: bool = True) -> Tuple[List[dict], List[dict]]:
        
        support_levels, resistance_levels = [], []
        min_touch = self.params['min_touch_count'] if strict else 1
        median_vol = max(hist['volume'].median(), 1.0)
        
        for cluster, origin in [(c, 'high') for c in high_clusters] + [(c, 'low') for c in low_clusters]:
            price, count, last_idx, indices = cluster['price'], cluster['count'], cluster['last_idx'], cluster['indices']

            if (current_idx - last_idx) > self.params['max_age_candles'] or count < min_touch:
                continue

            role = self._classify_role(hist, price, atr, self.params['level_atr_multiple'], indices)
            if role == 'neutral': role = 'resistance' if origin == 'high' else 'support'

            if self._is_broken(hist, price, role, atr, self.params['level_atr_multiple'], last_idx):
                continue

            vol_factor = cluster['avg_volume'] / median_vol
            score = count * (1 + np.log1p(max(0, vol_factor - 1)))
            
            level = {'price': price, 'score': score, 'touches': count, 'last_idx': last_idx, 'role': role, 'avg_volume': cluster['avg_volume']}
            (support_levels if role == 'support' else resistance_levels).append(level)

        return support_levels, resistance_levels


# ==================================================================== #
#  TEST RUNNER & VISUALIZATION WITH ZONES
# ==================================================================== #
if __name__ == "__main__":
    import random
    import matplotlib.pyplot as plt

    def make_random_stock(seed: int, n: int = 500) -> pd.DataFrame:
        #np.random.seed(seed)
        returns = np.random.normal(0.0005, 0.015, n)
        close = 100 * np.exp(np.cumsum(returns))
        noise = np.random.uniform(0.005, 0.015, n)
        base_vol = np.random.randint(1_000_000, 5_000_000, n)
        spikes = np.random.choice([1, 5, 10], p=[0.8, 0.15, 0.05], size=n)
        return pd.DataFrame({
            'open': close * (1 - np.random.uniform(0, 0.005, n)),
            'high': close * (1 + noise), 'low': close * (1 - noise),
            'close': close, 'volume': base_vol * spikes,
        })

    calc = SupportResistanceCalculator()

    print("Testing 20 random synthetic stocks …\n")
    failures = 0
    for seed in range(20):
        df = make_random_stock(seed, n=random.randint(50, 500))
        hl = df['high'] - df['low']
        tr = pd.concat([hl, (df['high'] - df['close'].shift()).abs(), (df['low'] - df['close'].shift()).abs()], axis=1).max(axis=1)
        atr = tr.ewm(span=14, adjust=False).mean().iloc[-1]
        if pd.isna(atr) or atr <= 0: atr = (df['high'].max() - df['low'].min()) * 0.01

        support, resistance = calc.calculate(df, current_idx=len(df), current_atr=atr)
        
        assert isinstance(support, list) and all(isinstance(x, float) for x in support)
        assert isinstance(resistance, list) and all(isinstance(x, float) for x in resistance)

        ok = len(support) > 0 and len(resistance) > 0
        print(f"{'✅' if ok else '❌'} Seed {seed:2d} | n={len(df):3d} | Sup:{len(support)} Res:{len(resistance)}")
        if not ok: failures += 1

    print(f"\n{'='*50}\nResults: {20 - failures}/20 passed\n")

    # ==================================================================== #
    #  VISUALIZATION WITH ZONES
    # ==================================================================== #
    print("Generating visualization with zones for a sample stock...")
    vis_seed = 5
    df_vis = make_random_stock(vis_seed, n=300)
    hl_vis = df_vis['high'] - df_vis['low']
    tr_vis = pd.concat([hl_vis, (df_vis['high'] - df_vis['close'].shift()).abs(), (df_vis['low'] - df_vis['close'].shift()).abs()], axis=1).max(axis=1)
    atr_vis = tr_vis.ewm(span=14, adjust=False).mean().iloc[-1]
    
    # Use calculate_with_zones to get zone thickness data
    sup_zones, res_zones = calc.calculate_with_zones(df_vis, current_idx=len(df_vis), current_atr=atr_vis)
    
    fig, ax = plt.subplots(figsize=(14, 7))
    ax.plot(df_vis.index, df_vis['close'], label='Close Price', color='#1f77b4', linewidth=1.5, zorder=5)
    ax.fill_between(df_vis.index, df_vis['low'], df_vis['high'], color='#1f77b4', alpha=0.15, label='High-Low Range', zorder=1)
    
    # Plot Support ZONES (shaded areas)
    for i, zone in enumerate(sup_zones):
        price = zone['price']
        thickness_pct = zone['zone_thickness_pct']
        zone_lower = price * (1 - thickness_pct / 2 / 100)
        zone_upper = price * (1 + thickness_pct / 2 / 100)
        
        # Alpha based on score (stronger = more opaque)
        alpha = min(0.3 + zone['score'] * 0.05, 0.7)
        
        lbl = 'Support Zones' if i == 0 else None
        ax.axhspan(zone_lower, zone_upper, color='green', alpha=alpha, linewidth=0, label=lbl, zorder=2)
        ax.axhline(price, color='darkgreen', linestyle='-', linewidth=1, alpha=0.8, zorder=3)
        ax.text(len(df_vis) - 1, price, f' S: {price:.2f} (T:{zone["touches"]}) ', color='darkgreen', 
                va='center', ha='right', fontsize=9, fontweight='bold',
                bbox=dict(boxstyle='round,pad=0.2', fc='white', ec='darkgreen', alpha=0.8), zorder=4)
        
    # Plot Resistance ZONES
    for i, zone in enumerate(res_zones):
        price = zone['price']
        thickness_pct = zone['zone_thickness_pct']
        zone_lower = price * (1 - thickness_pct / 2 / 100)
        zone_upper = price * (1 + thickness_pct / 2 / 100)
        
        alpha = min(0.3 + zone['score'] * 0.05, 0.7)
        
        lbl = 'Resistance Zones' if i == 0 else None
        ax.axhspan(zone_lower, zone_upper, color='red', alpha=alpha, linewidth=0, label=lbl, zorder=2)
        ax.axhline(price, color='darkred', linestyle='-', linewidth=1, alpha=0.8, zorder=3)
        ax.text(len(df_vis) - 1, price, f' R: {price:.2f} (T:{zone["touches"]}) ', color='darkred', 
                va='center', ha='right', fontsize=9, fontweight='bold',
                bbox=dict(boxstyle='round,pad=0.2', fc='white', ec='darkred', alpha=0.8), zorder=4)
        
    ax.set_title(f'Support & Resistance ZONES (Seed {vis_seed}) - Thickness based on importance', fontsize=14)
    ax.set_xlabel('Time (Candle Index)', fontsize=12)
    ax.set_ylabel('Price', fontsize=12)
    ax.legend(loc='upper left', fontsize=10)
    ax.grid(True, linestyle=':', alpha=0.6)
    
    plt.tight_layout()
    plt.show()