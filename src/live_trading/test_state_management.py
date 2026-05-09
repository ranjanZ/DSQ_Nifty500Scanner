"""
Tests for Live Trading System with State Management
"""

import sys
import os
import logging
import time
import json
from datetime import datetime
import pytz
import tempfile
import shutil

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("LiveTradingTests")


# ============================================================================
# Test Suite 1: State Manager
# ============================================================================

def test_state_manager():
    """Test state manager functionality"""
    logger.info("\n" + "="*80)
    logger.info("TEST SUITE 1: State Manager")
    logger.info("="*80)
    
    from src.live_trading.state_manager import (
        StateManager, PositionState, OrderState, TradingSessionState
    )
    
    # Create temporary directory for test
    temp_dir = tempfile.mkdtemp()
    
    try:
        # Test 1.1: Create new session
        logger.info("\nTest 1.1: Create new session")
        manager = StateManager(state_dir=temp_dir)
        session = manager.create_new_session("test_session_1", initial_capital=50000)
        
        assert session is not None
        assert session.session_id == "test_session_1"
        assert session.capital_available == 50000
        logger.info("✓ Session created successfully")
        
        # Test 1.2: Add position
        logger.info("\nTest 1.2: Add position to session")
        position = PositionState(
            symbol="NSE:SBIN-EQ",
            entry_price=500,
            entry_time=datetime.now(pytz.timezone('Asia/Kolkata')).isoformat(),
            quantity=10,
            capital_used=5000,
            entry_signal="BUY",
            target_price=525,
            stop_loss_price=485
        )
        
        result = manager.add_position(position)
        assert result == True
        
        # Verify position was added
        positions = manager.get_all_positions()
        assert "NSE:SBIN-EQ" in positions
        logger.info("✓ Position added successfully")
        
        # Test 1.3: Update position
        logger.info("\nTest 1.3: Update position")
        manager.update_position("NSE:SBIN-EQ", {
            'highest_price': 510,
            'status': 'UPDATED'
        })
        
        pos = manager.get_position("NSE:SBIN-EQ")
        assert pos.highest_price == 510
        logger.info("✓ Position updated successfully")
        
        # Test 1.4: Add order
        logger.info("\nTest 1.4: Add order")
        order = OrderState(
            order_id="ORD_1001",
            symbol="NSE:SBIN-EQ",
            side="BUY",
            quantity=10,
            order_type="LIMIT",
            price=500
        )
        
        result = manager.add_order(order)
        assert result == True
        
        orders = manager.get_all_orders()
        assert "ORD_1001" in orders
        logger.info("✓ Order added successfully")
        
        # Test 1.5: Save and load session
        logger.info("\nTest 1.5: Save and load session")
        manager.save_session()
        
        # Create new manager instance and load the saved session
        manager2 = StateManager(state_dir=temp_dir)
        loaded_session = manager2.load_session("test_session_1")
        
        assert loaded_session is not None
        assert len(loaded_session.positions) == 1
        assert len(loaded_session.orders) == 1
        logger.info("✓ Session saved and loaded successfully")
        
        # Test 1.6: Session summary
        logger.info("\nTest 1.6: Get session summary")
        summary = manager.get_session_summary()
        
        assert summary['session_id'] == "test_session_1"
        assert summary['open_positions'] == 1
        assert summary['total_orders'] == 1
        logger.info(f"✓ Session summary: {summary}")
        
        # Test 1.7: List sessions
        logger.info("\nTest 1.7: List saved sessions")
        sessions = manager.list_sessions()
        
        assert "test_session_1" in sessions
        logger.info(f"✓ Saved sessions: {sessions}")
        
        logger.info("\n✓ All State Manager tests passed!")
        
    finally:
        # Cleanup
        shutil.rmtree(temp_dir)


# ============================================================================
# Test Suite 2: Broker Sync
# ============================================================================

def test_broker_sync():
    """Test broker synchronization"""
    logger.info("\n" + "="*80)
    logger.info("TEST SUITE 2: Broker Sync")
    logger.info("="*80)
    
    from src.live_trading.state_manager import StateManager, PositionState
    from src.live_trading.broker_sync import BrokerSync
    from unittest.mock import Mock
    
    temp_dir = tempfile.mkdtemp()
    
    try:
        # Setup
        state_manager = StateManager(state_dir=temp_dir)
        state_manager.create_new_session("test_sync_1", initial_capital=50000)
        
        # Add a test position
        position = PositionState(
            symbol="NSE:INFY-EQ",
            entry_price=1000,
            entry_time=datetime.now(pytz.timezone('Asia/Kolkata')).isoformat(),
            quantity=5,
            capital_used=5000,
            entry_signal="BUY",
            target_price=1050,
            stop_loss_price=980
        )
        state_manager.add_position(position)
        
        # Mock broker
        mock_broker = Mock()
        
        # Test 2.1: Create BrokerSync
        logger.info("\nTest 2.1: Create BrokerSync")
        sync = BrokerSync(broker=mock_broker, state_manager=state_manager)
        
        assert sync is not None
        logger.info("✓ BrokerSync created successfully")
        
        # Test 2.2: Get sync status
        logger.info("\nTest 2.2: Get sync status")
        status = sync.get_sync_status()
        
        assert status.get('local_positions') == 1
        logger.info(f"✓ Sync status: {status}")
        
        # Test 2.3: Reconcile position
        logger.info("\nTest 2.3: Reconcile position")
        matches, message = sync.reconcile_position("NSE:INFY-EQ")
        
        logger.info(f"Reconciliation message: {message}")
        logger.info("✓ Position reconciliation completed")
        
        # Test 2.4: Full sync
        logger.info("\nTest 2.4: Full synchronization")
        result = sync.full_sync()
        
        assert result.get('success') == True
        logger.info(f"✓ Full sync completed: {result}")
        
        logger.info("\n✓ All Broker Sync tests passed!")
        
    finally:
        shutil.rmtree(temp_dir)


# ============================================================================
# Test Suite 3: Live Trading Engine
# ============================================================================

def test_live_trading_engine():
    """Test live trading engine"""
    logger.info("\n" + "="*80)
    logger.info("TEST SUITE 3: Live Trading Engine")
    logger.info("="*80)
    
    from src.live_trading.engine import LiveTradingEngine
    from unittest.mock import Mock, patch
    
    temp_dir = tempfile.mkdtemp()
    
    try:
        # Create test config
        config_file = os.path.join(temp_dir, "test_config.yaml")
        with open(config_file, 'w') as f:
            f.write("""
live_trading:
  market_open: "09:15"
  market_close: "15:20"
  timezone: "Asia/Kolkata"
  initial_capital: 50000
  max_positions: 3
  max_position_size: 5000
  target_profit_pct: 0.05
  stop_loss_pct: 0.02
  trailing_stop_pct: 0.01
  data_refresh_interval: 60
  strategy_type: "RSI_W_Pattern"
  strategy_params:
    rsi_period: 14
    oversold: 30
    overbought: 70
  watchlist: ["nifty_top_500"]
  scan_symbols: 5
""")
        
        # Test 3.1: Initialize engine
        logger.info("\nTest 3.1: Initialize engine")
        
        with patch('src.live_trading.engine.StateManager') as mock_state:
            with patch('src.live_trading.engine.BrokerSync'):
                engine = LiveTradingEngine(
                    config_path=config_file,
                    session_id="test_engine_1",
                    recover=False
                )
        
        assert engine is not None
        assert engine.session_id == "test_engine_1"
        logger.info("✓ Engine initialized successfully")
        
        # Test 3.2: Market hours check
        logger.info("\nTest 3.2: Market hours check")
        is_open = engine.is_market_open()
        
        current_time = datetime.now(engine.tz)
        logger.info(f"Current time: {current_time.strftime('%H:%M:%S')}")
        logger.info(f"Market open: {is_open}")
        logger.info("✓ Market hours check completed")
        
        logger.info("\n✓ All Live Trading Engine tests passed!")
        
    finally:
        shutil.rmtree(temp_dir)


# ============================================================================
# Test Suite 4: State Recovery
# ============================================================================

def test_state_recovery():
    """Test state recovery after crash"""
    logger.info("\n" + "="*80)
    logger.info("TEST SUITE 4: State Recovery")
    logger.info("="*80)
    
    from src.live_trading.state_manager import StateManager, PositionState, OrderState
    
    temp_dir = tempfile.mkdtemp()
    
    try:
        # Test 4.1: Create session with multiple positions
        logger.info("\nTest 4.1: Create session with multiple positions")
        manager1 = StateManager(state_dir=temp_dir)
        manager1.create_new_session("recovery_test", initial_capital=100000)
        
        # Add multiple positions
        positions_data = [
            ("NSE:SBIN-EQ", 500, 10),
            ("NSE:INFY-EQ", 1000, 5),
            ("NSE:ITC-EQ", 250, 20),
        ]
        
        for symbol, price, qty in positions_data:
            pos = PositionState(
                symbol=symbol,
                entry_price=price,
                entry_time=datetime.now(pytz.timezone('Asia/Kolkata')).isoformat(),
                quantity=qty,
                capital_used=price * qty,
                entry_signal="BUY",
                target_price=price * 1.05,
                stop_loss_price=price * 0.98
            )
            manager1.add_position(pos)
        
        # Add orders
        for i, (symbol, price, qty) in enumerate(positions_data):
            order = OrderState(
                order_id=f"ORD_{i+1}",
                symbol=symbol,
                side="BUY",
                quantity=qty,
                order_type="LIMIT",
                price=price
            )
            manager1.add_order(order)
        
        logger.info(f"✓ Created session with {len(positions_data)} positions")
        
        # Test 4.2: Simulate crash - save state
        logger.info("\nTest 4.2: Save state to disk")
        manager1.save_session()
        logger.info("✓ State saved to disk")
        
        # Test 4.3: Recover from crash
        logger.info("\nTest 4.3: Recover from crash")
        manager2 = StateManager(state_dir=temp_dir)
        recovered_session = manager2.load_session("recovery_test")
        
        assert recovered_session is not None
        assert len(recovered_session.positions) == len(positions_data)
        assert len(recovered_session.orders) == len(positions_data)
        logger.info(f"✓ Recovered {len(positions_data)} positions and orders")
        
        # Test 4.4: Verify recovered data
        logger.info("\nTest 4.4: Verify recovered data")
        for symbol, expected_price, expected_qty in positions_data:
            pos = manager2.get_position(symbol)
            assert pos is not None
            assert pos.entry_price == expected_price
            assert pos.quantity == expected_qty
            logger.info(f"✓ Verified {symbol}: price={pos.entry_price}, qty={pos.quantity}")
        
        logger.info("\n✓ All State Recovery tests passed!")
        
    finally:
        shutil.rmtree(temp_dir)


# ============================================================================
# Test Suite 5: Integration Tests
# ============================================================================

def test_integration():
    """Integration tests"""
    logger.info("\n" + "="*80)
    logger.info("TEST SUITE 5: Integration Tests")
    logger.info("="*80)
    
    from src.live_trading.state_manager import StateManager, PositionState
    from src.live_trading.broker_sync import BrokerSync
    
    temp_dir = tempfile.mkdtemp()
    
    try:
        # Test 5.1: Complete workflow
        logger.info("\nTest 5.1: Complete trading workflow")
        
        manager = StateManager(state_dir=temp_dir)
        manager.create_new_session("integration_test", initial_capital=50000)
        
        # Add position
        position = PositionState(
            symbol="NSE:LT-EQ",
            entry_price=1500,
            entry_time=datetime.now(pytz.timezone('Asia/Kolkata')).isoformat(),
            quantity=3,
            capital_used=4500,
            entry_signal="BUY",
            target_price=1575,
            stop_loss_price=1470
        )
        manager.add_position(position)
        logger.info("✓ Position added")
        
        # Update metrics
        manager.update_session_metrics(
            total_pnl=100,
            capital_available=45500,
            capital_used=4500
        )
        logger.info("✓ Session metrics updated")
        
        # Get summary
        summary = manager.get_session_summary()
        assert summary['open_positions'] == 1
        assert summary['capital_used'] == 4500
        logger.info(f"✓ Summary: {summary}")
        
        # Save session
        manager.save_session()
        logger.info("✓ Session saved")
        
        # Test 5.2: Multi-session management
        logger.info("\nTest 5.2: Multi-session management")
        
        # Create multiple sessions
        for i in range(3):
            mgr = StateManager(state_dir=temp_dir)
            mgr.create_new_session(f"multi_session_{i}", initial_capital=50000)
        
        # List all sessions
        all_sessions = manager.list_sessions()
        logger.info(f"✓ Found {len(all_sessions)} sessions: {all_sessions}")
        
        # Test 5.3: Export session
        logger.info("\nTest 5.3: Export session data")
        
        export_path = os.path.join(temp_dir, "export", "session_export.json")
        result = manager.export_session("integration_test", export_path)
        
        assert result == True
        assert os.path.exists(export_path)
        
        with open(export_path, 'r') as f:
            exported_data = json.load(f)
        
        assert exported_data['session_id'] == "integration_test"
        logger.info("✓ Session exported successfully")
        
        logger.info("\n✓ All Integration tests passed!")
        
    finally:
        shutil.rmtree(temp_dir)


# ============================================================================
# Run All Tests
# ============================================================================

def run_all_tests():
    """Run all test suites"""
    logger.info("\n" + "="*80)
    logger.info("LIVE TRADING SYSTEM - COMPREHENSIVE TEST SUITE")
    logger.info("="*80)
    
    try:
        test_state_manager()
        test_broker_sync()
        test_live_trading_engine()
        test_state_recovery()
        test_integration()
        
        logger.info("\n" + "="*80)
        logger.info("✓✓✓ ALL TESTS PASSED SUCCESSFULLY! ✓✓✓")
        logger.info("="*80)
        
    except AssertionError as e:
        logger.error(f"✗ Test assertion failed: {e}")
        raise
    except Exception as e:
        logger.error(f"✗ Test failed with error: {e}")
        raise


if __name__ == "__main__":
    try:
        run_all_tests()
    except KeyboardInterrupt:
        logger.info("Tests interrupted by user")
    except Exception as e:
        logger.error(f"Error running tests: {e}")
        import traceback
        traceback.print_exc()
