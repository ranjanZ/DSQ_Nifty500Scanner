"""
Moving Average Crossover Strategy
Buy when fast MA crosses above slow MA
Sell when fast MA crosses below slow MA
"""

import pandas as pd
import numpy as np
from typing import Dict, Any
from pathlib import Path
import sys

# Set up path for imports
_file = Path(__file__).resolve()
_src_dir = _file.parent.parent.parent.parent
if _src_dir.name == "src" and str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

from strategy_service.strategy_base import TradingStrategy
from strategy_service.utils.chart_plotter import StrategyChartPlotter


class MovingAverageCrossoverStrategy(TradingStrategy):
    """
    Moving Average Crossover Strategy
    """
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'fast_period': 20,
            'slow_period': 50,
            'use_volume_confirmation': False,
            'volume_threshold': 1.2
        }
        
        if params:
            default_params.update(params)
            
        super().__init__(name="MA_Crossover_Strategy", params=default_params)
        
    def calculate_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        """Calculate moving averages and additional indicators"""
        df = data.copy()
        
        # Calculate moving averages
        df['sma_fast'] = self.calculate_sma(df['close'], self.params['fast_period'])
        df['sma_slow'] = self.calculate_sma(df['close'], self.params['slow_period'])
        
        # Volume confirmation if enabled
        if self.params['use_volume_confirmation']:
            df['volume_sma'] = self.calculate_sma(df['volume'], 20)
            df['volume_ratio'] = df['volume'] / df['volume_sma']
            
        return df
    
    def generate_signals(self, data: pd.DataFrame, num_back_signals: int = None) -> pd.DataFrame:
        """
        Generate signals based on MA crossover
        Returns: DataFrame with 'signal' column (-1, 0, 1)
        """
        self.validate_data(data)
        df = self.calculate_indicators(data)
        
        # Initialize signals
        df['signal'] = 0
        
        # Determine start index
        min_history = max(self.params['fast_period'], self.params['slow_period']) + 5
        start_idx = min_history
        
        if num_back_signals is not None and len(df) > num_back_signals:
            start_idx = max(min_history, len(df) - num_back_signals)
        
        # Generate crossover signals
        for i in range(start_idx, len(df)):
            # Current and previous values
            fast_curr = df['sma_fast'].iloc[i]
            slow_curr = df['sma_slow'].iloc[i]
            fast_prev = df['sma_fast'].iloc[i-1]
            slow_prev = df['sma_slow'].iloc[i-1]
            
            # Check for crossover
            buy_signal = (fast_curr > slow_curr) and (fast_prev <= slow_prev)
            sell_signal = (fast_curr < slow_curr) and (fast_prev >= slow_prev)
            
            # Apply volume confirmation if enabled
            if self.params['use_volume_confirmation'] and 'volume_ratio' in df.columns:
                volume_ok = df['volume_ratio'].iloc[i] > self.params['volume_threshold']
                buy_signal = buy_signal and volume_ok
                sell_signal = sell_signal and volume_ok
            
            if buy_signal:
                df.loc[df.index[i], 'signal'] = 1
            elif sell_signal:
                df.loc[df.index[i], 'signal'] = -1
        
        return df
    
    def plot_signals(self, data_with_signals: pd.DataFrame, output_dir: str = "data/outputs/strategy_plots"):
        """Generate and save strategy plot."""
        import os
        from datetime import datetime
        
        # Create output directory
        os.makedirs(output_dir, exist_ok=True)
        
        # Initialize plotter
        plotter = StrategyChartPlotter(plot_dir=output_dir)
        
        # Define indicators to plot (SMA fast and slow)
        indicators = []
        if 'sma_fast' in data_with_signals.columns:
            indicators.append({
                "column": "sma_fast",
                "label": f"SMA Fast ({self.params['fast_period']})",
                "color": "#58a6ff",
                "line_style": "-",
                "line_width": 1.5
            })
        if 'sma_slow' in data_with_signals.columns and len(indicators) < 2:
            indicators.append({
                "column": "sma_slow",
                "label": f"SMA Slow ({self.params['slow_period']})",
                "color": "#f0883e",
                "line_style": "--",
                "line_width": 1.5
            })
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"crossover_strategy_{timestamp}.png"
        
        # Plot and save
        plotter.plot(
            df=data_with_signals,
            strategy_name="MA Crossover Strategy",
            indicators=indicators,
            filename=filename
        )


# ==================================================================== #
#  TEST RUNNER
# ==================================================================== #
if __name__ == "__main__":
    import yaml
    from datetime import datetime, timedelta
    
    # Load config
    config_path = Path(__file__).parent / "config.yaml"
    params = {}
    if config_path.exists():
        with open(config_path, "r") as f:
            cfg = yaml.safe_load(f)
            params = cfg.get("params", {})
    
    # Create sample data
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
    
    print(f"📊 Testing MovingAverageCrossoverStrategy with {len(data)} candles")
    print("=" * 60)
    
    # Initialize strategy with custom parameters
    strategy_params = {
        'fast_period': 10,
        'slow_period': 30,
        'use_volume_confirmation': True,
        'volume_threshold': 1.5
    }
    strategy_params.update(params)
    strategy = MovingAverageCrossoverStrategy(params=strategy_params)
    
    print(f"✅ Strategy initialized: {strategy.name}")
    print(f"   Parameters: {strategy.params}")
    
    # Generate signals
    signals_df = strategy.generate_signals(data, num_back_signals=100)
    
    # Display results
    buy_signals = signals_df[signals_df['signal'] == 1]
    sell_signals = signals_df[signals_df['signal'] == -1]
    
    print(f"\n📈 Generated {len(buy_signals)} BUY signals")
    print(f"📉 Generated {len(sell_signals)} SELL signals")
    
    if not buy_signals.empty:
        print("\nLast 5 BUY signals:")
        cols_to_show = ['date', 'close', 'sma_fast', 'sma_slow']
        available_cols = [c for c in cols_to_show if c in buy_signals.columns]
        print(buy_signals[available_cols].tail().to_string(index=False))
    
    # Generate and save plot
    print("\n📊 Generating plot...")
    strategy.plot_signals(signals_df, output_dir="data/outputs/strategy_plots")
    
    print("\n" + "=" * 60)
    print("✅ MovingAverageCrossoverStrategy test completed!")
