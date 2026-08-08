"""
Backtesting Swing Service - Backtest and optimize swing trading strategies
"""

from .backtest_engine import BacktestEngine

# OptimizationEngine might not exist in all versions
try:
    from .optimization_engine import Optimizer as OptimizationEngine
except ImportError:
    OptimizationEngine = None

__all__ = ['BacktestEngine', 'OptimizationEngine']
