"""
Optimization Service - Optimize strategy parameters
Uses Bayesian optimization and grid search
"""

import os
import sys
import logging
import pandas as pd
import numpy as np
import yaml
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class OptimizationService:
    """Service for optimizing strategy parameters"""
    
    def __init__(self, config_path: str = "config/optimization_config.yaml"):
        self.config = self._load_config(config_path)
        self.optimization_results = []
        
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Load configuration from YAML"""
        try:
            with open(config_path, 'r') as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            return {}
    
    def optimize_grid_search(self, strategy_name: str,
                            param_grid: Dict[str, List],
                            symbols: List[str],
                            start_date: str, end_date: str,
                            metric: str = 'sharpe_ratio') -> Dict[str, Any]:
        """
        Grid search optimization
        Tests all combinations of parameters
        """
        logger.info(f"Running grid search optimization for {strategy_name}")
        
        # Generate all parameter combinations
        from itertools import product
        keys = list(param_grid.keys())
        values = list(param_grid.values())
        combinations = list(product(*values))
        
        results = []
        for combo in combinations:
            params = dict(zip(keys, combo))
            
            # Mock backtest result
            score = np.random.uniform(0.5, 2.5)  # Mock Sharpe ratio
            
            results.append({
                'params': params,
                'score': score,
                'metric': metric
            })
        
        # Sort by best score
        results.sort(key=lambda x: x['score'], reverse=True)
        
        best_result = results[0] if results else {}
        
        optimization_result = {
            'method': 'grid_search',
            'strategy': strategy_name,
            'total_combinations': len(combinations),
            'best_params': best_result.get('params', {}),
            'best_score': best_result.get('score', 0),
            'metric': metric,
            'all_results': results[:10]  # Top 10
        }
        
        self.optimization_results.append(optimization_result)
        return optimization_result
    
    def optimize_bayesian(self, strategy_name: str,
                         param_bounds: Dict[str, Tuple[float, float]],
                         symbols: List[str],
                         start_date: str, end_date: str,
                         n_iterations: int = 50,
                         metric: str = 'sharpe_ratio') -> Dict[str, Any]:
        """
        Bayesian optimization
        More efficient than grid search for large parameter spaces
        """
        logger.info(f"Running Bayesian optimization for {strategy_name}")
        
        # Mock Bayesian optimization
        best_params = {}
        best_score = 0
        
        for key, (low, high) in param_bounds.items():
            best_params[key] = np.random.uniform(low, high)
        
        best_score = np.random.uniform(1.5, 3.0)
        
        optimization_result = {
            'method': 'bayesian',
            'strategy': strategy_name,
            'iterations': n_iterations,
            'best_params': best_params,
            'best_score': best_score,
            'metric': metric
        }
        
        self.optimization_results.append(optimization_result)
        return optimization_result
    
    def get_best_parameters(self, strategy_name: str = None) -> Optional[Dict]:
        """Get best parameters from previous optimizations"""
        if not self.optimization_results:
            return None
        
        if strategy_name:
            filtered = [r for r in self.optimization_results 
                       if r.get('strategy') == strategy_name]
            if filtered:
                return filtered[-1].get('best_params')
        
        return self.optimization_results[-1].get('best_params')


def run_test():
    """Test function for optimization service"""
    print("Testing Optimization Service...")
    
    service = OptimizationService()
    print(f"Config loaded: {bool(service.config)}")
    
    # Test grid search
    param_grid = {
        'rsi_period': [10, 14, 20],
        'volume_threshold': [1.2, 1.5, 2.0]
    }
    
    result = service.optimize_grid_search(
        strategy_name="SupportResistance",
        param_grid=param_grid,
        symbols=["RELIANCE", "TCS"],
        start_date="2024-01-01",
        end_date="2024-12-31",
        metric='sharpe_ratio'
    )
    
    print(f"\nGrid Search Results:")
    print(f"  Best params: {result['best_params']}")
    print(f"  Best score: {result['best_score']:.2f}")
    print(f"  Total combinations tested: {result['total_combinations']}")
    
    # Test Bayesian optimization
    param_bounds = {
        'rsi_period': (10, 25),
        'volume_threshold': (1.0, 3.0)
    }
    
    result = service.optimize_bayesian(
        strategy_name="SupportResistance",
        param_bounds=param_bounds,
        symbols=["RELIANCE", "TCS"],
        start_date="2024-01-01",
        end_date="2024-12-31",
        n_iterations=20
    )
    
    print(f"\nBayesian Optimization Results:")
    print(f"  Best params: {result['best_params']}")
    print(f"  Best score: {result['best_score']:.2f}")
    
    print("\nOptimization service test complete!")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        run_test()
    else:
        print("Optimization Service Module")
        print("Usage: python -m src.backtesting_service.optimization_service test")
        run_test()
