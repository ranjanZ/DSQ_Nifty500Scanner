"""
Live Trading Service - Real-time trading execution
Uses broker service for order execution and strategy service for signals
"""

import os
import sys
import time
import logging
import yaml
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import pytz

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)


class LiveTradingService:
    """Main live trading service orchestrator"""
    
    def __init__(self, config_path: str = "config/live_trading_config.yaml"):
        self.config = self._load_config(config_path)
        self.trading_config = self.config.get('live_trading', {})
        
        # Initialize services
        self.broker = None
        self.strategy = None
        self.data_service = None
        
        # Trading state
        self.is_running = False
        self.positions = {}
        self.orders = {}
        
        self.logger = logging.getLogger("LiveTradingService")
        
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Load configuration from YAML"""
        try:
            with open(config_path, 'r') as f:
                return yaml.safe_load(f)
        except Exception as e:
            self.logger.error(f"Error loading config: {e}")
            raise
    
    def initialize(self):
        """Initialize all required services"""
        try:
            # Initialize broker
            from src.broker_service.fyers.fyers_broker_impl import FyersBroker
            self.broker = FyersBroker()
            
            if not self.broker.connect():
                raise Exception("Failed to connect to broker")
            
            self.logger.info("✅ Broker connected")
            
            # Initialize strategy
            from src.strategy_service.strategies import get_strategy
            strategy_name = self.trading_config.get('strategy_type', 'Support_Resistance')
            strategy_params = self.trading_config.get('strategy_params', {})
            self.strategy = get_strategy(strategy_name, strategy_params)
            
            self.logger.info(f"✅ Strategy initialized: {strategy_name}")
            
            # Initialize data service
            from src.data_service import DataService
            self.data_service = DataService({
                'db_name': self.config.get('database', {}).get('db_name', 'spot_db_anamika'),
                'stock_list_path': 'config/stock_list.yaml'
            })
            
            self.logger.info("✅ Data service initialized")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Initialization failed: {e}")
            return False
    
    def start(self):
        """Start live trading loop"""
        self.is_running = True
        self.logger.info("🚀 Starting live trading...")
        
        tz = pytz.timezone(self.trading_config.get('timezone', 'Asia/Kolkata'))
        
        while self.is_running:
            try:
                now = datetime.now(tz)
                
                # Check market hours
                if not self._is_market_open(now):
                    self.logger.info("Market closed, waiting...")
                    time.sleep(60)
                    continue
                
                # Run trading cycle
                self._trading_cycle()
                
                # Wait before next cycle
                time.sleep(self.trading_config.get('scan_interval_seconds', 300))
                
            except KeyboardInterrupt:
                self.logger.info("⏹️  Stopping by user request")
                self.stop()
                break
            except Exception as e:
                self.logger.error(f"Trading cycle error: {e}")
                time.sleep(60)
    
    def stop(self):
        """Stop live trading"""
        self.is_running = False
        if self.broker:
            self.broker.disconnect()
        self.logger.info("⏹️  Live trading stopped")
    
    def _is_market_open(self, now: datetime) -> bool:
        """Check if market is open"""
        if now.weekday() >= 5:  # Weekend
            return False
        
        market_open = datetime.strptime(self.trading_config.get('market_open', '09:15'), '%H:%M').time()
        market_close = datetime.strptime(self.trading_config.get('market_close', '15:30'), '%H:%M').time()
        
        return market_open <= now.time() <= market_close
    
    def _trading_cycle(self):
        """Execute one trading cycle"""
        self.logger.info("Running trading cycle...")
        
        # 1. Get stock list
        stocks = self.data_service.get_stock_list()
        
        # 2. Scan for signals
        signals = self._scan_for_signals(stocks[:50])  # Limit for speed
        
        # 3. Process signals
        for signal in signals:
            if signal['signal'] == 1:  # Buy signal
                self._process_buy_signal(signal)
        
        # 4. Monitor existing positions
        self._monitor_positions()
    
    def _scan_for_signals(self, stocks: List[Dict]) -> List[Dict]:
        """Scan stocks for trading signals"""
        signals = []
        
        for stock in stocks:
            symbol = stock['symbol']
            
            # Get historical data
            end_date = datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.now() - timedelta(days=100)).strftime('%Y-%m-%d')
            
            df = self.data_service.get_historical_data(symbol, start_date, end_date)
            
            if df is None or df.empty:
                continue
            
            # Generate signals
            signal_df = self.strategy.generate_signals(df)
            
            if signal_df is not None and not signal_df.empty:
                latest = signal_df.iloc[-1]
                if latest['signal'] == 1:
                    signals.append({
                        'symbol': symbol,
                        'signal': 1,
                        'price': latest['close'],
                        'strength': latest.get('signal_strength', 0),
                        'timestamp': latest['time']
                    })
        
        return signals
    
    def _process_buy_signal(self, signal: Dict):
        """Process a buy signal"""
        symbol = signal['symbol']
        
        # Check if we already have a position
        if symbol in self.positions:
            self.logger.info(f"Already have position in {symbol}")
            return
        
        # Calculate position size
        capital = self.trading_config.get('capital_per_trade', 50000)
        price = signal['price']
        qty = int(capital / price)
        
        if qty <= 0:
            return
        
        # Place order
        order_params = {
            'symbol': symbol,
            'qty': qty,
            'side': 'BUY',
            'type': 'MARKET',
            'product_type': 'CNC'
        }
        
        result = self.broker.place_order(order_params)
        
        if result.get('success'):
            self.positions[symbol] = {
                'entry_price': price,
                'quantity': qty,
                'order_id': result.get('order_id'),
                'entry_time': datetime.now()
            }
            self.logger.info(f"✅ Bought {qty} shares of {symbol} at {price}")
        else:
            self.logger.error(f"❌ Order failed for {symbol}: {result.get('error')}")
    
    def _monitor_positions(self):
        """Monitor and manage existing positions"""
        for symbol, pos in list(self.positions.items()):
            # Get current price
            ltp = self.broker.get_ltp(symbol)
            
            if ltp <= 0:
                continue
            
            # Calculate P&L
            pnl_pct = (ltp - pos['entry_price']) / pos['entry_price']
            
            # Check exit conditions
            target = self.trading_config.get('target_profit_pct', 0.05)
            stoploss = self.trading_config.get('stop_loss_pct', 0.02)
            
            if pnl_pct >= target:
                self._exit_position(symbol, "Target hit")
            elif pnl_pct <= -stoploss:
                self._exit_position(symbol, "Stoploss hit")
    
    def _exit_position(self, symbol: str, reason: str):
        """Exit a position"""
        pos = self.positions.get(symbol)
        if not pos:
            return
        
        qty = pos['quantity']
        
        # Place sell order
        order_params = {
            'symbol': symbol,
            'qty': qty,
            'side': 'SELL',
            'type': 'MARKET',
            'product_type': 'CNC'
        }
        
        result = self.broker.place_order(order_params)
        
        if result.get('success'):
            del self.positions[symbol]
            self.logger.info(f"✅ Exited {symbol}: {reason}")
        else:
            self.logger.error(f"❌ Exit failed for {symbol}")


def run_test():
    """Test live trading service initialization"""
    print("Testing Live Trading Service")
    print("=" * 50)
    
    service = LiveTradingService()
    
    if service.initialize():
        print("✅ Service initialized successfully")
        print("Note: Not starting actual trading loop in test mode")
    else:
        print("❌ Initialization failed")
    
    print("\n✅ Test completed")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        run_test()
    else:
        print("Live Trading Service")
        print("Run with 'test' argument to test initialization")
        print("Run without arguments to start live trading")
        
        service = LiveTradingService()
        if service.initialize():
            service.start()
