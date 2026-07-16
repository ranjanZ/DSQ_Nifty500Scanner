from typing import Dict, Any
import pandas as pd
from ...strategy_base import TradingStrategy
import numpy as np

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
    
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Generate signals based on MA crossover
        Returns: DataFrame with 'signal' column (-1, 0, 1)
        """
        self.validate_data(data)
        df = self.calculate_indicators(data)
        
        # Initialize signals
        df['signal'] = 0
        
        # Generate crossover signals
        buy_signals = (df['sma_fast'] > df['sma_slow']) & (df['sma_fast'].shift(1) <= df['sma_slow'].shift(1))
        sell_signals = (df['sma_fast'] < df['sma_slow']) & (df['sma_fast'].shift(1) >= df['sma_slow'].shift(1))
        
        # Apply volume confirmation if enabled
        if self.params['use_volume_confirmation']:
            volume_condition = df['volume_ratio'] > self.params['volume_threshold']
            buy_signals = buy_signals & volume_condition
            sell_signals = sell_signals & volume_condition
        
        df.loc[buy_signals, 'signal'] = 1   # Buy signal
        df.loc[sell_signals, 'signal'] = -1 # Sell signal
        
        return df



if __name__ == "__main__":
    
    def create_sample_data():
        dates = pd.date_range(start='2023-01-01', end='2023-12-31', freq='D')
        np.random.seed(42)
        price = 100 + np.cumsum(np.random.randn(len(dates)) * 0.5)
        data = pd.DataFrame({
            'time': dates,
            'open': price + np.random.randn(len(dates)) * 0.2,
            'high': price + 0.5 + np.random.randn(len(dates)) * 0.2,
            'low': price - 0.5 + np.random.randn(len(dates)) * 0.2,
            'close': price,
            'volume': np.random.randint(1000, 10000, len(dates))
        })
        return data

    df= create_sample_data()



    # Initialize strategy with custom parameters
    strategy_params = {
        'fast_period': 10,
        'slow_period': 30,
        'use_volume_confirmation': True,
        'volume_threshold': 1.5
    }
    strategy = MovingAverageCrossoverStrategy(params=strategy_params)
    
    # Generate signals
    signals_df = strategy.generate_signals(df)
    
    print(signals_df[['time', 'close', 'sma_fast', 'sma_slow', 'signal']].tail(20))