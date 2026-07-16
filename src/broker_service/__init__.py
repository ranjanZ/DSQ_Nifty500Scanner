"""
Broker Service - Provides unified interface for multiple brokers
"""

from .broker_base import BrokerBase, BrokerRegistry
from .fyers.fyers_broker_impl import FyersBroker

# Registry of available brokers
BROKER_REGISTRY = {
    'fyers': FyersBroker,
}

def get_broker(name: str, config: dict = None):
    """Get broker instance by name"""
    if name not in BROKER_REGISTRY:
        raise ValueError(f"Unknown broker: {name}. Available: {list(BROKER_REGISTRY.keys())}")
    return BROKER_REGISTRY[name](config=config)

def list_brokers():
    """List all available brokers"""
    return list(BROKER_REGISTRY.keys())

__all__ = [
    'BrokerBase',
    'BrokerRegistry', 
    'FyersBroker',
    'BROKER_REGISTRY',
    'get_broker',
    'list_brokers'
]
