"""
Optimized Swing Trading Engine
- Scans for signals at 3:13 PM only (before market close)
- Places OCO orders (SL + TP) with broker
- Re-places SL/TP at 9:15 AM (market open)
- No continuous 5-second polling - Broker manages exits
- Checks time-based exits once daily
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
from src.strategy.madam_strategy import SupportResistanceStrategy
from src.strategy.market_scanner import MarketScanner
from src.live_trading.state_manager import StateManager, PositionState, OrderState
from src.live_trading.broker_sync import BrokerSync
from src.data_pipeline.db_utils import get_table_content


def setup_logging(log_dir: str = "logs") -> logging.Logger:
    """Configure logging for swing trading"""
    os.makedirs(log_dir, exist_ok=True)
    
    logger = logging.getLogger("SwingTradingEngine")
    logger.setLevel(logging.DEBUG)
    
    log_file = os.path.join(log_dir, f"swing_trading_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    fh = logging.FileHandler(log_file)
    fh.setLevel(logging.DEBUG)
    
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    
    logger.addHandler(fh)
    logger.addHandler(ch)
    
    return logger


logger = setup_logging()


class SwingTradingEngine:
    """Optimized swing trading engine - Scans daily at 3:13 PM, lets broker manage SL/TP"""
    
    def __init__(self, config_path: str = "config/live_trading_config.yaml",
                 stock_list_path: str = "config/stock_list.yaml",
                 backtest_config_path: str = "config/backtest_config.yaml",
                 session_id: str = None, recover: bool = True):
        """Initialize Swing Trading Engine"""
        
        # Load configs
        self.config = self._load_config(config_path)
        self.trading_config = self.config['live_trading']
        
        with open(backtest_config_path, 'r') as f:
            self.backtest_cfg = yaml.safe_load(f)['backtest']
        
        # Initialize session
        self.session_id = session_id or f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        
        # Initialize broker and state management
        self.broker = fyers_API()
        
        # Initialize strategy directly (no factory needed)
        strategy_params = self.trading_config.get('strategy_params', {})
        self.strategy = SupportResistanceStrategy(params=strategy_params)
        
        # Initialize MarketScanner ONLY for getting stock symbols (not for strategy)
        self.scanner = MarketScanner(
            yaml_config_path=stock_list_path,
            watch_list=self.backtest_cfg.get('watchlist', ['nifty_top_500'])
        )
        # Don't create strategy through scanner - we have it directly
        
        self.state_manager = StateManager(state_dir="data/trading_state")
        self.broker_sync = BrokerSync(broker=self.broker, state_manager=self.state_manager)
        
        # Timezone
        self.tz = pytz.timezone(self.trading_config['timezone'])
        
        # Trading parameters
        self.target_profit_pct = float(self.backtest_cfg.get('target_profit_pct', 0.05))
        self.stop_loss_pct = float(self.backtest_cfg.get('stop_loss_pct', 0.02))
        self.max_hold_days = int(self.backtest_cfg.get('max_holding_days', 7))
        self.position_weights_config = self.backtest_cfg.get('position_weights', {})
        
        # Timing configuration
        self.daily_scan_time = "15:13"  # 3:13 PM - scan for signals before market close at 3:30 PM
        self.market_open_time = "09:15"  # 9:15 AM - re-place SL/TP orders
        
        # Trading state
        self.market_open = False
        self.trading_active = Event()
        self.stop_flag = Event()
        self.state_lock = Lock()
        
        # Data cache
        self.data_cache = {}
        self.stock_meta = {}
        self.sl_tp_orders = {}  # Track OCO order IDs: {symbol: {'sl_order_id': ..., 'tp_order_id': ...}}
        
        # Recover from previous session
        if recover:
            self._recover_session()
        else:
            self.state_manager.create_new_session(
                self.session_id,
                self.trading_config['initial_capital']
            )
        
        logger.info(f"Swing Trading Engine initialized - Session: {self.session_id}")
        logger.info(f"Daily scan at {self.daily_scan_time} PM (before market close)")
        logger.info(f"SL/TP re-placed at {self.market_open_time} AM (at market open)")
    
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
    
    def _recover_session(self) -> bool:
        """Recover from previous session"""
        try:
            logger.info("Attempting to recover from previous session")
            sessions = self.state_manager.list_sessions()
            
            if not sessions:
                logger.info("No previous sessions found, creating new session")
                self.state_manager.create_new_session(
                    self.session_id,
                    self.trading_config['initial_capital']
                )
                return True
            
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
    
    def should_scan_for_signals(self) -> bool:
        """Check if it's 3:13 PM (time to scan for signals)"""
        now = datetime.now(self.tz)
        current_time = now.strftime("%H:%M")
        return current_time == self.daily_scan_time
    
    def should_refresh_sl_tp_orders(self) -> bool:
        """Check if it's 9:15 AM (time to re-place SL/TP orders)"""
        now = datetime.now(self.tz)
        current_time = now.strftime("%H:%M")
        return current_time == self.market_open_time
    
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
        return utilisation < 0.51
    
    # ===== STOCK SELECTION (FROM BACKTEST) =====
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
        
        # Sort each sector by confidence
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
    
    def scan_for_signals(self, days_back: int = 100) -> List[Dict]:
        """Scan for swing trading signals at 3:13 PM"""
        signals = []
        stocks = self.scanner.get_stock_symbols()[:200]
        
        logger.info(f"🔍 Daily signal scan at 3:13 PM - Scanning {len(stocks)} stocks...")
        
        for stock in stocks:
            try:
                symbol = stock['symbol']
                table = self.scanner.get_table_name(symbol)
                
                end_date = datetime.now(self.tz).replace(hour=0, minute=0, second=0, microsecond=0)
                start_date = end_date - timedelta(days=days_back)
                
                df = get_table_content(
                    db_name=self.scanner.stock_config['database_config']['db_name'],
                    table_name=table,
                    start_date=start_date,
                    end_date=end_date
                )
                
                if df is None or df.empty:
                    continue
                
                df = df.sort_values('time')
                df['time'] = pd.to_datetime(df['time'])
                df = df[['time', 'open', 'high', 'low', 'close', 'volume']]
                
                # Generate signals using the strategy directly
                signal_df = self.strategy.generate_signals(df)
                
                if signal_df is None or signal_df.empty:
                    continue
                
                # Take last 5 rows, check only the latest
                last_5 = signal_df.iloc[-5:]
                latest = last_5.iloc[-1]
                
                if latest['signal'] == 1:
                    # Calculate confidence using scanner's method
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
        
        logger.info(f"✅ Found {len(signals)} buy signals at 3:13 PM")
        return signals
    
    def place_buy_order_with_ocoo(self, symbol: str, signal_info: Dict) -> bool:
        """
        Place BUY order + OCO (One-Cancels-Other) SL/TP bracket with broker
        
        OCO Order:
        ├─ Main order: BUY at entry_price
        └─ Bracket (triggered when main fills):
           ├─ SL order: SELL at stop_loss_price
           └─ TP order: SELL at target_price (one will execute, other cancels)
        """
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
                
                # Check available capital
                if not self.can_open_position():
                    utilisation = self.get_utilisation_pct()
                    logger.warning(f"Cannot open position - capital utilisation at {utilisation:.2%} (need <50%)")
                    return False
                
                # Calculate position size
                entry_price = signal_info.get('open', signal_info.get('price', 0))
                if entry_price <= 0:
                    logger.warning(f"Invalid entry price for {symbol}: {entry_price}")
                    return False
                
                weight = signal_info.get('final_weight', 0)
                total_capital = self.get_total_capital()
                allocated_capital = total_capital * weight if weight > 0 else self.trading_config['max_position_size']
                
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
                target_price = entry_price * (1 + self.target_profit_pct)
                stop_loss_price = entry_price * (1 - self.stop_loss_pct)
                
                # ✅ PLACE BUY ORDER WITH OCO BRACKET
                try:
                    # Step 1: Place BUY order
                    buy_order_id = self.broker.place_order(
                        symbol=symbol,
                        qty=quantity,
                        side="BUY",
                        type="MARKET",
                        price=entry_price
                    )
                    
                    if not buy_order_id:
                        logger.error(f"Failed to place BUY order with broker for {symbol}")
                        return False
                    
                    logger.info(f"✅ BUY Order placed: {symbol} | Qty: {quantity} @ {entry_price:.2f} | Order ID: {buy_order_id}")
                    
                    # Step 2: Place OCO bracket (SL + TP)
                    # OCO works like: if one leg executes, the other is cancelled
                    try:
                        sl_order_id = self.broker.place_order(
                            symbol=symbol,
                            qty=quantity,
                            side="SELL",
                            type="STOP_LOSS",
                            price=stop_loss_price,
                            trigger_price=stop_loss_price
                        )
                        
                        tp_order_id = self.broker.place_order(
                            symbol=symbol,
                            qty=quantity,
                            side="SELL",
                            type="LIMIT",
                            price=target_price,
                            trigger_price=target_price
                        )
                        
                        if sl_order_id and tp_order_id:
                            self.sl_tp_orders[symbol] = {
                                'sl_order_id': sl_order_id,
                                'tp_order_id': tp_order_id,
                                'sl_price': stop_loss_price,
                                'tp_price': target_price
                            }
                            logger.info(f"✅ OCO Bracket placed for {symbol} | SL: {stop_loss_price:.2f} | TP: {target_price:.2f}")
                        else:
                            logger.warning(f"⚠️  Failed to place OCO bracket for {symbol}")
                    
                    except Exception as oco_error:
                        logger.warning(f"OCO placement issue for {symbol}: {oco_error}")
                    
                    # Step 3: Save position state
                    position = PositionState(
                        symbol=symbol,
                        entry_price=entry_price,
                        entry_time=datetime.now(self.tz).isoformat(),
                        quantity=quantity,
                        capital_used=actual_capital_used,
                        entry_signal=str(signal_info),
                        target_price=target_price,
                        stop_loss_price=stop_loss_price,
                        highest_price=entry_price,
                        order_id=buy_order_id
                    )
                    
                    if self.state_manager.add_position(position):
                        log_msg = (f"📈 Swing Position opened: {symbol} | Qty: {quantity} | "
                                  f"Entry: {entry_price:.2f} | Target: {target_price:.2f} | "
                                  f"SL: {stop_loss_price:.2f} | Capital: {actual_capital_used:.2f}")
                        logger.info(log_msg)
                        logger.info("   🤖 Broker will manage SL/TP exit automatically!")
                        return True
                    else:
                        logger.error(f"Failed to save position for {symbol}")
                        return False
                
                except Exception as broker_error:
                    logger.error(f"Broker order error for {symbol}: {broker_error}")
                    return False
        
        except Exception as e:
            logger.error(f"Error placing order for {symbol}: {e}")
            traceback.print_exc()
            return False
    
    def check_time_based_exits(self):
        """Check positions that exceeded max_holding_days - execute manual exit"""
        try:
            positions = self.state_manager.get_all_positions()
            
            for symbol, position in positions.items():
                try:
                    entry_time = datetime.fromisoformat(position.entry_time)
                    days_held = (datetime.now(self.tz) - entry_time).days
                    
                    if days_held >= self.max_hold_days:
                        logger.warning(f"⏱️  {symbol} exceeded max holding days ({days_held} days)")
                        
                        # Get current price and exit
                        data = self.get_historical_data(symbol, days_back=5)
                        if data is not None and not data.empty:
                            current_price = data.iloc[-1]['close']
                            
                            # Cancel OCO orders first
                            self._cancel_oco_orders(symbol)
                            
                            # Execute manual sell
                            self._manual_close_position(symbol, current_price, "TIME_LIMIT_EXCEEDED")
                        
                except Exception as e:
                    logger.debug(f"Error checking time exit for {symbol}: {e}")
        
        except Exception as e:
            logger.error(f"Error in time-based exit check: {e}")
    
    def _cancel_oco_orders(self, symbol: str):
        """Cancel OCO orders for a symbol"""
        try:
            if symbol in self.sl_tp_orders:
                orders = self.sl_tp_orders[symbol]
                
                try:
                    self.broker.cancel_order(orders['sl_order_id'])
                    logger.info(f"Cancelled SL order for {symbol}")
                except:
                    pass
                
                try:
                    self.broker.cancel_order(orders['tp_order_id'])
                    logger.info(f"Cancelled TP order for {symbol}")
                except:
                    pass
                
                del self.sl_tp_orders[symbol]
        
        except Exception as e:
            logger.debug(f"Error cancelling OCO orders for {symbol}: {e}")
    
    def _manual_close_position(self, symbol: str, exit_price: float, reason: str):
        """Manually close a position (when time limit exceeded)"""
        try:
            with self.state_lock:
                position = self.state_manager.get_position(symbol)
                if position is None:
                    return
                
                # Place manual SELL order
                try:
                    sell_order_id = self.broker.place_order(
                        symbol=symbol,
                        qty=position.quantity,
                        side="SELL",
                        type="MARKET",
                        price=exit_price
                    )
                    
                    if sell_order_id:
                        logger.info(f"✅ Manual sell for {symbol} @ {exit_price:.2f}")
                except Exception as e:
                    logger.error(f"Error placing manual sell for {symbol}: {e}")
                
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
                    'exit_reason': reason
                }
                self.state_manager.update_position(symbol, updates)
                self.state_manager.remove_position(symbol)
                
                logger.info(f"🔴 Position closed: {symbol} | P&L: {pnl:.2f} ({pnl_pct:.2f}%) | Reason: {reason}")
        
        except Exception as e:
            logger.error(f"Error closing position {symbol}: {e}")
    
    def refresh_sl_tp_orders_at_market_open(self):
        """
        At 9:15 AM (market open):
        1. Cancel yesterday's SL/TP orders (they expire after market close)
        2. Re-place new SL/TP orders for the day
        """
        try:
            positions = self.state_manager.get_all_positions()
            
            if not positions:
                logger.info("No active positions - no SL/TP to refresh")
                return
            
            logger.info("🔄 Refreshing SL/TP orders at market open...")
            
            for symbol, position in positions.items():
                try:
                    # Cancel old OCO orders
                    self._cancel_oco_orders(symbol)
                    
                    # Re-place new SL/TP orders
                    try:
                        sl_order_id = self.broker.place_order(
                            symbol=symbol,
                            qty=position.quantity,
                            side="SELL",
                            type="STOP_LOSS",
                            price=position.stop_loss_price,
                            trigger_price=position.stop_loss_price
                        )
                        
                        tp_order_id = self.broker.place_order(
                            symbol=symbol,
                            qty=position.quantity,
                            side="SELL",
                            type="LIMIT",
                            price=position.target_price,
                            trigger_price=position.target_price
                        )
                        
                        if sl_order_id and tp_order_id:
                            self.sl_tp_orders[symbol] = {
                                'sl_order_id': sl_order_id,
                                'tp_order_id': tp_order_id,
                                'sl_price': position.stop_loss_price,
                                'tp_price': position.target_price
                            }
                            logger.info(f"✅ Refreshed SL/TP for {symbol} | SL: {position.stop_loss_price:.2f} | TP: {position.target_price:.2f}")
                    
                    except Exception as e:
                        logger.error(f"Error re-placing SL/TP for {symbol}: {e}")
                
                except Exception as e:
                    logger.debug(f"Error refreshing {symbol}: {e}")
        
        except Exception as e:
            logger.error(f"Error in SL/TP refresh: {e}")
    
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
    
    def print_status(self):
        """Print current trading status"""
        try:
            summary = self.state_manager.get_session_summary()
            
            logger.info("=" * 80)
            logger.info("SWING TRADING STATUS")
            logger.info("=" * 80)
            logger.info(f"Session ID: {summary.get('session_id')}")
            logger.info(f"Open Positions: {summary.get('open_positions')}")
            logger.info(f"Total P&L: ${summary.get('total_pnl'):.2f}")
            logger.info(f"Closed Positions: {summary.get('closed_positions')}")
            logger.info(f"Available Capital: ${summary.get('capital_available'):.2f}")
            logger.info(f"Capital Used: ${summary.get('capital_used'):.2f}")
            logger.info("=" * 80)
        
        except Exception as e:
            logger.error(f"Error printing status: {e}")
    
    def run_swing_trading_loop(self):
        """
        Main swing trading loop
        - Only scans at 3:13 PM
        - Refreshes SL/TP at 9:15 AM
        - No continuous polling
        """
        logger.info("Starting Swing Trading Loop")
        logger.info("📍 Only scans at 3:13 PM for new entries")
        logger.info("📍 SL/TP refreshed at 9:15 AM (market open)")
        logger.info("📍 Broker manages all exits automatically")
        
        last_scan_time = None
        last_refresh_time = None
        
        while not self.stop_flag.is_set():
            try:
                current_time = time.time()
                now = datetime.now(self.tz)
                
                # Check if market is open
                if not self.is_market_open():
                    if self.market_open:
                        logger.info("Market closed")
                        self.print_status()
                        self.market_open = False
                    time.sleep(60)
                    continue
                
                if not self.market_open:
                    logger.info("Market opened")
                    self.market_open = True
                    self.broker_sync.full_sync()
                
                # ✅ AT 9:15 AM - Refresh SL/TP orders
                if self.should_refresh_sl_tp_orders():
                    if last_refresh_time != now.strftime("%Y-%m-%d"):
                        logger.info("🔄 Market open trigger - Refreshing SL/TP orders...")
                        self.refresh_sl_tp_orders_at_market_open()
                        last_refresh_time = now.strftime("%Y-%m-%d")
                
                # ✅ AT 3:13 PM - Scan for signals and enter
                if self.should_scan_for_signals():
                    if last_scan_time != now.strftime("%Y-%m-%d"):
                        logger.info("🔍 3:13 PM trigger - Scanning for signals...")
                        
                        all_signals = self.scan_for_signals(days_back=100)
                        
                        if all_signals:
                            selected_signals = self.select_and_weight_signals(all_signals)
                            logger.info(f"Selected {len(selected_signals)} signals for entry")
                            
                            if self.can_open_position():
                                for signal in selected_signals:
                                    if self.state_manager.get_position(signal['symbol']) is not None:
                                        continue
                                    
                                    if self.place_buy_order_with_ocoo(signal['symbol'], signal):
                                        logger.info(f"✅ Entered: {signal['symbol']}")
                                    
                                    time.sleep(1)  # Avoid overloading broker
                            else:
                                utilisation = self.get_utilisation_pct()
                                logger.info(f"Cannot open new positions - capital usage at {utilisation:.2%}")
                        
                        last_scan_time = now.strftime("%Y-%m-%d")
                
                # ✅ ONCE DAILY - Check time-based exits
                if now.hour == 15 and now.minute == 15:  # 3:15 PM - after scanning
                    logger.info("Checking for time-based exits...")
                    self.check_time_based_exits()
                
                # Sleep - no need to poll every 5 seconds!
                time.sleep(60)  # Check every minute for timing triggers
            
            except KeyboardInterrupt:
                logger.info("Swing trading interrupted by user")
                break
            except Exception as e:
                logger.error(f"Error in swing trading loop: {e}")
                traceback.print_exc()
                time.sleep(60)
        
        logger.info("Swing trading loop stopped")
        self.print_status()
    
    def start(self):
        """Start swing trading"""
        try:
            logger.info("Starting Swing Trading Engine")
            self.trading_active.set()
            self.run_swing_trading_loop()
        
        except Exception as e:
            logger.error(f"Error starting swing trading: {e}")
            traceback.print_exc()
        
        finally:
            self.stop()
    
    def stop(self):
        """Stop swing trading gracefully"""
        try:
            logger.info("Stopping Swing Trading Engine")
            self.trading_active.clear()
            self.stop_flag.set()
            
            # Cancel all OCO orders
            for symbol in list(self.sl_tp_orders.keys()):
                self._cancel_oco_orders(symbol)
            
            # Final sync
            self.broker_sync.full_sync()
            
            # Save final state
            self.state_manager.save_session()
            
            self.print_status()
            logger.info("Swing Trading Engine stopped")
        
        except Exception as e:
            logger.error(f"Error stopping trading: {e}")


def main():
    """Main entry point"""
    try:
        # Initialize swing trading engine
        engine = SwingTradingEngine(
            config_path="config/live_trading_config.yaml",
            recover=True
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
