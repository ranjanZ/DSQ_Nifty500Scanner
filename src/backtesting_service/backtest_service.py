"""
Backtesting Service - Run backtests on historical data
Supports multiple strategies and configurations
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


class BacktestService:
    """Service for running backtests"""
    
    def __init__(self, config_path: str = "config/backtest_config.yaml"):
        self.config = self._load_config(config_path)
        self.results = {}
        
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Load configuration from YAML"""
        try:
            with open(config_path, 'r') as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            return {}
    
    def run_backtest(self, strategy_name: str, symbols: List[str],
                    start_date: str, end_date: str,
                    initial_capital: float = 100000) -> Dict[str, Any]:
        """
        Run backtest for a strategy on given symbols
        Returns performance metrics
        """
        logger.info(f"Running backtest: {strategy_name} from {start_date} to {end_date}")
        
        # Placeholder implementation
        # In production, this would integrate with backtest_normal.py logic
        
        results = {
            'strategy': strategy_name,
            'symbols': symbols,
            'period': {'start': start_date, 'end': end_date},
            'initial_capital': initial_capital,
            'final_capital': initial_capital * 1.1,  # Mock result
            'total_return_pct': 10.0,
            'sharpe_ratio': 1.5,
            'max_drawdown_pct': -5.0,
            'total_trades': 50,
            'win_rate': 0.60,
            'profit_factor': 1.8
        }
        
        self.results[strategy_name] = results
        return results
    
    def compare_strategies(self, strategy_names: List[str],
                          symbols: List[str],
                          start_date: str, end_date: str) -> pd.DataFrame:
        """Compare multiple strategies"""
        results_list = []
        
        for strategy in strategy_names:
            result = self.run_backtest(strategy, symbols, start_date, end_date)
            results_list.append(result)
        
        df = pd.DataFrame(results_list)
        return df
    
    def save_results(self, filename: str):
        """Save backtest results to file"""
        raise NotImplementedError("Not yet implemented")


def run_test():
    """Test function for backtest service"""
    print("Testing Backtest Service...")
    
    service = BacktestService()
    print(f"Config loaded: {bool(service.config)}")
    
    # Mock test
    result = service.run_backtest(
        strategy_name="SupportResistance",
        symbols=["RELIANCE", "TCS", "INFY"],
        start_date="2024-01-01",
        end_date="2024-12-31",
        initial_capital=100000
    )
    
    print(f"\nBacktest Results:")
    for key, value in result.items():
        print(f"  {key}: {value}")
    
    print("\nBacktest service test complete!")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        run_test()
    else:
        print("Backtest Service Module")
        print("Usage: python -m src.backtesting_service.backtest_service test")
        run_test()
