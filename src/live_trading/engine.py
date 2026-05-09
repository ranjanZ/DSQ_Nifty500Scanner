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
import pandas as pd

from src.utils.fyers.fyers_broker import fyers_API
from src.strategy.rsi_w_strategy import RSIWPatternStrategy
from src.strategy.market_scanner import MarketScanner
from src.live_trading.state_manager import StateManager, PositionState, OrderState
from src.live_trading.broker_sync import BrokerSync
from src.data_pipeline.db_utils import get_table_content


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
                 stock_list_path: str = "config/stock_list.yaml",
                 backtest_config_path: str = "config/backtest_config.yaml",
                 session_id: str = None, recover: bool = True):
        """
        Initialize Live Trading Engine
        
        Args:
            config_path: Path to live trading configuration file
            stock_list_path: Path to stock list configuration file
            backtest_config_path: Path to backtest configuration (for rules like target, stop loss)
            session_id: Session ID (auto-generated if None)
            recover: Recover from previous session if available
        """
        # Load configs
        self.config = self._load_config(config_path)
        self.trading_config = self.config['live_trading']
        
        # Load backtest config for trading rules
        with open(backtest_config_path, 'r') as f:
            self.backtest_cfg = yaml.safe_load(f)['backtest']
        
        # Initialize session
        self.session_id = session_id or f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        
        # Initialize components
        self.broker = fyers_API()
        self.strategy = self._create_strategy()
        
        # Initialize MarketScanner for stock selection
        self.scanner = MarketScanner(
            yaml_config_path=stock_list_path,
            watch_list=self.backtest_cfg.get('watchlist', ['nifty_top_500'])
        )
        self.scanner.create_strategy(
            self.backtest_cfg['strategy_name'],
            self.backtest_cfg['strategy_name'],
            params=self.trading_config.get('strategy_params', {})
        )
        
        self.state_manager = StateManager(state_dir="data/trading_state")
        self.broker_sync = BrokerSync(broker=self.broker, state_manager=self.state_manager)
        
        # Timezone
        self.tz = pytz.timezone(self.trading_config['timezone'])
        
        # Trading parameters from backtest config
        self.target_profit_pct = float(self.backtest_cfg.get('target_profit_pct', 0.05))
        self.stop_loss_pct = float(self.backtest_cfg.get('stop_loss_pct', 0.02))
        self.max_hold_days = int(self.backtest_cfg.get('max_holding_days', 7))
        self.position_weights_config = self.backtest_cfg.get('position_weights', {})
        
        # Trading state
        self.market_open = False
        self.trading_active = Event()
        self.stop_flag = Event()
        self.state_lock = Lock()
        
        # Data cache
        self.data_cache = {}  # {symbol: DataFrame}
        self.stock_meta = {}  # {symbol: metadata}
        
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
        
        # Market closed on weekends
        if now.weekday() >= 5:  # Saturday=5, Sunday=6
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
    
    # ===== CAPITAL AND POSITION MANAGEMENT =====
    def get_available_capital(self) -> float:
        """Get available capital not yet allocated to positions"""
        summary = self.state_manager.get_session_summary()
        return summary.get('capital_available', self.trading_config['initial_capital'])
    
    def get_used_capital(self) -> float:
        """Get capital already allocated to positions"""
        summary = self.state_manager.get_session_summary()
        return summary.get('capital_used', 0.0)
    
    def get_total_capital(self) -> float:
        """Get total trading capital"""
        summary = self.state_manager.get_session_summary()
        return summary.get('capital_total', self.trading_config['initial_capital'])
    
    def get_utilisation_pct(self) -> float:
        """Get capital utilisation percentage"""
        total = self.get_total_capital()
        used = self.get_used_capital()
        if total <= 0:
            return 0.0
        return used / total
    
    def can_open_position(self) -> bool:
        """Check if we can open new positions (must have >50% capital free)"""
        utilisation = self.get_utilisation_pct()
        return utilisation < 0.51  # Allow if less than 51% utilized
    
    # ===== STOCK SELECTION (FROM BACKTEST_OFFLINE) =====
    def select_and_weight_signals(self, signals: List[Dict]) -> List[Dict]:
        """Select and weight signals using sector-based allocation"""
        if not signals:
            return []
        
        config = self.position_weights_config
        max_pos = config.get('max_positions', 5)
        max_per_sector = config.get('max_per_sector', 2)
        sector_weights = config.get('sector_allocation', {})
        redistribute = config.get('redistribute_unused', True)
        
        # Group by sector
        sectors = {}
        for signal in signals:
            sector = signal.get('sector', 'Unknown')
            if sector not in sectors:
                sectors[sector] = []
            sectors[sector].append(signal)
        
        # Sort each sector by confidence and limit
        for sector in sectors:
            sectors[sector] = sorted(
                sectors[sector],
                key=lambda x: x.get('confidence', 0),
                reverse=True
            )[:max_per_sector]
        
        # Separate priority and others
        priority = []
        others = []
        for sector, stocks in sectors.items():
            weight = sector_weights.get(sector, 0)
            for stock in stocks:
                stock['sector_weight'] = weight
            if weight > 0:
                priority.extend(stocks)
            else:
                others.extend(stocks)
        
        # If no priority sectors, use top signals
        if not priority:
            final = sorted(others, key=lambda x: x.get('confidence', 0), reverse=True)[:max_pos]
            for signal in final:
                signal['final_weight'] = 1.0 / len(final) if final else 0
            return final
        
        # Allocate based on sector weights
        sector_map = {}
        for signal in priority:
            sector = signal['sector']
            if sector not in sector_map:
                sector_map[sector] = []
            sector_map[sector].append(signal)
        
        total_weight = sum(sector_weights.get(sec, 0) for sec in sector_map)
        final = []
        for sector, stocks in sector_map.items():
            sector_weight = sector_weights.get(sector, 0)
            per_stock_weight = (sector_weight / total_weight) / len(stocks) if stocks and total_weight > 0 else 0
            for signal in stocks:
                signal['final_weight'] = per_stock_weight
            final.extend(stocks)
        
        # Add fillers if needed
        remaining = max_pos - len(final)
        if remaining > 0 and others and redistribute:
            fillers = sorted(others, key=lambda x: x.get('confidence', 0), reverse=True)[:remaining]
            for signal in fillers:
                signal['final_weight'] = 0.0
            final.extend(fillers)
        
        # Ensure max positions and normalize weights
        if len(final) > max_pos:
            final = sorted(final, key=lambda x: (x.get('final_weight', 0), x.get('confidence', 0)), reverse=True)[:max_pos]
        
        total_weight = sum(s.get('final_weight', 0) for s in final)
        if total_weight > 0:
            for signal in final:
                signal['final_weight'] = signal.get('final_weight', 0) / total_weight
        
        return final
    
    def scan_for_signals_with_history(self, days_back: int = 100) -> List[Dict]:
        """Scan all stocks for trading signals using historical data"""
        signals = []
        stocks = self.scanner.get_stock_symbols()[:200]  # Limit to 200 stocks
        
        logger.info(f"Scanning {len(stocks)} stocks for signals...")
        
        for stock in stocks:
            try:
                symbol = stock['symbol']
                table = self.scanner.get_table_name(symbol)
                
                # Fetch data from database or broker
                end_date = datetime.now()
                start_date = end_date - timedelta(days=days_back)
                
                df = get_table_content(
                    db_name=self.scanner.stock_config['database_config']['db_name'],
                    table_name=table,
                    start_date=start_date,
                    end_date=end_date
                )
                
                if df is None or df.empty:
                    continue
                
                # Prepare data
                df = df.sort_values('time')
                df['time'] = pd.to_datetime(df['time'])
                df = df[['time', 'open', 'high', 'low', 'close', 'volume']]
                
                # Generate signals
                strategy = self.scanner.strategies.get(self.backtest_cfg['strategy_name'])
                if strategy is None:
                    continue
                
                signal_df = strategy.generate_signals(df)
                
                if signal_df is None or signal_df.empty:
                    continue
                
                # Get latest signal
                latest = signal_df.iloc[-1]
                
                # Check for buy signal
                if latest.get('signal', 0) == 1:
                    confidence = self.scanner._calculate_confidence(signal_df)
                    signals.append({
                        'symbol': symbol,
                        'name': stock.get('name', symbol),
                        'close': float(latest['close']),
                        'open': float(latest['open']),
                        'sector': stock.get('sector', 'Unknown'),
                        'confidence': confidence,
                        'market_cap': stock.get('market_cap', 'Unknown')
                    })
                
                self.data_cache[symbol] = df
                self.stock_meta[symbol] = stock
            
            except Exception as e:
                logger.debug(f"Error scanning {symbol}: {e}")
        
        logger.info(f"Found {len(signals)} buy signals")
        return signals
    
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
        """Place a buy order through broker"""
        try:
            with self.state_lock:
                # Check if position already exists
                if self.state_manager.get_position(symbol) is not None:
                    logger.warning(f"Position already exists for {symbol}")
                    return False
                
                # Check max positions
                positions = self.state_manager.get_all_positions()
                if len(positions) >= self.trading_config['max_positions']:
                    logger.warning(f"Max positions reached ({len(positions)})")
                    return False
                
                # Check available capital (must be >50% free)
                if not self.can_open_position():
                    utilisation = self.get_utilisation_pct()
                    logger.warning(f"Cannot open position - capital utilisation at {utilisation:.2%} (need <50%)")
                    return False
                
                # Calculate position size
                entry_price = signal_info.get('price', signal_info.get('close', 0))
                if entry_price <= 0:
                    logger.warning(f"Invalid entry price for {symbol}: {entry_price}")
                    return False
                
                weight = signal_info.get('final_weight', 0)
                total_capital = self.get_total_capital()
                allocated_capital = total_capital * weight if weight > 0 else self.trading_config['max_position_size']
                
                # Limit to available capital
                available = self.get_available_capital()
                allocated_capital = min(allocated_capital, available)
                
                if allocated_capital <= 0:
                    logger.warning(f"No capital available for {symbol}")
                    return False
                
                quantity = int(allocated_capital / entry_price)
                
                if quantity <= 0:
                    logger.warning(f"Invalid quantity for {symbol}: {quantity}")
                    return False
                
                actual_capital_used = quantity * entry_price
                
                # EXECUTE ORDER THROUGH BROKER
                try:
                    order_id = self.broker.place_order(
                        symbol=symbol,
                        qty=quantity,
                        side="BUY",
                        type="MARKET",
                        price=entry_price
                    )
                    
                    if not order_id:
                        logger.error(f"Failed to place order with broker for {symbol}")
                        return False
                    
                    logger.info(f"✅ Order placed with broker: {symbol} | Qty: {quantity} @ {entry_price:.2f} | Order ID: {order_id}")
                
                except Exception as broker_error:
                    logger.error(f"Broker order placement error for {symbol}: {broker_error}")
                    return False
                
                # Create position state
                position = PositionState(
                    symbol=symbol,
                    entry_price=entry_price,
                    entry_time=datetime.now(self.tz).isoformat(),
                    quantity=quantity,
                    capital_used=actual_capital_used,
                    entry_signal=str(signal_info),
                    target_price=entry_price * (1 + self.target_profit_pct),
                    stop_loss_price=entry_price * (1 - self.stop_loss_pct),
                    highest_price=entry_price,
                    order_id=order_id
                )
                
                # Add to state
                if self.state_manager.add_position(position):
                    log_msg = (f"Position opened: {symbol} | Qty: {quantity} | "
                              f"Entry: {entry_price:.2f} | Target: {position.target_price:.2f} | "
                              f"SL: {position.stop_loss_price:.2f} | Capital allocated: {actual_capital_used:.2f}")
                    logger.info(f"📈 {log_msg}")
                    return True
                else:
                    logger.error(f"Failed to add position to state manager for {symbol}")
                    # Try to cancel the broker order if state addition fails
                    try:
                        self.broker.cancel_order(order_id)
                    except:
                        pass
                    return False
            
            return False
        
        except Exception as e:
            logger.error(f"Error placing buy order for {symbol}: {e}")
            traceback.print_exc()
            return False
    
    def check_exit_signals(self):
        """Check for exit signals using backtest exit rules"""
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
                    exit_price = None
                    
                    # 1. Check stop loss first
                    if current_price <= position.stop_loss_price:
                        exit_reason = "STOP_LOSS"
                        exit_price = position.stop_loss_price
                    
                    # 2. Check target hit
                    elif current_price >= position.target_price:
                        exit_reason = "TARGET"
                        exit_price = position.target_price
                    
                    # 3. Check trailing stop
                    trailing_stop = position.highest_price * (1 - self.trading_config.get('trailing_stop_pct', 0.01))
                    if exit_reason is None and current_price <= trailing_stop:
                        exit_reason = "TRAILING_STOP"
                        exit_price = trailing_stop
                    
                    # 4. Check time-based exit (max holding days)
                    if exit_reason is None:
                        entry_time = datetime.fromisoformat(position.entry_time)
                        days_held = (datetime.now(self.tz) - entry_time).days
                        if days_held >= self.max_hold_days:
                            exit_reason = "TIME_EXIT"
                            exit_price = current_price
                    
                    # Exit if signal triggered
                    if exit_reason and exit_price:
                        self.close_position(symbol, exit_price, exit_reason)
                
                except Exception as e:
                    logger.debug(f"Error checking exit for {symbol}: {e}")
        
        except Exception as e:
            logger.error(f"Error in exit signal check: {e}")
    
    def close_position(self, symbol: str, exit_price: float, reason: str) -> bool:
        """Close a position and execute sell order through broker"""
        try:
            with self.state_lock:
                position = self.state_manager.get_position(symbol)
                
                if position is None:
                    return False
                
                # EXECUTE SELL ORDER THROUGH BROKER
                try:
                    order_id = self.broker.place_order(
                        symbol=symbol,
                        qty=position.quantity,
                        side="SELL",
                        type="MARKET",
                        price=exit_price
                    )
                    
                    if not order_id:
                        logger.error(f"Failed to place sell order with broker for {symbol}")
                        return False
                    
                    logger.info(f"✅ Sell order placed with broker: {symbol} | Qty: {position.quantity} @ {exit_price:.2f} | Order ID: {order_id}")
                
                except Exception as broker_error:
                    logger.error(f"Broker sell order error for {symbol}: {broker_error}")
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
                    'pnl_pct': pnl_pct,
                    'exit_reason': reason,
                    'exit_order_id': order_id
                }
                self.state_manager.update_position(symbol, updates)
                self.state_manager.remove_position(symbol)
                
                log_msg = (f"Position closed: {symbol} @ {exit_price:.2f} | P&L: {pnl:.2f} ({pnl_pct:.2f}%) | "
                          f"Reason: {reason} | Qty: {position.quantity}")
                logger.info(f"🔴 {log_msg}")
                return True
        
        except Exception as e:
            logger.error(f"Error closing position {symbol}: {e}")
            traceback.print_exc()
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
        last_daily_scan_time = 0
        daily_scan_interval = 3600  # Full scan every hour
        
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
                
                # Daily full stock scan (every hour or at startup)
                if current_time - last_daily_scan_time >= daily_scan_interval:
                    try:
                        logger.info("Running full stock scan with signal generation")
                        all_signals = self.scan_for_signals_with_history(days_back=100)
                        
                        # Select and weight signals
                        if all_signals:
                            selected_signals = self.select_and_weight_signals(all_signals)
                            logger.info(f"Selected {len(selected_signals)} signals for trading")
                            
                            # Check if we can open new positions (>50% capital free)
                            if self.can_open_position():
                                for signal in selected_signals:
                                    # Check if already in position
                                    if self.state_manager.get_position(signal['symbol']) is not None:
                                        continue
                                    
                                    # Add price info for order placement
                                    signal['price'] = signal['close']
                                    
                                    # Place order
                                    if self.place_buy_order(signal['symbol'], signal):
                                        logger.info(f"Opened position: {signal['symbol']}")
                                    
                                    # Don't overload - wait a bit between orders
                                    time.sleep(1)
                            else:
                                utilisation = self.get_utilisation_pct()
                                logger.info(f"Cannot open new positions - capital usage at {utilisation:.2%}")
                        
                        last_daily_scan_time = current_time
                    
                    except Exception as e:
                        logger.error(f"Error in daily signal generation: {e}")
                        traceback.print_exc()
                
                # Check exit signals frequently
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
