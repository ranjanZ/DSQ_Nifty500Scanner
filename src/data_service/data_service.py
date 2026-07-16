"""
Data Service - Unified data access layer
Provides historical and real-time market data
"""

import pandas as pd
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class DataService:
    """Unified data access service"""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.logger = logging.getLogger("DataService")
        
    def get_historical_data(self, symbol: str, start_date: str, end_date: str, 
                           interval: str = "1D", source: str = "db") -> Optional[pd.DataFrame]:
        """
        Get historical OHLCV data
        
        Args:
            symbol: Stock symbol
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            interval: Data interval (1D, 1h, 5m, etc.)
            source: Data source ('db', 'broker', 'file')
        
        Returns:
            DataFrame with OHLCV data
        """
        try:
            if source == "db":
                return self._get_from_db(symbol, start_date, end_date)
            elif source == "broker":
                return self._get_from_broker(symbol, start_date, end_date, interval)
            else:
                self.logger.error(f"Unknown data source: {source}")
                return None
        except Exception as e:
            self.logger.error(f"Error fetching data: {e}")
            return None
    
    def _get_from_db(self, symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """Get data from database"""
        try:
            from src.data_pipeline.db_utils import get_table_content
            
            # Convert symbol to table name format
            table_name = f"{symbol.lower().replace(':', '_').replace('-', '_')}_eq"
            
            df = get_table_content(
                db_name=self.config.get('db_name', 'spot_db_anamika'),
                table_name=table_name,
                start_date=start_date,
                end_date=end_date
            )
            
            if df is not None and not df.empty:
                self.logger.info(f"Fetched {len(df)} records for {symbol} from DB")
            
            return df
        except Exception as e:
            self.logger.error(f"DB fetch error: {e}")
            return None
    
    def _get_from_broker(self, symbol: str, start_date: str, end_date: str, 
                         interval: str) -> Optional[pd.DataFrame]:
        """Get data from broker"""
        try:
            from src.broker_service.fyers.fyers_broker_impl import FyersBroker
            
            broker = FyersBroker()
            if not broker.connect():
                return None
            
            df = broker.get_historical_data(symbol, start_date, end_date, interval)
            broker.disconnect()
            
            return df
        except Exception as e:
            self.logger.error(f"Broker fetch error: {e}")
            return None
    
    def get_stock_list(self, watchlist: str = "nifty_500") -> List[Dict[str, str]]:
        """Get list of stocks from a watchlist"""
        try:
            import yaml
            with open(self.config.get('stock_list_path', 'config/stock_list.yaml'), 'r') as f:
                stock_config = yaml.safe_load(f)
            
            if watchlist in stock_config:
                return stock_config[watchlist]
            return []
        except Exception as e:
            self.logger.error(f"Error loading stock list: {e}")
            return []
    
    def validate_data(self, df: pd.DataFrame) -> bool:
        """Validate data quality"""
        required_cols = ['time', 'open', 'high', 'low', 'close', 'volume']
        
        if df is None or df.empty:
            return False
        
        missing = [col for col in required_cols if col not in df.columns]
        if missing:
            self.logger.error(f"Missing columns: {missing}")
            return False
        
        # Check for NaN values
        if df[required_cols].isnull().any().any():
            self.logger.warning("Data contains NaN values")
        
        return True


def run_test():
    """Test data service"""
    print("Testing Data Service")
    print("=" * 50)
    
    service = DataService({'db_name': 'spot_db_anamika'})
    
    # Test getting stock list
    stocks = service.get_stock_list()
    print(f"Available stocks: {len(stocks)}")
    
    if stocks:
        symbol = stocks[0]['symbol']
        print(f"Testing with symbol: {symbol}")
        
        # Test historical data
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        
        df = service.get_historical_data(symbol, start_date, end_date)
        if df is not None:
            print(f"✅ Retrieved {len(df)} candles")
            print(df.head())
        else:
            print("❌ Failed to retrieve data")
    
    print("\n✅ Data service test completed")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        run_test()
    else:
        print("Data Service Module")
        print("Run with 'test' argument: python data_service.py test")
