"""
All trading strategies available in the system
Each strategy is in its own folder with config.yaml and strategy.py
"""

from .volume_support_resistance_strategy.strategy import VolumeSupportResistanceStrategy as SupportResistanceStrategy
from .rsi_w_strategy.strategy import RSIWPatternStrategy
from .crossover_strategy.strategy import MovingAverageCrossoverStrategy
from .random_strategy.strategy import RandomStrategy

# Strategy registry for easy lookup - uses class names directly from config
STRATEGY_REGISTRY = {
    'SupportResistance': SupportResistanceStrategy,
    'RSI_WPattern': RSIWPatternStrategy,
    'MA_Crossover': MovingAverageCrossoverStrategy,
    'RandomStrategy': RandomStrategy,
}

def get_strategy(name: str, params: dict = None):
    """Get strategy instance by name"""
    if name not in STRATEGY_REGISTRY:
        raise ValueError(f"Unknown strategy: {name}. Available: {list(STRATEGY_REGISTRY.keys())}")
    return STRATEGY_REGISTRY[name](params=params)

def list_strategies():
    """List all available strategies"""
    return list(STRATEGY_REGISTRY.keys())

__all__ = [
    'SupportResistanceStrategy',
    'RSIWPatternStrategy', 
    'MovingAverageCrossoverStrategy',
    'RandomStrategy',
    'STRATEGY_REGISTRY',
    'get_strategy',
    'list_strategies'
]
