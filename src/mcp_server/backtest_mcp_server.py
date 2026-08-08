"""
Backtesting MCP Server
=======================
Model Context Protocol (MCP) server for backtesting services.
Provides tools for running backtests on strategies.

Features:
- Run backtest for a single instrument based on strategy
- Support for both swing and intraday backtesting
- Access to backtest results and metrics
- Strategy optimization capabilities

Usage:
    python -m src.mcp_server.backtest_mcp_server
"""

import os
import sys
import json
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

# MCP imports
try:
    from mcp.server.fastmcp import FastMCP
    from mcp.types import Resource, Tool
    HAS_MCP = True
except ImportError:
    HAS_MCP = False
    print("⚠️  MCP not installed. Install with: pip install mcp")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

logger = logging.getLogger(__name__)

# Path resolution
_CUR_FILE = os.path.abspath(__file__)
_CUR_DIR = os.path.dirname(_CUR_FILE)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_CUR_DIR))

if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ═══════════════════════════════════════════════════════════════════════
# MCP Server Setup
# ═══════════════════════════════════════════════════════════════════════

if HAS_MCP:
    mcp = FastMCP(
        name="BacktestServiceMCP",
        instructions="""
        Backtesting Service MCP Server
        
        This server provides access to backtesting capabilities.
        You can:
        - Run backtests for single instruments
        - Test strategies on historical data
        - Get backtest metrics and performance analysis
        - Optimize strategy parameters
        
        Supported backtest types:
        - Swing trading (daily timeframe)
        - Intraday trading (minute/hourly timeframes)
        
        Available strategies are loaded from strategy_service/strategies/
        """
    )
else:
    mcp = None


# ═══════════════════════════════════════════════════════════════════════
# Backtest Service Integration
# ═══════════════════════════════════════════════════════════════════════

class BacktestServiceWrapper:
    """Wrapper around backtesting services for MCP tools."""
    
    def __init__(self):
        self._swing_engine = None
        self._intraday_engine = None
    
    @property
    def swing_engine(self):
        if self._swing_engine is None:
            try:
                from src.backtesting_swing_service.backtest_engine import BacktestEngine, load_strategy_class
                self._swing_engine_cls = BacktestEngine
                self._load_strategy = load_strategy_class
                logger.info("Swing BacktestEngine initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Swing BacktestEngine: {e}")
                self._swing_engine_cls = None
        return self._swing_engine_cls
    
    @property
    def intraday_engine(self):
        if self._intraday_engine is None:
            try:
                from src.backtesting_intraday_service.backtest_engine import BacktestEngine as IntradayBacktestEngine
                self._intraday_engine_cls = IntradayBacktestEngine
                logger.info("Intraday BacktestEngine initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Intraday BacktestEngine: {e}")
                self._intraday_engine_cls = None
        return self._intraday_engine_cls
    
    def get_available_strategies(self) -> List[str]:
        """Get list of available strategies."""
        try:
            strategies_dir = os.path.join(_PROJECT_ROOT, "src", "strategy_service", "strategies")
            if not os.path.exists(strategies_dir):
                return []
            
            strategies = []
            for folder in os.listdir(strategies_dir):
                folder_path = os.path.join(strategies_dir, folder)
                if os.path.isdir(folder_path) and not folder.startswith('_'):
                    config_file = os.path.join(folder_path, "config.yaml")
                    if os.path.exists(config_file):
                        strategies.append(folder)
            
            return sorted(strategies)
        except Exception as e:
            logger.error(f"Error fetching strategies: {e}")
            return []
    
    def get_strategy_info(self, strategy_name: str) -> Dict[str, Any]:
        """Get detailed information about a strategy."""
        try:
            import yaml
            
            strategies_dir = os.path.join(_PROJECT_ROOT, "src", "strategy_service", "strategies")
            config_file = os.path.join(strategies_dir, strategy_name, "config.yaml")
            
            if not os.path.exists(config_file):
                return {"error": f"Strategy '{strategy_name}' not found"}
            
            with open(config_file, 'r') as f:
                config = yaml.safe_load(f)
            
            # Read strategy description if available
            readme_file = os.path.join(strategies_dir, strategy_name, "README.md")
            description = ""
            if os.path.exists(readme_file):
                with open(readme_file, 'r') as f:
                    description = f.read()[:500]  # First 500 chars
            
            return {
                "name": strategy_name,
                "class_name": config.get("class_name", "Unknown"),
                "description": description or config.get("description", ""),
                "parameters": config.get("params", {}),
                "timeframe": config.get("timeframe", "auto"),
                "category": config.get("category", "general")
            }
        except Exception as e:
            logger.error(f"Error fetching strategy info: {e}")
            return {"error": str(e)}
    
    def run_backtest(
        self,
        symbol: str,
        strategy_name: str,
        start_date: str,
        end_date: str,
        initial_capital: float = 100000,
        interval: str = "1D",
        backtest_type: str = "swing"
    ) -> Dict[str, Any]:
        """
        Run a backtest for a single instrument.
        
        Args:
            symbol: Instrument symbol (e.g., "NIFTY", "RELIANCE")
            strategy_name: Name of the strategy to test
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format
            initial_capital: Initial capital for backtest
            interval: Timeframe ("1m", "5m", "15m", "1h", "1D", etc.)
            backtest_type: Type of backtest ("swing" or "intraday")
        
        Returns:
            Dictionary containing backtest results and metrics
        """
        try:
            # Load strategy
            try:
                strategy_cls = self._load_strategy(strategy_name, _PROJECT_ROOT)
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Failed to load strategy '{strategy_name}': {str(e)}",
                    "available_strategies": self.get_available_strategies()
                }
            
            # Create backtest config
            backtest_config = {
                "backtest": {
                    "initial_capital": initial_capital,
                    "target_profit_pct": 5.0,
                    "stop_loss_pct": 2.0,
                    "max_holding_days": 30,
                    "lookback_days": 100,
                    "position_weights": {
                        "max_new_positions": 5,
                        "max_per_sector": 1
                    },
                    "watchlist": "default",
                    "max_capital_allocation_per_day": 0.8
                },
                "backtest_service": {
                    "save_plots": False,
                    "save_metrics": True,
                    "verbose": False
                }
            }
            
            # Initialize strategy instance
            try:
                strategy_instance = strategy_cls()
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Failed to instantiate strategy: {str(e)}"
                }
            
            # Select engine based on backtest type
            if backtest_type == "intraday":
                engine_cls = self.intraday_engine
                if engine_cls is None:
                    return {"success": False, "error": "Intraday backtest engine not available"}
            else:
                engine_cls = self.swing_engine
                if engine_cls is None:
                    return {"success": False, "error": "Swing backtest engine not available"}
            
            # Create engine
            engine = engine_cls(
                strategy=strategy_instance,
                config=backtest_config,
                project_root=_PROJECT_ROOT
            )
            
            # Run backtest for single symbol
            symbols = [symbol]
            
            try:
                metrics = engine.run(symbols=symbols)
                
                # Convert metrics to dict
                metrics_dict = metrics.to_dict() if hasattr(metrics, 'to_dict') else {}
                
                # Get trades if available
                trades = []
                if hasattr(engine, 'trades'):
                    for trade in engine.trades[:20]:  # Limit to first 20 trades
                        trade_dict = {
                            "symbol": trade.symbol,
                            "entry_date": str(trade.entry_date) if trade.entry_date else None,
                            "exit_date": str(trade.exit_date) if trade.exit_date else None,
                            "entry_price": trade.entry_price,
                            "exit_price": trade.exit_price,
                            "pnl": trade.pnl,
                            "pnl_pct": trade.pnl_pct,
                            "exit_reason": trade.exit_reason
                        }
                        trades.append(trade_dict)
                
                return {
                    "success": True,
                    "symbol": symbol,
                    "strategy": strategy_name,
                    "start_date": start_date,
                    "end_date": end_date,
                    "initial_capital": initial_capital,
                    "final_equity": metrics_dict.get('final_equity', initial_capital),
                    "total_return_pct": metrics_dict.get('total_return_pct', 0),
                    "sharpe_ratio": metrics_dict.get('sharpe_ratio', 0),
                    "win_rate_pct": metrics_dict.get('win_rate_pct', 0),
                    "total_trades": metrics_dict.get('total_trades', 0),
                    "max_drawdown_pct": metrics_dict.get('max_drawdown_pct', 0),
                    "metrics": metrics_dict,
                    "sample_trades": trades,
                    "backtest_type": backtest_type,
                    "interval": interval
                }
                
            except Exception as e:
                logger.error(f"Backtest execution failed: {e}")
                import traceback
                return {
                    "success": False,
                    "error": f"Backtest execution failed: {str(e)}",
                    "traceback": traceback.format_exc()
                }
            
        except Exception as e:
            logger.error(f"Error running backtest: {e}")
            import traceback
            return {
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc()
            }
    
    def get_backtest_options(self) -> Dict[str, Any]:
        """Get all available backtesting options."""
        try:
            strategies = self.get_available_strategies()
            strategy_details = {}
            
            for strategy in strategies:
                info = self.get_strategy_info(strategy)
                if "error" not in info:
                    strategy_details[strategy] = info
            
            return {
                "strategies": strategies,
                "strategy_details": strategy_details,
                "backtest_types": ["swing", "intraday"],
                "supported_intervals": {
                    "swing": ["1D", "1W", "1M"],
                    "intraday": ["1m", "5m", "15m", "30m", "1h"]
                },
                "default_parameters": {
                    "initial_capital": 100000,
                    "target_profit_pct": 5.0,
                    "stop_loss_pct": 2.0,
                    "max_holding_days": 30
                }
            }
        except Exception as e:
            logger.error(f"Error fetching backtest options: {e}")
            return {"error": str(e)}


# Global wrapper instance
_backtest_wrapper = None

def get_backtest_wrapper():
    global _backtest_wrapper
    if _backtest_wrapper is None:
        _backtest_wrapper = BacktestServiceWrapper()
    return _backtest_wrapper


# ═══════════════════════════════════════════════════════════════════════
# MCP Resources
# ═══════════════════════════════════════════════════════════════════════

if HAS_MCP:
    @mcp.resource("backtest://strategies")
    def list_strategies() -> str:
        """List available backtesting strategies."""
        wrapper = get_backtest_wrapper()
        strategies = wrapper.get_available_strategies()
        
        if not strategies:
            return "No strategies available"
        
        return f"Available strategies ({len(strategies)}):\n" + "\n".join(f"- {s}" for s in strategies)
    
    @mcp.resource("backtest://options")
    def get_backtest_options_resource() -> str:
        """Get all available backtesting options."""
        wrapper = get_backtest_wrapper()
        options = wrapper.get_backtest_options()
        
        if "error" in options:
            return f"Error: {options['error']}"
        
        result = f"""
Backtesting Options
===================

Available Strategies ({len(options['strategies'])}):
{chr(10).join(f"- {s}" for s in options['strategies'])}

Backtest Types:
{chr(10).join(f"- {t}" for t in options['backtest_types'])}

Supported Intervals:
- Swing: {', '.join(options['supported_intervals']['swing'])}
- Intraday: {', '.join(options['supported_intervals']['intraday'])}

Default Parameters:
{json.dumps(options['default_parameters'], indent=2)}
"""
        return result


# ═══════════════════════════════════════════════════════════════════════
# MCP Tools
# ═══════════════════════════════════════════════════════════════════════

if HAS_MCP:
    @mcp.tool()
    def run_single_backtest(
        symbol: str,
        strategy: str,
        start_date: str,
        end_date: str,
        initial_capital: float = 100000,
        interval: str = "1D",
        backtest_type: str = "swing"
    ) -> Dict[str, Any]:
        """
        Run a backtest for a single instrument with specified strategy.
        
        Args:
            symbol: Instrument symbol (e.g., "NIFTY", "RELIANCE", "SBIN")
            strategy: Strategy name to test (use list_strategies to see available)
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format
            initial_capital: Initial capital for backtest (default: 100000)
            interval: Timeframe ("1m", "5m", "15m", "30m", "1h", "1D", "1W", "1M")
            backtest_type: Type of backtest ("swing" for daily, "intraday" for minute/hourly)
        
        Returns:
            Dictionary containing:
            - success: Boolean indicating if backtest succeeded
            - symbol: The tested symbol
            - strategy: The tested strategy
            - final_equity: Final equity value
            - total_return_pct: Total return percentage
            - sharpe_ratio: Sharpe ratio
            - win_rate_pct: Win rate percentage
            - total_trades: Number of trades executed
            - max_drawdown_pct: Maximum drawdown percentage
            - sample_trades: List of sample trade records
            - error: Error message if success is False
        """
        wrapper = get_backtest_wrapper()
        return wrapper.run_backtest(
            symbol=symbol,
            strategy_name=strategy,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            interval=interval,
            backtest_type=backtest_type
        )
    
    @mcp.tool()
    def list_backtest_strategies() -> List[str]:
        """
        List all available backtesting strategies.
        
        Returns:
            List of strategy names that can be used in run_single_backtest
        """
        wrapper = get_backtest_wrapper()
        return wrapper.get_available_strategies()
    
    @mcp.tool()
    def get_strategy_details(strategy_name: str) -> Dict[str, Any]:
        """
        Get detailed information about a specific strategy.
        
        Args:
            strategy_name: Name of the strategy to query
        
        Returns:
            Dictionary containing:
            - name: Strategy name
            - class_name: Python class name
            - description: Strategy description
            - parameters: Strategy parameters and their default values
            - timeframe: Recommended timeframe
            - category: Strategy category
        """
        wrapper = get_backtest_wrapper()
        return wrapper.get_strategy_info(strategy_name)
    
    @mcp.tool()
    def get_backtest_configuration_options() -> Dict[str, Any]:
        """
        Get all available backtesting configuration options.
        
        Returns:
            Dictionary containing:
            - strategies: List of available strategies
            - strategy_details: Detailed info for each strategy
            - backtest_types: Available backtest types (swing, intraday)
            - supported_intervals: Timeframes for each backtest type
            - default_parameters: Default backtest parameters
        """
        wrapper = get_backtest_wrapper()
        return wrapper.get_backtest_options()


# ═══════════════════════════════════════════════════════════════════════
# Main Entry Point
# ═══════════════════════════════════════════════════════════════════════

def main():
    if not HAS_MCP:
        print("❌ MCP library not installed.")
        print("   Install with: pip install mcp")
        print("\nAlternatively, you can test the BacktestServiceWrapper directly:")
        print("   from src.mcp_server.backtest_mcp_server import BacktestServiceWrapper")
        print("   wrapper = BacktestServiceWrapper()")
        print("   strategies = wrapper.get_available_strategies()")
        return
    
    print("=" * 60)
    print("🚀 Starting MCP Backtest Service Server")
    print("=" * 60)
    print(f"Server Name: BacktestServiceMCP")
    print(f"Project Root: {_PROJECT_ROOT}")
    print("=" * 60)
    
    # Initialize backtest wrapper
    wrapper = get_backtest_wrapper()
    strategies = wrapper.get_available_strategies()
    
    if not strategies:
        print("⚠️  Warning: No strategies found")
    else:
        print(f"✅ Found {len(strategies)} strategies: {', '.join(strategies)}")
    
    print("\n📋 Available Tools:")
    print("   - run_single_backtest")
    print("   - list_backtest_strategies")
    print("   - get_strategy_details")
    print("   - get_backtest_configuration_options")
    print("\n📋 Available Resources:")
    print("   - backtest://strategies/{strategy_name?}")
    print("   - backtest://options")
    print("\n🔗 Run with:")
    print("   python -m src.mcp_server.backtest_mcp_server")
    print("=" * 60)
    
    # Run MCP server
    mcp.run()


if __name__ == '__main__':
    main()
