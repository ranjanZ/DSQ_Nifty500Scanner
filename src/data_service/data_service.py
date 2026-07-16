"""
Data Service - Handles all data operations
Fetches, stores, and retrieves market data
"""

import os
import sys
import logging
import pandas as pd
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class DataService:
    """Central service for all data operations"""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.db_config = self.config.get('database', {})
        self.data_sources = {}
        
    def register_source(self, name: str, source):
        """Register a data source"""
        self.data_sources[name] = source
        logger.info(f"Registered data source: {name}")
    
    def get_historical_data(self, symbol: str, from_date: str, 
                           to_date: str, interval: str = "1",
                           source: str = None) -> Optional[pd.DataFrame]:
        """
        Get historical data for a symbol
        Args:
            symbol: Stock symbol
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (YYYY-MM-DD)
            interval: Candle interval (1, 5, 15, etc.)
            source: Data source name (uses default if None)
        Returns:
            DataFrame with OHLCV data
        """
        if source:
            if source not in self.data_sources:
                logger.error(f"Unknown data source: {source}")
                return None
            return self.data_sources[source].get_historical_data(
                symbol, from_date, to_date, interval
            )
        
        # Default: try broker sources first, then database
        for name, src in self.data_sources.items():
            if hasattr(src, 'get_historical_data'):
                df = src.get_historical_data(symbol, from_date, to_date, interval)
                if df is not None and not df.empty:
                    return df
        
        logger.warning(f"No data found for {symbol}")
        return None
    
    def get_latest_data(self, symbol: str, bars: int = 100, 
                       source: str = None) -> Optional[pd.DataFrame]:
        """Get latest N bars of data"""
        to_date = datetime.now().strftime("%Y-%m-%d")
        from_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        return self.get_historical_data(symbol, from_date, to_date, "1", source)
    
    def store_data(self, symbol: str, data: pd.DataFrame, 
                   source: str = None) -> bool:
        """Store data to database"""
        raise NotImplementedError("Database storage not yet implemented")
    
    def update_data(self, symbols: List[str], source: str = None) -> Dict[str, bool]:
        """Update data for multiple symbols"""
        results = {}
        for symbol in symbols:
            try:
                df = self.get_latest_data(symbol, source=source)
                if df is not None and not df.empty:
                    results[symbol] = True
                else:
                    results[symbol] = False
            except Exception as e:
                logger.error(f"Failed to update {symbol}: {e}")
                results[symbol] = False
        return results


class BrokerDataSource:
    """Data source that fetches from a broker"""
    
    def __init__(self, broker):
        self.broker = broker
    
    def get_historical_data(self, symbol: str, from_date: str, 
                           to_date: str, interval: str = "1") -> Optional[pd.DataFrame]:
        """Fetch historical data from broker"""
        if not self.broker.is_connected():
            logger.warning("Broker not connected")
            return None
        
        return self.broker.get_historical_data(symbol, from_date, to_date, interval)


def run_test():
    """Test function for data service"""
    print("Testing Data Service...")
    
    service = DataService()
    print(f"Data service initialized")
    print(f"Available sources: {list(service.data_sources.keys())}")
    
    # Test with mock data
    test_df = pd.DataFrame({
        'time': pd.date_range('2024-01-01', periods=10),
        'open': [100 + i for i in range(10)],
        'high': [105 + i for i in range(10)],
        'low': [95 + i for i in range(10)],
        'close': [102 + i for i in range(10)],
        'volume': [1000 + i*100 for i in range(10)]
    })
    
    print(f"\nSample data shape: {test_df.shape}")
    print(test_df.head())
    
    print("\nData service test complete!")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        run_test()
    else:
        print("Data Service Module")
        print("Usage: python -m src.data_service.data_service test")
        run_test()
