"""
Random Strategy for Backtesting
Generates random buy signals based on probability threshold
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional
from strategy_service.strategy_base import TradingStrategy


class RandomStrategy(TradingStrategy):
    """
    A simple random strategy that generates buy signals based on:
    1. Random probability threshold
    2. Volume above average (optional filter)
    
    This is useful for testing the backtesting engine infrastructure.
    """
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'signal_probability': 0.05,  # 5% chance of signal
            'use_volume_filter': True,
            'volume_threshold': 1.5,  # 1.5x average volume
            'lookback_window': 20,  # For volume average
            'seed': 42,  # For reproducibility
        }
        
        if params:
            default_params.update(params)
        
        self.params = default_params
        self.name = "RandomStrategy"
        
        # Set random seed for reproducibility
        np.random.seed(self.params['seed'])
    
    def calculate_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        """Calculate required indicators."""
        df = data.copy()
        
        # Calculate average volume for filtering
        if self.params.get('use_volume_filter', True) and 'volume' in df.columns:
            lookback = self.params.get('lookback_window', 20)
            df['avg_volume'] = df['volume'].rolling(window=lookback).mean()
            df['volume_ratio'] = df['volume'] / df['avg_volume']
        
        return df
    
    def generate_signals(self, data: pd.DataFrame, num_back_signals: int = None) -> pd.DataFrame:
        """
        Generate random buy signals for each stock.
        
        Args:
            data: DataFrame with OHLCV data
            num_back_signals: Number of signals to generate from the end (optional)
            
        Returns:
            DataFrame with added 'signal' column (1 for buy, 0 for no action)
        """
        df = self.calculate_indicators(data)
        
        # Initialize signal columns
        df['signal'] = 0
        df['signal_strength'] = 0.0
        
        # Determine start index for signal generation
        min_history = self.params.get('lookback_window', 20) + 10
        start_idx = max(min_history, 0)
        
        if num_back_signals is not None and len(df) > num_back_signals:
            start_idx = max(start_idx, len(df) - num_back_signals)
        
        # Generate random signals
        signal_prob = self.params.get('signal_probability', 0.05)
        
        for i in range(start_idx, len(df)):
            # Base random signal
            is_signal = np.random.random() < signal_prob
            
            # Apply volume filter if enabled
            if self.params.get('use_volume_filter', True) and 'volume_ratio' in df.columns:
                vol_threshold = self.params.get('volume_threshold', 1.5)
                volume_ok = df.iloc[i]['volume_ratio'] > vol_threshold if pd.notna(df.iloc[i]['volume_ratio']) else False
                
                # Either pure random (lower prob) or random + volume condition
                if np.random.random() < (signal_prob / 3):
                    is_signal = True  # Pure random signal
                else:
                    is_signal = is_signal and volume_ok
            
            if is_signal:
                df.loc[df.index[i], 'signal'] = 1
                df.loc[df.index[i], 'signal_strength'] = np.random.random() * 0.5 + 0.5  # 0.5-1.0
        
        return df
    
    def get_required_columns(self) -> List[str]:
        """Return required columns for this strategy."""
        cols = ['date', 'open', 'high', 'low', 'close']
        if self.params.get('use_volume_filter', True):
            cols.append('volume')
        return cols
    
    def get_minimum_history(self) -> int:
        """Return minimum history required for this strategy."""
        return self.params.get('lookback_window', 20) + 10
