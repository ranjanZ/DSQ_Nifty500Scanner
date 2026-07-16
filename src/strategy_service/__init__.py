"""
Strategy Service - Manages all trading strategies
"""

from .strategy_base import TradingStrategy
from .strategies import (
    SupportResistanceStrategy,
    RSIWPatternStrategy,
    MovingAverageCrossoverStrategy,
    STRATEGY_REGISTRY,
    get_strategy,
    list_strategies
)

__all__ = [
    'TradingStrategy',
    'SupportResistanceStrategy',
    'RSIWPatternStrategy',
    'MovingAverageCrossoverStrategy',
    'STRATEGY_REGISTRY',
    'get_strategy',
    'list_strategies'
]
