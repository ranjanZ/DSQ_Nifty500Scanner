"""
Live Trading Service - Execute trades in real-time
Utilizes broker service for order execution
"""

import os
import sys
import time
import logging
import yaml
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dotenv import load_dotenv
import pytz

load_dotenv()

logger = logging.getLogger(__name__)


class LiveTradingService:
    """Service for live trading execution"""
    
    def __init__(self, config_path: str = "config/live_trading_config.yaml",
                 broker=None, strategy_service=None):
        self.config = self._load_config(config_path)
        self.broker = broker
        self.strategy_service = strategy_service
        
        self.positions = {}
        self.orders = {}
        self.is_running = False
        self.tz = pytz.timezone("Asia/Kolkata")
        
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Load configuration from YAML"""
        try:
            with open(config_path, 'r') as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            return {}
    
    def initialize(self) -> bool:
        """Initialize the trading service"""
        logger.info("Initializing Live Trading Service...")
        
        if not self.broker:
            logger.error("No broker configured")
            return False
        
        if not self.broker.is_connected():
            if not self.broker.connect():
                logger.error("Failed to connect to broker")
                return False
        
        logger.info("Live Trading Service initialized successfully")
        return True
    
    def start_trading(self):
        """Start the trading loop"""
        logger.info("Starting trading loop...")
        self.is_running = True
        
        while self.is_running:
            try:
                self._trading_loop_iteration()
                time.sleep(5)  # Sleep between iterations
            except KeyboardInterrupt:
                logger.info("Trading interrupted by user")
                self.stop_trading()
            except Exception as e:
                logger.error(f"Error in trading loop: {e}")
                time.sleep(5)
    
    def stop_trading(self):
        """Stop the trading loop"""
        logger.info("Stopping trading loop...")
        self.is_running = False
    
    def _trading_loop_iteration(self):
        """Single iteration of the trading loop"""
        now = datetime.now(self.tz)
        
        # Check market hours
        if not self._is_market_open():
            logger.debug("Market is closed")
            return
        
        # Update positions
        self._update_positions()
        
        # Check for exit conditions
        self._check_exits()
        
        # Scan for new signals
        if self._should_scan_for_signals():
            self._scan_and_execute_signals()
    
    def _is_market_open(self) -> bool:
        """Check if market is currently open"""
        now = datetime.now(self.tz)
        
        if now.weekday() >= 5:  # Weekend
            return False
        
        market_open = datetime.strptime(
            self.config.get('live_trading', {}).get('market_open', '09:15'),
            "%H:%M"
        ).time()
        market_close = datetime.strptime(
            self.config.get('live_trading', {}).get('market_close', '15:30'),
            "%H:%M"
        ).time()
        
        return market_open <= now.time() <= market_close
    
    def _update_positions(self):
        """Update current positions from broker"""
        if self.broker:
            self.positions = self.broker.get_positions()
            logger.debug(f"Updated positions: {len(self.positions)}")
    
    def _check_exits(self):
        """Check and execute exit conditions"""
        for symbol, position in self.positions.items():
            # Implement exit logic (target, stop loss, etc.)
            pass
    
    def _should_scan_for_signals(self) -> bool:
        """Determine if we should scan for new signals"""
        # Implement logic based on time, capital availability, etc.
        return True
    
    def _scan_and_execute_signals(self):
        """Scan for signals and execute trades"""
        if not self.strategy_service:
            return
        
        # Get signals from strategy service
        signals = self.strategy_service.generate_signals()
        
        for signal in signals:
            if signal.get('signal') == 1:  # Buy signal
                self._execute_buy(signal)
            elif signal.get('signal') == -1:  # Sell signal
                self._execute_sell(signal)
    
    def _execute_buy(self, signal: Dict[str, Any]):
        """Execute a buy order"""
        symbol = signal.get('symbol')
        qty = signal.get('quantity', 1)
        
        if self.broker:
            order_id = self.broker.place_order(
                symbol=symbol,
                qty=qty,
                side="BUY",
                type="MARKET"
            )
            
            if order_id:
                logger.info(f"Buy order placed: {symbol} | Order ID: {order_id}")
                self.orders[order_id] = {'type': 'BUY', 'symbol': symbol}
    
    def _execute_sell(self, signal: Dict[str, Any]):
        """Execute a sell order"""
        symbol = signal.get('symbol')
        qty = signal.get('quantity', 1)
        
        if self.broker:
            order_id = self.broker.place_order(
                symbol=symbol,
                qty=qty,
                side="SELL",
                type="MARKET"
            )
            
            if order_id:
                logger.info(f"Sell order placed: {symbol} | Order ID: {order_id}")
                self.orders[order_id] = {'type': 'SELL', 'symbol': symbol}
    
    def get_status(self) -> Dict[str, Any]:
        """Get current trading status"""
        return {
            'is_running': self.is_running,
            'positions_count': len(self.positions),
            'orders_count': len(self.orders),
            'market_open': self._is_market_open()
        }


def run_test():
    """Test function for live trading service"""
    print("Testing Live Trading Service...")
    
    service = LiveTradingService()
    print(f"Config loaded: {bool(service.config)}")
    print(f"Market open: {service._is_market_open()}")
    
    status = service.get_status()
    print(f"\nService Status:")
    for key, value in status.items():
        print(f"  {key}: {value}")
    
    print("\nLive Trading Service test complete!")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        run_test()
    else:
        print("Live Trading Service Module")
        print("Usage: python -m src.live_trading_service.live_trading_service test")
        run_test()
