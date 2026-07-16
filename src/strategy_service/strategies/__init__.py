"""
All trading strategies available in the system
"""

from .madam_strategy import SupportResistanceStrategy
from .rsi_w_strategy import RSIWPatternStrategy
from .crossover_strategy import MovingAverageCrossoverStrategy

# Strategy registry for easy lookup
STRATEGY_REGISTRY = {
    'Support_Resistance': SupportResistanceStrategy,
    'RSI_W_Pattern': RSIWPatternStrategy,
    'MA_Crossover': MovingAverageCrossoverStrategy,
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
    'STRATEGY_REGISTRY',
    'get_strategy',
    'list_strategies'
]
