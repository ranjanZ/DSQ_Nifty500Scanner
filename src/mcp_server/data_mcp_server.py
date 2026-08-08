"""
MCP Server for Data Service
============================
Model Context Protocol (MCP) server that provides access to market data.
Allows extracting any data for any symbol for any timeframe.

Features:
- Fetch historical data for any symbol
- Support for multiple timeframes (1m, 5m, 15m, 1h, 1D, etc.)
- Access to OHLCV data from database or broker
- Real-time LTP quotes

Usage:
    python -m src.mcp_server.data_mcp_server
"""

import os
import sys
import json
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, date, timedelta

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
        name="DataServiceMCP",
        instructions="""
        Market Data Service MCP Server
        
        This server provides access to historical and real-time market data.
        You can:
        - Fetch historical OHLCV data for any symbol
        - Query data across different timeframes
        - Get latest available data dates
        - Retrieve real-time LTP quotes
        
        Supported timeframes: 1m, 5m, 15m, 30m, 1h, 1D, 1W, 1M
        Data sources: Database (primary), Broker (fallback)
        """
    )
else:
    mcp = None


# ═══════════════════════════════════════════════════════════════════════
# Data Service Integration
# ═══════════════════════════════════════════════════════════════════════

class DataServiceWrapper:
    """Wrapper around DataService for MCP tools."""
    
    def __init__(self):
        self._service = None
    
    @property
    def service(self):
        if self._service is None:
            try:
                from src.data_service.data_service import DataService
                self._service = DataService()
                logger.info("DataService initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize DataService: {e}")
                self._service = None
        return self._service
    
    def get_historical_data(self, symbol: str, start_date: str, end_date: str,
                           interval: str = "1D", source: str = "db") -> Optional[Dict]:
        """Fetch historical data for a symbol."""
        try:
            if self.service is None:
                return {"error": "DataService not available"}
            
            df = self.service.get_historical_data(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                interval=interval,
                source=source
            )
            
            if df is None or df.empty:
                return {
                    "symbol": symbol,
                    "start_date": start_date,
                    "end_date": end_date,
                    "interval": interval,
                    "records": 0,
                    "data": [],
                    "message": "No data found"
                }
            
            # Convert DataFrame to list of records
            records = []
            for _, row in df.iterrows():
                record = {
                    "timestamp": str(row.get('time', row.get('date', ''))),
                    "open": float(row.get('open', 0)),
                    "high": float(row.get('high', 0)),
                    "low": float(row.get('low', 0)),
                    "close": float(row.get('close', 0)),
                    "volume": int(row.get('volume', 0))
                }
                records.append(record)
            
            return {
                "symbol": symbol,
                "start_date": start_date,
                "end_date": end_date,
                "interval": interval,
                "records": len(records),
                "data": records
            }
            
        except Exception as e:
            logger.error(f"Error fetching historical data: {e}")
            return {"error": str(e)}
    
    def get_ltp(self, symbol: str) -> Optional[Dict]:
        """Get last traded price for a symbol."""
        try:
            if self.service is None:
                return {"error": "DataService not available"}
            
            ltp = self.service.get_ltp(symbol)
            
            if ltp is None:
                return {"symbol": symbol, "ltp": None, "message": "LTP not available"}
            
            return {
                "symbol": symbol,
                "ltp": float(ltp),
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error fetching LTP: {e}")
            return {"error": str(e)}
    
    def get_available_symbols(self, watchlist: str = None) -> List[str]:
        """Get list of available symbols."""
        try:
            if self.service is None:
                return []
            
            return self.service.get_symbols(watchlist)
            
        except Exception as e:
            logger.error(f"Error fetching symbols: {e}")
            return []
    
    def get_latest_data_date(self, symbol: str) -> Optional[str]:
        """Get the latest available data date for a symbol."""
        try:
            from src.data_service.db_utils import get_latest_data_date as db_get_latest
            
            table_name = self.service._symbol_to_table_name(symbol) if self.service else symbol.lower().replace('-eq', '_eq')
            latest_date = db_get_latest('spot_db_anamika', table_name)
            
            if latest_date:
                return str(latest_date)
            
            return None
            
        except Exception as e:
            logger.error(f"Error fetching latest date: {e}")
            return None


# Global wrapper instance
_data_wrapper = None

def get_data_wrapper():
    global _data_wrapper
    if _data_wrapper is None:
        _data_wrapper = DataServiceWrapper()
    return _data_wrapper


# ═══════════════════════════════════════════════════════════════════════
# MCP Resources
# ═══════════════════════════════════════════════════════════════════════

if HAS_MCP:
    @mcp.resource("data://symbols")
    def list_symbols() -> str:
        """List available symbols."""
        wrapper = get_data_wrapper()
        symbols = wrapper.get_available_symbols(None)
        
        if not symbols:
            return "No symbols available"
        
        return f"Available symbols ({len(symbols)}):\n" + "\n".join(symbols)
    
    
    @mcp.resource("data://latest-date/{symbol}")
    def get_latest_date(symbol: str) -> str:
        """Get the latest available data date for a symbol."""
        wrapper = get_data_wrapper()
        latest = wrapper.get_latest_data_date(symbol)
        
        if latest:
            return f"Latest data date for {symbol}: {latest}"
        
        return f"No data found for {symbol}"


# ═══════════════════════════════════════════════════════════════════════
# MCP Tools
# ═══════════════════════════════════════════════════════════════════════

if HAS_MCP:
    @mcp.tool()
    def fetch_historical_data(
        symbol: str,
        start_date: str,
        end_date: str,
        interval: str = "1D",
        source: str = "db"
    ) -> Dict[str, Any]:
        """
        Fetch historical OHLCV data for a symbol.
        
        Args:
            symbol: Instrument symbol (e.g., "NIFTY", "RELIANCE", "NSE:NIFTY-EQ")
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format
            interval: Timeframe ("1m", "5m", "15m", "30m", "1h", "1D", "1W", "1M")
            source: Data source ("db" for database, "broker" for broker API)
        
        Returns:
            Dictionary containing:
            - symbol: The requested symbol
            - start_date: Start date
            - end_date: End date
            - interval: Timeframe
            - records: Number of data points
            - data: List of OHLCV records
        """
        wrapper = get_data_wrapper()
        result = wrapper.get_historical_data(symbol, start_date, end_date, interval, source)
        return result
    
    
    @mcp.tool()
    def get_current_price(symbol: str) -> Dict[str, Any]:
        """
        Get the current last traded price (LTP) for a symbol.
        
        Args:
            symbol: Instrument symbol (e.g., "NIFTY", "RELIANCE")
        
        Returns:
            Dictionary containing:
            - symbol: The requested symbol
            - ltp: Last traded price
            - timestamp: When the price was fetched
        """
        wrapper = get_data_wrapper()
        return wrapper.get_ltp(symbol)
    
    
    @mcp.tool()
    def list_available_symbols(watchlist: str = None) -> List[str]:
        """
        List all available symbols that can be queried.
        
        Args:
            watchlist: Optional watchlist name to filter symbols
        
        Returns:
            List of symbol names
        """
        wrapper = get_data_wrapper()
        return wrapper.get_available_symbols(watchlist)
    
    
    @mcp.tool()
    def check_data_availability(symbol: str) -> Dict[str, Any]:
        """
        Check the latest available data date for a symbol.
        
        Args:
            symbol: Instrument symbol to check
        
        Returns:
            Dictionary containing:
            - symbol: The checked symbol
            - latest_date: Most recent data date available
            - has_data: Boolean indicating if data exists
        """
        wrapper = get_data_wrapper()
        latest = wrapper.get_latest_data_date(symbol)
        
        return {
            "symbol": symbol,
            "latest_date": latest,
            "has_data": latest is not None
        }


# ═══════════════════════════════════════════════════════════════════════
# MCP Prompts (Optional)
# ═══════════════════════════════════════════════════════════════════════

if HAS_MCP:
    @mcp.prompt()
    def analyze_symbol(symbol: str, days: int = 30) -> str:
        """
        Create a prompt for analyzing a symbol's recent performance.
        
        Args:
            symbol: Symbol to analyze
            days: Number of days to analyze
        
        Returns:
            Prompt text for analysis
        """
        end_date = date.today()
        start_date = end_date - timedelta(days=days)
        
        return f"""
        Please analyze the performance of {symbol} from {start_date} to {end_date}.
        
        Steps:
        1. Fetch historical data using fetch_historical_data tool
        2. Calculate key metrics (returns, volatility, etc.)
        3. Identify trends and patterns
        4. Provide insights on price movement
        """


# ═══════════════════════════════════════════════════════════════════════
# Main Entry Point
# ═══════════════════════════════════════════════════════════════════════

def main():
    if not HAS_MCP:
        print("❌ MCP library not installed.")
        print("   Install with: pip install mcp")
        print("\nAlternatively, you can test the DataServiceWrapper directly:")
        print("   from src.mcp_server.data_mcp_server import DataServiceWrapper")
        print("   wrapper = DataServiceWrapper()")
        print("   data = wrapper.get_historical_data('NIFTY', '2024-01-01', '2024-01-31')")
        return
    
    print("=" * 60)
    print("🚀 Starting MCP Data Service Server")
    print("=" * 60)
    print(f"Server Name: DataServiceMCP")
    print(f"Project Root: {_PROJECT_ROOT}")
    print("=" * 60)
    
    # Initialize data wrapper
    wrapper = get_data_wrapper()
    if wrapper.service is None:
        print("⚠️  Warning: DataService could not be initialized")
        print("   Some tools may not function properly")
    else:
        print("✅ DataService initialized successfully")
    
    print("\n📋 Available Tools:")
    print("   - fetch_historical_data")
    print("   - get_current_price")
    print("   - list_available_symbols")
    print("   - check_data_availability")
    print("\n📋 Available Resources:")
    print("   - data://symbols/{watchlist?}")
    print("   - data://latest-date/{symbol}")
    print("\n🔗 Run with:")
    print("   python -m src.mcp_server.data_mcp_server")
    print("=" * 60)
    
    # Run MCP server
    mcp.run()


if __name__ == '__main__':
    main()
