# market_scanner.py
import pandas as pd
import logging
from typing import Dict, List, Any, Optional
import yaml
from datetime import datetime, timedelta
import numpy as np 
logger = logging.getLogger(__name__)
from src.strategy.strategy_base import TradingStrategy, StrategyFactory
from src.data_pipeline.db_utils import get_table_content



class MarketScanner:
    """Real-time market scanner for multiple trading strategies"""
    
    def __init__(self, yaml_config_path: str = "stock_list.yaml",watch_list=["nifty_top_500"]):
        self.yaml_config_path = yaml_config_path
        self.stock_config = self.load_yaml_config()
        self.strategies: Dict[str, TradingStrategy] = {}
        self.scan_results: Dict[str, List[Dict]] = {}
        self.watch_list=watch_list


    def load_yaml_config(self) -> Dict[str, Any]:
        """Load stock configuration from YAML file"""
        try:
            with open(self.yaml_config_path, 'r') as file:
                config = yaml.safe_load(file)
                logger.info(f"Loaded config with {len(config.get('watchlists', {}))} watchlists")
                return config
        except Exception as e:
            logger.error(f"Error loading YAML config: {e}")
            raise
    
    def get_table_name(self, fyers_symbol):
        """Convert Fyers symbol to table name format"""
        # Remove 'NSE:' prefix and replace special characters
        table_name = fyers_symbol.replace('NSE:', '').replace('-', '_').replace(':', '_').lower()
        table_name=table_name.replace('&','_')
        table_name = table_name.lstrip('0123456789')
        return table_name
    


    
    def get_stock_symbols(self) -> List[Dict[str, Any]]:
        """Get all stock symbols from watchlists with metadata"""
        symbols = []
        watchlists = self.stock_config.get('watchlists', {})

        for w_list in self.watch_list:
            if w_list not in watchlists:
                logger.warning(f"Watchlist '{w_list}' not found in config")
                continue

            for stock in watchlists[w_list]:
                symbols.append({
                    'name': stock['name'],
                    'symbol': stock['fyers_symbol'],
                    'watchlist': w_list,
                    'sector': stock.get('sector', 'Unknown'),
                    'market_cap': stock.get('market_cap', 'Unknown')
                })
        
        logger.info(f"Found {len(symbols)} stocks across {len(watchlists)} watchlists")
        return symbols
    
    def add_strategy(self, name: str, strategy: TradingStrategy):
        """Add strategy to scanner"""
        self.strategies[name] = strategy
        logger.info(f"Added strategy: {name}")
    
    def create_strategy(self, strategy_type: str, strategy_name: str, params: Dict[str, Any] = None):
        """Create and add strategy using StrategyFactory"""
        try:
            strategy = StrategyFactory.create_strategy(strategy_type, params)
            self.add_strategy(strategy_name, strategy)
        except Exception as e:
            logger.error(f"Error creating strategy {strategy_name}: {e}")
            raise
    
    def get_stock_data(self, symbol: str, days_back: int = 100) -> Optional[pd.DataFrame]:
        """Get stock data from database with proper formatting"""
        try:
            table_name = self.get_table_name(symbol)
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days_back)
            
            df = get_table_content(
                db_name=self.stock_config['database_config']['db_name'],
                table_name=table_name,
                start_date=start_date,
                end_date=end_date
            )
            
            if df is None or df.empty:
                logger.warning(f"No data found for {symbol}")
                return None
            
            # Ensure proper formatting
            df = df.sort_values('time')
            df['time'] = pd.to_datetime(df['time'])
            
            # Rename columns to match strategy requirements
            column_mapping = {
                'open': 'open',
                'high': 'high', 
                'low': 'low',
                'close': 'close',
                'volume': 'volume'
            }
            
            df = df.rename(columns=column_mapping)
            df = df[['time'] + list(column_mapping.values())]
            
            logger.debug(f"Retrieved {len(df)} records for {symbol}")
            return df
                
        except Exception as e:
            logger.error(f"Error getting data for {symbol}: {e}")
            return None
    
    def scan_single_stock(self, stock_info: Dict[str, Any], strategy_name: str) -> Dict[str, Any]:
        """Scan single stock with specific strategy"""
        if strategy_name not in self.strategies:
            return {
                'error': f'Strategy {strategy_name} not found',
                'symbol': stock_info['symbol'],
                'name': stock_info['name']
            }
        
        strategy = self.strategies[strategy_name]
        df = self.get_stock_data(stock_info['symbol'])
        
        if df is None or len(df) < 5:  # Minimum data points for reliable signals
            return {
                'error': 'Insufficient data mininum 5 data points',
                'symbol': stock_info['symbol'],
                'name': stock_info['name']
            }
       
        #print(DBG)
        try:
            # Generate signals using strategy
            signals_df = strategy.generate_signals(df)
            
            # Get latest signal
            #latest_signal = signals_df.iloc[-1]
            last_5 = signals_df.iloc[-5:]
            latest_signal = last_5[last_5['signal']!= 0].iloc[-1] if any(last_5['signal']!= 0) else last_5.iloc[-1]
            
            
            previous_signal = signals_df.iloc[-2] if len(signals_df) > 1 else latest_signal
            
            # Prepare result
            result = {
                'symbol': stock_info['symbol'],
                'name': stock_info['name'],
                'watchlist': stock_info['watchlist'],
                'sector': stock_info['sector'],
                'signal': self._signal_to_action(latest_signal['signal']),
                'signal_value': int(latest_signal['signal']),
                'previous_signal': self._signal_to_action(previous_signal['signal']),
                'confidence': self._calculate_confidence(signals_df),
                'current_price': float(latest_signal['close']),
                'timestamp': datetime.now(),
                'strategy': strategy_name,
                'data_points': len(signals_df)
            }
            
            # Add strategy-specific indicators
            result.update(self._extract_indicators(signals_df, strategy))
            
            return result
            
        except Exception as e:
            logger.error(f"Error scanning {stock_info['symbol']} with {strategy_name}: {e}")
            return {
                'error': str(e),
                'symbol': stock_info['symbol'],
                'name': stock_info['name']
            }
    
    def scan_all_stocks(self, strategy_name: str, min_confidence: float = 0.7) -> List[Dict[str, Any]]:
        """Scan all stocks with specific strategy and filter by confidence"""
        if strategy_name not in self.strategies:
            raise ValueError(f"Strategy '{strategy_name}' not found. Available: {list(self.strategies.keys())}")
        
        stocks = self.get_stock_symbols()
        results = []
        
        logger.info(f"Scanning {len(stocks)} stocks with {strategy_name}...")
        
        for i, stock in enumerate(stocks, 1):
            if i % 10 == 0:
                logger.info(f"Progress: {i}/{len(stocks)}")
                
            result = self.scan_single_stock(stock, strategy_name)
             
            if 'error' not in result:
                    if(result['signal']=="BUY" or result['signal']=="SELL"):
                        results.append(result)
                        #print(DB)
            else:
                logger.debug(f"Scan failed for {stock['symbol']}: {result['error']}")
        
        self.scan_results[strategy_name] = results
        logger.info(f"Scan completed: {len(results)} signals found with confidence >= {min_confidence}")
        
        return results
    
    def multi_strategy_scan(self, min_confidence: float = 0.7) -> Dict[str, List[Dict[str, Any]]]:
        """Scan with all strategies and return consolidated results"""
        results = {}
        
        for strategy_name in self.strategies:
            logger.info(f"Running scan for strategy: {strategy_name}")
            results[strategy_name] = self.scan_all_stocks(strategy_name, min_confidence)
        
        return results
    
    def get_scan_summary(self, strategy_name: str = None) -> Dict[str, Any]:
        """Get summary of scan results for specific strategy or all strategies"""
        if strategy_name:
            if strategy_name not in self.scan_results:
                self.scan_all_stocks(strategy_name)
            results = self.scan_results[strategy_name]
        else:
            # Aggregate all strategies
            all_results = []
            for strategy_results in self.scan_results.values():
                all_results.extend(strategy_results)
            results = all_results
        
        buy_signals = [r for r in results if r.get('signal') == 'BUY']
        sell_signals = [r for r in results if r.get('signal') == 'SELL']
        hold_signals = [r for r in results if r.get('signal') == 'HOLD']
        
        high_confidence_buys = [r for r in buy_signals if r.get('confidence', 0) >= 0.8]
        high_confidence_sells = [r for r in sell_signals if r.get('confidence', 0) >= 0.8]
        
        return {
            'total_stocks_scanned': len(results),
            'buy_signals': len(buy_signals),
            'sell_signals': len(sell_signals),
            'hold_signals': len(hold_signals),
            'high_confidence_buys': len(high_confidence_buys),
            'high_confidence_sells': len(high_confidence_sells),
            'scan_timestamp': datetime.now(),
            'strategies_used': list(self.strategies.keys()) if not strategy_name else [strategy_name]
        }
    
    def get_top_signals(self, strategy_name: str, top_n: int = 10, signal_type: str = 'BUY') -> List[Dict[str, Any]]:
        """Get top N signals by confidence for specific strategy and signal type"""
        if strategy_name not in self.scan_results:
            self.scan_all_stocks(strategy_name)
        
        signals = [
            r for r in self.scan_results[strategy_name] 
            if r.get('signal') == signal_type
        ]
        
        return sorted(signals, key=lambda x: x.get('confidence', 0), reverse=True)[:top_n]
    
    def _signal_to_action(self, signal_value: int) -> str:
        """Convert numeric signal to action string"""
        if signal_value == 1:
            return 'BUY'
        elif signal_value == -1:
            return 'SELL'
        else:
            return 'HOLD'
    
    def _calculate_confidence(self, signals_df: pd.DataFrame) -> float:
        """Calculate confidence score based on signal strength and consistency"""
        if len(signals_df) < 2:
            return 0.0
        
        recent_signals = signals_df['signal'].tail(5)
        
        # Confidence based on signal consistency
        if len(recent_signals) > 1:
            consistency = (recent_signals == recent_signals.iloc[-1]).mean()
        else:
            consistency = 1.0
        
        # Confidence based on signal strength (you can enhance this)
        current_signal = signals_df['signal'].iloc[-1]
        signal_strength = abs(current_signal)  # -1, 0, 1
        
        return min(consistency * signal_strength, 1.0)
    
    def _extract_indicators(self, signals_df: pd.DataFrame, strategy: TradingStrategy) -> Dict[str, Any]:
        """Extract relevant indicators from the signals dataframe"""
        latest = signals_df.iloc[-1]
        indicators = {}
        
        # Extract common indicators
        for col in signals_df.columns:
            if col not in ['signal', 'open', 'high', 'low', 'close', 'volume']:
                if pd.api.types.is_numeric_dtype(signals_df[col]):
                    indicators[f'indicator_{col}'] = float(latest[col])
        
        return indicators
    
    def export_results(self, filepath: str = None) -> str:
        """Export scan results to CSV file"""
        if not filepath:
            filepath = f"scan_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        all_results = []
        for strategy_name, results in self.scan_results.items():
            for result in results:
                result['strategy'] = strategy_name
                all_results.append(result)
        
        if all_results:
            df = pd.DataFrame(all_results)
            df.to_csv(filepath, index=False)
            logger.info(f"Results exported to {filepath}")
            return filepath
        else:
            logger.warning("No results to export")
            return ""


def get_stgy_out():
    logging.basicConfig(level=logging.INFO)

    # Example usage
    scanner = MarketScanner("stock_list.yaml")

    # Add strategies
    #scanner.create_strategy('rsi', 'RSI_Quick', {'rsi_period': 10, 'oversold': 25, 'overbought': 75})
    #scanner.create_strategy('ma_crossover', 'MA_Fast', {'fast_period': 10, 'slow_period': 20})
    scanner.create_strategy('Volume_Price_Strategy', 'Volume_Price_Strategy')

    # Run scans
    results = scanner.multi_strategy_scan(min_confidence=0.6)

    # Get summary
    summary = scanner.get_scan_summary()
    print("Scan Summary:", summary)

    return summary,results


# Example usage
if __name__ == "__main__":
    from strategy.market_scanner import *  

    #update data
    from data_pipeline.read_data_store_db_lambda1 import *
    #main()



    # This would be in your main application
    logging.basicConfig(level=logging.INFO)
    
    # Example usage
    scanner = MarketScanner("config/stock_list.yaml",watch_list=["nifty_top_500"])
    
    # Add strategies
    #scanner.create_strategy('rsi', 'RSI_Quick', {'rsi_period': 10, 'oversold': 25, 'overbought': 75})
    #scanner.create_strategy('ma_crossover', 'MA_Fast', {'fast_period': 10, 'slow_period': 20})
    scanner.create_strategy('Volume_Price_Strategy', 'Volume_Price_Strategy')
    
    # Run scans
    results = scanner.multi_strategy_scan(min_confidence=0.6)
    
    # Get summary
    summary = scanner.get_scan_summary()
    print("Scan Summary:", summary)
    
    # Get top BUY signals
    top_buys = scanner.get_top_signals('Volume_Price_Strategy', top_n=20, signal_type='BUY')
    top_sells = scanner.get_top_signals('Volume_Price_Strategy', top_n=20, signal_type='SELL')
    #print("Top BUY signals:", top_buys )
    

    # Get automatic scan date
    scan_date = datetime.now().strftime("%dth %B %Y")
    scan_time = datetime.now().strftime("%I:%M %p")

    print("=" * 60)
    print(f"📊 NIFTY 500 SCAN RESULTS - {scan_date} 📊")
    print(f"🕐 Scan Time: {scan_time}")
    print("=" * 60)

    for i, stock in enumerate(top_buys, 1):
        print(f"\n📌 STOCK #{i}")
        print(f"   Symbol: {stock['symbol'].replace('NSE:', '').replace('-EQ', '')}")
        print(f"   Name: {stock['name']}")
        print(f"   Watchlist: {stock['watchlist'].replace('_', ' ').title()}")
        print(f"   Sector: {stock['sector']}")
        print(f"   Signal: {stock['signal']} (Value: {stock['signal_value']})")
        print(f"   Previous Signal: {stock['previous_signal']}")
        print("-" * 50)




    # Get automatic scan date
    scan_date = datetime.now().strftime("%dth %B %Y")
    scan_time = datetime.now().strftime("%I:%M %p")

    print("=" * 60)
    print(f"📊 NIFTY 500 SCAN RESULTS - {scan_date} 📊")
    print(f"🕐 Scan Time: {scan_time}")
    print("=" * 60)

    for i, stock in enumerate(top_sells, 1):
        print(f"\n📌 STOCK #{i}")
        print(f"   Symbol: {stock['symbol'].replace('NSE:', '').replace('-EQ', '')}")
        print(f"   Name: {stock['name']}")
        print(f"   Watchlist: {stock['watchlist'].replace('_', ' ').title()}")
        print(f"   Sector: {stock['sector']}")
        print(f"   Signal: {stock['signal']} (Value: {stock['signal_value']})")
        print(f"   Previous Signal: {stock['previous_signal']}")
        print("-" * 50)




