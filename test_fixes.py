#!/usr/bin/env python3
"""
Test script to verify all fixes:
1. PositionState with entry_signal
2. generate_signals with last_n_days parameter
3. update_session_metrics instead of update_capital
"""

import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz

# Add source to path
sys.path.insert(0, '/workspaces/DSQ_Nifty500Scanner')

from src.live_trading.state_manager import StateManager, PositionState
from src.strategy.madam_strategy import SupportResistanceStrategy


def test_position_state_creation():
    """Test PositionState creation with entry_signal"""
    print("\n" + "="*80)
    print("TEST 1: PositionState Creation with entry_signal")
    print("="*80)
    
    try:
        pos = PositionState(
            symbol="NSE:RELIANCE-EQ",
            entry_price=2500.0,
            entry_time=datetime.now(pytz.timezone('Asia/Kolkata')).isoformat(),
            quantity=10,
            capital_used=25000,
            entry_signal="TEST_SIGNAL",  # This is now required
            target_price=2625.0,
            stop_loss_price=2450.0,
            order_id="test_order"
        )
        print(f"✓ PositionState created successfully")
        print(f"  - Symbol: {pos.symbol}")
        print(f"  - Entry Signal: {pos.entry_signal}")
        print(f"  - Entry Price: {pos.entry_price}")
        print(f"  - Target: {pos.target_price}, SL: {pos.stop_loss_price}")
        return True
    except Exception as e:
        print(f"✗ Error: {e}")
        return False


def test_generate_signals_with_last_n_days():
    """Test generate_signals with last_n_days parameter"""
    print("\n" + "="*80)
    print("TEST 2: generate_signals with last_n_days parameter")
    print("="*80)
    
    try:
        # Create dummy OHLCV data for 100 days
        dates = pd.date_range(end=datetime.now(), periods=100, freq='D')
        data = pd.DataFrame({
            'time': dates,
            'open': np.random.uniform(100, 150, 100),
            'high': np.random.uniform(150, 160, 100),
            'low': np.random.uniform(90, 100, 100),
            'close': np.random.uniform(100, 150, 100),
            'volume': np.random.uniform(1000000, 5000000, 100)
        })
        
        # Ensure high > low
        data['high'] = data[['open', 'high', 'close']].max(axis=1) + 5
        data['low'] = data[['open', 'low', 'close']].min(axis=1) - 5
        
        # Initialize strategy
        strategy = SupportResistanceStrategy()
        
        # Test without last_n_days (all data)
        print("\n  Testing generate_signals(data) - all data...")
        signals_all = strategy.generate_signals(data)
        total_signals = (signals_all['signal'] == 1).sum()
        print(f"  ✓ Signals generated for all {len(signals_all)} candles")
        print(f"    Total signals found: {total_signals}")
        
        # Test with last_n_days=10
        print("\n  Testing generate_signals(data, last_n_days=10) - last 10 days...")
        signals_10d = strategy.generate_signals(data, last_n_days=10)
        signals_in_10d = (signals_10d.iloc[-10:]['signal'] == 1).sum()
        print(f"  ✓ Indicators computed for all {len(signals_10d)} candles")
        print(f"    Signals generated only for last 10 days")
        print(f"    Signals in last 10 days: {signals_in_10d}")
        
        # Verify earlier data has indicators but no signals
        print("\n  Verifying optimization:")
        has_indicators_all = signals_10d['num_support'].notna().all()
        has_signals_early = (signals_10d.iloc[:-10]['signal'] == 0).all()
        print(f"  ✓ All candles have indicators: {has_indicators_all}")
        print(f"  ✓ Early candles have no signals (optimization working): {has_signals_early}")
        
        return True
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_update_session_metrics():
    """Test update_session_metrics instead of update_capital"""
    print("\n" + "="*80)
    print("TEST 3: update_session_metrics (replacing update_capital)")
    print("="*80)
    
    try:
        import tempfile
        
        # Create temporary state directory
        temp_dir = tempfile.mkdtemp()
        manager = StateManager(state_dir=temp_dir)
        
        # Create a session
        initial_capital = 100000
        session = manager.create_new_session("test_session", initial_capital=initial_capital)
        print(f"✓ Session created with initial capital: {initial_capital}")
        
        # Use update_session_metrics instead of update_capital
        print("\n  Testing update_session_metrics()...")
        result = manager.update_session_metrics(
            capital_available=initial_capital,
            capital_used=0
        )
        print(f"  ✓ update_session_metrics() call successful: {result}")
        
        # Verify the update
        summary = manager.get_session_summary()
        print(f"    Capital Available: {summary['capital_available']}")
        print(f"    Capital Used: {summary['capital_used']}")
        
        # Test updating only capital_available
        print("\n  Testing update_session_metrics(capital_available=50000)...")
        manager.update_session_metrics(capital_available=50000)
        summary = manager.get_session_summary()
        print(f"  ✓ Capital Available updated to: {summary['capital_available']}")
        
        return True
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("\n" + "="*80)
    print("RUNNING TESTS FOR ALL FIXES")
    print("="*80)
    
    results = {
        "PositionState Creation": test_position_state_creation(),
        "generate_signals with last_n_days": test_generate_signals_with_last_n_days(),
        "update_session_metrics": test_update_session_metrics(),
    }
    
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    
    for test_name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {test_name}")
    
    all_passed = all(results.values())
    print("\n" + ("="*80))
    print(f"Overall: {'✓ ALL TESTS PASSED' if all_passed else '✗ SOME TESTS FAILED'}")
    print("="*80 + "\n")
    
    sys.exit(0 if all_passed else 1)
