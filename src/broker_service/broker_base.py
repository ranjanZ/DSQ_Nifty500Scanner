"""
Broker Service - Abstract base class for all brokers
Supports multiple brokers (Fyers, Zerodha, etc.)
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
import pandas as pd
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class BrokerBase(ABC):
    """Abstract base class for all broker implementations"""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.name = "BaseBroker"
        self.connected = False
        
    @abstractmethod
    def connect(self) -> bool:
        """Connect to broker API"""
        pass
    
    @abstractmethod
    def disconnect(self):
        """Disconnect from broker API"""
        pass
    
    @abstractmethod
    def place_order(self, symbol: str, qty: int, side: str, 
                    type: str = "MARKET", price: float = 0.0, 
                    product_type: str = "INTRADAY") -> Optional[str]:
        """Place an order and return order ID"""
        pass
    
    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order"""
        pass
    
    @abstractmethod
    def get_positions(self) -> Dict[str, Any]:
        """Get current positions"""
        pass
    
    @abstractmethod
    def get_orders(self) -> Dict[str, Any]:
        """Get current orders"""
        pass
    
    @abstractmethod
    def get_holdings(self) -> Dict[str, Any]:
        """Get current holdings"""
        pass
    
    @abstractmethod
    def get_historical_data(self, symbol: str, from_date: str, 
                           to_date: str, interval: str = "1") -> pd.DataFrame:
        """Get historical candle data"""
        pass
    
    @abstractmethod
    def get_quotes(self, symbols: List[str]) -> Dict[str, Any]:
        """Get real-time quotes for symbols"""
        pass
    
    def is_connected(self) -> bool:
        """Check if broker is connected"""
        return self.connected
    
    def validate_credentials(self) -> bool:
        """Validate broker credentials"""
        raise NotImplementedError("Subclasses must implement this method")


class BrokerFactory:
    """Factory class to create broker instances"""
    
    _brokers = {}
    
    @classmethod
    def register_broker(cls, name: str, broker_class):
        """Register a broker implementation"""
        cls._brokers[name.lower()] = broker_class
        logger.info(f"Registered broker: {name}")
    
    @classmethod
    def create_broker(cls, name: str, config: Dict[str, Any] = None) -> BrokerBase:
        """Create a broker instance"""
        broker_class = cls._brokers.get(name.lower())
        if not broker_class:
            raise ValueError(f"Unknown broker: {name}. Available: {list(cls._brokers.keys())}")
        return broker_class(config=config)
    
    @classmethod
    def get_available_brokers(cls) -> List[str]:
        """Get list of available brokers"""
        return list(cls._brokers.keys())


# Register default brokers
try:
    from src.broker_service.fyers.fyers_broker_impl import FyersBroker
    BrokerFactory.register_broker("fyers", FyersBroker)
    logger.info("Fyers broker registered")
except ImportError as e:
    logger.warning(f"Could not register Fyers broker: {e}")

try:
    from src.broker_service.zerodha.zerodha_broker_impl import ZerodhaBroker
    BrokerFactory.register_broker("zerodha", ZerodhaBroker)
    logger.info("Zerodha broker registered")
except ImportError as e:
    logger.warning(f"Could not register Zerodha broker: {e}")


def run_test():
    """Test function for broker service"""
    print("Testing Broker Service...")
    print(f"Available brokers: {BrokerFactory.get_available_brokers()}")
    
    # Test factory creation
    try:
        broker = BrokerFactory.create_broker("fyers")
        print(f"Created broker: {broker.name}")
    except Exception as e:
        print(f"Expected error (no credentials): {e}")
    
    print("Broker service test complete!")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        run_test()
    else:
        print("Broker Service Module")
        print("Usage: python -m src.broker_service.broker_base test")
        run_test()
