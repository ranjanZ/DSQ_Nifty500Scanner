"""
Optimized Swing Trading Engine - Live Trading with OCO Orders
- Morning (9:16 AM): Re‑place SL/TP for all open positions
- 3:00 PM: Refresh state & close time‑exceeded positions
- 3:13 PM: Run DB updater, scan signals, place new OCO orders
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
from threading import Event, Lock
import traceback
import pandas as pd

from src.utils.fyers.fyers_broker import fyers_API
from src.strategy.madam_strategy import SupportResistanceStrategy
from src.strategy.market_scanner import MarketScanner
from src.live_trading.state_manager import StateManager, PositionState
from src.live_trading.broker_sync import BrokerSync
from src.data_pipeline.db_utils import get_table_content
from src.data_pipeline.read_data_store_db_lambda1 import update as update_database
from src.data_pipeline.read_data_store_db_lambda1 import delete_old_data_for_all_stocks


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
    """Live swing trading engine with OCO orders, timed scans, and state recovery"""

    def __init__(self, config_path: str = "config/live_trading_config.yaml",
                 stock_list_path: str = "config/stock_list.yaml",
                 backtest_config_path: str = "config/backtest_config.yaml",
                 session_id: str = None, recover: bool = True):
        # Load configs
        self.config = self._load_config(config_path)
        self.trading_config = self.config['live_trading']
        with open(backtest_config_path, 'r') as f:
            self.backtest_cfg = yaml.safe_load(f)['backtest']

        # Get initial capital
        initial_capital = self.trading_config.get('initial_capital')
        if initial_capital is None:
            logger.info("Initial capital not set, fetching from broker...")
            funds = self.broker.get_funds()
            initial_capital = funds.get('available_margin', 0)
            logger.info(f"Using broker available margin as initial capital: {initial_capital}")
            self.trading_config['initial_capital'] = initial_capital

        # Session ID
        #self.session_id = session_id or f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        self.session_id="parmanent"
        # Broker & state
        self.broker = fyers_API()
        self.strategy = SupportResistanceStrategy(params=self.trading_config.get('strategy_params', {}))
        self.scanner = MarketScanner(
            yaml_config_path=stock_list_path,
            watch_list=self.backtest_cfg.get('watchlist', ['nifty_top_500'])
        )
        self.state_manager = StateManager(state_dir="data/trading_state")
        self.broker_sync = BrokerSync(broker=self.broker, state_manager=self.state_manager)

        # Timezone
        self.tz = pytz.timezone(self.trading_config['timezone'])

        # Trading parameters
        self.target_profit_pct = float(self.backtest_cfg.get('target_profit_pct', 0.05))
        self.stop_loss_pct = float(self.backtest_cfg.get('stop_loss_pct', 0.02))
        self.max_hold_days = int(self.backtest_cfg.get('max_holding_days', 7))
        self.position_weights_config = self.backtest_cfg.get('position_weights', {})

        # Timing (all in 24‑hour format)
        self.position_refresh_time = self.trading_config.get('position_refresh_time', "15:00")     # 3:00 PM - refresh state & time exits
        self.scan_time = self.trading_config.get('scan_time', "15:13")                # 3:13 PM - update DB & scan signals

        # Threading / state
        self.market_open = False
        self.trading_active = Event()
        self.stop_flag = Event()
        self.state_lock = Lock()

        # Data caches
        self.data_cache = {}
        self.stock_meta = {}

        # Recover previous session
        if recover:
            self._recover_session()
        else:
            self.state_manager.create_new_session(self.session_id, self.trading_config['initial_capital'])

        logger.info(f"Swing Trading Engine initialized – Session: {self.session_id}")
        logger.info(f"Position refresh: {self.position_refresh_time}")
        logger.info(f"Signal scan: {self.scan_time} (after DB update)")

    def _load_config(self, config_path: str) -> Dict[str, Any]:
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)

    def _recover_session(self) -> bool:
        try:
            sessions = self.state_manager.list_sessions()
            if not sessions:
                self.state_manager.create_new_session(self.session_id, self.trading_config['initial_capital'])
                return True
            last_session = sessions[-1]
            logger.info(f"Recovering session: {last_session}")
            session = self.state_manager.load_session(last_session)
            if session is None:
                self.state_manager.create_new_session(self.session_id, self.trading_config['initial_capital'])
                return False
            self.session_id = last_session
            sync_result = self.broker_sync.full_sync()
            if not sync_result.get('success'):
                logger.warning(f"Broker sync issues: {sync_result}")
            logger.info(f"Recovered session: {self.state_manager.get_session_summary()}")
            return True
        except Exception as e:
            logger.error(f"Recovery error: {e}")
            return False

    # ------------------------------------------------------------------
    # Market & timing helpers
    # ------------------------------------------------------------------
    def is_market_open(self) -> bool:
        return True
        now = datetime.now(self.tz)
        if now.weekday() >= 5:
            return False
        open_time = datetime.strptime(self.trading_config['market_open'], "%H:%M").time()
        close_time = datetime.strptime(self.trading_config['market_close'], "%H:%M").time()
        print(f"Checking market hours: now={now.time()} | open={open_time} - close={close_time}")
        return open_time <= now.time() <= close_time

    def _current_time_str(self) -> str:
        return datetime.now(self.tz).strftime("%H:%M")

    # ------------------------------------------------------------------
    # Capital management
    # ------------------------------------------------------------------
    def get_available_capital(self) -> float:
        return self.state_manager.get_session_summary().get('capital_available', 0)

    def get_used_capital(self) -> float:
        return self.state_manager.get_session_summary().get('capital_used', 0)

    def get_total_capital(self) -> float:
        #return self.state_manager.get_session_summary().get('capital_total', self.trading_config['initial_capital'])
        return self.trading_config['operating_capital'] # Use fixed operating capital for allocation decisions
    
    def utilisation_pct(self) -> float:
        total = self.get_total_capital()
        used = self.get_used_capital()
        return used / total if total > 0 else 0.0

    def can_open_position(self) -> bool:
        return self.utilisation_pct() < 0.95



    # ------------------------------------------------------------------
    # Position refresh at 3:00 PM – sync & close time‑exceeded
    # ------------------------------------------------------------------
    def refresh_positions(self):
        """
        - Sync with broker: detect any positions auto‑closed by SL/TP
        - Close positions that exceeded max_hold_days
        - Update capital accordingly
        - Compute profit for open positions
        """
        logger.info("📊 3:00 PM position refresh – syncing with broker...")
        # Full sync updates capital and open positions automatically
        sync_result = self.broker_sync.full_sync()
        logger.info(f"Sync completed: {sync_result}")

        # Update pnl for open positions
        positions = self.state_manager.get_all_positions()
        for symbol, pos in positions.items():
            current_price = self._get_current_price(symbol)
            if current_price:
                pnl = (current_price - pos.entry_price) * pos.quantity
                pnl_pct = ((current_price - pos.entry_price) / pos.entry_price) * 100
                updates = {'pnl': pnl, 'pnl_pct': pnl_pct}
                self.state_manager.update_position(symbol, updates)
                logger.debug(f"Updated P&L for {symbol}: {pnl:.2f} ({pnl_pct:.2f}%)")



        now_time = datetime.now()
        holdding_positions = self.state_manager.get_all_current_holdings()
        for position in holdding_positions:
            symbol = position['symbol']
            entry_date = datetime.strptime(position['entry_time'], "%d-%b-%Y %H:%M:%S")
            days_held = (now_time - entry_date).days
            print(f"*************************Checking {symbol}: held for {days_held} days (entry: {entry_date.date()}, now: {now_time.date()})")
            if days_held >= self.max_hold_days:
                logger.warning(f"⏱️  {symbol} exceeded {self.max_hold_days} days – closing")
                # Get latest price from broker
                current_price = self._get_current_price(symbol)
                if current_price:
                    self._manual_close_position(symbol, current_price, "TIME_LIMIT_EXCEEDED")

            

        # # Now check time‑based exits (holding period exceeded)
        # now_time = datetime.now(self.tz)
        # for symbol, pos in positions.items():
        #     entry_date = datetime.fromisoformat(pos.entry_time)
        #     days_held = (now_time - entry_date).days
        #     print(f"*************************Checking {symbol}: held for {days_held} days (entry: {entry_date.date()}, now: {now_time.date()})")
        #     if days_held >= self.max_hold_days:
        #         logger.warning(f"⏱️  {symbol} exceeded {self.max_hold_days} days – closing")
        #         # Get latest price from broker
        #         current_price = self._get_current_price(symbol)
        #         if current_price:
        #             self._manual_close_position(symbol, current_price, "TIME_LIMIT_EXCEEDED")

    def _get_current_price(self, symbol: str) -> Optional[float]:
        """Fetch current LTP for a symbol (via broker)"""
        try:
            quotes = self.broker.get_quotes(symbol)
            if not quotes or not quotes.get('d'):
                logger.warning(f"No quote data for {symbol}")
                return None
            
            quote_data = quotes.get('d', [])
            if not quote_data or len(quote_data) == 0:
                logger.warning(f"Empty quote data for {symbol}")
                return None
            
            # Fyers format: quotes['d'][0]['v']['lp']
            try:
                ltp = quote_data[0].get('v', {}).get('lp')
                if ltp is not None:
                    return float(ltp)
                else:
                    logger.warning(f"LTP not found in quote for {symbol}")
                    return None
            except (KeyError, TypeError, ValueError, IndexError) as e:
                logger.warning(f"Could not parse LTP for {symbol}: {e}")
                return None
        except Exception as e:
            logger.error(f"Error fetching quote for {symbol}: {e}")
            return None

    def _get_order_status(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Check the current status of an order from broker and normalize to standard format"""
        try:
            orders = self.broker.get_orders()

            for order_idx in orders:
                order = orders[str(order_idx)]['raw']
                if order.get('id') == order_id:
                    # Normalize Fyers response to standard format
                    return self._normalize_order_response(order)
                
            logger.warning(f"Order {order_id} not found in broker orders")
            return None
        except Exception as e:
            logger.error(f"Error checking order status for {order_id}: {e}")
            return None
    
    def _normalize_order_response(self, fyers_order: Dict[str, Any]) -> Dict[str, Any]:
        """Convert Fyers order response to standard format
        Fyers uses: status (int), filledQty, remainingQuantity, etc
        We standardize to: status (str), filled_qty, qty, etc
        """
        # Map Fyers status codes to strings
        # 1=PENDING, 2=EXECUTED/FILLED, 3=REJECTED, 4=CANCELLED, 5=EXPIRED
        status_map = {
            1: 'CANCELLED',
            2: 'FILLED',
            4: 'TRANSIT',
            5: 'REJECTED',
            6: 'PENDING',
            7: 'EXPIRED'
        }

        
        status_code = fyers_order.get('status')
        status_str = status_map.get(status_code, 'UNKNOWN')
        
        return {
            'id': fyers_order.get('id'),
            'status': status_str,
            'filled_qty': fyers_order.get('filledQty', 0),
            'qty': fyers_order.get('qty', 0),
            'price': fyers_order.get('limitPrice', 0),
            'symbol': fyers_order.get('symbol'),
            'side': fyers_order.get('side'),
            'orderDateTime': fyers_order.get('orderDateTime'),
            'message': fyers_order.get('message')
        }
    
    def _wait_for_order_fill(self, order_id: str, max_wait_seconds: int = 30) -> bool:
        """Poll order status until it's filled/executed. Returns True if filled, False otherwise."""
        logger.info(f"⏳ Waiting for entry order {order_id} to fill (max {max_wait_seconds}s)...")
        start_time = time.time()
        
        while time.time() - start_time < max_wait_seconds:
            order = self._get_order_status(order_id)
            
            if order:
                status = order.get('status', '').upper()
                filled = order.get('filled_qty', 0)
                qty = order.get('qty', 0)
                
                # Success: fully filled or partially filled (acceptable for entry)
                if status in ['EXECUTED', 'FILLED'] or filled > 0:
                    logger.info(f"✅ Entry order {order_id} FILLED: {filled}/{qty} units")
                    return True
                
                # Failure: explicit rejection or cancellation
                elif status in ['REJECTED', 'CANCELLED', 'EXPIRED', 'FAILED']:
                    logger.error(f"❌ Entry order {order_id} {status}")
                    return False
            
            time.sleep(1)  # Poll every 1 second
        
        # Timeout: still pending
        logger.warning(f"⏱️  Entry order {order_id} still PENDING after {max_wait_seconds}s")
        return False

    def _manual_close_position(self, symbol: str, exit_price: float, reason: str):
        """Manually close a position with market sell order"""
        with self.state_lock:
            # pos = self.state_manager.get_position(symbol)
            # if not pos:
            #     logger.warning(f"Position not found for {symbol}")
            #     return
            
            # try:
            #     exit_price = float(exit_price)
            # except (ValueError, TypeError):
            #     logger.error(f"Invalid exit price for {symbol}: {exit_price}")
            #     return
                
            # Place market sell order
            try:
                order_id = self.broker.place_order(
                    symbol=symbol,
                    qty=pos.quantity,
                    side="SELL",
                    type="MARKET",
                    price=exit_price
                )
                if order_id:
                    logger.info(f"✅ Manual SELL for {symbol} @ {exit_price:.2f} | Order: {order_id}")
                else:
                    logger.error(f"SELL order failed for {symbol}")
                    return
            except Exception as e:
                logger.error(f"Error placing sell order for {symbol}: {e}")
                return
            
            pnl = (exit_price - pos.entry_price) * pos.quantity
            pnl_pct = ((exit_price - pos.entry_price) / pos.entry_price) * 100
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
            logger.info(f"🔴 Closed {symbol} | P&L: {pnl:.2f} ({pnl_pct:.2f}%)")

    # ------------------------------------------------------------------
    # 3:13 PM – run DB updater, scan signals, place new OCO orders
    # ------------------------------------------------------------------
    def run_data_updater(self) -> bool:
        """Execute database updater by direct import and run"""
        try:
            logger.info("🔄 Running database updater...")
            delete_old_data_for_all_stocks(num_days=1)
            update_database()
            logger.info("✅ Database update completed successfully")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to run DB updater: {e}")
            traceback.print_exc()
            return False

    def scan_and_place_signals(self, days_back: int = 100) -> Dict[str, Any]:
        """Scan for new signals and place OCO orders if capital <50% utilised
        Returns dict with 'success', 'signals_found', 'positions_opened' keys"""
        result = {'success': False, 'signals_found': 0, 'positions_opened': 0}
        
        if not self.can_open_position():
            logger.info(f"Capital utilisation {self.utilisation_pct():.2%} – cannot open new positions")
            result['success'] = True
            result['message'] = "Capital limit reached"
            return result

        logger.info("🔍 3:13 PM – scanning for new signals...")
        raw_signals = self._scan_for_signals(days_back)
        if not raw_signals:
            logger.info("No buy signals found")
            result['success'] = True
            result['signals_found'] = 0
            return result


        result['signals_found'] = len(raw_signals)
        selected = self._select_and_weight_signals(raw_signals)
        logger.info(f"****** Selected {selected} signals for entry")

        for signal in selected:
            symbol = signal['symbol']
            if self.state_manager.get_position(symbol) is not None:
                logger.warning(f"Position already open for {symbol}")
                continue
            if not self.can_open_position():
                logger.warning("Capital limit reached, stopping new entries")
                break
            if self._place_new_position(symbol, signal):
                result['positions_opened'] += 1
        
        result['success'] = True
        return result

    def _scan_for_signals(self, days_back: int) -> List[Dict]:
        """Internal signal scanner using the strategy"""
        signals = []
        stocks = self.scanner.get_stock_symbols()[:200]
        end_date=datetime.now()
        start_date = end_date - timedelta(days=days_back)
        #print(DBG)
        for stock in stocks:
            try:
                symbol = stock['symbol']
                table = self.scanner.get_table_name(symbol)
                df = get_table_content(
                    db_name=self.scanner.stock_config['database_config']['db_name'],
                    table_name=table,
                    start_date=start_date,
                    end_date=end_date
                )
                print(df)
                if df is None or df.empty:
                    continue
                df = df.sort_values('time')
                df['time'] = pd.to_datetime(df['time'])
                df = df[['time', 'open', 'high', 'low', 'close', 'volume']]

                signal_df = self.strategy.generate_signals(df,num_back_signals=2)
                if signal_df is None or signal_df.empty:
                    continue
                latest = signal_df.iloc[-1]
                if latest['signal'] == 1:
                    confidence = self.scanner._calculate_confidence(signal_df)
                    signals.append({
                        'symbol': symbol,
                        'name': stock.get('name', symbol),
                        'open': float(latest['open']),
                        'close': float(latest['close']),
                        'sector': stock.get('sector', 'Unknown'),
                        'confidence': confidence,
                    })
                self.data_cache[symbol] = df
            except Exception as e:
                logger.debug(f"Scan error {symbol}: {e}")
        logger.info(f"Found {len(signals)} raw buy signals")
        return signals

    def _select_and_weight_signals(self, signals: List[Dict]) -> List[Dict]:
        """Sector‑based weighting (as in backtest)"""
        config = self.position_weights_config
        max_pos = config.get('max_positions', 5)
        max_per_sector = config.get('max_per_sector', 2)
        sector_weights = config.get('sector_allocation', {})

        # Group by sector
        sectors = {}
        for s in signals:
            sec = s.get('sector', 'Unknown')
            sectors.setdefault(sec, []).append(s)
        for sec in sectors:
            sectors[sec] = sorted(sectors[sec], key=lambda x: x['confidence'], reverse=True)[:max_per_sector]

        priority, others = [], []
        for sec, stocks in sectors.items():
            w = sector_weights.get(sec, 0)
            for s in stocks:
                s['sector_weight'] = w
            (priority if w > 0 else others).extend(stocks)

        if not priority:
            final = sorted(others, key=lambda x: x['confidence'], reverse=True)[:max_pos]
            for s in final: s['final_weight'] = 1.0 / len(final) if final else 0
            return final

        # Allocate according to sector weights
        sec_map = {}
        for s in priority:
            sec_map.setdefault(s['sector'], []).append(s)
        total_w = sum(sector_weights.get(sec, 0) for sec in sec_map)
        final = []
        for sec, stocks in sec_map.items():
            per_stock = (sector_weights.get(sec, 0) / total_w) / len(stocks)
            for s in stocks:
                s['final_weight'] = per_stock
            final.extend(stocks)

        # Add fillers if needed
        remaining = max_pos - len(final)
        if remaining > 0 and others:
            fillers = sorted(others, key=lambda x: x['confidence'], reverse=True)[:remaining]
            for f in fillers: f['final_weight'] = 0.0
            final.extend(fillers)

        # Cap and renormalise
        if len(final) > max_pos:
            final = sorted(final, key=lambda x: (x.get('final_weight', 0), x['confidence']), reverse=True)[:max_pos]
        total_fw = sum(s.get('final_weight', 0) for s in final)
        if total_fw > 0:
            for s in final: s['final_weight'] /= total_fw
        return final

    def _place_new_position(self, symbol: str, signal_info: Dict) -> bool:
        """Place BUY + OCO order. Broker handles full sequence: entry→wait→GTT.
        Returns True only if entry is filled (GTT is secondary)."""
        entry_price = signal_info.get('close', 0)
        if entry_price <= 0:
            logger.warning(f"Invalid entry price for {symbol}: {entry_price}")
            return False

        try:
            entry_price = float(entry_price)
        except (ValueError, TypeError):
            logger.error(f"Cannot convert entry price for {symbol}: {entry_price}")
            return False

        # quantity = 1
        # logger.info(f"🧪 TESTING MODE: Using fixed quantity = {quantity}")
        

        #===== ACTUAL PRODUCTION MODE (COMMENTED FOR TESTING): =====
        weight = signal_info.get('final_weight', 0)
        total_cap = self.get_total_capital()
        alloc_cap = total_cap * weight 
        if weight <= 0:
            logger.warning(f"Invalid weight for {symbol}: {weight}")
            return False

        available = self.get_available_capital()
        #alloc_cap = min(alloc_cap, available)
        # if alloc_cap <= 100:
        #     logger.warning(f"Insufficient capital for {symbol}")
        #     return False
        

        quantity = int(alloc_cap // entry_price)
        if quantity == 0:
            logger.warning(f"Cannot afford even 1 share of {symbol}  entry_price={entry_price:.2f} with alloc_cap={alloc_cap:.2f}")
            return False
        used_capital = quantity * entry_price  # ACTUAL: Dynamic capital for production

        print(f"Allocating capital for {symbol}: total_cap={total_cap:.2f}, weight={weight:.4f}, alloc_cap={alloc_cap:.2f}, available={available:.2f} => quantity={quantity}, used_capital={used_capital:.2f}")

        target_price = entry_price * (1.0 + self.target_profit_pct)
        stop_loss_price = entry_price * (1.0 - self.stop_loss_pct)

        logger.info(f"Placing position: {symbol} | Entry: {entry_price:.2f} | Qty: {quantity} | SL: {stop_loss_price:.2f} | TP: {target_price:.2f}")
        
        return True # TESTING: Skip actual order placement for now

        # BROKER HANDLES FULL SEQUENCE: entry → wait → GTT
        result = self.broker.place_swing_oco(
            symbol=symbol,
            qty=quantity,
            side="BUY",
            entry_price=entry_price,
            sl_price=stop_loss_price,
            tp_price=target_price
        )
        
        if not result or result.get('s') != 'ok':
            logger.error(f"✗ OCO placement failed for {symbol}: {result}")
            return False
        
        buy_order_id = result.get('entry_order_id')
        entry_filled = result.get('entry_filled')
        
        if not entry_filled:
            logger.error(f"✗ Entry order did not fill: {result.get('message')}")
            return False
        
        logger.info(f"✅ {result.get('message')}")
        
        # Save position state
        used_capital = quantity * entry_price
        pos = PositionState(
            symbol=symbol,
            entry_price=entry_price,
            entry_time=datetime.now(self.tz).isoformat(),
            quantity=quantity,
            capital_used=used_capital,
            entry_signal=str(signal_info),
            target_price=target_price,
            stop_loss_price=stop_loss_price,
            highest_price=entry_price,
            order_id=buy_order_id
        )
        if self.state_manager.add_position(pos):
            logger.info(f"✅ Position opened: {symbol} | Cap: {used_capital:.2f} | SL: {stop_loss_price:.2f} | TP: {target_price:.2f}")
            return True
        else:
            logger.error(f"Failed to save state for {symbol}")
            return False



    # ------------------------------------------------------------------
    # Main Trading Loop (time‑triggered)
    # ------------------------------------------------------------------
    def _load_timing_metadata(self) -> tuple:
        """Load last_date_position_refresh and last_date_scan from state"""
        try:
            if self.state_manager.current_session is None:
                logger.warning("No active session to load timing metadata")
                return None, None
            
            # Ensure metadata dict exists
            if not hasattr(self.state_manager.current_session, 'metadata'):
                self.state_manager.current_session.metadata = {}
            
            metadata = self.state_manager.current_session.metadata
            pos_refresh = metadata.get('last_date_position_refresh')
            scan_date = metadata.get('last_date_scan')
            
            logger.info(f"📅 Loaded timing metadata: position_refresh={pos_refresh}, scan={scan_date}")
            return pos_refresh, scan_date
        except Exception as e:
            logger.error(f"Error loading timing metadata: {e}")
            return None, None
    
    def _save_timing_metadata(self, position_refresh_date: str = None, scan_date: str = None):
        """Save timing metadata to state - ENSURES PERSISTENCE TO DISK"""
        try:
            if self.state_manager.current_session is None:
                logger.warning("Cannot save timing metadata: no active session")
                return
            
            # Ensure metadata dict exists
            if not hasattr(self.state_manager.current_session, 'metadata'):
                self.state_manager.current_session.metadata = {}
            
            if position_refresh_date:
                self.state_manager.current_session.metadata['last_date_position_refresh'] = position_refresh_date
                logger.info(f"💾 Saved position_refresh_date: {position_refresh_date}")
            
            if scan_date:
                self.state_manager.current_session.metadata['last_date_scan'] = scan_date
                logger.info(f"💾 Saved scan_date: {scan_date}")
            
            # CRITICAL: Save to disk immediately
            self.state_manager.save_session()
            logger.debug(f"Timing metadata persisted to disk")
        except Exception as e:
            logger.error(f"Error saving timing metadata: {e}")
            traceback.print_exc()

    def run_swing_trading_loop(self):
        logger.info("Starting live swing trading loop")
        
        # Load timing metadata from state (recovers from restart)
        last_date_position_refresh, last_date_scan = self._load_timing_metadata()
        logger.info(f"🔄 Recovered timing state: Last position_refresh={last_date_position_refresh}, last_scan={last_date_scan}")

        while not self.stop_flag.is_set():
            try:
                now = datetime.now(self.tz)
                current_time = now.strftime("%H:%M")
                current_date = now.strftime("%Y-%m-%d")

                # Market open check
                is_open = self.is_market_open()
                print(f"Market open: {is_open} | Time: {current_time} | Date: {current_date}")
                if not is_open:
                    if self.market_open:
                        logger.info("Market closed")
                        self.market_open = False
                    time.sleep(6)
                    continue

                if not self.market_open:
                    logger.info("Market opened")
                    self.market_open = True
                    self.broker_sync.full_sync()

                
                # --- 3:00 PM Position refresh ---
                if current_time == self.position_refresh_time:# and last_date_position_refresh != current_date:
                    logger.info("⏰ Position refresh trigger (3:00 PM)")
                    self.refresh_positions()
                    last_date_position_refresh = current_date
                    self._save_timing_metadata(position_refresh_date=current_date)

                # --- 3:13 PM DB update + signal scan ---
                if current_time == self.scan_time:# and last_date_scan != current_date:
                    logger.info("⏰ 3:13 PM – Database update & signal scan")
                    db_success = self.run_data_updater()
                    if not db_success:
                        logger.error("⚠️ Database update failed - skipping signal scan")
                    else:
                        scan_result = self.scan_and_place_signals(days_back=100)
                        logger.info(f"🎯 Scan result: {scan_result}")
                        if not scan_result.get('success'):
                            logger.error(f"⚠️ Signal scan not Successful: {scan_result.get('message', 'Unknown error')}")
                    
                    last_date_scan = current_date
                    self._save_timing_metadata(scan_date=current_date)

                time.sleep(30)   # check every 30 seconds

            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Loop error: {e}")
                traceback.print_exc()
                time.sleep(60)

        logger.info("Swing trading loop stopped")

    def start(self):
        try:
            self.trading_active.set()
            self.run_swing_trading_loop()
        except Exception as e:
            logger.error(f"Fatal error: {e}")
        finally:
            self.stop()

    def stop(self):
        logger.info("Stopping engine...")
        self.stop_flag.set()
        self.broker_sync.full_sync()
        self.state_manager.save_session()
        logger.info("Engine stopped")


def main():
    engine = SwingTradingEngine(
        config_path="config/live_trading_config.yaml",
        recover=True
    )
    engine.start()


# if __name__ == "__main__":
#     main()

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Swing Trading Engine Test Harness")
    parser.add_argument("--test", choices=["position_refresh", "signal_scan", "place_order", "all"],
                        help="Run a specific test")
    parser.add_argument("--dry_run", action="store_true", default=True,
                        help="Run in dry-run mode (default True). Use --no-dry_run to execute real orders.")
    args = parser.parse_args()

    # Initialize engine with dry_run=True by default (safe)
    engine = SwingTradingEngine(
        config_path="config/live_trading_config.yaml",
        recover=True,   # start fresh for testing
    )

    # Helper to print current state
    def print_state():
        summary = engine.state_manager.get_session_summary()
        print("\n📊 Current State:")
        print(f"  Open positions: {summary.get('open_positions')}")
        print(f"  Capital used: {summary.get('capital_used'):.2f}")
        print(f"  Available: {summary.get('capital_available'):.2f}")
        print(f"  Utilisation: {engine.utilisation_pct():.2%}\n")

    if args.test == "position_refresh":
        print("🔄 Testing position refresh (3:00 PM equivalent)...")
        # Add a dummy position that is old (exceeds max_hold_days)
        old_date = (datetime.now(engine.tz) - timedelta(days=engine.max_hold_days + 1)).isoformat()
        engine.state_manager.add_position(PositionState(
            symbol="NSE:INFY-EQ",
            entry_price=1500.0,
            entry_time=old_date,
            quantity=20,
            capital_used=30000,
            entry_signal="TEST",
            target_price=1575.0,
            stop_loss_price=1470.0,
            order_id="test_order2"
        ))
        print_state()
        engine.refresh_positions()
        print("✅ Sync and time-exit check completed.")

    elif args.test == "signal_scan":
        print("🔍 Testing signal scan and order placement (3:13 PM equivalent)...")
        # Ensure we have enough free capital (set initial capital high)
        engine.state_manager.update_session_metrics(
            capital_available=10000,
            capital_used=0
        )  # reset
        print_state()
        engine.scan_and_place_signals(days_back=100)
        print("✅ Scan completed. New positions would be opened (dry-run).")

    elif args.test == "place_order":
        print("💰 Testing direct order placement...")
        test_signal = {
            'symbol': 'NSE:SBIN-EQ',
            'name': 'SBI BANK',
            'close': 980.0,
            'sector': 'Technology',
            'confidence': 0.85,
            'final_weight': 0.2
        }
        engine._place_new_position(test_signal['symbol'], test_signal)
        print_state()

    elif args.test == "all":
        print("🚀 Running all tests sequentially (dry-run mode recommended)...")
        # 1. Position refresh (add an old position)
        old_date = (datetime.now(engine.tz) - timedelta(days=engine.max_hold_days + 1)).isoformat()
        engine.state_manager.add_position(PositionState(
            symbol="NSE:INFY-EQ", entry_price=1500.0, entry_time=old_date,
            quantity=20, capital_used=30000, entry_signal="TEST", target_price=1575.0, stop_loss_price=1470.0, order_id="test2"
        ))
        engine.refresh_positions()

        # 2. Signal scan
        engine.scan_and_place_signals(days_back=30)

        # 3. Direct order
        test_signal = {'symbol': 'NSE:TCS-EQ', 'open': 3500.0, 'final_weight': 0.2}
        engine._place_new_position(test_signal['symbol'], test_signal)

        print_state()
        print("✅ All tests executed. Check logs for details.")

    else:
        # Normal live trading mode (requires --no-dry_run if you want real orders)
        print("Starting normal live trading engine...")
        engine.start()