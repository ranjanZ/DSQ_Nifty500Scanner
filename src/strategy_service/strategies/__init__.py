"""
All trading strategies available in the system
Each strategy is now in its own folder with config.yaml
"""

from .volume_support_resistance_strategy import VolumeSupportResistanceStrategy as SupportResistanceStrategy
from .rsi_w_strategy import RSIWPatternStrategy
from .crossover_strategy import MovingAverageCrossoverStrategy
from .random_strategy import RandomStrategy

# Strategy registry for easy lookup
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
