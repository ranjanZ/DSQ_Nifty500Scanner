"""
Broker Service - Abstract Base and Registry
Supports multiple broker implementations
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class BrokerBase(ABC):
    """
    Abstract base class for all broker implementations
    """
    
    def __init__(self, name: str, config: Dict[str, Any] = None):
        self.name = name
        self.config = config or {}
        self.connected = False
        self.logger = logging.getLogger(f"Broker.{name}")
    
    @abstractmethod
    def connect(self) -> bool:
        """Connect to broker API"""
        pass
    
    @abstractmethod
    def disconnect(self):
        """Disconnect from broker API"""
        pass
    
    @abstractmethod
    def get_historical_data(self, symbol: str, from_date: str, to_date: str, interval: str) -> Optional[Any]:
        """Fetch historical candle data"""
        pass
    
    @abstractmethod
    def get_ltp(self, symbol: str) -> float:
        """Get Last Traded Price"""
        pass
    
    @abstractmethod
    def place_order(self, order_params: Dict[str, Any]) -> Dict[str, Any]:
        """Place an order"""
        pass
    
    @abstractmethod
    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancel an order"""
        pass
    
    @abstractmethod
    def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """Get order status"""
        pass
    
    @abstractmethod
    def get_positions(self) -> List[Dict[str, Any]]:
        """Get all positions"""
        pass
    
    @abstractmethod
    def get_funds(self) -> Dict[str, Any]:
        """Get available funds"""
        pass
    
    def is_connected(self) -> bool:
        """Check if broker is connected"""
        return self.connected
    
    def is_market_open(self) -> bool:
        """Check if market is currently open"""
        now = datetime.now()
        # Indian market hours: 9:15 AM - 3:30 PM IST
        if now.weekday() >= 5:  # Weekend
            return False
        market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
        market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
        return market_open <= now <= market_close


class BrokerRegistry:
    """Registry for broker implementations"""
    
    _brokers: Dict[str, type] = {}
    
    @classmethod
    def register(cls, name: str, broker_class: type):
        """Register a broker implementation"""
        cls._brokers[name.lower()] = broker_class
        logger.info(f"Registered broker: {name}")
    
    @classmethod
    def get_broker(cls, name: str, config: Dict[str, Any] = None) -> BrokerBase:
        """Get broker instance by name"""
        broker_class = cls._brokers.get(name.lower())
        if not broker_class:
            raise ValueError(f"Unknown broker: {name}. Available: {list(cls._brokers.keys())}")
        return broker_class(config=config)
    
    @classmethod
    def list_brokers(cls) -> List[str]:
        """List all registered brokers"""
        return list(cls._brokers.keys())


def register_broker(name: str):
    """Decorator to register broker implementations"""
    def decorator(broker_class: type):
        BrokerRegistry.register(name, broker_class)
        return broker_class
    return decorator


if __name__ == "__main__":
    # Import fyers broker to register it
    import os
    import sys
    # Add the current directory and its parent to path so we can import fyers.fyers_broker_impl
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    if '.' not in sys.path:
        sys.path.insert(0, '.')
    
    try:
        from fyers.fyers_broker_impl import FyersBroker
    except Exception as e:
        print(f"Note: Could not import Fyers broker: {e}")
    
    print("Testing Broker Base Module")
    print("=" * 50)
    print(f"Available brokers: {BrokerRegistry.list_brokers()}")
    
    if BrokerRegistry.list_brokers():
        print("✅ Brokers registered successfully")
    else:
        print("⚠️  No brokers registered (import fyers.fyers_broker_impl to register)")
    
    print("✅ Broker base module loaded successfully")
