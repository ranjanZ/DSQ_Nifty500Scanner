"""
Quick Start Guide for Live Trading System
Shows how to set up and run live trading
"""

import logging
import pytz
from datetime import datetime, time

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("QuickStart")


# ============================================================================
# EXAMPLE 1: Simple Live Trading
# ============================================================================

def example_simple_live_trading():
    """
    Simple example: Run basic live trading during market hours
    """
    logger.info("\n" + "="*80)
    logger.info("EXAMPLE 1: Simple Live Trading")
    logger.info("="*80)
    
    from src.backtesting.live.live_trader import LiveTrader
    
    # Initialize trader
    trader = LiveTrader(config_path="config/live_trading_config.yaml")
    
    # Start trading (runs until market close or manual stop)
    try:
        trader.start_trading()
    except KeyboardInterrupt:
        logger.info("Trading stopped by user")
        trader.stop_trading()


# ============================================================================
# EXAMPLE 2: Real-time Data Streaming
# ============================================================================

def example_realtime_data():
    """
    Example: Connect to real-time data stream
    """
    logger.info("\n" + "="*80)
    logger.info("EXAMPLE 2: Real-time Data Streaming")
    logger.info("="*80)
    
    from src.backtesting.live.realtime_data import MockRealtimeDataHandler
    import time
    
    # Create data handler (using mock for testing)
    handler = MockRealtimeDataHandler(symbols=["NSE:SBIN-EQ", "NSE:INFY-EQ", "NSE:ITC-EQ"])
    
    # Register callbacks
    def on_price_update(data):
        logger.info(f"Price update received: {len(data)} symbols")
        for item in data:
            logger.info(f"  {item['symbol']}: ${item['ltp']}")
    
    def on_connect():
        logger.info("Connected to real-time data stream")
    
    def on_error(error):
        logger.error(f"Data stream error: {error}")
    
    handler.register_on_price_update(on_price_update)
    handler.register_on_connect(on_connect)
    handler.register_on_error(on_error)
    
    # Connect
    handler.connect()
    time.sleep(1)  # Wait for connection
    
    # Simulate price updates
    logger.info("Simulating price updates...")
    for i in range(5):
        handler.set_mock_price("NSE:SBIN-EQ", 500 + i)
        handler.set_mock_price("NSE:INFY-EQ", 1000 + i*2)
        handler.set_mock_price("NSE:ITC-EQ", 250 + i)
        time.sleep(1)
    
    # Disconnect
    handler.disconnect()


# ============================================================================
# EXAMPLE 3: Order Management
# ============================================================================

def example_order_management():
    """
    Example: Manage orders
    """
    logger.info("\n" + "="*80)
    logger.info("EXAMPLE 3: Order Management")
    logger.info("="*80)
    
    from src.backtesting.live.order_manager import OrderManager
    
    manager = OrderManager()
    
    # Create orders
    logger.info("Creating orders...")
    
    buy_order = manager.create_order(
        symbol="NSE:SBIN-EQ",
        side="BUY",
        quantity=10,
        order_type="LIMIT",
        price=500,
        metadata={"strategy": "RSI_W_Pattern"}
    )
    
    sell_order = manager.create_order(
        symbol="NSE:INFY-EQ",
        side="SELL",
        quantity=5,
        order_type="MARKET"
    )
    
    # Place orders
    logger.info("Placing orders...")
    manager.place_order(buy_order)
    manager.place_order(sell_order)
    
    # Get order status
    logger.info(f"\nBuy Order: {buy_order.order_id}")
    logger.info(f"  Status: {buy_order.status.value}")
    logger.info(f"  Symbol: {buy_order.symbol}")
    logger.info(f"  Quantity: {buy_order.quantity}")
    logger.info(f"  Price: {buy_order.price}")
    
    # Modify order
    logger.info("\nModifying buy order...")
    manager.modify_order(buy_order.order_id, quantity=12, price=505)
    logger.info(f"  New Qty: {buy_order.quantity}, Price: {buy_order.price}")
    
    # Update order status
    logger.info("\nUpdating order status...")
    manager.update_order_status(buy_order.order_id, status="FILLED", filled_qty=12, avg_price=502)
    logger.info(f"  Status: {buy_order.status.value}")
    logger.info(f"  Filled: {buy_order.filled_quantity} @{buy_order.average_price}")
    
    # Print summary
    manager.print_orders_summary()


# ============================================================================
# EXAMPLE 4: Portfolio Management
# ============================================================================

def example_portfolio_management():
    """
    Example: Manage portfolio and positions
    """
    logger.info("\n" + "="*80)
    logger.info("EXAMPLE 4: Portfolio Management")
    logger.info("="*80)
    
    from src.backtesting.live.live_trader import PortfolioManager, Position
    import pytz
    from datetime import datetime
    
    # Create portfolio
    portfolio = PortfolioManager(initial_capital=100000)
    
    # Add positions
    logger.info("Adding positions...")
    
    pos1 = Position(
        symbol="NSE:SBIN-EQ",
        entry_price=500,
        entry_time=datetime.now(pytz.timezone('Asia/Kolkata')),
        quantity=10,
        capital_used=5000,
        entry_signal="BUY",
        target_price=525,
        stop_loss_price=485
    )
    
    pos2 = Position(
        symbol="NSE:INFY-EQ",
        entry_price=1000,
        entry_time=datetime.now(pytz.timezone('Asia/Kolkata')),
        quantity=5,
        capital_used=5000,
        entry_signal="BUY",
        target_price=1050,
        stop_loss_price=980
    )
    
    portfolio.add_position(pos1)
    portfolio.add_position(pos2)
    
    # Get portfolio stats
    logger.info("\nPortfolio statistics:")
    stats = portfolio.get_portfolio_stats()
    for key, value in stats.items():
        logger.info(f"  {key}: {value}")
    
    # Close a position
    logger.info("\nClosing position...")
    portfolio.close_position("NSE:SBIN-EQ", exit_price=520, exit_time=datetime.now(pytz.timezone('Asia/Kolkata')))
    
    # Updated stats
    logger.info("\nUpdated portfolio statistics:")
    stats = portfolio.get_portfolio_stats()
    for key, value in stats.items():
        logger.info(f"  {key}: {value}")


# ============================================================================
# EXAMPLE 5: Market Hours Scheduling
# ============================================================================

def example_market_hours():
    """
    Example: Check market hours and schedule trades
    """
    logger.info("\n" + "="*80)
    logger.info("EXAMPLE 5: Market Hours Scheduling")
    logger.info("="*80)
    
    from src.backtesting.live.live_trader import LiveTrader
    
    trader = LiveTrader(config_path="config/live_trading_config.yaml")
    
    # Check market hours
    tz = pytz.timezone('Asia/Kolkata')
    now = datetime.now(tz)
    
    logger.info(f"Current time: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    logger.info(f"Timezone: {tz}")
    logger.info(f"Day of week: {now.strftime('%A')}")
    
    logger.info(f"\nMarket hours: {trader.trading_config['market_open']} - {trader.trading_config['market_close']}")
    
    is_open = trader.is_market_open()
    logger.info(f"Market open: {is_open}")
    
    # Schedule information
    market_open_time = datetime.strptime(trader.trading_config['market_open'], "%H:%M").time()
    market_close_time = datetime.strptime(trader.trading_config['market_close'], "%H:%M").time()
    
    logger.info(f"\nMarket will:")
    logger.info(f"  Open at: {market_open_time}")
    logger.info(f"  Close at: {market_close_time}")


# ============================================================================
# EXAMPLE 6: Strategy Integration
# ============================================================================

def example_strategy_integration():
    """
    Example: Integrate custom strategy
    """
    logger.info("\n" + "="*80)
    logger.info("EXAMPLE 6: Strategy Integration")
    logger.info("="*80)
    
    from src.strategy.rsi_w_strategy import RSIWPatternStrategy
    import pandas as pd
    import numpy as np
    
    # Create synthetic data
    np.random.seed(42)
    dates = pd.date_range(start='2026-01-01', periods=100, freq='1H')
    
    close_prices = [100]
    for i in range(1, 100):
        change = np.random.randn() * 2
        close_prices.append(max(close_prices[-1] + change, 50))
    
    data = pd.DataFrame({
        'time': dates,
        'open': close_prices,
        'high': [p + abs(np.random.randn()) for p in close_prices],
        'low': [max(p - abs(np.random.randn()), 50) for p in close_prices],
        'close': close_prices,
        'volume': [np.random.randint(1000, 10000) for _ in range(100)]
    })
    
    logger.info(f"Generated data: {len(data)} candles")
    
    # Create and test strategy
    strategy = RSIWPatternStrategy(params={
        'rsi_period': 14,
        'oversold': 30,
        'overbought': 70
    })
    
    logger.info(f"Strategy: {strategy.name}")
    logger.info(f"Parameters: {strategy.params}")
    
    # Generate signals
    logger.info("\nGenerating signals...")
    try:
        signals = strategy.generate_signals(data)
        logger.info(f"Signals generated: {len(signals)} rows")
        logger.info("\nLast 5 signals:")
        logger.info(signals.tail())
    except Exception as e:
        logger.info(f"Signal generation completed with info: {e}")


# ============================================================================
# MAIN - Run Examples
# ============================================================================

def main():
    """
    Run examples
    
    Uncomment the examples you want to run:
    """
    
    # Example 1: Simple Live Trading (requires market hours and Fyers credentials)
    # example_simple_live_trading()
    
    # Example 2: Real-time Data Streaming
    example_realtime_data()
    
    # Example 3: Order Management
    example_order_management()
    
    # Example 4: Portfolio Management
    example_portfolio_management()
    
    # Example 5: Market Hours Scheduling
    example_market_hours()
    
    # Example 6: Strategy Integration
    example_strategy_integration()
    
    logger.info("\n" + "="*80)
    logger.info("All examples completed!")
    logger.info("="*80)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Examples interrupted by user")
    except Exception as e:
        logger.error(f"Error running examples: {e}")
        raise
