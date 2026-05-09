# scanner/market_scanner.py
import pandas as pd
import logging
from typing import Dict, List, Any, Optional
import yaml
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Import strategies
from strategy.strategy_base import TradingStrategy
from utils.db_utils import get_table_content


class MarketScanner:
    """Real-time market scanner for multiple trading strategies"""
    
    def __init__(self, config_path: str = "stock_list.yaml"):
        self.config_path = config_path
        self.stock_config = self.load_config()
        self.strategies: Dict[str, TradingStrategy] = {}
        self.scan_results: Dict[str, List[Dict]] = {}
        
    def load_config(self) -> Dict[str, Any]:
        """Load stock configuration from YAML file"""
        try:
            with open(self.config_path, 'r') as file:
                config = yaml.safe_load(file)
                logger.info(f"Loaded config from {self.config_path}")
                return config
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            raise
    
    def get_table_name(self, symbol: str) -> str:
        """Convert symbol to table name format"""
        return (
            symbol
            .replace('NSE:', '')
            .replace('-', '_')
            .replace(':', '_')
            .lower()
        )
    
    def get_stock_symbols(self) -> List[Dict[str, Any]]:
        """Get all stock symbols from watchlists"""
        symbols = []
        watchlists = self.stock_config.get('watchlists', {})
        
        for watchlist_name, stocks in watchlists.items():
            for stock in stocks:
                symbols.append({
                    'name': stock['name'],
                    'symbol': stock['fyers_symbol'],
                    'watchlist': watchlist_name,
                    'sector': stock.get('sector', 'Unknown')
                })
        
        logger.info(f"Found {len(symbols)} stocks")
        return symbols
    
    def add_strategy(self, name: str, strategy: TradingStrategy):
        """Add strategy to scanner"""
        self.strategies[name] = strategy
        logger.info(f"Added strategy: {name}")
    
    def get_stock_data(self, symbol: str, days: int = 200) -> Optional[pd.DataFrame]:
        """Get stock data from database"""
        try:
            table_name = self.get_table_name(symbol)
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            
            df = get_table_content(
                db_name=self.stock_config['database_config']['db_name'],
                table_name=table_name,
                start_date=start_date,
                end_date=end_date
            )
            
            if df is None or df.empty:
                logger.warning(f"No data for {symbol}")
                return None
            
            # Format data
            df = df.sort_values('time')
            df['time'] = pd.to_datetime(df['time'])
            
            # Ensure required columns exist
            required_cols = ['open', 'high', 'low', 'close', 'volume']
            for col in required_cols:
                if col not in df.columns:
                    logger.error(f"Missing column {col} for {symbol}")
                    return None
            
            return df[['time'] + required_cols]
                
        except Exception as e:
            logger.error(f"Error getting data for {symbol}: {e}")
            return None
    
    def scan_stock(self, stock_info: Dict[str, Any], strategy_name: str) -> Dict[str, Any]:
        """Scan single stock with specific strategy"""
        if strategy_name not in self.strategies:
            return {
                'error': f'Strategy {strategy_name} not found',
                'symbol': stock_info['symbol'],
                'name': stock_info['name']
            }
        
        strategy = self.strategies[strategy_name]
        df = self.get_stock_data(stock_info['symbol'])
        
        if df is None or len(df) < 20:  # Need enough data for meaningful signals
            return {
                'error': 'Insufficient data',
                'symbol': stock_info['symbol'],
                'name': stock_info['name']
            }
        
        #print(DBG)
        try:
            # Generate signals
            signals_df = strategy.generate_signals(df)
            
            # Get latest non-zero signal from last 5 candles
            last_5 = signals_df.iloc[-1:]
            
            # Find latest non-zero signal, or use the latest candle if all zeros
            non_zero = last_5[last_5['signal'] != 0]
            if not non_zero.empty:
                latest_signal = non_zero.iloc[-1]
            else:
                latest_signal = last_5.iloc[-1]
            
            # Get previous signal for comparison
            previous_signal = signals_df.iloc[-2] if len(signals_df) > 1 else latest_signal
            
            # Prepare result
            result = {
                'symbol': stock_info['symbol'],
                'name': stock_info['name'],
                'watchlist': stock_info['watchlist'],
                'signal': self.signal_to_text(latest_signal['signal']),
                'signal_value': int(latest_signal['signal']),
                'previous_signal': self.signal_to_text(previous_signal['signal']),
                'price': float(latest_signal['close']),
                'timestamp': datetime.now(),
                'strategy': strategy_name
            }
            
            return result
            
        except Exception as e:
            logger.error(f"Error scanning {stock_info['symbol']}: {e}")
            return {
                'error': str(e),
                'symbol': stock_info['symbol'],
                'name': stock_info['name']
            }
    
    def scan_all_stocks(self, strategy_name: str) -> List[Dict[str, Any]]:
        """Scan all stocks with specific strategy"""
        if strategy_name not in self.strategies:
            raise ValueError(f"Strategy '{strategy_name}' not found")
        
        stocks = self.get_stock_symbols()[:50]
        results = []
        
        logger.info(f"Scanning {len(stocks)} stocks with {strategy_name}...")
        
        for i, stock in enumerate(stocks, 1):
            result = self.scan_stock(stock, strategy_name)
            
            if 'error' not in result:
                if result['signal'] in ["BUY", "SELL"]:
                    results.append(result)
            
            # Log progress every 10 stocks
            if i % 10 == 0:
                logger.info(f"Progress: {i}/{len(stocks)}")
        
        self.scan_results[strategy_name] = results
        logger.info(f"Scan completed: {len(results)} signals found")
        
        return results
    
    def multi_strategy_scan(self) -> Dict[str, List[Dict[str, Any]]]:
        """Scan with all strategies"""
        results = {}
        
        for strategy_name in self.strategies:
            logger.info(f"Running scan for strategy: {strategy_name}")
            results[strategy_name] = self.scan_all_stocks(strategy_name)
        
        return results
    
    def get_scan_summary(self) -> Dict[str, Any]:
        """Get summary of scan results"""
        all_results = []
        for strategy_results in self.scan_results.values():
            all_results.extend(strategy_results)
        
        buy_signals = [r for r in all_results if r.get('signal') == 'BUY']
        sell_signals = [r for r in all_results if r.get('signal') == 'SELL']
        
        return {
            'total_stocks_scanned': len(all_results),
            'buy_signals': len(buy_signals),
            'sell_signals': len(sell_signals),
            'scan_timestamp': datetime.now(),
            'strategies_used': list(self.strategies.keys())
        }
    
    def signal_to_text(self, signal_value: int) -> str:
        """Convert numeric signal to text"""
        if signal_value == 1:
            return 'BUY'
        elif signal_value == -1:
            return 'SELL'
        return 'HOLD'
    
    def export_results(self, filename: str = None) -> str:
        """Export scan results to CSV file"""
        if not filename:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"scan_results_{timestamp}.csv"
        
        all_results = []
        for strategy_name, results in self.scan_results.items():
            for result in results:
                result['strategy'] = strategy_name
                all_results.append(result)
        
        if all_results:
            df = pd.DataFrame(all_results)
            df.to_csv(filename, index=False)
            logger.info(f"Results exported to {filename}")
            return filename
        
        logger.warning("No results to export")
        return ""
    


def display_chart(strategy,scanner,results):
    from utils.db_utils import get_table_content
    from utils.plot_chart import plot_signals
    end_date = datetime.now()
    start_date = end_date - timedelta(days=200)
    for result in results:
        data=get_table_content(
                    db_name='spot_db_anamika',
                    table_name=scanner.get_table_name(symbol=result['symbol']),
                    start_date=start_date,
                    end_date=end_date
                )

        print(result)
        signals = strategy.generate_signals(data)
        plot_signals(signals)







import logging
from strategy.madam_strategy import SupportResistanceStrategy
from strategy.rsi_w_strategy import RSIWPatternStrategy

# Configure logging
logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    """Simple usage example"""
    
    # Initialize scanner
    scanner = MarketScanner("stock_list.yaml")
    
    # Add strategy with default parameters
    #strategy = SupportResistanceStrategy()
    #scanner.add_strategy("SupportResistance", strategy)
    strategy = RSIWPatternStrategy()
    scanner.add_strategy("RSI_W_Pattern", strategy)
    
    # Run scan
    print("Starting scan...")
    #results = scanner.scan_all_stocks("SupportResistance")
    results = scanner.scan_all_stocks("RSI_W_Pattern")

    # Show results
    buy_signals = [r for r in results if r['signal'] == 'BUY']
    sell_signals = [r for r in results if r['signal'] == 'SELL']
    
    print(f"\nScan Results:")
    print(f"Total signals: {len(results)}")
    print(f"BUY signals: {len(buy_signals)}")
    print(f"SELL signals: {len(sell_signals)}")
    
    # Show first few BUY signals
    if buy_signals:
        print("\nBUY Signals:")
        for signal in buy_signals[:5]:
            print(f"  {signal['name']}: ₹{signal['price']:.2f}")
    
    # Export results
    scanner.export_results()
    display_chart(strategy,scanner,results)    
   





