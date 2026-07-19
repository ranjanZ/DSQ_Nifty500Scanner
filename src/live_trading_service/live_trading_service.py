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
                    self.daily_stats = {
                        'trades_today': 0,
                        'pnl_today': 0.0,
                        'date': now.date()
                    }
                    self._pending_signals = []
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
        if self.broker:
            self.broker.disconnect()
        self.logger.info("⏹️  Live trading stopped")

    def _is_market_open(self, now: datetime) -> bool:
        if now.weekday() >= 7:  # FIX: Saturday=5, Sunday=6
            return False
        market_open = datetime.strptime(self.market_open, '%H:%M').time()
        market_close = datetime.strptime(self.market_close, '%H:%M').time()
        return market_open <= now.time() <= market_close

    def _scan_for_signals(self, num_days_back: int = 10) -> List[Dict]:
        """
        Scan ALL stocks for signals. No capital allocation here.
        Returns raw signals sorted by strength.
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
                        'sector': stock.get('sector', 'Unknown'),
                    })

        signals.sort(key=lambda x: x.get('strength', 0), reverse=True)
        self.logger.info(f"Found {len(signals)} raw buy signals")
        return signals

    def _process_signals(self, signals: List[Dict]):
        if not signals:
            return

        for signal in signals:
            symbol = signal['symbol']
            if symbol in self.positions:
                continue

            #allocated_capital = signal.get('allocated_capital', self.initial_capital * self.risk_per_trade)
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

            if pnl_pct >= self.target_profit_pct:
                self._exit_position(symbol, f"Target hit (+{pnl_pct*100:.1f}%)", ltp)
                continue

            if pnl_pct <= -self.stop_loss_pct:
                self._exit_position(symbol, f"Stoploss hit ({pnl_pct*100:.1f}%)", ltp)
                continue

            holding_days = (datetime.now() - pos['entry_time']).days
            if holding_days >= self.max_holding_days:
                self._exit_position(symbol, f"Max hold days ({holding_days}d)", ltp)
                continue

            if int(time.time()) % 300 < self.price_update_interval:
                self.logger.info(f"📊 {symbol}: LTP ₹{ltp:.2f} | P&L: {pnl_pct*100:+.1f}% (₹{pnl_amount:,.0f}) | "
                                 f"Hold: {holding_days}d | Sector: {pos.get('sector', 'Unknown')}")

    def _exit_position(self, symbol: str, reason: str, exit_price: Optional[float] = None):
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
        raw_signals=service._scan_for_signals()
        signal=service._allocate_capital_to_signals(raw_signals)
        service._process_signals(signal)