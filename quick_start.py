#!/usr/bin/env python
"""
Quick Start Script for Live Trading System
Demonstrates usage and runs the system
"""

import sys
import os
import logging

# Setup path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("QuickStart")


def show_menu():
    """Display main menu"""
    print("\n" + "="*80)
    print("LIVE TRADING SYSTEM - Quick Start")
    print("="*80)
    print("1. Run Tests")
    print("2. Start Live Trading")
    print("3. Check Session Status")
    print("4. View Session Summary")
    print("5. Manual Full Sync")
    print("6. Exit")
    print("="*80)
    
    choice = input("Enter your choice (1-6): ").strip()
    return choice


def run_tests():
    """Run test suite"""
    logger.info("Running test suite...")
    
    try:
        from src.live_trading.test_state_management import run_all_tests
        run_all_tests()
        logger.info("Tests completed successfully!")
    except Exception as e:
        logger.error(f"Tests failed: {e}")


def start_live_trading():
    """Start live trading"""
    logger.info("Starting Live Trading Engine...")
    
    try:
        from src.live_trading.engine import LiveTradingEngine
        
        # Initialize
        engine = LiveTradingEngine(
            config_path="config/live_trading_config.yaml",
            recover=True
        )
        
        logger.info(f"Session: {engine.session_id}")
        logger.info("Type Ctrl+C to stop trading")
        
        # Start
        engine.start()
    
    except KeyboardInterrupt:
        logger.info("Trading stopped by user")
    except Exception as e:
        logger.error(f"Error: {e}")


def check_session_status():
    """Check current session status"""
    logger.info("Checking session status...")
    
    try:
        from src.live_trading.state_manager import StateManager
        from src.live_trading.broker_sync import BrokerSync
        
        manager = StateManager()
        sessions = manager.list_sessions()
        
        if not sessions:
            logger.info("No sessions found")
            return
        
        # Load latest session
        last_session = sessions[-1]
        session = manager.load_session(last_session)
        
        if session is None:
            logger.error("Failed to load session")
            return
        
        # Print status
        print(f"\n{'='*80}")
        print(f"Session: {last_session}")
        print(f"{'-'*80}")
        print(f"Start Time: {session.start_time}")
        print(f"Open Positions: {len(session.positions)}")
        print(f"Total Orders: {len(session.orders)}")
        print(f"Total P&L: ${session.total_pnl:.2f}")
        print(f"Closed Positions: {session.closed_positions_count}")
        print(f"Capital Available: ${session.capital_available:.2f}")
        print(f"Capital Used: ${session.capital_used:.2f}")
        print(f"{'='*80}\n")
        
        # Check sync status
        sync = BrokerSync(state_manager=manager)
        sync_status = sync.get_sync_status()
        
        print(f"Sync Status:")
        print(f"  Local Positions: {sync_status.get('local_positions')}")
        print(f"  Broker Positions: {sync_status.get('broker_positions')}")
        print(f"  Synced: {sync_status.get('synced')}")
    
    except Exception as e:
        logger.error(f"Error: {e}")


def view_session_summary():
    """View detailed session summary"""
    logger.info("Viewing session summary...")
    
    try:
        from src.live_trading.state_manager import StateManager
        import json
        
        manager = StateManager()
        sessions = manager.list_sessions()
        
        if not sessions:
            logger.info("No sessions found")
            return
        
        print(f"\nAvailable sessions:")
        for i, session_id in enumerate(sessions[-5:], 1):  # Show last 5
            print(f"  {i}. {session_id}")
        
        choice = input(f"\nSelect session (1-{len(sessions[-5:])}): ").strip()
        
        try:
            idx = int(choice) - 1
            if idx < 0 or idx >= len(sessions[-5:]):
                logger.error("Invalid choice")
                return
            
            session_id = sessions[-5:][idx]
        except ValueError:
            logger.error("Invalid input")
            return
        
        # Load and display
        session = manager.load_session(session_id)
        
        print(f"\n{'='*80}")
        print(f"Session: {session_id}")
        print(f"{'='*80}")
        
        # Positions
        print(f"\nPositions ({len(session.positions)}):")
        print(f"{'-'*80}")
        for symbol, pos in session.positions.items():
            print(f"  {symbol}:")
            print(f"    Entry Price: ${pos.entry_price}")
            print(f"    Quantity: {pos.quantity}")
            print(f"    Target: ${pos.target_price}")
            print(f"    Stop Loss: ${pos.stop_loss_price}")
            print(f"    Status: {pos.status}")
            print(f"    P&L: ${pos.pnl:.2f} ({pos.pnl_pct:.2f}%)")
        
        # Orders
        print(f"\nOrders ({len(session.orders)}):")
        print(f"{'-'*80}")
        for order_id, order in session.orders.items():
            print(f"  {order_id}:")
            print(f"    Symbol: {order.symbol}")
            print(f"    Side: {order.side}")
            print(f"    Type: {order.order_type}")
            print(f"    Quantity: {order.quantity}")
            print(f"    Status: {order.status}")
            print(f"    Filled: {order.filled_quantity} @ ${order.average_price}")
        
        print(f"\n{'='*80}")
    
    except Exception as e:
        logger.error(f"Error: {e}")


def manual_full_sync():
    """Manually trigger full sync"""
    logger.info("Triggering full synchronization...")
    
    try:
        from src.live_trading.state_manager import StateManager
        from src.live_trading.broker_sync import BrokerSync
        
        manager = StateManager()
        sessions = manager.list_sessions()
        
        if not sessions:
            logger.info("No sessions found")
            return
        
        # Load latest session
        last_session = sessions[-1]
        session = manager.load_session(last_session)
        
        if session is None:
            logger.error("Failed to load session")
            return
        
        # Perform sync
        sync = BrokerSync(state_manager=manager)
        result = sync.full_sync()
        
        print(f"\n{'='*80}")
        print("Sync Results:")
        print(f"{'='*80}")
        print(f"Status: {'SUCCESS' if result.get('success') else 'FAILED'}")
        print(f"\nPositions:")
        for key, items in result.get('positions', {}).items():
            if items:
                print(f"  {key}: {items}")
        print(f"\nOrders:")
        for key, items in result.get('orders', {}).items():
            if items:
                print(f"  {key}: {items}")
        print(f"{'='*80}\n")
    
    except Exception as e:
        logger.error(f"Error: {e}")


def main_menu_loop():
    """Main menu loop"""
    while True:
        choice = show_menu()
        
        if choice == "1":
            run_tests()
        elif choice == "2":
            start_live_trading()
        elif choice == "3":
            check_session_status()
        elif choice == "4":
            view_session_summary()
        elif choice == "5":
            manual_full_sync()
        elif choice == "6":
            logger.info("Exiting...")
            break
        else:
            logger.warning("Invalid choice")


if __name__ == "__main__":
    try:
        main_menu_loop()
    except KeyboardInterrupt:
        logger.info("Exiting...")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
