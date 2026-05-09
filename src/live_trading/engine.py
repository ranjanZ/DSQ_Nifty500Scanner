"""
Live Trading Engine with State Management
Runs during Indian market hours with full state persistence and recovery
"""

import os
import sys
import time
import logging
import yaml
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import pytz
from threading import Thread, Event, Lock
import traceback

from src.utils.fyers.fyers_broker import fyers_API
from src.strategy.rsi_w_strategy import RSIWPatternStrategy
from src.live_trading.state_manager import StateManager, PositionState, OrderState
from src.live_trading.broker_sync import BrokerSync


# Setup Logging
def setup_logging(log_dir: str = "logs") -> logging.Logger:
    """Configure logging for live trading"""
    os.makedirs(log_dir, exist_ok=True)
    
    logger = logging.getLogger("LiveTradingEngine")
    logger.setLevel(logging.DEBUG)
    
    # File handler - detailed
    log_file = os.path.join(log_dir, f"live_trading_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    fh = logging.FileHandler(log_file)
    fh.setLevel(logging.DEBUG)
    
    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    
    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    
    logger.addHandler(fh)
    logger.addHandler(ch)
    
    return logger


logger = setup_logging()


class LiveTradingEngine:
    """Main live trading engine with state management"""
    
    def __init__(self, config_path: str = "config/live_trading_config.yaml",
                 session_id: str = None, recover: bool = True):
        """
        Initialize Live Trading Engine
        
        Args:
            config_path: Path to configuration file
            session_id: Session ID (auto-generated if None)
            recover: Recover from previous session if available
        """
        # Load config
        self.config = self._load_config(config_path)
        self.trading_config = self.config['live_trading']
        
        # Initialize session
        self.session_id = session_id or f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        
        # Initialize components
        self.broker = fyers_API()
        self.strategy = self._create_strategy()
        self.state_manager = StateManager(state_dir="data/trading_state")
        self.broker_sync = BrokerSync(broker=self.broker, state_manager=self.state_manager)
        
        # Timezone
        self.tz = pytz.timezone(self.trading_config['timezone'])
        
        # Trading state
        self.market_open = False
        self.trading_active = Event()
        self.stop_flag = Event()
        self.state_lock = Lock()
        
        # Recover from previous session if available
        if recover:
            self._recover_session()
        else:
            self.state_manager.create_new_session(
                self.session_id,
                self.trading_config['initial_capital']
            )
        
        logger.info(f"Live Trading Engine initialized - Session: {self.session_id}")
    
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Load configuration from YAML file"""
        try:
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
            logger.info(f"Configuration loaded from {config_path}")
            return config
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            raise
    
    def _create_strategy(self) -> object:
        """Create trading strategy"""
        strategy_type = self.trading_config.get('strategy_type', 'RSI_W_Pattern')
        strategy_params = self.trading_config.get('strategy_params', {})
        
        if strategy_type == "RSI_W_Pattern":
            return RSIWPatternStrategy(params=strategy_params)
        else:
            raise ValueError(f"Unknown strategy type: {strategy_type}")
    
    def _recover_session(self) -> bool:
        """Recover from previous session"""
        try:
            logger.info("Attempting to recover from previous session")
            
            # Find previous sessions
            sessions = self.state_manager.list_sessions()
            
            if not sessions:
                logger.info("No previous sessions found, creating new session")
                self.state_manager.create_new_session(
                    self.session_id,
                    self.trading_config['initial_capital']
                )
                return True
            
            # Load the most recent session
            last_session_id = sessions[-1]
            logger.info(f"Recovering session: {last_session_id}")
            
            session = self.state_manager.load_session(last_session_id)
            
            if session is None:
                logger.warning("Failed to load last session, creating new session")
                self.state_manager.create_new_session(
                    self.session_id,
                    self.trading_config['initial_capital']
                )
                return False
            
            self.session_id = last_session_id
            
            # Sync with broker
            logger.info("Syncing recovered session with broker")
            sync_result = self.broker_sync.full_sync()
            
            if not sync_result.get('success', False):
                logger.warning(f"Broker sync had issues: {sync_result}")
            
            # Print recovered state
            summary = self.state_manager.get_session_summary()
            logger.info(f"Recovered session: {summary}")
            
            return True
        
        except Exception as e:
            logger.error(f"Error recovering session: {e}")
            traceback.print_exc()
            return False
    
    def is_market_open(self) -> bool:
        """Check if Indian market is currently open"""
        now = datetime.now(self.tz)
        return True
    
    
        # Market closed on weekends
        if now.weekday() >= 5:  # Saturday=5, Sunday=6
            logger.info("Market closed on weekends")
            return False
        
        market_open = datetime.strptime(
            self.trading_config['market_open'], "%H:%M"
        ).time()
        market_close = datetime.strptime(
            self.trading_config['market_close'], "%H:%M"
        ).time()
        
        return market_open <= now.time() <= market_close
        

    def get_historical_data(self, symbol: str, days_back: int = 30):
        """Fetch historical data"""
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            past_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
            
            data = self.broker.get_his_candle_data(
                symbol=symbol,
                fromdate=past_date,
                todate=today,
                interval="1"
            )
            
            return data
        
        except Exception as e:
            logger.error(f"Error fetching data for {symbol}: {e}")
            return None
    
    def scan_for_signals(self, symbols: List[str]) -> Dict[str, Any]:
        """Scan symbols for trading signals"""
        signals = {}
        
        for symbol in symbols:
            try:
                data = self.get_historical_data(symbol, days_back=30)
                
                if data is None or len(data) < 20:
                    continue
                
                # Generate signals
                signal_data = self.strategy.generate_signals(data)
                
                if signal_data is not None and not signal_data.empty:
                    latest_signal = signal_data.iloc[-1]
                    
                    if latest_signal.get('signal', 0) != 0:
                        signals[symbol] = {
                            'signal': latest_signal['signal'],
                            'price': latest_signal.get('close', 0),
                            'strength': latest_signal.get('signal_strength', 0)
                        }
            
            except Exception as e:
                logger.debug(f"Error scanning {symbol}: {e}")
        
        return signals
    
    def place_buy_order(self, symbol: str, signal_info: Dict) -> bool:
        """Place a buy order"""
        try:
            with self.state_lock:
                # Check if position already exists
                if self.state_manager.get_position(symbol) is not None:
                    logger.warning(f"Position already exists for {symbol}")
                    return False
                
                # Check max positions
                positions = self.state_manager.get_all_positions()
                if len(positions) >= self.trading_config['max_positions']:
                    logger.warning(f"Max positions reached {len(positions)}")
                    return False
                
                # Calculate position size
                price = signal_info['price']
                max_pos_size = self.trading_config['max_position_size']
                quantity = int(max_pos_size / price)
                
                if quantity <= 0:
                    logger.warning(f"Invalid quantity for {symbol}")
                    return False
                
                # Create position state
                position = PositionState(
                    symbol=symbol,
                    entry_price=price,
                    entry_time=datetime.now(self.tz).isoformat(),
                    quantity=quantity,
                    capital_used=quantity * price,
                    entry_signal=str(signal_info),
                    target_price=price * (1 + self.trading_config['target_profit_pct']),
                    stop_loss_price=price * (1 - self.trading_config['stop_loss_pct']),
                    highest_price=price
                )
                
                # Add to state
                if self.state_manager.add_position(position):
                    logger.info(f"Buy order placed: {symbol} @ {price}")
                    return True
            
            return False
        
        except Exception as e:
            logger.error(f"Error placing buy order for {symbol}: {e}")
            return False
    
    def check_exit_signals(self):
        """Check for exit signals"""
        try:
            positions = self.state_manager.get_all_positions()
            
            for symbol, position in positions.items():
                try:
                    # Get current price
                    data = self.get_historical_data(symbol, days_back=5)
                    
                    if data is None or data.empty:
                        continue
                    
                    current_price = data.iloc[-1]['close']
                    
                    # Update highest price
                    if current_price > position.highest_price:
                        self.state_manager.update_position(symbol, {'highest_price': current_price})
                    
                    exit_reason = None
                    
                    # Check stop loss
                    if current_price <= position.stop_loss_price:
                        exit_reason = "STOP_LOSS"
                    
                    # Check target
                    elif current_price >= position.target_price:
                        exit_reason = "TARGET_HIT"
                    
                    # Check trailing stop
                    trailing_stop = position.highest_price * (1 - self.trading_config.get('trailing_stop_pct', 0.01))
                    if current_price <= trailing_stop:
                        exit_reason = "TRAILING_STOP"
                    
                    # Exit if signal triggered
                    if exit_reason:
                        self.close_position(symbol, current_price, exit_reason)
                
                except Exception as e:
                    logger.debug(f"Error checking exit for {symbol}: {e}")
        
        except Exception as e:
            logger.error(f"Error in exit signal check: {e}")
    
    def close_position(self, symbol: str, exit_price: float, reason: str) -> bool:
        """Close a position"""
        try:
            with self.state_lock:
                position = self.state_manager.get_position(symbol)
                
                if position is None:
                    return False
                
                # Calculate P&L
                pnl = (exit_price - position.entry_price) * position.quantity
                pnl_pct = ((exit_price - position.entry_price) / position.entry_price) * 100
                
                # Update position
                updates = {
                    'status': 'CLOSED',
                    'exit_price': exit_price,
                    'exit_time': datetime.now(self.tz).isoformat(),
                    'pnl': pnl,
                    'pnl_pct': pnl_pct
                }
                self.state_manager.update_position(symbol, updates)
                self.state_manager.remove_position(symbol)
                
                logger.info(f"Position closed: {symbol} @ {exit_price} | P&L: {pnl:.2f} ({pnl_pct:.2f}%) | Reason: {reason}")
                return True
        
        except Exception as e:
            logger.error(f"Error closing position {symbol}: {e}")
            return False
    
    def print_status(self):
        """Print current trading status"""
        try:
            summary = self.state_manager.get_session_summary()
            sync_status = self.broker_sync.get_sync_status()
            
            logger.info("=" * 80)
            logger.info("TRADING STATUS")
            logger.info("=" * 80)
            logger.info(f"Session ID: {summary.get('session_id')}")
            logger.info(f"Start Time: {summary.get('start_time')}")
            logger.info(f"Open Positions: {summary.get('open_positions')}")
            logger.info(f"Total Orders: {summary.get('total_orders')}")
            logger.info(f"Total P&L: ${summary.get('total_pnl'):.2f}")
            logger.info(f"Closed Positions: {summary.get('closed_positions')}")
            logger.info(f"Available Capital: ${summary.get('capital_available'):.2f}")
            logger.info(f"Capital Used: ${summary.get('capital_used'):.2f}")
            logger.info("")
            logger.info("SYNC STATUS")
            logger.info("=" * 80)
            logger.info(f"Local Positions: {sync_status.get('local_positions')}")
            logger.info(f"Broker Positions: {sync_status.get('broker_positions')}")
            logger.info(f"Synced: {sync_status.get('synced')}")
            logger.info("=" * 80)
        
        except Exception as e:
            logger.error(f"Error printing status: {e}")
    
    def run_trading_loop(self):
        """Main trading loop"""
        logger.info("Starting trading loop")
        scan_interval = self.trading_config['data_refresh_interval']
        last_scan_time = 0
        sync_interval = 300  # Sync every 5 minutes
        last_sync_time = 0
        
        while not self.stop_flag.is_set():
            try:
                current_time = time.time()
                
                # Check market status
                if not self.is_market_open():
                    if self.market_open:
                        logger.info("Market closed")
                        self.print_status()
                        self.market_open = False
                    time.sleep(30)
                    continue
                
                if not self.market_open:
                    logger.info("Market opened")
                    self.market_open = True
                    # Sync on market open
                    self.broker_sync.full_sync()
                
                # Periodic sync with broker
                if current_time - last_sync_time >= sync_interval:
                    logger.debug("Performing periodic broker sync")
                    self.broker_sync.full_sync()
                    last_sync_time = current_time
                
                # Scan for signals
                if current_time - last_scan_time >= scan_interval:
                    try:
                        symbols = [
                            "NSE:SBIN-EQ", "NSE:INFY-EQ", "NSE:ITC-EQ",
                            "NSE:LT-EQ", "NSE:MARUTI-EQ"
                        ]
                        
                        signals = self.scan_for_signals(symbols[:self.trading_config.get('scan_symbols', 5)])
                        
                        for symbol, signal_info in signals.items():
                            if signal_info['signal'] == 1:
                                self.place_buy_order(symbol, signal_info)
                        
                        last_scan_time = current_time
                    
                    except Exception as e:
                        logger.error(f"Error in signal generation: {e}")
                
                # Check exit signals
                self.check_exit_signals()
                
                # Sleep before next check
                time.sleep(5)
            
            except KeyboardInterrupt:
                logger.info("Trading loop interrupted by user")
                break
            except Exception as e:
                logger.error(f"Error in trading loop: {e}")
                traceback.print_exc()
                time.sleep(10)
        
        logger.info("Trading loop stopped")
        self.print_status()
    
    def start(self):
        """Start live trading"""
        try:
            logger.info("Starting Live Trading Engine")
            self.trading_active.set()
            self.run_trading_loop()
        
        except Exception as e:
            logger.error(f"Error starting trading: {e}")
            traceback.print_exc()
        
        finally:
            self.stop()
    
    def stop(self):
        """Stop live trading gracefully"""
        try:
            logger.info("Stopping Live Trading Engine")
            self.trading_active.clear()
            self.stop_flag.set()
            
            # Final sync
            self.broker_sync.full_sync()
            
            # Save final state
            self.state_manager.save_session()
            
            self.print_status()
            logger.info("Live Trading Engine stopped")
        
        except Exception as e:
            logger.error(f"Error stopping trading: {e}")


def main():
    """Main entry point"""
    try:
        # Initialize engine
        engine = LiveTradingEngine(
            config_path="config/live_trading_config.yaml",
            recover=True  # Recover from previous session
        )
        
        # Start trading
        engine.start()
    
    except KeyboardInterrupt:
        logger.info("Trading interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    main()
