"""
RSI W-Pattern Strategy
Buy signal when RSI crosses above the middle peak of W pattern
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, List
from pathlib import Path
import sys

# Set up path for imports
_file = Path(__file__).resolve()
_src_dir = _file.parent.parent.parent.parent
if _src_dir.name == "src" and str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

from strategy_service.strategy_base import TradingStrategy
from strategy_service.utils.chart_plotter import StrategyChartPlotter


class RSIWPatternStrategy(TradingStrategy):
    """
    RSI W-Pattern Strategy
    Buy signal when RSI crosses above the middle peak of W pattern
    """
    
    def __init__(self, params: Dict[str, Any] = None):
        # Default parameters
        default_params = {
            'rsi_period': 14,
            'oversold': 30,
            'overbought': 70,
            'min_improvement': 1.5,      # Min RSI improvement between bottoms
            'lookback_period': 30,       # How far back to look for pattern
            'tolerance_pct': 0.05,       # Tolerance for matching peaks/bottoms
        }
        
        if params:
            default_params.update(params)
        
        super().__init__(name="RSI_W_Pattern", params=default_params)
    
    def calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """Calculate RSI"""
        delta = prices.diff()
        gain = delta.where(delta > 0, 0).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))
    
    def find_pattern_points(self, rsi_values: pd.Series) -> Dict[str, Any]:
        """
        Find W pattern points in RSI:
        - First bottom (B1)
        - Middle peak (P)
        - Second bottom (B2)
        Returns positions and values
        """
        values = rsi_values.values
        n = len(values)
        
        if n < 10:
            return {'found': False, 'reason': 'Not enough data'}
        
        # Find local minima (bottoms) and maxima (peaks)
        bottoms = []
        peaks = []
        
        for i in range(2, n - 2):
            # Local minima (bottom)
            if (values[i] < values[i-1] and values[i] < values[i-2] and
                values[i] < values[i+1] and values[i] < values[i+2]):
                bottoms.append({'idx': i, 'value': values[i]})
            
            # Local maxima (peak)
            if (values[i] > values[i-1] and values[i] > values[i-2] and
                values[i] > values[i+1] and values[i] > values[i+2]):
                peaks.append({'idx': i, 'value': values[i]})
        
        if len(bottoms) < 2 or len(peaks) < 1:
            return {'found': False, 'reason': 'Not enough pattern points'}
        
        # Sort by index
        bottoms.sort(key=lambda x: x['idx'])
        peaks.sort(key=lambda x: x['idx'])
        
        # Find W pattern: Bottom-Peak-Bottom
        for i in range(len(bottoms) - 1):
            b1 = bottoms[i]
            b2 = bottoms[i + 1]
            
            # Find peak between these two bottoms
            middle_peaks = [p for p in peaks if b1['idx'] < p['idx'] < b2['idx']]
            
            if not middle_peaks:
                continue
            
            # Take the highest peak in between
            middle_peak = max(middle_peaks, key=lambda x: x['value'])
            
            # W pattern conditions:
            # 1. Second bottom should be higher than first (bullish)
            if b2['value'] <= b1['value']:
                continue
            
            # 2. Minimum improvement
            improvement = b2['value'] - b1['value']
            if improvement < self.params['min_improvement']:
                continue
            
            # 3. Check if bottoms are reasonable (not too low)
            if b1['value'] < self.params['oversold'] or b2['value'] < self.params['oversold']:
                continue
            
            return {
                'found': True,
                'b1': b1,
                'b2': b2,
                'middle_peak': middle_peak,
                'improvement': improvement,
                'pattern_length': b2['idx'] - b1['idx']
            }
        
        return {'found': False, 'reason': 'No valid W pattern found'}
    
    def generate_signals(self, data: pd.DataFrame, num_back_signals: int = None) -> pd.DataFrame:
        """
        Generate signals when RSI crosses above the middle peak
        of a W pattern (completes the pattern)
        """
        df = data.copy()
        
        # Calculate RSI
        df['rsi'] = self.calculate_rsi(df['close'], self.params['rsi_period'])
        
        # Initialize signal columns
        df['signal'] = 0
        df['signal_strength'] = 0.0
        df['pattern_found'] = False
        
        # Skip early periods
        start_idx = max(self.params['rsi_period'] + 20, 30)
        
        if num_back_signals is not None and len(df) > num_back_signals:
            start_idx = max(start_idx, len(df) - num_back_signals)
        
        for i in range(start_idx, len(df)):
            # Get RSI history up to current point
            rsi_history = df['rsi'].iloc[:i+1]
            
            # Find W pattern
            pattern = self.find_pattern_points(rsi_history)
            
            if not pattern['found']:
                continue
            
            # Get pattern points
            middle_peak = pattern['middle_peak']
            b2 = pattern['b2']  # Second bottom
            
            # Current RSI position relative to pattern
            current_pos = i
            b2_pos = b2['idx']
            
            # We're past the second bottom
            if current_pos > b2_pos:
                # Get RSI values after second bottom
                idx_start = b2_pos + 1
                idx_end = current_pos
                
                # Check if RSI has crossed above the middle peak since second bottom
                crossed_above_peak = False
                for j in range(idx_start, idx_end + 1):
                    if j < len(rsi_history):
                        if rsi_history.iloc[j] > middle_peak['value']:
                            # This is where it first crossed
                            if j == current_pos:  # Current candle is the cross
                                crossed_above_peak = True
                                break
                
                # Generate signal if just crossed above middle peak
                if crossed_above_peak:
                    # Calculate signal strength based on pattern quality
                    improvement = pattern['improvement']
                    strength = min(1.0, improvement / 5)  # Normalize
                    
                    df.loc[df.index[i], 'signal'] = 1
                    df.loc[df.index[i], 'signal_strength'] = strength
                    df.loc[df.index[i], 'pattern_found'] = True
                    
                    # Store pattern details
                    df.loc[df.index[i], 'b1_value'] = pattern['b1']['value']
                    df.loc[df.index[i], 'b2_value'] = pattern['b2']['value']
                    df.loc[df.index[i], 'middle_peak'] = middle_peak['value']
                    df.loc[df.index[i], 'improvement'] = improvement
        
        return df
    
    def plot_signals(self, data_with_signals: pd.DataFrame, output_dir: str = "data/outputs/strategy_plots"):
        """Generate and save strategy plot."""
        import os
        from datetime import datetime
        
        # Create output directory
        os.makedirs(output_dir, exist_ok=True)
        
        # Initialize plotter
        plotter = StrategyChartPlotter(plot_dir=output_dir)
        
        # Define indicators to plot (RSI)
        indicators = []
        if 'rsi' in data_with_signals.columns:
            indicators.append({
                "column": "rsi",
                "label": f"RSI ({self.params['rsi_period']})",
                "color": "#58a6ff",
                "line_style": "-",
                "line_width": 1.5
            })
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"rsi_w_pattern_{timestamp}.png"
        
        # Plot and save
        plotter.plot(
            df=data_with_signals,
            strategy_name="RSI W-Pattern Strategy",
            indicators=indicators,
            filename=filename
        )


# ==================================================================== #
#  TEST RUNNER
# ==================================================================== #
if __name__ == "__main__":
    import yaml
    
    # Load config
    config_path = Path(__file__).parent / "config.yaml"
    params = {}
    if config_path.exists():
        with open(config_path, "r") as f:
            cfg = yaml.safe_load(f)
            params = cfg.get("params", {})
    
    # Create sample data
    dates = pd.date_range(start='2023-01-01', periods=200, freq='D')
    np.random.seed(42)
    
    base_price = 1000
    prices = [base_price]
    for i in range(1, 200):
        change = np.random.randn() * 10
        prices.append(prices[-1] + change)
    
    data = pd.DataFrame({
        'date': dates,
        'open': prices,
        'high': [p + abs(np.random.randn() * 5) for p in prices],
        'low': [p - abs(np.random.randn() * 5) for p in prices],
        'close': prices,
        'volume': np.random.randint(1000, 10000, 200)
    })
    
    print(f"📊 Testing RSIWPatternStrategy with {len(data)} candles")
    print("=" * 60)
    
    # Create strategy
    strategy_params = {
        'rsi_period': 14,
        'neckline': 50,
        'lookback_period': 40
    }
    strategy_params.update(params)
    strategy = RSIWPatternStrategy(params=strategy_params)
    
    print(f"✅ Strategy initialized: {strategy.name}")
    print(f"   Parameters: {strategy.params}")
    
    # Generate signals
    signals = strategy.generate_signals(data, num_back_signals=100)
    
    # Show summary
    buy_signals = signals[signals['signal'] == 1]
    print(f"\n📈 Total candles: {len(signals)}")
    print(f"✅ Buy signals: {len(buy_signals)}")
    
    if not buy_signals.empty:
        print("\n📋 Last 5 Buy Signals:")
        cols_to_show = ['date', 'close', 'rsi', 'signal_strength']
        available_cols = [c for c in cols_to_show if c in buy_signals.columns]
        print(buy_signals[available_cols].tail().to_string(index=False))
    
    # Generate and save plot
    print("\n📊 Generating plot...")
    strategy.plot_signals(signals, output_dir="data/outputs/strategy_plots")
    
    print("\n" + "=" * 60)
    print("✅ RSIWPatternStrategy test completed!")
