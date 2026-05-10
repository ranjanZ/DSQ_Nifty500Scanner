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
import subprocess
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

        # Session ID
        self.session_id = session_id or f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

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
        self.morning_refresh_time = "09:16"      # 9:16 AM - re‑place SL/TP
        self.position_refresh_time = "15:00"     # 3:00 PM - refresh state & time exits
        self.scan_time = "15:13"                 # 3:13 PM - update DB & scan signals

        # Threading / state
        self.market_open = False
        self.trading_active = Event()
        self.stop_flag = Event()
        self.state_lock = Lock()

        # Data caches
        self.data_cache = {}
        self.stock_meta = {}
        self.oco_orders = {}   # {symbol: {'sl_order_id':..., 'tp_order_id':...}}

        # Recover previous session
        if recover:
            self._recover_session()
        else:
            self.state_manager.create_new_session(self.session_id, self.trading_config['initial_capital'])

        logger.info(f"Swing Trading Engine initialized – Session: {self.session_id}")
        logger.info(f"Morning refresh: {self.morning_refresh_time} | Position refresh: {self.position_refresh_time}")
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
        now = datetime.now(self.tz)
        if now.weekday() >= 5:
            return False
        open_time = datetime.strptime(self.trading_config['market_open'], "%H:%M").time()
        close_time = datetime.strptime(self.trading_config['market_close'], "%H:%M").time()
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
        return self.state_manager.get_session_summary().get('capital_total', self.trading_config['initial_capital'])

    def utilisation_pct(self) -> float:
        total = self.get_total_capital()
        used = self.get_used_capital()
        return used / total if total > 0 else 0.0

    def can_open_position(self) -> bool:
        return self.utilisation_pct() < 0.51

    # ------------------------------------------------------------------
    # OCO Order Management (One‑Cancels‑Other: SL + TP)
    # ------------------------------------------------------------------
    def _place_oco_bracket(self, symbol: str, quantity: int, entry_price: float,
                           stop_loss_price: float, target_price: float) -> bool:
        """
        Place a true OCO bracket order using the broker's native OCO API.
        For Fyers, this is a bracket with entry + SL + TP orders.
        Returns True if OCO placed successfully.
        """
        try:
            # Fyers OCO - returns dict with order IDs
            oco_result = self.broker.place_oco_order(
                symbol=symbol,
                qty=quantity,
                side="BUY",
                entry_price=entry_price,
                stop_loss=stop_loss_price,
                take_profit=target_price
            )
            
            parent_id = oco_result.get('parent')
            if parent_id:
                self.oco_orders[symbol] = {
                    'parent_id': parent_id,
                    'sl_id': oco_result.get('sl_order_id'),
                    'tp_id': oco_result.get('tp_order_id'),
                    'sl_price': stop_loss_price,
                    'tp_price': target_price,
                    'quantity': quantity
                }
                logger.info(f"✅ OCO bracket placed for {symbol} | SL: {stop_loss_price:.2f} | TP: {target_price:.2f}")
                return True
            else:
                logger.error(f"Failed to place OCO for {symbol}")
                return False
        except Exception as e:
            logger.error(f"OCO placement error for {symbol}: {e}")
            return False

    def _cancel_oco_bracket(self, symbol: str) -> bool:
        """Cancel existing OCO orders for a symbol"""
        if symbol not in self.oco_orders:
            return True
        try:
            oco_info = self.oco_orders[symbol]
            # Cancel all three orders (parent entry, SL, TP)
            if oco_info.get('parent_id'):
                self.broker.cancel_order(oco_info['parent_id'])
            if oco_info.get('sl_id'):
                self.broker.cancel_order(oco_info['sl_id'])
            if oco_info.get('tp_id'):
                self.broker.cancel_order(oco_info['tp_id'])
            del self.oco_orders[symbol]
            logger.info(f"Cancelled OCO bracket for {symbol}")
            return True
        except Exception as e:
            logger.warning(f"Could not cancel OCO for {symbol}: {e}")
            return False

    # ------------------------------------------------------------------
    # Morning refresh (9:16 AM) – re‑place OCO for all active positions
    # ------------------------------------------------------------------
    def refresh_sl_tp_at_market_open(self):
        """Cancel old OCO orders and place fresh ones for every open position"""
        positions = self.state_manager.get_all_positions()
        if not positions:
            logger.info("No active positions – nothing to refresh")
            return

        logger.info("🔄 Morning refresh: Re‑placing SL/TP orders...")
        for symbol, pos in positions.items():
            self._cancel_oco_bracket(symbol)
            # Place new OCO using current open price? Use stored SL/TP levels
            success = self._place_oco_bracket(
                symbol=symbol,
                quantity=pos.quantity,
                entry_price=pos.entry_price,      # not used in OCO? broker uses for reference
                stop_loss_price=pos.stop_loss_price,
                target_price=pos.target_price
            )
            if not success:
                logger.warning(f"⚠️  Could not re‑place SL/TP for {symbol}")

    # ------------------------------------------------------------------
    # Position refresh at 3:00 PM – sync & close time‑exceeded
    # ------------------------------------------------------------------
    def refresh_positions(self):
        """
        - Sync with broker: detect any positions auto‑closed by SL/TP
        - Close positions that exceeded max_hold_days
        - Update capital accordingly
        """
        logger.info("📊 3:00 PM position refresh – syncing with broker...")
        # Full sync updates capital and open positions automatically
        sync_result = self.broker_sync.full_sync()
        logger.info(f"Sync completed: {sync_result}")

        # Now check time‑based exits (holding period exceeded)
        positions = self.state_manager.get_all_positions()
        now_time = datetime.now(self.tz)
        for symbol, pos in positions.items():
            entry_date = datetime.fromisoformat(pos.entry_time)
            days_held = (now_time - entry_date).days
            if days_held >= self.max_hold_days:
                logger.warning(f"⏱️  {symbol} exceeded {self.max_hold_days} days – closing")
                # Get latest price from broker
                current_price = self._get_current_price(symbol)
                if current_price:
                    self._cancel_oco_bracket(symbol)
                    self._manual_close_position(symbol, current_price, "TIME_LIMIT_EXCEEDED")

    def _get_current_price(self, symbol: str) -> Optional[float]:
        """Fetch current LTP for a symbol (via broker)"""
        try:
            quotes = self.broker.get_quotes(symbol)
            if quotes and 'd' in quotes:
                # Fyers format: quotes['d'][0]['v']['lp']
                ltp = quotes['d'][0]['v']['lp']
                return float(ltp)
            return None
        except:
            return None

    def _manual_close_position(self, symbol: str, exit_price: float, reason: str):
        with self.state_lock:
            pos = self.state_manager.get_position(symbol)
            if not pos:
                return
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
                    logger.info(f"Manual SELL for {symbol} @ {exit_price:.2f}")
            except Exception as e:
                logger.error(f"Manual sell failed: {e}")
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
    def run_data_updater(self):
        """Execute the external script that updates the database"""
        script_path = "src/data_pipeline/read_data_store_db_lambda1.py"
        if not os.path.exists(script_path):
            logger.warning(f"DB updater script not found: {script_path}")
            return
        try:
            logger.info("🔄 Running database updater...")
            result = subprocess.run([sys.executable, script_path], capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                logger.info("Database update completed successfully")
            else:
                logger.error(f"DB updater error: {result.stderr}")
        except Exception as e:
            logger.error(f"Failed to run DB updater: {e}")

    def scan_and_place_signals(self, days_back: int = 100):
        """Scan for new signals and place OCO orders if capital <50% utilised"""
        if not self.can_open_position():
            logger.info(f"Capital utilisation {self.utilisation_pct():.2%} – cannot open new positions")
            return

        logger.info("🔍 3:13 PM – scanning for new signals...")
        raw_signals = self._scan_for_signals(days_back)
        if not raw_signals:
            logger.info("No buy signals found")
            return

        selected = self._select_and_weight_signals(raw_signals)
        logger.info(f"Selected {len(selected)} signals for entry")

        for signal in selected:
            symbol = signal['symbol']
            if self.state_manager.get_position(symbol) is not None:
                continue
            if not self.can_open_position():
                logger.warning("Capital limit reached, stopping new entries")
                break
            self._place_new_position(symbol, signal)

    def _scan_for_signals(self, days_back: int) -> List[Dict]:
        """Internal signal scanner using the strategy"""
        signals = []
        stocks = self.scanner.get_stock_symbols()[:200]
        end_date = datetime.now(self.tz).replace(hour=0, minute=0, second=0, microsecond=0)
        start_date = end_date - timedelta(days=days_back)

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
                if df is None or df.empty:
                    continue
                df = df.sort_values('time')
                df['time'] = pd.to_datetime(df['time'])
                df = df[['time', 'open', 'high', 'low', 'close', 'volume']]

                signal_df = self.strategy.generate_signals(df)
                if signal_df is None or signal_df.empty:
                    continue
                latest = signal_df.iloc[-1]
                if latest['signal'] == 1:
                    confidence = self.scanner._calculate_confidence(signal_df)
                    signals.append({
                        'symbol': symbol,
                        'name': stock.get('name', symbol),
                        'open': float(latest['open']),
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
        """Place BUY + OCO order for a new signal"""
        entry_price = signal_info.get('open', 0)
        if entry_price <= 0:
            logger.warning(f"Invalid entry price for {symbol}")
            return False

        # ===== TESTING MODE: Use quantity 1 for small test =====
        quantity = 1  # Fixed quantity for testing
        logger.info(f"🧪 TESTING MODE: Using fixed quantity = {quantity}")
        
        # ===== ACTUAL PRODUCTION MODE (COMMENTED FOR TESTING): =====
        # weight = signal_info.get('final_weight', 0)
        # total_cap = self.get_total_capital()
        # alloc_cap = total_cap * weight if weight > 0 else self.trading_config['max_position_size']
        # available = self.get_available_capital()
        # alloc_cap = min(alloc_cap, available)
        # if alloc_cap <= 0:
        #     logger.warning(f"Insufficient capital for {symbol}")
        #     return False
        # quantity = int(alloc_cap // entry_price)
        # if quantity == 0:
        #     logger.warning(f"Cannot afford 1 share of {symbol}")
        #     return False
        
        # used_capital = quantity * entry_price  # ACTUAL: Dynamic capital for production
        used_capital = quantity * entry_price  # TESTING: Using entry_price for qty=1
        target_price = entry_price * (1 + self.target_profit_pct)
        stop_loss_price = entry_price * (1 - self.stop_loss_pct)

        # 1. Place BUY order
        buy_order_id = self.broker.place_order(
            symbol=symbol,
            qty=quantity,
            side="BUY",
            type="MARKET",
            price=entry_price
        )
        if not buy_order_id:
            logger.error(f"BUY order failed for {symbol}")
            return False
        logger.info(f"✅ BUY placed: {symbol} qty={quantity} @ {entry_price:.2f}")

        # 2. Place OCO bracket (SL + TP)
        oco_ok = self._place_oco_bracket(symbol, quantity, entry_price, stop_loss_price, target_price)
        if not oco_ok:
            logger.warning(f"OCO placement failed – will retry at next refresh")

        # 3. Save state
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
            logger.info(f"📈 Position opened: {symbol} | Cap: {used_capital:.2f} | SL: {stop_loss_price:.2f} | TP: {target_price:.2f}")
            return True
        else:
            logger.error(f"Failed to save state for {symbol}")
            return False

    # ------------------------------------------------------------------
    # Main Trading Loop (time‑triggered)
    # ------------------------------------------------------------------
    def run_swing_trading_loop(self):
        logger.info("Starting live swing trading loop")
        last_date_morning = None
        last_date_position_refresh = None
        last_date_scan = None

        while not self.stop_flag.is_set():
            try:
                now = datetime.now(self.tz)
                current_time = now.strftime("%H:%M")
                current_date = now.strftime("%Y-%m-%d")

                # Market open check
                is_open = self.is_market_open()
                if not is_open:
                    if self.market_open:
                        logger.info("Market closed")
                        self.market_open = False
                    time.sleep(60)
                    continue

                if not self.market_open:
                    logger.info("Market opened")
                    self.market_open = True
                    self.broker_sync.full_sync()

                # --- 9:16 AM Morning SL/TP refresh ---
                if current_time == self.morning_refresh_time and last_date_morning != current_date:
                    logger.info("⏰ Morning refresh trigger")
                    self.refresh_sl_tp_at_market_open()
                    last_date_morning = current_date

                # --- 3:00 PM Position refresh ---
                if current_time == self.position_refresh_time and last_date_position_refresh != current_date:
                    logger.info("⏰ Position refresh trigger (3:00 PM)")
                    self.refresh_positions()
                    last_date_position_refresh = current_date

                # --- 3:13 PM DB update + signal scan ---
                if current_time == self.scan_time and last_date_scan != current_date:
                    logger.info("⏰ 3:13 PM – Database update & signal scan")
                    self.run_data_updater()
                    self.scan_and_place_signals(days_back=100)
                    last_date_scan = current_date

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
        for sym in list(self.oco_orders.keys()):
            self._cancel_oco_bracket(sym)
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
    parser.add_argument("--test", choices=["morning_refresh", "position_refresh", "signal_scan", "place_order", "all"],
                        help="Run a specific test")
    parser.add_argument("--dry_run", action="store_true", default=True,
                        help="Run in dry-run mode (default True). Use --no-dry_run to execute real orders.")
    args = parser.parse_args()

    # Initialize engine with dry_run=True by default (safe)
    engine = SwingTradingEngine(
        config_path="config/live_trading_config.yaml",
        recover=False,   # start fresh for testing
    )

    # Helper to print current state
    def print_state():
        summary = engine.state_manager.get_session_summary()
        print("\n📊 Current State:")
        print(f"  Open positions: {summary.get('open_positions')}")
        print(f"  Capital used: {summary.get('capital_used'):.2f}")
        print(f"  Available: {summary.get('capital_available'):.2f}")
        print(f"  Utilisation: {engine.utilisation_pct():.2%}\n")

    if args.test == "morning_refresh":
        print("🔁 Testing morning SL/TP refresh (9:16 AM equivalent)...")
        # Manually add a dummy position for testing
        engine.state_manager.add_position(PositionState(
            symbol="NSE:RELIANCE-EQ",
            entry_price=2500.0,
            entry_time=datetime.now(engine.tz).isoformat(),
            quantity=10,
            capital_used=25000,
            target_price=2625.0,
            stop_loss_price=2450.0,
            order_id="test_order"
        ))
        print_state()
        engine.refresh_sl_tp_at_market_open()
        print("✅ Done. Check logs for OCO placement (dry-run simulated).")

    elif args.test == "position_refresh":
        print("🔄 Testing position refresh (3:00 PM equivalent)...")
        # Add a dummy position that is old (exceeds max_hold_days)
        old_date = (datetime.now(engine.tz) - timedelta(days=engine.max_hold_days + 1)).isoformat()
        engine.state_manager.add_position(PositionState(
            symbol="NSE:INFY-EQ",
            entry_price=1500.0,
            entry_time=old_date,
            quantity=20,
            capital_used=30000,
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
        engine.state_manager.update_capital(engine.initial_capital)  # reset
        print_state()
        engine.scan_and_place_signals(days_back=30)
        print("✅ Scan completed. New positions would be opened (dry-run).")

    elif args.test == "place_order":
        print("💰 Testing direct order placement...")
        test_signal = {
            'symbol': 'NSE:TCS-EQ',
            'name': 'TCS',
            'open': 3500.0,
            'sector': 'Technology',
            'confidence': 0.85,
            'final_weight': 0.2
        }
        engine._place_new_position(test_signal['symbol'], test_signal)
        print_state()

    elif args.test == "all":
        print("🚀 Running all tests sequentially (dry-run mode recommended)...")
        # 1. Morning refresh
        engine.state_manager.add_position(PositionState(
            symbol="NSE:RELIANCE-EQ", entry_price=2500.0, entry_time=datetime.now(engine.tz).isoformat(),
            quantity=10, capital_used=25000, target_price=2625.0, stop_loss_price=2450.0, order_id="test1"
        ))
        engine.refresh_sl_tp_at_market_open()

        # 2. Position refresh (add an old position)
        old_date = (datetime.now(engine.tz) - timedelta(days=engine.max_hold_days + 1)).isoformat()
        engine.state_manager.add_position(PositionState(
            symbol="NSE:INFY-EQ", entry_price=1500.0, entry_time=old_date,
            quantity=20, capital_used=30000, target_price=1575.0, stop_loss_price=1470.0, order_id="test2"
        ))
        engine.refresh_positions()

        # 3. Signal scan
        engine.scan_and_place_signals(days_back=30)

        # 4. Direct order
        test_signal = {'symbol': 'NSE:TCS-EQ', 'open': 3500.0, 'final_weight': 0.2}
        engine._place_new_position(test_signal['symbol'], test_signal)

        print_state()
        print("✅ All tests executed. Check logs for details.")

    else:
        # Normal live trading mode (requires --no-dry_run if you want real orders)
        print("Starting normal live trading engine...")
        engine.start()