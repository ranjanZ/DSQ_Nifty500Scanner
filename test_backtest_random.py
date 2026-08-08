"""
Test script for Random Strategy backtesting with mock data
This tests the entire workflow without requiring PostgreSQL
"""

import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Add src to path
sys.path.insert(0, '/workspace/src')

from strategy_service.strategies.random_strategy.strategy import RandomStrategy
from backtesting_service.backtest_engine import BacktestEngine

# Generate mock data for 10 stocks
def generate_mock_data(symbol: str, days: int = 400) -> pd.DataFrame:
    """Generate realistic mock OHLCV data"""
    np.random.seed(hash(symbol) % 2**32)
    
    dates = pd.date_range(end=datetime.now(), periods=days, freq='D')
    # Remove weekends
    dates = dates[dates.dayofweek < 5]
    
    base_price = np.random.uniform(100, 5000)
    prices = [base_price]
    
    for _ in range(len(dates) - 1):
        change = np.random.normal(0, 0.02)
        prices.append(prices[-1] * (1 + change))
    
    prices = np.array(prices)
    high = prices * (1 + np.abs(np.random.normal(0, 0.01, len(prices))))
    low = prices * (1 - np.abs(np.random.normal(0, 0.01, len(prices))))
    open_prices = prices * (1 + np.random.normal(0, 0.005, len(prices)))
    volume = np.random.randint(100000, 10000000, len(prices))
    
    df = pd.DataFrame({
        'date': dates,
        'open': open_prices,
        'high': high,
        'low': low,
        'close': prices,
        'volume': volume
    })
    
    return df

# Create mock stock list
print("=" * 60)
print("🧪 Testing Random Strategy Backtest Engine")
print("=" * 60)

symbols = [f"stock{i}_eq" for i in range(1, 51)]  # 50 stocks
print(f"\n📊 Generating mock data for {len(symbols)} stocks...")

mock_data = {}
for sym in symbols:
    mock_data[sym] = generate_mock_data(sym, days=400)
    print(f"   {sym}: {len(mock_data[sym])} days")

# Initialize strategy
print("\n🔬 Loading Random Strategy...")
strategy_params = {
    'signal_probability': 0.08,  # 8% chance
    'use_volume_filter': False,
    'seed': 42
}
strategy = RandomStrategy(params=strategy_params)
print(f"   Strategy: {strategy.name}")
print(f"   Signal probability: {strategy_params['signal_probability']}")
print(f"   Lookback: {strategy.get_minimum_history()} days")

# Test signal generation on one stock
print("\n📈 Testing signal generation...")
test_sym = symbols[0]
test_df = mock_data[test_sym]
signals_df = strategy.generate_signals(test_df)
buy_signals = signals_df[signals_df['signal'] == 1]
print(f"   {test_sym}: {len(buy_signals)} buy signals in {len(signals_df)} days ({len(buy_signals)/len(signals_df)*100:.1f}%)")

# Setup backtest config
config = {
    'backtest': {
        'initial_capital': 100000,
        'target_profit_pct': 0.08,
        'stop_loss_pct': 0.04,
        'max_holding_days': 7,
        'max_capital_allocation_per_day': 50000,
        'start_date': '2025-01-01',
        'end_date': '2025-12-31',
    },
    'backtest_service': {
        'verbose': True,
        'save_plots': False,
        'save_metrics': False,
    }
}

# Create backtest engine
print("\n⚙️  Creating Backtest Engine...")
engine = BacktestEngine(
    strategy=strategy,
    config=config,
    project_root='/workspace'
)

# Override position weights
engine.position_weights = {
    'method': 'sector_based',
    'max_positions': 7,
    'max_per_sector': 1,
    'sector_allocation': {
        'Financial Services': 0.30,
        'Technology': 0.20,
        'Healthcare': 0.15,
        'Consumer': 0.15,
        'Industrial': 0.10,
        'Energy': 0.10,
    }
}

# Mock sector mapping
original_get_sector = engine._get_sector
def mock_get_sector(symbol):
    sectors = ['Financial Services', 'Technology', 'Healthcare', 'Consumer', 'Industrial', 'Energy']
    idx = hash(symbol) % len(sectors)
    return sectors[idx]
engine._get_sector = mock_get_sector

# Run backtest
print("\n🚀 Running backtest...")
print("=" * 60)

try:
    metrics = engine.run(symbols=symbols[:20])  # Test with 20 stocks first
    
    print("\n" + "=" * 60)
    print("✅ BACKTEST COMPLETED SUCCESSFULLY!")
    print("=" * 60)
    
except Exception as e:
    print(f"\n❌ Error during backtest: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
