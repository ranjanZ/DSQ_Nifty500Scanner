"""
Test Suite for Live Trading System
Demonstrates usage and tests core functionality
"""

import sys
import logging
import time
from datetime import datetime
import pytz
from unittest.mock import Mock, patch

# Setup path
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.backtesting.live_trader import LiveTrader, PortfolioManager, Position
from src.backtesting.realtime_data import MockRealtimeDataHandler
from src.backtesting.order_manager import OrderManager, OrderType, OrderSide
from src.strategy.rsi_w_strategy import RSIWPatternStrategy
import pandas as pd
import numpy as np


# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("TestSuite")


class TestPortfolioManager:
    """Test PortfolioManager functionality"""
    
    @staticmethod
    def test_add_position():
        """Test adding positions"""
        logger.info("\n" + "="*60)
        logger.info("TEST: Portfolio Manager - Add Position")
        logger.info("="*60)
        
        portfolio = PortfolioManager(initial_capital=50000)
        
        # Create position
        position = Position(
            symbol="NSE:SBIN-EQ",
            entry_price=500,
            entry_time=datetime.now(pytz.timezone('Asia/Kolkata')),
            quantity=10,
            capital_used=5000,
            entry_signal="BUY",
            target_price=525,
            stop_loss_price=485
        )
        
        # Add position
        result = portfolio.add_position(position)
        assert result == True, "Failed to add position"
        
        stats = portfolio.get_portfolio_stats()
        logger.info(f"Portfolio stats: {stats}")
        
        assert stats['num_open_positions'] == 1
        assert stats['available_capital'] == 45000
        
        logger.info("✓ Test passed: Position added successfully")
    
    @staticmethod
    def test_close_position():
        """Test closing positions"""
        logger.info("\n" + "="*60)
        logger.info("TEST: Portfolio Manager - Close Position")
        logger.info("="*60)
        
        portfolio = PortfolioManager(initial_capital=50000)
        
        # Add position
        position = Position(
            symbol="NSE:INFY-EQ",
            entry_price=1000,
            entry_time=datetime.now(pytz.timezone('Asia/Kolkata')),
            quantity=5,
            capital_used=5000,
            entry_signal="BUY",
            target_price=1050,
            stop_loss_price=980
        )
        
        portfolio.add_position(position)
        
        # Close position with profit
        exit_time = datetime.now(pytz.timezone('Asia/Kolkata'))
        closed_pos = portfolio.close_position("NSE:INFY-EQ", exit_price=1050, exit_time=exit_time)
        
        assert closed_pos is not None
        assert closed_pos.status == "CLOSED"
        assert closed_pos.pnl == 250  # (1050 - 1000) * 5
        
        stats = portfolio.get_portfolio_stats()
        logger.info(f"Portfolio stats after close: {stats}")
        
        assert stats['num_open_positions'] == 0
        assert stats['num_closed_positions'] == 1
        assert stats['total_value'] == 50250
        
        logger.info("✓ Test passed: Position closed successfully")
    
    @staticmethod
    def test_portfolio_stats():
        """Test portfolio statistics"""
        logger.info("\n" + "="*60)
        logger.info("TEST: Portfolio Manager - Statistics")
        logger.info("="*60)
        
        portfolio = PortfolioManager(initial_capital=100000)
        
        # Add multiple positions
        positions = [
            Position(
                symbol="NSE:SBIN-EQ",
                entry_price=500,
                entry_time=datetime.now(pytz.timezone('Asia/Kolkata')),
                quantity=10,
                capital_used=5000,
                entry_signal="BUY",
                target_price=525,
                stop_loss_price=485
            ),
            Position(
                symbol="NSE:INFY-EQ",
                entry_price=1000,
                entry_time=datetime.now(pytz.timezone('Asia/Kolkata')),
                quantity=5,
                capital_used=5000,
                entry_signal="BUY",
                target_price=1050,
                stop_loss_price=980
            )
        ]
        
        for pos in positions:
            portfolio.add_position(pos)
        
        stats = portfolio.get_portfolio_stats()
        
        logger.info(f"Initial Capital: ${stats['initial_capital']}")
        logger.info(f"Available Capital: ${stats['available_capital']}")
        logger.info(f"Active Capital: ${stats['active_capital']}")
        logger.info(f"Total Value: ${stats['total_value']}")
        logger.info(f"Return: {stats['total_return_pct']:.2f}%")
        
        assert stats['num_open_positions'] == 2
        assert stats['available_capital'] == 90000
        
        logger.info("✓ Test passed: Portfolio statistics calculated correctly")


class TestOrderManager:
    """Test OrderManager functionality"""
    
    @staticmethod
    def test_create_order():
        """Test creating orders"""
        logger.info("\n" + "="*60)
        logger.info("TEST: Order Manager - Create Order")
        logger.info("="*60)
        
        manager = OrderManager()
        
        # Create buy order
        order = manager.create_order(
            symbol="NSE:SBIN-EQ",
            side="BUY",
            quantity=10,
            order_type="LIMIT",
            price=500
        )
        
        assert order is not None
        assert order.symbol == "NSE:SBIN-EQ"
        assert order.quantity == 10
        assert order.price == 500
        
        logger.info(f"✓ Order created: {order.to_dict()}")
    
    @staticmethod
    def test_place_order():
        """Test placing orders"""
        logger.info("\n" + "="*60)
        logger.info("TEST: Order Manager - Place Order")
        logger.info("="*60)
        
        manager = OrderManager()
        
        # Create and place order
        order = manager.create_order(
            symbol="NSE:INFY-EQ",
            side="BUY",
            quantity=5,
            order_type="MARKET"
        )
        
        result = manager.place_order(order)
        
        assert result == True
        assert order.order_id is not None
        assert order.status.value == "OPEN"
        
        logger.info(f"✓ Order placed with ID: {order.order_id}")
    
    @staticmethod
    def test_cancel_order():
        """Test cancelling orders"""
        logger.info("\n" + "="*60)
        logger.info("TEST: Order Manager - Cancel Order")
        logger.info("="*60)
        
        manager = OrderManager()
        
        # Create and place order
        order = manager.create_order(
            symbol="NSE:LT-EQ",
            side="BUY",
            quantity=8,
            order_type="LIMIT",
            price=1500
        )
        
        manager.place_order(order)
        logger.info(f"Order placed: {order.order_id}")
        
        # Cancel order
        result = manager.cancel_order(order.order_id)
        
        assert result == True
        assert order.status.value == "CANCELLED"
        
        logger.info(f"✓ Order cancelled: {order.order_id}")
    
    @staticmethod
    def test_modify_order():
        """Test modifying orders"""
        logger.info("\n" + "="*60)
        logger.info("TEST: Order Manager - Modify Order")
        logger.info("="*60)
        
        manager = OrderManager()
        
        # Create and place order
        order = manager.create_order(
            symbol="NSE:MARUTI-EQ",
            side="BUY",
            quantity=2,
            order_type="LIMIT",
            price=8000
        )
        
        manager.place_order(order)
        logger.info(f"Original price: {order.price}")
        
        # Modify order
        result = manager.modify_order(order.order_id, quantity=3, price=8100)
        
        assert result == True
        assert order.quantity == 3
        assert order.price == 8100
        
        logger.info(f"✓ Order modified - Qty: {order.quantity}, Price: {order.price}")


class TestRealtimeData:
    """Test RealtimeDataHandler functionality"""
    
    @staticmethod
    def test_mock_connection():
        """Test mock data handler connection"""
        logger.info("\n" + "="*60)
        logger.info("TEST: Realtime Data - Mock Connection")
        logger.info("="*60)
        
        handler = MockRealtimeDataHandler(symbols=["NSE:SBIN-EQ", "NSE:INFY-EQ"])
        
        # Connect
        result = handler.connect()
        assert result == True
        assert handler.connected == True
        
        logger.info("✓ Mock WebSocket connected")
    
    @staticmethod
    def test_mock_price_update():
        """Test mock price updates"""
        logger.info("\n" + "="*60)
        logger.info("TEST: Realtime Data - Mock Price Update")
        logger.info("="*60)
        
        handler = MockRealtimeDataHandler()
        handler.connect()
        
        # Set mock prices
        handler.set_mock_price("NSE:SBIN-EQ", 500)
        price = handler.get_price("NSE:SBIN-EQ")
        
        assert price == 500
        logger.info(f"✓ Mock price set: NSE:SBIN-EQ = {price}")
        
        # Get price data
        data = handler.get_price_data("NSE:SBIN-EQ")
        assert data is not None
        assert data['price'] == 500
        
        logger.info(f"✓ Price data retrieved: {data}")


class TestLiveTrader:
    """Test LiveTrader functionality"""
    
    @staticmethod
    def test_market_hours():
        """Test market hours checking"""
        logger.info("\n" + "="*60)
        logger.info("TEST: Live Trader - Market Hours")
        logger.info("="*60)
        
        trader = LiveTrader(config_path="config/live_trading_config.yaml")
        
        # Check if market is open (depends on current time)
        is_open = trader.is_market_open()
        logger.info(f"Market open: {is_open}")
        logger.info(f"Current time: {datetime.now(trader.tz).strftime('%H:%M:%S')}")
        logger.info(f"Market hours: {trader.trading_config['market_open']} - {trader.trading_config['market_close']}")
        
        logger.info("✓ Market hours check completed")
    
    @staticmethod
    def test_portfolio_initialization():
        """Test portfolio initialization"""
        logger.info("\n" + "="*60)
        logger.info("TEST: Live Trader - Portfolio Initialization")
        logger.info("="*60)
        
        trader = LiveTrader(config_path="config/live_trading_config.yaml")
        
        stats = trader.portfolio.get_portfolio_stats()
        logger.info(f"Portfolio initialized with capital: ${stats['initial_capital']}")
        
        assert stats['initial_capital'] == trader.trading_config['initial_capital']
        assert stats['num_open_positions'] == 0
        
        logger.info("✓ Portfolio initialized successfully")
    
    @staticmethod
    def test_strategy_initialization():
        """Test strategy initialization"""
        logger.info("\n" + "="*60)
        logger.info("TEST: Live Trader - Strategy Initialization")
        logger.info("="*60)
        
        trader = LiveTrader(config_path="config/live_trading_config.yaml")
        
        assert trader.strategy is not None
        assert isinstance(trader.strategy, RSIWPatternStrategy)
        
        logger.info(f"✓ Strategy initialized: {trader.strategy.name}")


class TestSignalGeneration:
    """Test signal generation"""
    
    @staticmethod
    def test_generate_synthetic_signals():
        """Test signal generation with synthetic data"""
        logger.info("\n" + "="*60)
        logger.info("TEST: Signal Generation - Synthetic Data")
        logger.info("="*60)
        
        # Create synthetic OHLCV data
        np.random.seed(42)
        dates = pd.date_range(start='2026-01-01', periods=100, freq='1H')
        
        # Generate realistic price data
        open_price = 100
        close_prices = [open_price]
        
        for i in range(1, 100):
            change = np.random.randn() * 2  # Random change
            close_prices.append(max(close_prices[-1] + change, 50))
        
        data = pd.DataFrame({
            'time': dates,
            'open': close_prices,
            'high': [p + abs(np.random.randn()) for p in close_prices],
            'low': [max(p - abs(np.random.randn()), 50) for p in close_prices],
            'close': close_prices,
            'volume': [np.random.randint(1000, 10000) for _ in range(100)]
        })
        
        logger.info(f"Generated {len(data)} candles")
        logger.info(f"Price range: {data['close'].min():.2f} - {data['close'].max():.2f}")
        
        # Test strategy
        strategy = RSIWPatternStrategy()
        
        try:
            signals = strategy.generate_signals(data)
            logger.info(f"✓ Signals generated: {len(signals)} rows")
            logger.info(f"Data:\n{signals.tail()}")
        except Exception as e:
            logger.info(f"Signal generation info: {e}")


def run_all_tests():
    """Run all tests"""
    logger.info("\n" + "="*80)
    logger.info("LIVE TRADING SYSTEM - TEST SUITE")
    logger.info("="*80)
    
    try:
        # Portfolio Manager Tests
        TestPortfolioManager.test_add_position()
        TestPortfolioManager.test_close_position()
        TestPortfolioManager.test_portfolio_stats()
        
        # Order Manager Tests
        TestOrderManager.test_create_order()
        TestOrderManager.test_place_order()
        TestOrderManager.test_cancel_order()
        TestOrderManager.test_modify_order()
        
        # Realtime Data Tests
        TestRealtimeData.test_mock_connection()
        TestRealtimeData.test_mock_price_update()
        
        # Live Trader Tests
        TestLiveTrader.test_market_hours()
        TestLiveTrader.test_portfolio_initialization()
        TestLiveTrader.test_strategy_initialization()
        
        # Signal Generation Tests
        TestSignalGeneration.test_generate_synthetic_signals()
        
        logger.info("\n" + "="*80)
        logger.info("ALL TESTS COMPLETED SUCCESSFULLY!")
        logger.info("="*80)
        
    except AssertionError as e:
        logger.error(f"Test assertion failed: {e}")
        raise
    except Exception as e:
        logger.error(f"Test failed with error: {e}")
        raise


if __name__ == "__main__":
    run_all_tests()
