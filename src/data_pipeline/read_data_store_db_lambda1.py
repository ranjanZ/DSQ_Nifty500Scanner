import yaml
import pandas as pd
import datetime as dt
import psycopg2
from psycopg2 import sql
import logging
import time
import os

import sys
from pathlib import Path
#sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Now import
from src.utils.fyers.fyers_broker import *
from src.data_pipeline.db_utils import delete_old_data
from  src.data_pipeline.db_utils import crate_table_spot_data
from  src.data_pipeline.db_utils import insert_dataframe_to_table


# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
from datetime import  datetime,timedelta




class FyersDataManager:
    def __init__(self, yaml_file_path="stock_list.yaml"):
        self.fyers_client = fyers_API()
        self.yaml_file_path = yaml_file_path
        self.stock_config = self.load_yaml_config()
        self.db_config = self.get_db_config()
        self.create_database_if_not_exists()  # Create DB if it doesn't exist
       
    def load_yaml_config(self):
        """Load stock configuration from YAML file"""
        try:
            if not os.path.exists(self.yaml_file_path):
                logger.error(f"YAML file not found: {self.yaml_file_path}")
                # Create a sample YAML file if it doesn't exist
                self.create_sample_yaml()
                return self.load_yaml_config()
            
            with open(self.yaml_file_path, 'r') as file:
                config = yaml.safe_load(file)
            logger.info(f"YAML configuration loaded successfully from {self.yaml_file_path}")
            return config
        except Exception as e:
            logger.error(f"Error loading YAML config from {self.yaml_file_path}: {e}")
            raise
    
    def get_db_config(self):
        """Extract database configuration from YAML"""
        try:
            db_config = self.stock_config.get('database_config', {})
            
            # Validate required database configuration
            required_fields = ['db_name', 'user', 'password', 'host', 'port']
            for field in required_fields:
                if field not in db_config:
                    raise ValueError(f"Missing required database configuration field: {field}")
            
            logger.info("Database configuration loaded successfully")
            return db_config
            
        except Exception as e:
            logger.error(f"Error loading database configuration: {e}")
            # Fallback to default configuration
            return {
                'db_name': 'spot_db',
                'user': 'postgres',
                'password': '123',
                'host': 'localhost',
                'port': '5432'
            }
    
    def create_sample_yaml(self):
        """Create a sample stock_list.yaml file if it doesn't exist"""
        sample_yaml_content = """# stock_list.yaml
database_config:
  db_name: "spot_db"
  user: "postgres"
  password: "123"
  host: "localhost"
  port: "5432"

fyers_stocks_config:
  api_provider: "Fyers"
  exchange: "NSE"
  market_segment: "NSE Capital Market"
  symbol_format: "NSE:SYMBOL-EQ"

watchlists:
  nifty_top_10:
    - name: "Reliance Industries Limited"
      fyers_symbol: "NSE:RELIANCE-EQ"
      sector: "Energy"
      market_cap: "Large Cap"
    
    - name: "Tata Consultancy Services Limited"
      fyers_symbol: "NSE:TCS-EQ"
      sector: "Information Technology"
      market_cap: "Large Cap"
    
    - name: "HDFC Bank Limited"
      fyers_symbol: "NSE:HDFCBANK-EQ"
      sector: "Financial Services"
      market_cap: "Large Cap"

  bank_stocks:
    - name: "HDFC Bank Limited"
      fyers_symbol: "NSE:HDFCBANK-EQ"
      sector: "Financial Services"
      market_cap: "Large Cap"
    
    - name: "ICICI Bank Limited"
      fyers_symbol: "NSE:ICICIBANK-EQ"
      sector: "Financial Services"
      market_cap: "Large Cap"
"""
        try:
            with open(self.yaml_file_path, 'w') as file:
                file.write(sample_yaml_content)
            logger.info(f"Sample YAML file created at {self.yaml_file_path}")
        except Exception as e:
            logger.error(f"Error creating sample YAML file: {e}")

    def create_database_if_not_exists(self):
        """Create database if it doesn't exist"""
        try:
            # Connect to default postgres database first
            conn = psycopg2.connect(
                dbname="postgres",
                user=self.db_config['user'],
                password=self.db_config['password'],
                host=self.db_config['host'],
                port=self.db_config['port']
            )
            conn.autocommit = True
            cursor = conn.cursor()
            
            # Check if database exists
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (self.db_config['db_name'],))
            exists = cursor.fetchone()
            
            if not exists:
                cursor.execute(f"CREATE DATABASE {self.db_config['db_name']}")
                logger.info(f"Database '{self.db_config['db_name']}' created successfully")
            else:
                logger.info(f"Database '{self.db_config['db_name']}' already exists")
            
            cursor.close()
            conn.close()
            
        except Exception as e:
            logger.error(f"Error creating database: {e}")
            raise


    def create_required_tables(self):
        """Create all required tables in the database"""

        #print(DB)
        try:
            # Import your existing DB functions
            # Assuming these functions are in the same file or imported
            
            # Create tables for all stocks in watchlists
            watchlists = self.stock_config.get('watchlists', {})
            for watchlist_name, stocks in watchlists.items():
                for stock in stocks:
                    table_name = self.get_table_name(stock['fyers_symbol'])
                    crate_table_spot_data(self.db_config['db_name'], table_name)
                    logger.info(f"Created table: {table_name} for {stock['name']}")
                
            logger.info("All required tables created successfully")
            
        except Exception as e:
            logger.error(f"Error creating tables: {e}")
            raise
    
    def get_table_name(self, fyers_symbol):
        """Convert Fyers symbol to table name format"""
        # Remove 'NSE:' prefix and replace special characters
        table_name = fyers_symbol.replace('NSE:', '').replace('-', '_').replace(':', '_').lower()
        table_name=table_name.replace('&','_')
        table_name = table_name.lstrip('0123456789')
        return table_name
    
    def get_latest_data_date(self, table_name):
        """Get the latest date for which data exists in the table"""
        try:
            conn = psycopg2.connect(
                dbname=self.db_config['db_name'],
                user=self.db_config['user'],
                password=self.db_config['password'],
                host=self.db_config['host'],
                port=self.db_config['port']
            )
            cursor = conn.cursor()
            
            # First check if table exists
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = %s
                );
            """, (table_name,))
            
            table_exists = cursor.fetchone()[0]
            
            if not table_exists:
                cursor.close()
                conn.close()
                return None
            
            query = f"SELECT MAX(time) FROM {table_name}"
            cursor.execute(query)
            result = cursor.fetchone()
            
            cursor.close()
            conn.close()
            
            if result[0] is not None:
                return result[0].date()
            else:
                return None
                
        except Exception as e:
            logger.error(f"Error getting latest date for {table_name}: {e}")
            return None
    
            return None
    
    def save_data_to_db(self, df, table_name):
        """Save DataFrame to database table"""
        try:
            
            if df is not None and not df.empty:
                crate_table_spot_data(db_name=self.db_config['db_name'],table_name=table_name)
                insert_dataframe_to_table(df, self.db_config['db_name'], table_name)
                logger.info(f"Saved {len(df)} rows to {table_name}")
                return True
            else:
                logger.warning(f"No data to save for {table_name}")
                return False
                
        except Exception as e:
            logger.error(f"Error saving data to {table_name}: {e}")
            return False
    
    def update_stock_data(self, symbol, interval="1", days_back=600):
        """Update data for a single stock"""
        table_name = self.get_table_name(symbol)
        latest_date = self.get_latest_data_date(table_name)
        
        if latest_date:
            from_date = latest_date + timedelta(days=1)
        else:
            # If no data exists, fetch last 2 years of data
            from_date = datetime.now().date() - timedelta(days=days_back)
        
        to_date = datetime.now().date()
        
        # Skip if we're already up to date
        if from_date >= to_date:
            logger.info(f"Data for {symbol} is already up to date")
            return True
        
        # Don't fetch future dates
        if from_date > datetime.now().date():
            logger.info(f"Data for {symbol} is already up to date")
            return True
        all_dfs = []
        for start in pd.date_range(pd.Timestamp(from_date), pd.Timestamp(to_date), freq='100D'):
            end = min(start + timedelta(days=99), pd.Timestamp(to_date))
            df_chunk = self.fyers_client.get_his_candle_data(symbol, start.date(), end.date(), interval)
            if df_chunk is not None and not df_chunk.empty:
                all_dfs.append(df_chunk)
        
        df = pd.concat(all_dfs, ignore_index=True) if all_dfs else pd.DataFrame()
        print(df)
        return self.save_data_to_db(df, table_name)


    
    def get_all_stocks(self):
        """Get all stocks from watchlists"""
        stocks = []
        watchlists = self.stock_config.get('watchlists', {})
        
        for watchlist_name, stock_list in watchlists.items():
            for stock in stock_list:
                # Add watchlist name to stock info for reference
                stock_with_watchlist = stock.copy()
                stock_with_watchlist['watchlist'] = watchlist_name
                stocks.append(stock_with_watchlist)
        return stocks
   

    def get_all_symbols(self):
        """Get all symbols from watchlists"""
        stocks = self.get_all_stocks()
        symbols = [stock['fyers_symbol'] for stock in stocks]
        # Remove duplicates
        return list(set(symbols))
    
    def update_all_stocks(self, interval="D", batch_delay=0.1):
        """Update data for all stocks in watchlists"""
        #print(DBG)
        try:
            stocks = self.get_all_stocks()[:200]
            
            for stock in stocks:
                symbol = stock['fyers_symbol']
                logger.info(f"Updating data for: {stock['name']} ({symbol}) from watchlist: {stock['watchlist']}")
                success = self.update_stock_data(symbol, interval,days_back=1000)
                if success:
                    logger.info(f"Successfully updated: {stock['name']}")
                else:
                    logger.error(f"Failed to update: {stock['name']}")
                
                time.sleep(batch_delay)  # Rate limiting
            
            logger.info("All stock data update completed")
            
        except Exception as e:
            logger.error(f"Error updating all stocks: {e}")
    
    def initialize_database(self):
        """First-time setup: create all tables and fetch historical data"""
        logger.info("Initializing database for first-time use")
        
        # Create all required tables
        self.create_required_tables()
        
        # Fetch complete historical data for all stocks
        self.update_all_stocks()
        
        logger.info("Database initialization completed")
    
    def print_watchlist_summary(self):
        """Print summary of all watchlists and stocks"""
        stocks = self.get_all_stocks()
        
        # Group by watchlist
        watchlist_summary = {}
        for stock in stocks:
            watchlist = stock['watchlist']
            if watchlist not in watchlist_summary:
                watchlist_summary[watchlist] = []
            watchlist_summary[watchlist].append(stock)
        
        logger.info("Watchlist Summary:")
        for watchlist, stock_list in watchlist_summary.items():
            logger.info(f"  {watchlist}: {len(stock_list)} stocks")
            for stock in stock_list:
                logger.info(f"    - {stock['name']} ({stock['fyers_symbol']})")
    def delete_all_stocks_old_data(self, num_days, batch_delay=0.001):
        """Delete old data for all stocks in watchlists"""
        try:
            stocks = self.get_all_stocks()
            
            for stock in stocks:
                symbol = stock['fyers_symbol']
                table_name = self.get_table_name(symbol)
        
                logger.info(f"Deleting old data for: {stock['name']} ({symbol}) from watchlist: {stock['watchlist']}")
                
                rows_deleted = delete_old_data(
                    db_name=self.db_config['db_name'],
                    table_name=table_name,
                    num_days=num_days
                )
                
                if rows_deleted is not None:
                    logger.info(f"Successfully deleted {rows_deleted} rows for: {stock['name']}")
                else:
                    logger.error(f"Failed to delete old data for: {stock['name']}")
                
                time.sleep(batch_delay)
            
            logger.info("All stock old data deletion completed")
            
        except Exception as e:
            logger.error(f"Error deleting old data for all stocks: {e}")
    


def delete_old_data_for_all_stocks(num_days):
    data_manager = FyersDataManager(yaml_file_path="config/stock_list.yaml")
    data_manager.delete_all_stocks_old_data(num_days)
    print(f"Old data older than {num_days} days deleted for all stocks")


def update():
    # Create data manager with stock_list.yaml
    data_manager = FyersDataManager(yaml_file_path="config/stock_list.yaml")
    #data_manager.delete_all()


    # Display loaded configuration
    logger.info("Database Configuration:")
    logger.info(f"  DB Name: {data_manager.db_config['db_name']}")
    logger.info(f"  Host: {data_manager.db_config['host']}:{data_manager.db_config['port']}")
    
    # Print watchlist summary
    data_manager.print_watchlist_summary()
    
    # Display all symbols
    symbols = data_manager.get_all_symbols()
    logger.info(f"Total unique symbols: {len(symbols)}")
    
    # First time setup - uncomment below line for first run
    #data_manager.initialize_database()
    
    # Regular update - check and update missing data
    data_manager.update_all_stocks(interval="D", batch_delay=0.1)

if __name__ == "__main__":
    # data_manager = FyersDataManager(yaml_file_path="config/stock_list.yaml")
    # data_manager.delete_all_stocks_old_data(1)    

    update()



