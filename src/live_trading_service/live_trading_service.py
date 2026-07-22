"""
Live Trading Service - Real-time trading execution
Uses broker service for order execution and strategy service for signals
"""

import os
import sys
import time
import json
import logging
import yaml
import importlib.util
import types
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import pytz

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def _load_module_from_file(module_name: str, file_path: str):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _ensure_package(name: str):
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)
        sys.modules[name].__path__ = []


def load_strategy_class(strategy_name: str, project_root: str):
    """Load a strategy class directly from its file (mirrors backtest engine)."""
    strategies_dir = os.path.join(project_root, "src", "strategy_service", "strategies")

    aliases = {
        "volume_support_resistance": "volume_support_resistance_strategy",
        "support_resistance": "volume_support_resistance_strategy",
        "vss": "volume_support_resistance_strategy",
        "Support_Resistance": "volume_support_resistance_strategy",
    }
    folder = aliases.get(strategy_name, strategy_name)

    strategy_folder = os.path.join(strategies_dir, folder)
    if not os.path.isdir(strategy_folder):
        for f in os.listdir(strategies_dir):
            if os.path.isdir(os.path.join(strategies_dir, f)):
                if strategy_name.replace("_", "").lower() in f.replace("_", "").lower():
                    folder = f
                    strategy_folder = os.path.join(strategies_dir, folder)
                    break
        else:
            raise ValueError(f"Strategy folder not found: {strategy_name} (looked in {strategies_dir})")

    config_file = os.path.join(strategy_folder, "config.yaml")
    class_name = None
    if os.path.exists(config_file):
        with open(config_file, "r") as f:
            cfg = yaml.safe_load(f) or {}
        class_name = cfg.get("class_name")

    if not class_name:
        parts = folder.replace("_strategy", "").split("_")
        class_name = "".join(p.capitalize() for p in parts) + "Strategy"

    base_file = os.path.join(project_root, "src", "strategy_service", "strategy_base.py")
    _load_module_from_file("src.strategy_service.strategy_base", base_file)
    _ensure_package("src.strategy_service")
    _ensure_package("src.strategy_service.strategies")
    _ensure_package(f"src.strategy_service.strategies.{folder}")

    strategy_file = os.path.join(strategy_folder, "strategy.py")
    mod = _load_module_from_file(
        f"src.strategy_service.strategies.{folder}.strategy",
        strategy_file
    )

    if not hasattr(mod, class_name):
        available = [x for x in dir(mod) if not x.startswith("_")]
        raise AttributeError(
            f"Class '{class_name}' not found in {strategy_file}. "
            f"Available: {available}"
        )
    return getattr(mod, class_name)


class LiveTradingService:
    """Main live trading service orchestrator"""

    def __init__(self, config_path: Optional[str] = None):
        self.logger = logging.getLogger("LiveTradingService")
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s | %(name)s | %(levelname)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)
        self.logger.propagate = False

        if config_path is None:
            config_path = self._find_config_path()

        self.config = self._load_config(config_path)
        self.trading_config = self.config.get('live_trading_service', self.config.get('live_trading', {}))

        self.broker = None
        self.strategy = None
        self.data_service = None
        self.portfolio_state = None

        self.is_running = False
        self.positions = {}
        self.orders = {}
        self._pending_signals = []
        self.daily_stats = {
            'trades_today': 0,
            'pnl_today': 0.0,
            'date': None
        }

        self.enabled = self.trading_config.get('enabled', False)
        self.initial_capital = self.trading_config.get('initial_capital', 20000)
        self.risk_per_trade = self.trading_config.get('risk_per_trade', 0.02)
        self.target_profit_pct = self.trading_config.get('target_profit_pct', 0.05)
        self.stop_loss_pct = self.trading_config.get('stop_loss_pct', 0.02)
        self.max_holding_days = self.trading_config.get('max_holding_days', 7)

        self.market_open = self.trading_config.get('market_open', '09:15')
        self.market_close = self.trading_config.get('market_close', '15:30')

        self.scan_time = self.trading_config.get('scan_time')
        self.trade_time = self.trading_config.get('trade_time')

        self.price_update_interval = self.trading_config.get('price_update_interval', 5)

        self.position_weights = self.trading_config.get('position_weights', {})

        self._sector_lookup: Dict[str, str] = {}

    def _find_config_path(self) -> str:
        candidates = [
            os.path.join(_PROJECT_ROOT, "config", "live.user.yaml"),
            os.path.join(_PROJECT_ROOT, "config", "live_trading_config.yaml"),
            os.path.join(_PROJECT_ROOT, "config", "live.yaml"),
            os.path.join(_PROJECT_ROOT, "config", "live_trading.user.yaml"),
            os.path.join("config", "live.user.yaml"),
            os.path.join("config", "live_trading_config.yaml"),
            "config/live.user.yaml",
            "config/live_trading_config.yaml",
        ]
        for path in candidates:
            if os.path.exists(path):
                self.logger.info(f"Auto-detected config: {path}")
                return path
        return os.path.join(_PROJECT_ROOT, "config", "live.user.yaml")

    def _load_config(self, config_path: str) -> Dict[str, Any]:
        try:
            with open(config_path, 'r') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            self.logger.error(f"Error loading config from '{config_path}': {e}")
            raise

    def _build_sector_lookup(self, stocks: List[Dict[str, Any]]):
        """Build symbol->sector mapping from stock list."""
        self._sector_lookup = {}
        for stock in stocks:
            sym = stock.get('fyers_symbol', '')
            sector = stock.get('sector', 'Unknown')
            if sym:
                self._sector_lookup[sym] = sector

    def _get_sector(self, symbol: str) -> str:
        return self._sector_lookup.get(symbol, "Unknown")

    def _allocate_capital_to_signals(self, signals: List[Dict]) -> List[Dict]:
        """
        Allocate capital ONLY to stocks that generated signals.
        Returns: signals with 'allocated_capital' injected.
        """
        if not signals:
            return []

        pw = self.position_weights
        if not pw or pw.get("method") != "sector_based":
            per_signal = self.initial_capital / max(len(signals), 1)
            for s in signals:
                s['allocated_capital'] = per_signal
            return signals

        sector_alloc = pw.get("sector_allocation", {})
        max_positions = pw.get("max_positions", len(signals))
        max_per_sector = pw.get("max_per_sector", 1)

        # Group signals by sector
        sector_signals: Dict[str, List[Dict]] = {}
        for sig in signals:
            sector_signals.setdefault(sig.get('sector', 'Unknown'), []).append(sig)

        # Pick top N per sector (by signal strength)
        selected = []
        for sector, sigs in sector_signals.items():
            sigs.sort(key=lambda x: x.get('strength', 0), reverse=True)
            selected.extend(sigs[:max_per_sector])

        # Sort by sector weight → strength, then cap total positions
        selected.sort(
            key=lambda s: (sector_alloc.get(s.get('sector', 'Unknown'), 0),
                           s.get('strength', 0)),
            reverse=True
        )
        selected = selected[:max_positions]

        # Allocate capital proportional to sector weight
        total_weight = sum(sector_alloc.get(s.get('sector', 'Unknown'), 0) for s in selected)
        if total_weight <= 0:
            per_signal = self.initial_capital / max(len(selected), 1)
            for s in selected:
                s['allocated_capital'] = per_signal
        else:
            for s in selected:
                weight = sector_alloc.get(s.get('sector', 'Unknown'), 0)
                s['allocated_capital'] = self.initial_capital * (weight / total_weight)

        return selected

    def initialize(self):
        try:
            if not self.enabled:
                self.logger.warning("⚠️  Live trading is DISABLED in config. Set enabled: true to trade.")
                return False

            from src.broker_service.fyers.fyers_broker_impl import FyersBroker
            self.broker = FyersBroker()
            if not self.broker.connect():
                raise Exception("Failed to connect to broker")
            self.logger.info("✅ Broker connected")

            strategy_name = self.trading_config.get('strategy_type', 'Support_Resistance')
            StrategyClass = load_strategy_class(strategy_name, _PROJECT_ROOT)
            self.strategy = StrategyClass()
            self.logger.info(f"✅ Strategy initialized: {self.strategy.name}")

            from src.data_service import DataService
            # self.data_service = DataService({
            #     'db_name': self.config.get('database', {}).get('db_name', 'spot_db'),
            #     'stock_list_path': 'config/default/stock_list.yaml'
            # })
            self.data_service = DataService({
                'db_name':'spot_db_anamika',
                'stock_list_path': 'config/default/stock_list.yaml'
            })

            self.logger.info("✅ Data service initialized")
            
            # Initialize portfolio state manager for persistence
            from src.live_trading_service.portfolio_state import PortfolioStateManager
            self.portfolio_state = PortfolioStateManager(project_root=_PROJECT_ROOT)
            self.portfolio_state.load_state()
            self.logger.info("✅ Portfolio state manager initialized")
            
            # Sync local positions with broker positions on startup
            self._sync_positions_with_broker()
            
            self.logger.info(f"💰 Initial Capital: ₹{self.initial_capital:,.0f} | Risk/Trade: {self.risk_per_trade*100:.1f}%")
            self.logger.info(f"🎯 Target: {self.target_profit_pct*100:.1f}% | Stop: {self.stop_loss_pct*100:.1f}% | Max Hold: {self.max_holding_days}d")

            return True
        except Exception as e:
            self.logger.error(f"Initialization failed: {e}")
            return False

    def start(self):
        if not self.enabled:
            self.logger.error("❌ Cannot start: live trading is disabled in config")
            return

        self.is_running = True
        self.logger.info("🚀 Starting live trading...")

        tz = pytz.timezone(self.config.get('timezone', 'Asia/Kolkata'))
        last_scan_minute = None
        last_trade_minute = None
        last_price_check = 0

        while self.is_running:
            try:
                now = datetime.now(tz)

                if self.daily_stats['date'] != now.date():
                    # Save state before new day
                    if self.portfolio_state:
                        self._sync_positions_to_portfolio_state()
                        self.portfolio_state.save_state()
                    
                    self.daily_stats = {
                        'trades_today': 0,
                        'pnl_today': 0.0,
                        'date': now.date()
                    }
                    self._pending_signals = []
                    # Rollover portfolio state to new day
                    if self.portfolio_state:
                        self.portfolio_state.rollover_day(now.strftime('%Y-%m-%d'))
                    self.logger.info(f"📅 New trading day: {now.date()}")

                if not self._is_market_open(now):
                    self.logger.info("Market closed, waiting...")
                    time.sleep(60)
                    continue

                current_minute = now.strftime("%H:%M")

                if time.time() - last_price_check >= self.price_update_interval:
                    self._monitor_positions()
                    last_price_check = time.time()

                # SCAN: find signals on ALL stocks, then allocate capital
                if self.scan_time and current_minute == self.scan_time and last_scan_minute != current_minute:
                    self.logger.info(f"Updating the database at {now.strftime('%H:%M:%S')}...")
                    self.data_service.delete_all_stocks_new_data(num_days=1)
                    self.data_service.update_all_stocks()


                    self.logger.info(f"🔍 Scanning for signals at {now.strftime('%H:%M:%S')}...")
                    raw_signals = self._scan_for_signals()
                    self._pending_signals = self._allocate_capital_to_signals(raw_signals)
                    last_scan_minute = current_minute

                # TRADE: execute on allocated signals
                if self.trade_time and current_minute == self.trade_time and last_trade_minute != current_minute:
                    if self._pending_signals:
                        self.logger.info(f"📤 Executing trades at {now.strftime('%H:%M:%S')}...")
                        self._process_signals(self._pending_signals)
                        self._pending_signals = []
                    else:
                        self.logger.info("No pending signals to execute")
                    last_trade_minute = current_minute

                time.sleep(max(self.price_update_interval, 1))

            except KeyboardInterrupt:
                self.logger.info("⏹️  Stopping by user request")
                self.stop()
                break
            except Exception as e:
                self.logger.error(f"Trading cycle error: {e}")
                time.sleep(60)

    def stop(self):
        self.is_running = False
        # Save state before stopping
        if self.portfolio_state:
            self._sync_positions_to_portfolio_state()
            self.portfolio_state.save_state()
        if self.broker:
            self.broker.disconnect()
        self.logger.info("⏹️  Live trading stopped")

    def _is_market_open(self, now: datetime) -> bool:
        if now.weekday() >= 7:  # FIX: Saturday=5, Sunday=6
            return False
        market_open = datetime.strptime(self.market_open, '%H:%M').time()
        market_close = datetime.strptime(self.market_close, '%H:%M').time()
        return market_open <= now.time() <= market_close

    def _scan_for_signals(self, num_days_back: int = 100) -> List[Dict]:
        """
        Scan ALL stocks for signals. No capital allocation here.
        Returns raw signals sorted by strength.
        Also saves scan results to data/portfolio_state/signals/
        """
        signals = []
        stocks = self.data_service.get_stock_list()
        if not stocks:
            self.logger.warning("No stocks in watchlist")
            return signals

        self._build_sector_lookup(stocks)
        self.logger.info(f"🔍 Scanning ALL {len(stocks)} stocks for signals")

        for stock in stocks:
            symbol = stock.get('fyers_symbol')
            if not symbol:
                continue
            if symbol in self.positions:
                continue

            end_date = datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.now() - timedelta(days=num_days_back)).strftime('%Y-%m-%d')
            df = self.data_service.get_historical_data(symbol, start_date, end_date)

            if df is None or df.empty:
                continue

            signal_df = self.strategy.generate_signals(df, num_back_signals=1)
            if signal_df is not None and not signal_df.empty:
                latest = signal_df.iloc[-1]
                if latest.get('signal') == 1:
                    signals.append({
                        'symbol': symbol,
                        'signal': 1,
                        'price': latest.get('close', 0),
                        'strength': latest.get('signal_strength', 0),
                        'timestamp': latest.get('time', datetime.now().isoformat()),
                        'sector': stock.get('sector', 'Unknown'),
                    })

        signals.sort(key=lambda x: x.get('strength', 0), reverse=True)
        self.logger.info(f"Found {len(signals)} raw buy signals")
        
        # Save scan results to data/portfolio_state/signals/
        self._save_scan_results(signals)
        
        return signals
    
    def _save_scan_results(self, signals: List[Dict]):
        """Save scan results with timestamp to data/portfolio_state/signals/"""
        try:
            import os
            from datetime import datetime
            import pytz
            import tempfile
            
            tz = pytz.timezone(self.config.get('timezone', 'Asia/Kolkata'))
            now = datetime.now(tz)
            date_str = now.strftime('%Y-%m-%d')
            timestamp_str = now.strftime('%Y-%m-%d %H:%M:%S')
            
            # Create directory if it doesn't exist
            signals_dir = os.path.join(_PROJECT_ROOT, 'data', 'portfolio_state', 'signals')
            os.makedirs(signals_dir, exist_ok=True)
            
            # File path: data/portfolio_state/signals/signals_YYYY-MM-DD.json
            file_path = os.path.join(signals_dir, f'signals_{date_str}.json')
            
            # Convert signals to JSON-serializable format (handle numpy types)
            def convert_to_serializable(obj):
                """Convert numpy types and other non-serializable objects to native Python types."""
                if isinstance(obj, dict):
                    return {k: convert_to_serializable(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [convert_to_serializable(item) for item in obj]
                elif hasattr(obj, 'item'):  # numpy types
                    return obj.item()
                elif hasattr(obj, 'tolist'):  # numpy arrays
                    return obj.tolist()
                elif isinstance(obj, (datetime,)):
                    return obj.isoformat()
                else:
                    return obj
            
            serializable_signals = convert_to_serializable(signals)
            
            # Prepare new scan record
            scan_record = {
                'scan_time': timestamp_str,
                'total_stocks_scanned': len(self.data_service.get_stock_list()) if self.data_service else 0,
                'signals_found': len(signals),
                'signals': serializable_signals
            }
            
            # Load existing data if file exists
            existing_data = {'scans': [], 'last_scan_time': None}
            if os.path.exists(file_path):
                try:
                    with open(file_path, 'r') as f:
                        existing_data = json.load(f)
                        if not isinstance(existing_data, dict):
                            existing_data = {'scans': []}
                        if 'scans' not in existing_data:
                            existing_data['scans'] = []
                except Exception as e:
                    self.logger.warning(f"Could not load existing signals file: {e}. Starting fresh.")
                    existing_data = {'scans': []}
            
            # Add new scan to the list
            existing_data['scans'].append(scan_record)
            
            # Keep only last 30 days of scans to prevent file bloat
            cutoff_date = (now - timedelta(days=30)).strftime('%Y-%m-%d')
            existing_data['scans'] = [
                s for s in existing_data['scans'] 
                if s.get('scan_time', '')[:10] >= cutoff_date
            ]
            
            # Update last_scan_time metadata
            existing_data['last_scan_time'] = timestamp_str
            existing_data['last_updated'] = timestamp_str
            
            # Atomic write: write to temp file first, then rename
            temp_fd, temp_path = tempfile.mkstemp(dir=signals_dir, suffix='.json.tmp')
            try:
                with os.fdopen(temp_fd, 'w') as f:
                    json.dump(existing_data, f, indent=2)
                # Atomic rename
                os.replace(temp_path, file_path)
            except Exception:
                # Clean up temp file if something goes wrong
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                raise
            
            self.logger.info(f"💾 Saved {len(signals)} signals to {file_path}")
            
        except Exception as e:
            self.logger.error(f"Failed to save scan results: {e}")

    def _process_signals(self, signals: List[Dict]):
        if not signals:
            return

        for signal in signals:
            symbol = signal['symbol']
            if symbol in self.positions:
                continue

            allocated_capital = signal['allocated_capital']
            price = signal['price']

            if price <= 0:
                self.logger.warning(f"Invalid price for {symbol}: {price}")
                continue

            risk_amount = allocated_capital * self.risk_per_trade
            stop_distance = price * self.stop_loss_pct

            if stop_distance <= 0:
                self.logger.warning(f"Invalid stop distance for {symbol}")
                continue

            qty = int(risk_amount / stop_distance)
            if qty <= 0:
                qty = int(allocated_capital / price)

            if qty <= 0:
                self.logger.info(f"Skipping {symbol}: calculated qty is 0")
                continue

            # Calculate GTT prices for swing trading (delivery)
            sl_price = price * (1 - self.stop_loss_pct)
            tp_price = price * (1 + self.target_profit_pct)

            order_params = {
                'symbol': symbol,
                'qty': qty,
                'side': 'BUY',
                'type': 'MARKET',
                'product_type': 'CNC',  # Delivery for swing trading
                'stop_loss_price': sl_price,
                'take_profit_price': tp_price
            }

            result = self.broker.place_order_v1(order_params)
            if result.get('success'):
                order_id = result.get('order_id')
                gtt_order_id = result.get('gtt_order_id')
                entry_filled = result.get('entry_filled', False)
                gtt_placed = result.get('gtt_placed', False)

                # Store position info for tracking and potential GTT updates later
                self.positions[symbol] = {
                    'entry_price': price,
                    'quantity': qty,
                    'order_id': order_id,
                    'gtt_order_id': gtt_order_id,
                    'entry_time': datetime.now(),
                    'allocated_capital': allocated_capital,
                    'sector': signal.get('sector', 'Unknown'),
                    'sl_price': sl_price,
                    'tp_price': tp_price,
                    'entry_filled': entry_filled,
                    'gtt_active': gtt_placed
                }
                
                if entry_filled and gtt_placed:
                    self.logger.info(f"✅ BUY {qty} {symbol} @ ₹{price:.2f} | GTT Active: SL={sl_price:.2f} TP={tp_price:.2f} | ID: {gtt_order_id}")
                    
                    # Add to portfolio state immediately after successful order
                    if self.portfolio_state:
                        self.portfolio_state.add_holding(
                            symbol=symbol,
                            quantity=qty,
                            average_price=price,
                            current_value=price * qty,
                            entry_time=datetime.now().isoformat()
                        )
                elif entry_filled:
                    self.logger.warning(f"⚠️ BUY {qty} {symbol} @ ₹{price:.2f} | GTT FAILED to place")
                else:
                    self.logger.info(f"⏳ AMO order placed for {qty} {symbol}, waiting for market open")
                    
                self.daily_stats['trades_today'] += 1
            else:
                self.logger.error(f"❌ Order failed for {symbol}: {result.get('error')}")

    def _monitor_positions(self):
        """
        Monitor positions - NOT for exiting (GTT handles exits automatically).
        Used for:
          1. Syncing state with broker (checking if positions exist)
          2. Tracking entry fill status for AMO orders
          3. Logging position info for training/analysis
          4. Potential GTT SL/TP adjustment later
          5. Syncing local state with broker and portfolio state
        """
        # First, sync with broker to ensure we have latest positions
        try:
            broker_positions = self.broker.get_positions()
            broker_symbols = {pos['symbol']: pos for pos in broker_positions if pos.get('quantity', 0) > 0}
        except Exception as e:
            self.logger.warning(f"Could not fetch broker positions: {e}")
            broker_symbols = {}

        # Check for new positions in broker that aren't in local state
        for symbol, broker_pos in broker_symbols.items():
            if symbol not in self.positions:
                # Position exists in broker but not locally - add it
                self.logger.info(f"📥 Found position in broker not in local state: {symbol}")
                qty = broker_pos.get('quantity', 0)
                entry_price = broker_pos.get('entry_price', 0)
                self.positions[symbol] = {
                    'entry_price': entry_price,
                    'quantity': qty,
                    'order_id': None,
                    'gtt_order_id': None,
                    'entry_time': datetime.now(),
                    'allocated_capital': entry_price * qty,
                    'sector': self._get_sector(symbol),
                    'sl_price': 0,
                    'tp_price': 0,
                    'entry_filled': True,
                    'gtt_active': False
                }

                # Only add to portfolio state if it doesn't already exist there either
                if self.portfolio_state and not self.portfolio_state.is_held(symbol):
                    self.portfolio_state.add_holding(
                        symbol=symbol,
                        quantity=qty,
                        average_price=entry_price,
                        entry_time=datetime.now().isoformat()
                    )

        # Update existing positions with broker data
        for symbol, pos in list(self.positions.items()):
            # Check if position is still active in broker
            is_in_broker = symbol in broker_symbols
            
            # If position was exited at broker level (GTT triggered), remove from local state
            if not is_in_broker and pos.get('entry_filled', False):
                self.logger.info(f"📤 Position {symbol} no longer in broker (likely GTT exit)")
                # Record the exit in portfolio state before removing
                if self.portfolio_state:
                    self.portfolio_state.close_holding(
                        symbol=symbol,
                        exit_price=pos.get('last_ltp', pos['entry_price']),
                        exit_time=datetime.now().isoformat()
                    )
                del self.positions[symbol]
                continue
            
            # If we have an AMO order waiting for fill, check status
            if not pos.get('entry_filled', False):
                # Try to verify if order was filled by checking broker positions
                if is_in_broker:
                    pos['entry_filled'] = True
                    self.logger.info(f"✅ Position {symbol} confirmed filled by broker")
                    
                    # Add to portfolio state
                    if self.portfolio_state:
                        self.portfolio_state.add_holding(
                            symbol=symbol,
                            quantity=pos['quantity'],
                            average_price=pos['entry_price'],
                            entry_time=pos['entry_time'].isoformat()
                        )
            
            # Log position status (for training/analysis)
            if int(time.time()) % 300 < self.price_update_interval:
                try:
                    ltp = self.broker.get_ltp(symbol)
                    pos['last_ltp'] = ltp
                    pnl_pct = (ltp - pos['entry_price']) / pos['entry_price'] if pos['entry_price'] > 0 else 0
                    pnl_amount = (ltp - pos['entry_price']) * pos['quantity']
                    holding_days = (datetime.now() - pos['entry_time']).days
                    
                    gtt_status = "🟢 GTT Active" if pos.get('gtt_active') else "🔴 GTT Inactive"
                    self.logger.info(
                        f"📊 {symbol}: LTP ₹{ltp:.2f} | P&L: {pnl_pct*100:+.1f}% (₹{pnl_amount:,.0f}) | "
                        f"Hold: {holding_days}d | Sector: {pos.get('sector', 'Unknown')} | {gtt_status}"
                    )
                    
                    # Update portfolio state with latest LTP
                    if self.portfolio_state:
                        self.portfolio_state.update_holding_ltp(symbol, ltp)
                except Exception as e:
                    self.logger.debug(f"Could not fetch LTP for {symbol}: {e}")
        
        # Sync portfolio state periodically
        if self.portfolio_state:
            self._sync_positions_to_portfolio_state()

    def _exit_position(self, symbol: str, reason: str, exit_price: Optional[float] = None):
        """
        Manual exit position - NOT used for normal GTT exits.
        Only used for emergency exits or when GTT fails.
        Since we use GTT OCO orders, TP/SL exits happen automatically at broker level.
        This method should only be called for:
          1. Emergency manual exits
          2. Cancelling GTT and exiting manually
          3. Testing purposes
        """
        pos = self.positions.get(symbol)
        if not pos:
            self.logger.warning(f"Position {symbol} not found locally")
            return

        qty = pos['quantity']
        if exit_price is None or exit_price <= 0:
            try:
                exit_price = self.broker.get_ltp(symbol)
            except Exception as e:
                self.logger.error(f"Cannot get LTP for {symbol}: {e}")
                return

        if exit_price <= 0:
            self.logger.error(f"Cannot exit {symbol}: invalid LTP")
            return

        realized_pnl = (exit_price - pos['entry_price']) * qty
        self.daily_stats['pnl_today'] += realized_pnl

        # Cancel GTT first if it exists (to prevent double exit)
        gtt_id = pos.get('gtt_order_id')
        if gtt_id:
            self.logger.info(f"⚠️ Cancelling GTT {gtt_id} before manual exit...")
            try:
                self.broker.cancel_gtt(gtt_id)
            except Exception as e:
                self.logger.warning(f"Could not cancel GTT: {e}")

        order_params = {
            'symbol': symbol,
            'qty': qty,
            'side': 'SELL',
            'type': 'MARKET',
            'product_type': 'CNC'
        }

        result = self.broker.place_order(order_params)
        if result.get('success'):
            holding_days = (datetime.now() - pos['entry_time']).days
            self.logger.info(f"✅ Exited {symbol}: {reason} | Qty: {qty} | "
                             f"Entry: ₹{pos['entry_price']:.2f} | Exit: ₹{exit_price:.2f} | "
                             f"P&L: ₹{realized_pnl:,.0f} | Hold: {holding_days}d")
            del self.positions[symbol]
            
            # Update portfolio state for manual exit
            if self.portfolio_state:
                self.portfolio_state.close_holding(
                    symbol=symbol,
                    exit_price=exit_price,
                    exit_time=datetime.now().isoformat()
                )
        else:
            self.logger.error(f"❌ Exit failed for {symbol}: {result.get('error')}")

    def _sync_positions_with_broker(self):
        """
        Sync local positions with broker positions on startup.
        Ensures state consistency after restart.
        """
        try:
            broker_positions = self.broker.get_positions()
            self.logger.info(f"📊 Found {len(broker_positions)} positions in broker")
            
            for broker_pos in broker_positions:
                symbol = broker_pos.get('symbol', '')
                qty = broker_pos.get('quantity', 0)
                if qty <= 0:
                    continue
                    
                entry_price = broker_pos.get('entry_price', 0)
                
                # Check if we already have this position locally
                if symbol not in self.positions:
                    self.logger.info(f"📥 Syncing position from broker: {symbol} (qty={qty})")
                    self.positions[symbol] = {
                        'entry_price': entry_price,
                        'quantity': qty,
                        'order_id': None,
                        'gtt_order_id': None,
                        'entry_time': datetime.now(),
                        'allocated_capital': entry_price * qty,
                        'sector': self._get_sector(symbol),
                        'sl_price': 0,
                        'tp_price': 0,
                        'entry_filled': True,
                        'gtt_active': False,
                        'last_ltp': broker_pos.get('ltp', entry_price)
                    }
                    
                    # Only add to portfolio state if it doesn't already exist
                    # This prevents duplicate quantity additions on restart
                    if self.portfolio_state:
                        if not self.portfolio_state.is_held(symbol):
                            # New holding - add it
                            self.portfolio_state.add_holding(
                                symbol=symbol,
                                quantity=qty,
                                average_price=entry_price,
                                entry_time=datetime.now().isoformat()
                            )
                        else:
                            # Existing holding - sync quantity and avg price with broker
                            self.portfolio_state.sync_holding_with_broker(symbol, qty, entry_price)
                            self.portfolio_state.update_holding_ltp(symbol, broker_pos.get('ltp', entry_price))
                            self.logger.info(f"🔄 Synced holding {symbol}: qty={qty}, avg={entry_price:.2f}")
                else:
                    # Update existing position with broker data
                    self.positions[symbol]['quantity'] = qty
                    self.positions[symbol]['entry_price'] = entry_price
                    self.positions[symbol]['entry_filled'] = True
            
            # Save synced state
            if self.portfolio_state:
                self._sync_positions_to_portfolio_state()
                self.portfolio_state.save_state()
                
            self.logger.info(f"✅ Synced {len(self.positions)} positions with broker")
        except Exception as e:
            self.logger.error(f"Failed to sync with broker: {e}")

    def _sync_positions_to_portfolio_state(self):
        """
        Sync all active positions to portfolio state manager.
        Ensures persistence layer is up to date.
        NOTE: We do NOT call add_holding() here because that would duplicate quantities.
        Instead, we only update LTP for existing holdings. New holdings are added
        directly in _sync_positions_with_broker() and _monitor_positions().
        """
        if not self.portfolio_state:
            return
            
        for symbol, pos in self.positions.items():
            if pos.get('entry_filled', False):
                ltp = pos.get('last_ltp', pos['entry_price'])
                # Only update LTP - do NOT add holding again (that duplicates quantity)
                self.portfolio_state.update_holding_ltp(symbol, ltp)

    def get_status(self) -> Dict[str, Any]:
        return {
            'enabled': self.enabled,
            'is_running': self.is_running,
            'open_positions': len(self.positions),
            'pending_signals': len(self._pending_signals),
            'positions': {
                sym: {
                    'entry_price': p['entry_price'],
                    'quantity': p['quantity'],
                    'entry_time': p['entry_time'].isoformat(),
                    'sector': p.get('sector', 'Unknown'),
                    'allocated_capital': p.get('allocated_capital', 0),
                    'sl_price': p.get('sl_price', 0),
                    'tp_price': p.get('tp_price', 0),
                    'gtt_active': p.get('gtt_active', False),
                    'gtt_order_id': p.get('gtt_order_id'),
                    'entry_filled': p.get('entry_filled', False)
                }
                for sym, p in self.positions.items()
            },
            'daily_stats': self.daily_stats,
            'config': {
                'initial_capital': self.initial_capital,
                'risk_per_trade': self.risk_per_trade,
                'target_profit_pct': self.target_profit_pct,
                'stop_loss_pct': self.stop_loss_pct,
                'max_holding_days': self.max_holding_days,
            }
        }


def run_test():
    print("Testing Live Trading Service")
    print("=" * 50)

    service = LiveTradingService()

    if service.initialize():
        print("✅ Service initialized successfully")
        print(f"   Enabled: {service.enabled}")
        print(f"   Capital: ₹{service.initial_capital:,.0f}")
        print(f"   Risk/Trade: {service.risk_per_trade*100:.1f}%")
        print(f"   Target: {service.target_profit_pct*100:.1f}%")
        print(f"   Stop: {service.stop_loss_pct*100:.1f}%")
        print(f"   Max Hold: {service.max_holding_days}d")
        print(f"   Scan Time: {service.scan_time}")
        print(f"   Trade Time: {service.trade_time}")
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
        service.initialize()
        service.start()
        #raw_signals=service._scan_for_signals(num_days_back=100)
        #signal=service._allocate_capital_to_signals(raw_signals)
        #service._process_signals(signal)