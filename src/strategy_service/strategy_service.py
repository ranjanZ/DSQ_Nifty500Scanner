"""
Strategy Service - Manage and execute trading strategies
Central service for all strategy operations
"""

import os
import sys
import logging
import pandas as pd
import yaml
from typing import Dict, List, Optional, Any
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class StrategyService:
    """Service for managing trading strategies"""
    
    def __init__(self, config_path: str = "config/backtest_config.yaml"):
        self.config = self._load_config(config_path)
        self.strategies = {}
        self.active_strategy = None
        
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Load configuration from YAML"""
        try:
            with open(config_path, 'r') as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            return {}
    
    def register_strategy(self, name: str, strategy_instance):
        """Register a strategy instance"""
        self.strategies[name] = strategy_instance
        logger.info(f"Registered strategy: {name}")
    
    def set_active_strategy(self, name: str) -> bool:
        """Set the active strategy for signal generation"""
        if name not in self.strategies:
            logger.error(f"Strategy not found: {name}")
            return False
        
        self.active_strategy = name
        logger.info(f"Active strategy set to: {name}")
        return True
    
    def generate_signals(self, data: Dict[str, pd.DataFrame] = None) -> List[Dict[str, Any]]:
        """Generate signals using the active strategy"""
        if not self.active_strategy:
            logger.warning("No active strategy selected")
            return []
        
        strategy = self.strategies.get(self.active_strategy)
        if not strategy:
            logger.error(f"Strategy not found: {self.active_strategy}")
            return []
        
        # Generate signals
        signals = []
        
        # This would integrate with actual strategy implementation
        # For now, return empty list
        logger.debug(f"Generated signals using {self.active_strategy}")
        return signals
    
    def backtest_strategy(self, strategy_name: str, data: pd.DataFrame,
                         initial_capital: float = 100000) -> Dict[str, Any]:
        """Backtest a strategy on historical data"""
        if strategy_name not in self.strategies:
            logger.error(f"Strategy not found: {strategy_name}")
            return {}
        
        strategy = self.strategies[strategy_name]
        
        # This would integrate with backtest_service
        logger.info(f"Backtesting strategy: {strategy_name}")
        
        return {
            'strategy': strategy_name,
            'total_return_pct': 0.0,
            'sharpe_ratio': 0.0,
            'max_drawdown_pct': 0.0
        }
    
    def get_strategy_info(self, name: str) -> Optional[Dict[str, Any]]:
        """Get information about a registered strategy"""
        if name not in self.strategies:
            return None
        
        strategy = self.strategies[name]
        return {
            'name': name,
            'parameters': getattr(strategy, 'params', {}),
            'required_columns': getattr(strategy, 'required_columns', [])
        }
    
    def list_strategies(self) -> List[str]:
        """List all registered strategies"""
        return list(self.strategies.keys())


def run_test():
    """Test function for strategy service"""
    print("Testing Strategy Service...")
    
    service = StrategyService()
    print(f"Config loaded: {bool(service.config)}")
    print(f"Registered strategies: {service.list_strategies()}")
    
    # Test with mock strategy
    class MockStrategy:
        def __init__(self):
            self.params = {'test': True}
            self.required_columns = ['open', 'high', 'low', 'close']
    
    service.register_strategy("MockStrategy", MockStrategy())
    print(f"\nAfter registration: {service.list_strategies()}")
    
    # Set active strategy
    service.set_active_strategy("MockStrategy")
    
    # Get strategy info
    info = service.get_strategy_info("MockStrategy")
    print(f"\nStrategy Info:")
    print(f"  Name: {info['name']}")
    print(f"  Parameters: {info['parameters']}")
    
    print("\nStrategy Service test complete!")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        run_test()
    else:
        print("Strategy Service Module")
        print("Usage: python -m src.strategy_service.strategy_service test")
        run_test()
