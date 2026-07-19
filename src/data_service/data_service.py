"""
Data Service - Unified data access layer
Provides historical and real-time market data
"""

import os
import sys
import yaml
import time
import pandas as pd
from typing import Optional, List, Dict, Any
from datetime import datetime, date, timedelta
import logging



logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

logger = logging.getLogger(__name__)


# ── Path Resolution ──────────────────────────────────────────────────────────
_CUR_FILE = os.path.abspath(__file__)
_CUR_DIR = os.path.dirname(_CUR_FILE)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_CUR_DIR))

if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ── Imports ────────────────────────────────────────────────────────────────────
from src.data_service.db_utils import (
    get_table_content,
    crate_table_spot_data,
    insert_dataframe_to_table,
    delete_old_data,
    get_latest_data_date,
    table_exists,
    create_all_db,
)

try:
    from src.broker_service.fyers.fyers_broker_impl import FyersBroker
    BROKER_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Broker not available: {e}")
    BROKER_AVAILABLE = False


class DataService:
    """Unified data access service - path-independent, works from anywhere"""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.logger = logging.getLogger("DataService")
        
        self.stock_list_path = self._resolve_path(
            self.config.get('stock_list_path', 'config/default/stock_list.yaml')
        )
        self.db_name = self.config.get('db_name', 'spot_db')
        
        create_all_db([self.db_name])
        
        self._broker = None
        
    def _resolve_path(self, path: str) -> str:
        if os.path.isabs(path):
            return path
        return os.path.join(_PROJECT_ROOT, path)
    
    def _get_broker(self) -> Optional[Any]:
        if not BROKER_AVAILABLE:
            self.logger.error("FyersBroker not available")
            return None
        if self._broker is None:
            try:
                self._broker = FyersBroker()
                if not self._broker.connect():
                    self.logger.error("Broker connection failed")
                    self._broker = None
            except Exception as e:
                self.logger.error(f"Broker init failed: {e}")
                self._broker = None
        return self._broker
    
    def get_historical_data(self, symbol: str, start_date: str, end_date: str, 
                           interval: str = "1D", source: str = "db") -> Optional[pd.DataFrame]:
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
    
    def _symbol_to_table_name(self, symbol: str) -> str:
        if ':' in symbol:
            symbol = symbol.split(':', 1)[1]
        symbol = symbol.replace('-EQ', '').replace('-', '_').replace('&', '_')
        symbol = symbol.lstrip('0123456789')
        return f"{symbol.lower()}_eq"
    
    def _get_from_db(self, symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        try:
            table_name = self._symbol_to_table_name(symbol)
            df = get_table_content(
                db_name=self.db_name,
                table_name=table_name,
                start_date=start_date,
                end_date=end_date
            )
            if df is not None and not df.empty:
                self.logger.info(f"Fetched {len(df)} records for {symbol} from DB (table: {table_name})")
            else:
                self.logger.warning(f"No DB data found for {symbol} (table: {table_name})")
            return df
        except Exception as e:
            self.logger.error(f"DB fetch error for {symbol}: {e}")
            return None
    
    def _get_from_broker(self, symbol: str, start_date: str, end_date: str, 
                         interval: str) -> Optional[pd.DataFrame]:
        broker = self._get_broker()
        if broker is None:
            self.logger.error("Cannot fetch from broker - broker unavailable")
            return None
        
        try:
            if not symbol.startswith('NSE:'):
                symbol = f"NSE:{symbol}-EQ"
            
            df = broker.get_historical_data(symbol, start_date, end_date, interval)
            
            if df is not None and not df.empty:
                self.logger.info(f"Fetched {len(df)} records for {symbol} from broker")
            else:
                self.logger.warning(f"No broker data for {symbol}")
            
            return df
        except Exception as e:
            self.logger.error(f"Broker fetch error for {symbol}: {e}")
            return None
    
    def save_to_db(self, df: pd.DataFrame, symbol: str) -> bool:
        if df is None or df.empty:
            self.logger.warning("No data to save")
            return False
        
        try:
            table_name = self._symbol_to_table_name(symbol)
            crate_table_spot_data(db_name=self.db_name, table_name=table_name)
            insert_dataframe_to_table(df, self.db_name, table_name)
            self.logger.info(f"Saved {len(df)} rows to {table_name}")
            return True
        except Exception as e:
            self.logger.error(f"Error saving data for {symbol}: {e}")
            return False
    
    def update_stock_data(self, symbol: str, interval: str = "D", days_back: int = 600,
                          min_delay: float = 0.5) -> bool:
        """
        Update DB data for a single stock by fetching missing data from broker.
        
        Args:
            symbol: Stock symbol
            interval: "D" for daily, "1" for 1min, "5" for 5min, etc.
            days_back: How far back to fetch if table is empty
            min_delay: Minimum seconds between API calls (rate limiting)
        """
        if not BROKER_AVAILABLE:
            self.logger.error("Broker not available for update")
            return False
        
        table_name = self._symbol_to_table_name(symbol)
        
        # Find latest date in DB - returns datetime.date or None
        latest_date = get_latest_data_date(self.db_name, table_name)
        
        # Get today as date (not datetime) for comparison
        today = date.today()
        
        if latest_date:
            # latest_date is datetime.date, add 1 day
            from_date = latest_date + timedelta(days=1)
        else:
            # No data - fetch from days_back ago
            from_date = today - timedelta(days=days_back)
        
        # Both from_date and today are datetime.date now - safe comparison
        if from_date > today:
            self.logger.info(f"Data for {symbol} is already up to date (latest: {latest_date}, today: {today})")
            return True
        
        if from_date == today:
            self.logger.info(f"Data for {symbol} is already up to date")
            print(f"Data for {symbol} is already up to date")

            return True
        
        from_date_str = from_date.strftime('%Y-%m-%d')
        to_date_str = today.strftime('%Y-%m-%d')
        
        self.logger.info(f"[{symbol}] Fetching from {from_date_str} to {to_date_str}")
        
        # Fetch from broker in chunks with rate limiting
        broker = self._get_broker()
        if broker is None:
            return False
        
        all_dfs = []
        fyers_symbol = symbol if symbol.startswith('NSE:') else f"NSE:{symbol}-EQ"
        
        try:
            date_range = pd.date_range(pd.Timestamp(from_date_str), pd.Timestamp(to_date_str), freq='100D')
            
            for i, start in enumerate(date_range):
                end = min(start + timedelta(days=99), pd.Timestamp(to_date_str))
                
                self.logger.info(f"  [{symbol}] Chunk {i+1}/{len(date_range)}: {start.date()} to {end.date()}")
                
                df_chunk = broker.get_historical_data(
                    fyers_symbol, 
                    start.strftime('%Y-%m-%d'), 
                    end.strftime('%Y-%m-%d'), 
                    interval
                )
                
                if df_chunk is not None and not df_chunk.empty:
                    all_dfs.append(df_chunk)
                    self.logger.info(f"  [{symbol}] Got {len(df_chunk)} rows")
                else:
                    self.logger.warning(f"  [{symbol}] No data for chunk {i+1}")
                
                # Rate limiting: sleep between API calls
                if i < len(date_range) - 1:
                    time.sleep(min_delay)
                    
        except Exception as e:
            self.logger.error(f"Error fetching chunks for {symbol}: {e}")
        
        if not all_dfs:
            self.logger.warning(f"No new data fetched for {symbol}")
            return False
        
        df = pd.concat(all_dfs, ignore_index=True)
        
        # Remove duplicates if any overlap between chunks
        if 'time' in df.columns:
            df = df.drop_duplicates(subset=['time'], keep='first')
        
        return self.save_to_db(df, symbol)
    
    def update_all_stocks(self, watchlist: str = None, interval: str = "D", 
                          days_back: int = 600, batch_delay: float = 1.0,
                          chunk_delay: float = 0.5) -> None:
        """
        Update data for all stocks in a watchlist (or all stocks if no watchlist).
        
        Args:
            watchlist: Watchlist name, or None for all stocks
            interval: Data interval ("D", "1", "5", etc.)
            days_back: Days to fetch if table is empty
            batch_delay: Seconds between different stocks (default 1.0s for 500 stocks)
            chunk_delay: Seconds between chunk requests for same stock
        """
        stocks = self.get_stock_list(watchlist)
        total = len(stocks)
        self.logger.info(f"Updating {total} stocks (watchlist: {watchlist or 'ALL'})")
        
        success_count = 0
        fail_count = 0
        
        for idx, stock in enumerate(stocks, 1):
            symbol = stock.get('fyers_symbol')
            name = stock.get('name', symbol)
            if not symbol:
                continue
            
            #self.logger.info(f"[{idx}/{total}] Updating: {name} ({symbol})")
            print(f"[{idx}/{total}] Updating: {name} ({symbol})")

            try:
                success = self.update_stock_data(symbol, interval, days_back, min_delay=chunk_delay)
                if success:
                    success_count += 1
                    self.logger.info(f"[{idx}/{total}] Success: {name}")
                else:
                    fail_count += 1
                    self.logger.warning(f"[{idx}/{total}] No data: {name}")
            except Exception as e:
                fail_count += 1
                self.logger.error(f"[{idx}/{total}] Failed: {name} - {e}")
            
            # Rate limiting between stocks
            if idx < total:
                time.sleep(batch_delay)
        
        self.logger.info(f"Update complete: {success_count} succeeded, {fail_count} failed (total: {total})")
    
    def get_stock_list(self, watchlist: str = None) -> List[Dict[str, Any]]:
        try:
            if not os.path.exists(self.stock_list_path):
                self.logger.error(f"Stock list not found: {self.stock_list_path}")
                return []
            
            with open(self.stock_list_path, 'r') as f:
                stock_config = yaml.safe_load(f)
            
            watchlists = stock_config.get('watchlists', {})
            
            if watchlist:
                return watchlists.get(watchlist, [])
            
            all_stocks = []
            seen = set()
            for wl_name, stocks in watchlists.items():
                for stock in stocks:
                    sym = stock.get('fyers_symbol', stock.get('symbol', ''))
                    if sym and sym not in seen:
                        seen.add(sym)
                        stock_copy = stock.copy()
                        stock_copy['watchlist'] = wl_name
                        all_stocks.append(stock_copy)
            return all_stocks
            
        except Exception as e:
            self.logger.error(f"Error loading stock list: {e}")
            return []
    
    def get_symbols(self, watchlist: str = None) -> List[str]:
        stocks = self.get_stock_list(watchlist)
        return [s.get('fyers_symbol') for s in stocks if s.get('fyers_symbol')]
    
    def validate_data(self, df: pd.DataFrame) -> bool:
        required_cols = ['time', 'open', 'high', 'low', 'close', 'volume']
        
        if df is None or df.empty:
            return False
        
        missing = [col for col in required_cols if col not in df.columns]
        if missing:
            self.logger.error(f"Missing columns: {missing}")
            return False
        
        if df[required_cols].isnull().any().any():
            self.logger.warning("Data contains NaN values")
        
        return True
    
    def get_ltp(self, symbol: str) -> Optional[float]:
        broker = self._get_broker()
        if broker is None:
            return None
        try:
            if not symbol.startswith('NSE:'):
                symbol = f"NSE:{symbol}-EQ"
            return broker.get_ltp(symbol)
        except Exception as e:
            self.logger.error(f"Error getting LTP for {symbol}: {e}")
            return None
    
    def delete_old_data(self, symbol: str, num_days: int) -> Optional[int]:
        table_name = self._symbol_to_table_name(symbol)
        return delete_old_data(self.db_name, table_name, num_days)
    
    def disconnect(self):
        if self._broker:
            try:
                self._broker.disconnect()
            except Exception:
                pass
            self._broker = None


def run_test():
    print("Testing Data Service")
    print("=" * 50)
    
    service = DataService({
        'db_name': 'spot_db',
        'stock_list_path': 'config/default/stock_list.yaml'
    })
    
    print("\n--- Stock List ---")
    stocks = service.get_stock_list()
    print(f"Total unique stocks: {len(stocks)}")
    
    nifty_500 = service.get_stock_list('nifty_top_500')
    print(f"Nifty 500 stocks: {len(nifty_500)}")
    
    if stocks:
        symbol = stocks[0].get('fyers_symbol', 'NSE:SBIN-EQ')
        print(f"\n--- Testing with symbol: {symbol} ---")
        
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        
        print(f"\nFetching DB data from {start_date} to {end_date}")
        df = service.get_historical_data(symbol, start_date, end_date, source='db')
        if df is not None and not df.empty:
            print(f"Retrieved {len(df)} candles from DB")
            print(df.head())
        else:
            print("No DB data found")
        
        print(f"\nFetching broker data from {start_date} to {end_date}")
        df = service.get_historical_data(symbol, start_date, end_date, interval='D', source='broker')
        if df is not None and not df.empty:
            print(f"Retrieved {len(df)} candles from broker")
            print(df.head())
        else:
            print("No broker data found")
        
        print(f"\n--- LTP Test ---")
        ltp = service.get_ltp(symbol)
        print(f"LTP of {symbol}: {ltp}")
    
    want_update=input("Press Enter to update all Nifty 500 stocks (or Ctrl+C to skip)...")
    if want_update == "y":
        print("\nUpdating all Nifty 500 stocks...")
        service.update_all_stocks(watchlist='nifty_top_500', interval='D', days_back=300)




    service.disconnect()
    print("\nData service test completed")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        run_test()
    else:
        print("Data Service Module")
        print("Run with 'test' argument: python data_service.py test")

    """
    from src.data_service.data_service import DataService

    # Initialize (auto-creates DB if missing)
    service = DataService({
        'db_name': 'spot_db',
        'stock_list_path': 'config/default/stock_list.yaml'
    })

    # Get all Nifty 500 symbols
    symbols = service.get_symbols('nifty_top_500')

    # Update all Nifty 500 daily data
    service.update_all_stocks(watchlist='nifty_top_500', interval='D', days_back=60)

    # Fetch from DB
    df = service.get_historical_data('NSE:SBIN-EQ', '2026-01-01', '2026-07-18', source='db')

    # Fetch live from broker
    df = service.get_historical_data('NSE:SBIN-EQ', '2026-07-01', '2026-07-18', interval='D', source='broker')

    # Get LTP
    price = service.get_ltp('NSE:SBIN-EQ')

    # Cleanup
    service.disconnect()

    
    
    """