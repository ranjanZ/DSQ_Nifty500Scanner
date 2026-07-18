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

# ═══════════════════════════════════════════════════════════════════════
# FIX: Add project root (parent of src/) to sys.path so 'src.*' imports work
# ═══════════════════════════════════════════════════════════════════════
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# Strategy loader (same robust logic as backtest engine)
# ═══════════════════════════════════════════════════════════════════════

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

    # Read class name from config.yaml
    config_file = os.path.join(strategy_folder, "config.yaml")
    class_name = None
    if os.path.exists(config_file):
        with open(config_file, "r") as f:
            cfg = yaml.safe_load(f) or {}
        class_name = cfg.get("class_name")

    if not class_name:
        parts = folder.replace("_strategy", "").split("_")
        class_name = "".join(p.capitalize() for p in parts) + "Strategy"

    # Pre-load strategy_base for relative imports
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
        # Initialize logger FIRST — before anything that can fail
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

        # Auto-detect config path if not provided
        if config_path is None:
            config_path = self._find_config_path()

        self.config = self._load_config(config_path)
        self.trading_config = self.config.get('live_trading_service', self.config.get('live_trading', {}))

        # Initialize services
        self.broker = None
        self.strategy = None
        self.data_service = None

        # Trading state
        self.is_running = False
        self.positions = {}          # symbol -> position dict
        self.orders = {}             # order_id -> order dict
        self._pending_signals = []   # signals stored between scan_time and trade_time
        self.daily_stats = {
            'trades_today': 0,
            'pnl_today': 0.0,
            'date': None
        }

        # Extract config values with defaults matching the config file
        self.enabled = self.trading_config.get('enabled', False)
        self.initial_capital = self.trading_config.get('initial_capital', 20000)
        self.risk_per_trade = self.trading_config.get('risk_per_trade', 0.02)
        self.target_profit_pct = self.trading_config.get('target_profit_pct', 0.05)
        self.stop_loss_pct = self.trading_config.get('stop_loss_pct', 0.02)
        self.max_holding_days = self.trading_config.get('max_holding_days', 7)

        self.market_open = self.trading_config.get('market_open', '09:15')
        self.market_close = self.trading_config.get('market_close', '15:30')

        self.scan_time = self.trading_config.get('scan_time')      # e.g. "09:30"
        self.trade_time = self.trading_config.get('trade_time')    # e.g. "09:34"

        self.price_update_interval = self.trading_config.get('price_update_interval', 5)

        self.position_weights = self.trading_config.get('position_weights', {})

        # Sector cache (same as backtest engine)
        self._sector_cache = None

    def _find_config_path(self) -> str:
        """Auto-detect config file from common locations."""
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
        """Load configuration from YAML"""
        try:
            with open(config_path, 'r') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            self.logger.error(f"Error loading config from '{config_path}': {e}")
            raise

    def _get_sector(self, symbol: str) -> str:
        """Lookup sector for a symbol. Try cache first, fallback to hardcoded map."""
        if self._sector_cache is None:
            cache_path = os.path.join(_PROJECT_ROOT, "data", "sector_cache.json")
            if os.path.exists(cache_path):
                try:
                    with open(cache_path, "r") as f:
                        self._sector_cache = json.load(f)
                except Exception:
                    self._sector_cache = {}
            else:
                self._sector_cache = {}

        if symbol in self._sector_cache:
            return self._sector_cache[symbol]

        sector_map = {
            "aubank_eq": "Financial Services",
            "hdfcbank_eq": "Financial Services",
            "icicibank_eq": "Financial Services",
            "sbin_eq": "Financial Services",
            "kotakbank_eq": "Financial Services",
            "reliance_eq": "Oil Gas & Consumable Fuels",
            "infy_eq": "Information Technology",
            "tcs_eq": "Information Technology",
            "wipro_eq": "Information Technology",
            "hcltech_eq": "Information Technology",
            "lt_eq": "Capital Goods",
            "sunpharma_eq": "Healthcare",
            "drreddy_eq": "Healthcare",
            "maruti_eq": "Automobile and Auto Components",
            "tatamotors_eq": "Automobile and Auto Components",
            "hindunilvr_eq": "Fast Moving Consumer Goods",
            "itc_eq": "Fast Moving Consumer Goods",
            "nestleind_eq": "Fast Moving Consumer Goods",
            "powergrid_eq": "Power",
            "ntpc_eq": "Power",
            "adaniports_eq": "Services",
            "dlf_eq": "Realty",
        }
        return sector_map.get(symbol, "Unknown")

    def _allocate_capital(self, symbols: List[str]) -> Dict[str, float]:
        """
        Allocate capital per symbol based on sector allocation config.
        Returns: {symbol: capital_amount}
        """
        pw = self.position_weights
        if not pw or pw.get("method") != "sector_based":
            return {sym: self.initial_capital / max(len(symbols), 1) for sym in symbols}

        sector_alloc = pw.get("sector_allocation", {})
        max_positions = pw.get("max_positions", len(symbols))
        max_per_sector = pw.get("max_per_sector", 1)

        sector_symbols: Dict[str, List[str]] = {}
        for sym in symbols:
            sector = self._get_sector(sym)
            sector_symbols.setdefault(sector, []).append(sym)

        selected_symbols = []
        for sector, syms in sector_symbols.items():
            selected = syms[:max_per_sector]
            selected_symbols.extend(selected)

        if len(selected_symbols) > max_positions:
            def sector_weight(sym):
                return sector_alloc.get(self._get_sector(sym), 0)
            selected_symbols.sort(key=sector_weight, reverse=True)
            selected_symbols = selected_symbols[:max_positions]

        total_weight = sum(
            sector_alloc.get(self._get_sector(sym), 0)
            for sym in selected_symbols
        )
        if total_weight <= 0:
            return {sym: self.initial_capital / max(len(selected_symbols), 1) for sym in selected_symbols}

        allocations = {}
        for sym in selected_symbols:
            weight = sector_alloc.get(self._get_sector(sym), 0)
            allocations[sym] = self.initial_capital * (weight / total_weight)

        return allocations

    def initialize(self):
        """Initialize all required services"""
        try:
            if not self.enabled:
                self.logger.warning("⚠️  Live trading is DISABLED in config. Set enabled: true to trade.")
                return False

            # ── Broker ──
            from src.broker_service.fyers.fyers_broker_impl import FyersBroker
            self.broker = FyersBroker()
            if not self.broker.connect():
                raise Exception("Failed to connect to broker")
            self.logger.info("✅ Broker connected")

            # ── Strategy (use same loader as backtest engine) ──
            strategy_name = self.trading_config.get('strategy_type', 'Support_Resistance')
            StrategyClass = load_strategy_class(strategy_name, _PROJECT_ROOT)
            self.strategy = StrategyClass()
            self.logger.info(f"✅ Strategy initialized: {self.strategy.name}")

            # ── Data Service ──
            from src.data_service import DataService
            self.data_service = DataService({
                'db_name': self.config.get('database', {}).get('db_name', 'spot_db_anamika'),
                'stock_list_path': 'config/default/stock_list.yaml'
            })
            self.logger.info("✅ Data service initialized")
            self.logger.info(f"💰 Initial Capital: ₹{self.initial_capital:,.0f} | Risk/Trade: {self.risk_per_trade*100:.1f}%")
            self.logger.info(f"🎯 Target: {self.target_profit_pct*100:.1f}% | Stop: {self.stop_loss_pct*100:.1f}% | Max Hold: {self.max_holding_days}d")

            return True

        except Exception as e:
            self.logger.error(f"Initialization failed: {e}")
            return False

    def start(self):
        """Start live trading loop"""
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

                # Reset daily stats at market open
                if self.daily_stats['date'] != now.date():
                    self.daily_stats = {
                        'trades_today': 0,
                        'pnl_today': 0.0,
                        'date': now.date()
                    }
                    self._pending_signals = []
                    self.logger.info(f"📅 New trading day: {now.date()}")

                # Check market hours
                if not self._is_market_open(now):
                    self.logger.info("Market closed, waiting...")
                    time.sleep(60)
                    continue

                current_minute = now.strftime("%H:%M")

                # --- PRICE MONITORING (frequent) ---
                if time.time() - last_price_check >= self.price_update_interval:
                    self._monitor_positions()
                    last_price_check = time.time()

                # --- SCAN CYCLE (at configured scan_time) ---
                if self.scan_time and current_minute == self.scan_time and last_scan_minute != current_minute:
                    self.logger.info(f"🔍 Scanning for signals at {now.strftime('%H:%M:%S')}...")
                    self._pending_signals = self._scan_for_signals()
                    last_scan_minute = current_minute

                # --- TRADE CYCLE (at configured trade_time) ---
                if self.trade_time and current_minute == self.trade_time and last_trade_minute != current_minute:
                    if self._pending_signals:
                        self.logger.info(f"📤 Executing trades at {now.strftime('%H:%M:%S')}...")
                        self._process_signals(self._pending_signals)
                        self._pending_signals = []
                    else:
                        self.logger.info("No pending signals to execute")
                    last_trade_minute = current_minute

                # Sleep briefly — just for price monitoring cadence
                time.sleep(max(self.price_update_interval, 1))

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
        if now.weekday() >= 7:
            return False
        market_open = datetime.strptime(self.market_open, '%H:%M').time()
        market_close = datetime.strptime(self.market_close, '%H:%M').time()
        return market_open <= now.time() <= market_close

    def _scan_for_signals(self) -> List[Dict]:
        """Scan stocks for trading signals"""
        signals = []
        stocks = self.data_service.get_stock_list()
        if not stocks:
            self.logger.warning("No stocks in watchlist")
            return signals

        capital_alloc = self._allocate_capital([s['symbol'] for s in stocks])
        active_symbols = list(capital_alloc.keys())
        self.logger.info(f"Scanning {len(active_symbols)} symbols (sector-based allocation)")

        for symbol in active_symbols:
            if symbol in self.positions:
                continue

            end_date = datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.now() - timedelta(days=100)).strftime('%Y-%m-%d')
            df = self.data_service.get_historical_data(symbol, start_date, end_date)

            if df is None or df.empty:
                continue

            signal_df = self.strategy.generate_signals(df)
            if signal_df is not None and not signal_df.empty:
                latest = signal_df.iloc[-1]
                if latest.get('signal') == 1:
                    signals.append({
                        'symbol': symbol,
                        'signal': 1,
                        'price': latest.get('close', 0),
                        'strength': latest.get('signal_strength', 0),
                        'timestamp': latest.get('time', datetime.now().isoformat()),
                        'sector': self._get_sector(symbol),
                        'allocated_capital': capital_alloc.get(symbol, self.initial_capital / max(len(active_symbols), 1))
                    })

        signals.sort(key=lambda x: x.get('strength', 0), reverse=True)
        self.logger.info(f"Found {len(signals)} buy signals")
        return signals

    def _process_signals(self, signals: List[Dict]):
        """Process buy signals with sector-aware allocation"""
        if not signals:
            return

        for signal in signals:
            symbol = signal['symbol']
            if symbol in self.positions:
                continue

            allocated_capital = signal.get('allocated_capital', self.initial_capital * self.risk_per_trade)
            price = signal['price']

            if price <= 0:
                self.logger.warning(f"Invalid price for {symbol}: {price}")
                continue

            # Risk-based sizing
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
                    'entry_time': datetime.now(),
                    'allocated_capital': allocated_capital,
                    'sector': signal.get('sector', 'Unknown'),
                    'highest_price': price
                }
                self.daily_stats['trades_today'] += 1
                self.logger.info(f"✅ Bought {qty} shares of {symbol} at ₹{price:.2f} "
                                 f"(sector: {signal.get('sector', 'Unknown')}, alloc: ₹{allocated_capital:,.0f})")
            else:
                self.logger.error(f"❌ Order failed for {symbol}: {result.get('error')}")

    def _monitor_positions(self):
        """Monitor and manage existing positions"""
        if not self.positions:
            return

        for symbol, pos in list(self.positions.items()):
            ltp = self.broker.get_ltp(symbol)
            if ltp <= 0:
                continue

            if ltp > pos.get('highest_price', pos['entry_price']):
                pos['highest_price'] = ltp

            pnl_pct = (ltp - pos['entry_price']) / pos['entry_price']
            pnl_amount = (ltp - pos['entry_price']) * pos['quantity']

            # 1. Target hit
            if pnl_pct >= self.target_profit_pct:
                self._exit_position(symbol, f"Target hit (+{pnl_pct*100:.1f}%)", ltp)
                continue

            # 2. Stoploss hit
            if pnl_pct <= -self.stop_loss_pct:
                self._exit_position(symbol, f"Stoploss hit ({pnl_pct*100:.1f}%)", ltp)
                continue

            # 3. Max holding days exceeded
            holding_days = (datetime.now() - pos['entry_time']).days
            if holding_days >= self.max_holding_days:
                self._exit_position(symbol, f"Max hold days ({holding_days}d)", ltp)
                continue

            # Log position status periodically (every ~5 min)
            if int(time.time()) % 300 < self.price_update_interval:
                self.logger.info(f"📊 {symbol}: LTP ₹{ltp:.2f} | P&L: {pnl_pct*100:+.1f}% (₹{pnl_amount:,.0f}) | "
                                 f"Hold: {holding_days}d | Sector: {pos.get('sector', 'Unknown')}")

    def _exit_position(self, symbol: str, reason: str, exit_price: Optional[float] = None):
        """Exit a position"""
        pos = self.positions.get(symbol)
        if not pos:
            return

        qty = pos['quantity']
        if exit_price is None or exit_price <= 0:
            exit_price = self.broker.get_ltp(symbol)

        if exit_price <= 0:
            self.logger.error(f"Cannot exit {symbol}: invalid LTP")
            return

        realized_pnl = (exit_price - pos['entry_price']) * qty
        self.daily_stats['pnl_today'] += realized_pnl

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
        else:
            self.logger.error(f"❌ Exit failed for {symbol}: {result.get('error')}")

    def get_status(self) -> Dict[str, Any]:
        """Get current trading status"""
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
                    'allocated_capital': p.get('allocated_capital', 0)
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
    """Test live trading service initialization"""
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
        if service.initialize():
            service.start()