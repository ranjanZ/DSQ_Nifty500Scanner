"""
volume_support_resistance_strategy.py
=====================================
Buy signals generated when price bounces from a support ZONE
with volume confirmation. Uses utils/support_resistance.py for
level/zone detection.
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, List, Tuple, Optional
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
    Now utilizes Support/Resistance ZONES for more realistic bounce detection.
    """

    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'volume_ema_period': 20,
            'volume_threshold': 1.3,
            'lookback_window': 300,
            'pivot_window': 2,
            'min_touch_count': 2,
            'level_atr_multiple': 2,
            'num_levels': 5,
            'max_age_candles': 100,
            'broken_level_cooldown': 20,
            'min_history_candles': 10,
            'max_candle_size_atr': 2.0,
            # --- NEW OPTIMIZATION PARAM ---
            'calc_every_n_candles': 5,  # Calculate S/R every N candles to save computation
        }

        if params:
            default_params.update(params)

        self.params = default_params
        self.name = "VolumeSupportResistance"
        
        # Pass only the relevant params to the S/R calculator
        sr_params = {k: v for k, v in self.params.items() if k != 'calc_every_n_candles'}
        self.sr_calc = SupportResistanceCalculator(sr_params)

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

        # Support / Resistance ZONES
        support_zones_list = []
        resistance_zones_list = []
        
        # Optimization: Calculate S/R every N candles to speed up the loop
        calc_every = self.params['calc_every_n_candles']
        min_hist = self.params['min_history_candles']
        
        last_sup_zones = []
        last_res_zones = []

        for i in range(len(df)):
            if i >= min_hist:
                # Only recalculate every N candles
                if i % calc_every == 0:
                    atr = df['atr'].iloc[i] if pd.notna(df['atr'].iloc[i]) else 0.0
                    last_sup_zones, last_res_zones = self.sr_calc.calculate_with_zones(df, i, atr)
                
                # Append references (much faster than deep copying)
                support_zones_list.append(last_sup_zones)
                resistance_zones_list.append(last_res_zones)
            else:
                support_zones_list.append([])
                resistance_zones_list.append([])

        df['support_zones'] = support_zones_list
        df['resistance_zones'] = resistance_zones_list
        
        # Extract just the prices for backward compatibility / simple checks
        df['support_levels'] = [[z['price'] for z in zones] for zones in support_zones_list]
        df['resistance_levels'] = [[z['price'] for z in zones] for zones in resistance_zones_list]
        
        df['num_support'] = df['support_levels'].apply(len)
        df['num_resistance'] = df['resistance_levels'].apply(len)

        return df

    # ------------------------------------------------------------------ #
    #  Signal Logic
    # ------------------------------------------------------------------ #

    def is_at_support_zone(self, candle: pd.Series, support_zones: List[dict], atr: float) -> Tuple[bool, Optional[float], Optional[float]]:
        """
        Check if price is testing a support ZONE.
        Returns: (is_bouncing, zone_center_price, zone_upper_bound)
        """
        if not support_zones or atr <= 0 or pd.isna(atr):
            return False, None, None

        for zone in support_zones:
            price = zone['price']
            thickness_pct = zone['zone_thickness_pct']
            
            # Calculate zone boundaries
            zone_upper = price * (1 + thickness_pct / 50.0)
            zone_lower = price * (1 - thickness_pct/50.0)
            

            if zone_lower <= candle['close'] <= zone_upper:
                return True, price, zone_upper

        return False, None, None

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

            # Use the new zone-based support check
            is_at_sup, sup_level, zone_upper = self.is_at_support_zone(
                current_candle, current_candle['support_zones'], atr
            )
            
            if not is_at_sup:
                continue

            # Filter out candles that are too extended (e.g. massive news candles)
            candle_atr_ratio = current_candle['candle_size'] / atr if atr > 0 else 999
            if candle_atr_ratio > self.params['max_candle_size_atr']:
                continue

            # Support bounce conditions
            c1 = current_candle['is_green']                              # Bullish close
            c2 = current_candle['volume'] > (volume_threshold * current_candle['volume_ema']) # Volume spike
            
            # Additional candle shape conditions
            c3 = current_candle['body_size'] > 0.5 * current_candle['candle_size'] # Solid body
            
            # A bounce usually has a noticeable lower wick showing rejection. 
            # Reward rejection wicks instead of penalizing them.
            c4_rejection = current_candle['lower_wick'] >= 0.2 * current_candle['candle_size']

            if c1 and c2:
                df.loc[df.index[i], 'signal'] = 1

                strength = 0.5
                if c3:
                    strength += 0.2
                if c4_rejection:
                    strength += 0.3
                    
                df.loc[df.index[i], 'signal_strength'] = min(strength, 1.0)
                df.loc[df.index[i], 'signal_support'] = sup_level
                df.loc[df.index[i], 'volume_ratio'] = current_candle['volume'] / current_candle['volume_ema']

        return df


# ==================================================================== #
#  TEST RUNNER
# ==================================================================== #
if __name__ == "__main__":
    import yaml
    from datetime import datetime, timedelta
    
    # Adjust path if running directly - walk up to src/
    _file = Path(__file__).resolve()
    _src_dir = _file.parent.parent.parent.parent
    if _src_dir.name == "src" and str(_src_dir) not in sys.path:
        sys.path.insert(0, str(_src_dir))
    
    try:
        from data_service.data_service import get_table_content
    except ImportError as e:
        print(f"Warning: Could not import data_service: {e}")
        print("Using synthetic data for testing...")
        get_table_content = None

    config_path = Path(__file__).parent / "config.yaml"
    
    # Handle missing config gracefully
    params = {}
    if config_path.exists():
        with open(config_path, "r") as f:
            cfg = yaml.safe_load(f)
            params = cfg.get("params", {})
    else:
        print(f"Warning: Config file not found at {config_path}. Using default params.")

    data = None
    if get_table_content:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=200)
        
        # Note: Ensure 'axisbank_eq' and DB credentials are correctly configured in your data_service
        try:
            data = get_table_content(
                db_name="spot_db_anamika",
                table_name="axisbank_eq",
                start_date=start_date,
                end_date=end_date,
            )
        except Exception as e:
            print(f"Database error: {e}")
            print("Falling back to synthetic data...")
    
    # Generate synthetic data if database failed
    if data is None or data.empty:
        print("Generating synthetic test data...")
        dates = pd.date_range(end=datetime.now(), periods=200, freq='D')
        np.random.seed(42)
        base_price = 1000
        prices = [base_price]
        for i in range(1, 200):
            change = np.random.randn() * 15
            prices.append(prices[-1] + change)
        
        data = pd.DataFrame({
            'date': dates,
            'open': prices,
            'high': [p + abs(np.random.randn() * 8) for p in prices],
            'low': [p - abs(np.random.randn() * 8) for p in prices],
            'close': prices,
            'volume': np.random.randint(10000, 100000, 200)
        })

    strategy = VolumeSupportResistanceStrategy(params=params)
    signals_df = strategy.generate_signals(data, num_back_signals=100)
    
    # Display results
    buy_signals = signals_df[signals_df['signal'] == 1]
    print(f"\n📊 Testing VolumeSupportResistanceStrategy with {len(data)} candles")
    print("=" * 60)
    print(f"✅ Strategy initialized: {strategy.name}")
    print(f"   Parameters: {strategy.params}")
    print(f"\n📈 Generated {len(buy_signals)} buy signals in the last 100 candles.")
    if not buy_signals.empty:
        # Print relevant columns for the signals
        cols_to_show = ['date', 'close', 'volume', 'signal_strength']
        available_cols = [c for c in cols_to_show if c in buy_signals.columns]
        print("\nLast 5 Buy Signals:")
        print(buy_signals[available_cols].tail().to_string(index=False))
    
    print("\n" + "=" * 60)
    print("✅ VolumeSupportResistanceStrategy test completed!")