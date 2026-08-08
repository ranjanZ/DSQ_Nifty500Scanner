"""
Test Random Strategy with Mock Data - No Database Required
Tests the complete backtesting workflow
"""

import sys
sys.path.insert(0, '/workspace/src')

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from strategy_service.strategies.random_strategy.strategy import RandomStrategy
from backtesting_service.backtest_engine import BacktestEngine

# Generate realistic mock OHLCV data
def generate_mock_data(symbol: str, days: int = 400) -> pd.DataFrame:
    np.random.seed(hash(symbol) % 2**32)
    dates = pd.date_range(end=datetime.now(), periods=days, freq='D')
    dates = dates[dates.dayofweek < 5]  # Remove weekends
    
    base_price = np.random.uniform(500, 3000)
    prices = [base_price]
    for _ in range(len(dates) - 1):
        change = np.random.normal(0, 0.02)
        prices.append(prices[-1] * (1 + change))
    
    prices = np.array(prices)
    high = prices * (1 + np.abs(np.random.normal(0, 0.015, len(prices))))
    low = prices * (1 - np.abs(np.random.normal(0, 0.015, len(prices))))
    open_prices = prices * (1 + np.random.normal(0, 0.005, len(prices)))
    volume = np.random.randint(100000, 10000000, len(prices))
    
    return pd.DataFrame({
        'date': dates,
        'open': open_prices,
        'high': high,
        'low': low,
        'close': prices,
        'volume': volume
    })

print("="*70)
print("🧪 RANDOM STRATEGY BACKTEST TEST (No Database)")
print("="*70)

# Create 30 mock stocks
symbols = [f"stock{i}_eq" for i in range(1, 31)]
print(f"\n📊 Generating mock data for {len(symbols)} stocks...")

mock_data = {}
for sym in symbols:
    df = generate_mock_data(sym, days=365)
    mock_data[sym] = df

print(f"   Generated {len(mock_data)} stocks with ~{len(list(mock_data.values())[0])} days each")

# Initialize Random Strategy
print("\n🔬 Loading Random Strategy...")
strategy = RandomStrategy(params={
    'signal_probability': 0.08,
    'use_volume_filter': False,
    'seed': 42
})
print(f"   ✓ Strategy: {strategy.name}")
print(f"   ✓ Signal probability: 8%")

# Test signal generation
test_df = mock_data[symbols[0]]
signals = strategy.generate_signals(test_df)
buy_count = len(signals[signals['signal'] == 1])
print(f"   ✓ Test signals: {buy_count} buys in {len(signals)} days ({buy_count/len(signals)*100:.1f}%)")

# Setup config
config = {
    'backtest': {
        'initial_capital': 100000,
        'target_profit_pct': 0.08,
        'stop_loss_pct': 0.04,
        'max_holding_days': 7,
        'max_capital_allocation_per_day': 50000,
    },
    'backtest_service': {
        'verbose': True,
        'save_plots': False,
        'save_metrics': False,
    }
}

# Create engine
engine = BacktestEngine(strategy=strategy, config=config, project_root='/workspace')
engine.position_weights = {
    'method': 'sector_based',
    'max_positions': 7,
    'max_per_sector': 1,
    'sector_allocation': {
        'Financial Services': 0.30, 'Technology': 0.20, 'Healthcare': 0.15,
        'Consumer': 0.15, 'Industrial': 0.10, 'Energy': 0.10,
    }
}

# Mock sector getter
sectors_list = ['Financial Services', 'Technology', 'Healthcare', 'Consumer', 'Industrial', 'Energy']
engine._get_sector = lambda sym: sectors_list[hash(sym) % len(sectors_list)]

# Manually inject mock data and run simulation
print("\n🚀 Running backtest simulation...")
print("="*70)

# Get date range
all_dates = set()
for df in mock_data.values():
    all_dates.update(df['date'].dt.date)
sorted_dates = sorted(all_dates)

print(f"   Period: {sorted_dates[0]} to {sorted_dates[-1]} ({len(sorted_dates)} days)")
print(f"   Capital: ₹{engine.initial_capital:,}")
print(f"   Max Daily: ₹{engine.max_capital_allocation_per_day:,}")
print(f"   Symbols: {len(mock_data)}")

# Run daily simulation
capital_alloc = {sym: 10000 for sym in symbols}  # Dummy allocation

trades = engine.simulate_trades_daily_with_progress(
    mock_data, 
    list(mock_data.keys()), 
    capital_alloc,
    sorted_dates
)

print("\n" + "="*70)
print(f"✅ BACKTEST COMPLETE!")
print("="*70)
print(f"\n📊 RESULTS:")
print(f"   Total Trades: {len(trades)}")
if trades:
    winners = sum(1 for t in trades if t.pnl > 0)
    losers = sum(1 for t in trades if t.pnl <= 0)
    total_pnl = sum(t.pnl for t in trades)
    print(f"   Winners: {winners} ({winners/len(trades)*100:.1f}%)")
    print(f"   Losers: {losers} ({losers/len(trades)*100:.1f}%)")
    print(f"   Total P&L: ₹{total_pnl:,.0f}")
    print(f"   Avg Trade: ₹{total_pnl/len(trades):,.0f}")
    
    # Show sample trades
    print(f"\n📈 Sample Trades (first 5):")
    for i, t in enumerate(trades[:5], 1):
        print(f"   {i}. {t.symbol}: {t.entry_date.date()} @{t.entry_price:.0f} → {t.exit_date.date()} @{t.exit_price:.0f} | P&L: ₹{t.pnl:,.0f} ({t.exit_reason})")
else:
    print("   ⚠️ No trades executed")

print("\n" + "="*70)
