"""
Test module for RSI W-Pattern Strategy
Run with: python -m src.strategy_service.strategies.rsi_w_strategy test
"""

import sys
import os
from datetime import datetime, timedelta

def run_test():
    """Test the RSI W-Pattern Strategy"""
    print("Testing RSI W-Pattern Strategy")
    print("=" * 60)
    
    try:
        from src.strategy_service.strategies.rsi_w_strategy import RSIWPatternStrategy
        
        # Initialize strategy with default params
        strategy = RSIWPatternStrategy()
        print(f"✅ Strategy initialized: {strategy.name}")
        print(f"   Parameters: {strategy.params}")
        
        # Create sample data for testing
        import pandas as pd
        import numpy as np
        
        # Generate sample OHLCV data
        dates = pd.date_range(start='2024-01-01', periods=100, freq='D')
        np.random.seed(42)
        
        base_price = 1000
        prices = [base_price]
        for i in range(1, 100):
            change = np.random.randn() * 10
            prices.append(prices[-1] + change)
        
        data = pd.DataFrame({
            'date': dates,
            'open': prices,
            'high': [p + abs(np.random.randn() * 5) for p in prices],
            'low': [p - abs(np.random.randn() * 5) for p in prices],
            'close': prices,
            'volume': np.random.randint(1000, 10000, 100)
        })
        
        print(f"\n📊 Generated sample data: {len(data)} candles")
        print(f"   Date range: {data['date'].min()} to {data['date'].max()}")
        
        # Generate signals
        print("\n🔍 Generating signals...")
        try:
            signals = strategy.generate_signals(data, num_back_signals=30)
        except TypeError:
            # Some strategies don't support num_back_signals parameter
            signals = strategy.generate_signals(data)
        
        buy_signals = signals[signals['signal'] == 1]
        sell_signals = signals[signals['signal'] == -1]
        
        print(f"✅ Signals generated successfully!")
        print(f"   Buy signals: {len(buy_signals)}")
        print(f"   Sell signals: {len(sell_signals)}")
        
        if len(signals[signals['signal'] != 0]) > 0:
            print("\n📈 Sample signals:")
            print(signals[signals['signal'] != 0][['date', 'close', 'signal', 'signal_strength']].tail())
        
        print("\n" + "=" * 60)
        print("✅ RSI W-Pattern Strategy test completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Error during testing: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        success = run_test()
        sys.exit(0 if success else 1)
    else:
        print("RSI W-Pattern Strategy")
        print("Run with 'test' argument to test:")
        print("  python -m src.strategy_service.strategies.rsi_w_strategy test")
