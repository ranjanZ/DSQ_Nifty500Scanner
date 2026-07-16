"""
Strategy Service - Manages all trading strategies
"""

from .strategy_base import StrategyBase
from .strategies import (
    SupportResistanceStrategy,
    RSIWPatternStrategy,
    MovingAverageCrossoverStrategy,
    STRATEGY_REGISTRY,
    get_strategy,
    list_strategies
)

__all__ = [
    'StrategyBase',
    'SupportResistanceStrategy',
    'RSIWPatternStrategy',
    'MovingAverageCrossoverStrategy',
    'STRATEGY_REGISTRY',
    'get_strategy',
    'list_strategies'
]
