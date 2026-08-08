"""
Backtest Engine
===============
Strategy-agnostic backtesting framework.
Reads config from config/default/backtest.yaml + config/backtest.user.yaml
Saves equity curves and metrics to data/outputs/backtesting/

Run directly:
    python src/backtesting_service/backtest_engine.py
    python src/backtesting_service/backtest_engine.py --strategy volume_support_resistance
    python src/backtesting_service/backtest_engine.py --symbols aubank_eq reliance_eq
"""

import os
import sys
import json
import yaml
import argparse
import importlib.util
import types
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from tqdm import tqdm
from joblib import Parallel, delayed
import multiprocessing

plt.rcParams['axes.unicode_minus'] = False


# ═══════════════════════════════════════════════════════════════════════
# Data structures
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class Trade:
    """Single trade record."""
    symbol: str
    entry_date: datetime
    entry_price: float
    exit_date: Optional[datetime] = None
    exit_price: Optional[float] = None
    qty: int = 0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""  # "target", "stoploss", "max_hold", "end_of_data"
    holding_days: int = 0


@dataclass
class SectorMetrics:
    """Metrics per sector."""
    sector: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    win_rate_pct: float = 0.0
    avg_pnl_per_trade: float = 0.0
    avg_holding_days: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BacktestMetrics:
    """Computed backtest performance metrics."""
    total_return_pct: float = 0.0
    annualized_return_pct: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    max_drawdown_duration_days: int = 0
    win_rate_pct: float = 0.0
    profit_factor: float = 0.0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    avg_holding_days: float = 0.0
    initial_capital: float = 0.0
    final_equity: float = 0.0
    benchmark_return_pct: float = 0.0
    sector_metrics: List[SectorMetrics] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d

    def print_summary(self):
        print("\n" + "=" * 60)
        print("📊 BACKTEST RESULTS")
        print("=" * 60)
        print(f"   Initial Capital:     ₹{self.initial_capital:,.0f}")
        print(f"   Final Equity:        ₹{self.final_equity:,.0f}")
        print(f"   Total Return:        {self.total_return_pct:.2f}%")
        print(f"   Annualized Return:   {self.annualized_return_pct:.2f}%")
        print(f"   Sharpe Ratio:        {self.sharpe_ratio:.3f}")
        print(f"   Sortino Ratio:       {self.sortino_ratio:.3f}")
        print(f"   Max Drawdown:        {self.max_drawdown_pct:.2f}%")
        print(f"   Win Rate:            {self.win_rate_pct:.2f}%")
        print(f"   Profit Factor:       {self.profit_factor:.3f}")
        print(f"   Avg Win:             {self.avg_win_pct:.2f}%")
        print(f"   Avg Loss:            {self.avg_loss_pct:.2f}%")
        print(f"   Total Trades:        {self.total_trades}")
        print(f"   Avg Holding Days:    {self.avg_holding_days:.1f}")
        print("=" * 60)

        if self.sector_metrics:
            print("\n📂 SECTOR-WISE BREAKDOWN")
            print("-" * 60)
            print(f"{'Sector':<35} {'Trades':>7} {'Win%':>7} {'P&L (₹)':>12} {'Avg P&L':>10}")
            print("-" * 60)
            for sm in sorted(self.sector_metrics, key=lambda x: x.total_pnl, reverse=True):
                print(f"{sm.sector:<35} {sm.total_trades:>7} {sm.win_rate_pct:>7.1f} {sm.total_pnl:>12,.0f} {sm.avg_pnl_per_trade:>10,.0f}")
            print("-" * 60)
            print("=" * 60)


# ═══════════════════════════════════════════════════════════════════════
# Module loaders (bypass parent __init__.py)
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


def load_yaml(path: str) -> Dict:
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


def deep_merge(base: Dict, override: Dict) -> Dict:
    result = base.copy()
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result


# ═══════════════════════════════════════════════════════════════════════
# Strategy loader
# ═══════════════════════════════════════════════════════════════════════

def load_strategy_class(strategy_name: str, project_root: str):
    """Load a strategy class directly from its file."""
    strategies_dir = os.path.join(project_root, "src", "strategy_service", "strategies")

    # Map common aliases
    aliases = {
        "volume_support_resistance": "volume_support_resistance_strategy",
        "support_resistance": "volume_support_resistance_strategy",
        "vss": "volume_support_resistance_strategy",
        "Support_Resistance": "volume_support_resistance_strategy",
    }
    folder = aliases.get(strategy_name, strategy_name)

    strategy_folder = os.path.join(strategies_dir, folder)
    if not os.path.isdir(strategy_folder):
        # Try to find matching folder
        for f in os.listdir(strategies_dir):
            if os.path.isdir(os.path.join(strategies_dir, f)):
                # Match by removing underscores and case-insensitive compare
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
        cfg = load_yaml(config_file)
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


# ═══════════════════════════════════════════════════════════════════════
# Backtest Engine
# ═══════════════════════════════════════════════════════════════════════

class BacktestEngine:
    """
    Strategy-agnostic backtest engine.

    Usage:
        engine = BacktestEngine(strategy, config)
        metrics = engine.run(symbols=["aubank_eq", ...])
    """

    COLOR_BG = "#0d1117"
    COLOR_GRID = "#30363d"
    COLOR_TEXT = "#c9d1d9"
    COLOR_EQUITY = "#58a6ff"
    COLOR_BENCHMARK = "#8b949e"
    COLOR_DD = "#f85149"

    def __init__(
        self,
        strategy,
        config: Dict[str, Any],
        project_root: str = ".",
        db_getter=None,
    ):
        self.strategy = strategy
        self.config = config
        self.project_root = project_root
        self.db_getter = db_getter

        bt_cfg = config.get("backtest", {})
        self.initial_capital = bt_cfg.get("initial_capital", 10000)
        self.target_profit_pct = bt_cfg.get("target_profit_pct", 0.08)
        self.stop_loss_pct = bt_cfg.get("stop_loss_pct", 0.04)
        self.max_holding_days = bt_cfg.get("max_holding_days", 7)
        self.lookback_days = bt_cfg.get("lookback_days", 5)
        self.position_weights = bt_cfg.get("position_weights", {})
        self.watchlist = bt_cfg.get("watchlist", ["nifty_top_500"])
        # Max capital that can be allocated per day (for new positions)
        self.max_capital_allocation_per_day = bt_cfg.get("max_capital_allocation_per_day", self.initial_capital)

        svc_cfg = config.get("backtest_service", {})
        self.save_plots = svc_cfg.get("save_plots", True)
        self.save_metrics = svc_cfg.get("save_metrics", True)
        self.verbose = svc_cfg.get("verbose", True)

        # Changed output directory to data/outputs/backtesting/
        self.output_dir = os.path.join(project_root, "data", "outputs", "backtesting")
        os.makedirs(self.output_dir, exist_ok=True)

        self.trades: List[Trade] = []
        self.equity_curve: List[Tuple[datetime, float]] = []

    # ── Data fetching ─────────────────────────────────────────────────

    def _get_db_getter(self):
        if self.db_getter is not None:
            return self.db_getter
        try:
            from src.data_service.db_utils import get_table_content
            return get_table_content
        except ImportError:
            try:
                from src.data_pipeline.db_utils import get_table_content
                return get_table_content
            except ImportError:
                return None

    def fetch_data(self, symbol: str, start_date: datetime, end_date: datetime) -> Optional[pd.DataFrame]:
        getter = self._get_db_getter()
        if getter is None:
            if self.verbose:
                print(f"   ⚠️  No DB getter available for {symbol}")
            return None

        fetch_start = start_date - timedelta(days=self.lookback_days + 30)
        try:
            df = getter(
                db_name="spot_db_anamika",
                table_name=symbol,
                start_date=fetch_start,
                end_date=end_date,
            )
            if df is None or len(df) == 0:
                return None

            if "time" in df.columns and "date" not in df.columns:
                df = df.copy()
                df["date"] = pd.to_datetime(df["time"])
            elif "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])
            else:
                df = df.copy()
                df["date"] = pd.to_datetime(df.index)

            df = df[df["date"] >= start_date].reset_index(drop=True)
            print(f"🎉  Successfully fetched {symbol} len:{len(df)}")

            return df
        except Exception as e:
            if self.verbose:
                print(f"   ⚠️  Failed to fetch {symbol}: {e}")
            return None

    # ── Signal generation ─────────────────────────────────────────────

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        if len(df) < self.lookback_days:
            return df
        signals = self.strategy.generate_signals(df, num_back_signals=len(df))
        return signals

    # ── Trade simulation ──────────────────────────────────────────────

    def simulate_trades_daily(self, all_data: Dict[str, pd.DataFrame], symbols: List[str], capital_alloc: Dict[str, float]) -> List[Trade]:
        """
        Simulate trading day-by-day like live trading:
        1. Each day, scan all symbols for signals
        2. Allocate capital to new signals (respecting portfolio limits)
        3. Check existing positions for exit conditions
        4. Free capital when positions close
        5. Repeat for each trading day
        
        This mimics the live trading workflow where:
        - Max positions are limited (e.g., max_pos=7)
        - Max positions per sector (e.g., max_per_sector=1)
        - Capital is freed when positions close
        - New signals compete for available capital
        """
        trades = []
        
        # Track active positions: {symbol: {entry_date, entry_price, qty, target, stop, max_exit_date}}
        active_positions: Dict[str, Dict] = {}
        
        # Track used capital and available slots
        max_positions = self.position_weights.get('max_positions', len(symbols))
        max_per_sector = self.position_weights.get('max_per_sector', 1)
        
        # Get all unique dates across all symbols
        all_dates = set()
        for sym, df in all_data.items():
            if 'date' in df.columns:
                all_dates.update(df['date'].dt.date)
        sorted_dates = sorted(all_dates)
        
        if not sorted_dates:
            return trades
        
        # Track sector counts for current positions
        def get_sector_count(sector: str) -> int:
            return sum(1 for pos_sym, pos_info in active_positions.items() 
                      if self._get_sector(pos_sym) == sector)
        
        def can_open_position(symbol: str) -> bool:
            """Check if we can open a new position respecting limits."""
            if len(active_positions) >= max_positions:
                return False
            sector = self._get_sector(symbol)
            if get_sector_count(sector) >= max_per_sector:
                return False
            return True
        
        # Process each day
        for current_date in sorted_dates:
            current_dt = pd.Timestamp(current_date)
            
            # Step 1: Check existing positions for exits
            symbols_to_remove = []
            for symbol, pos in list(active_positions.items()):
                if symbol not in all_data:
                    continue
                df = all_data[symbol]
                day_data = df[df['date'].dt.date == current_date]
                
                if day_data.empty:
                    continue
                
                high = day_data.iloc[0]['high']
                low = day_data.iloc[0]['low']
                close = day_data.iloc[0]['close']
                
                exit_price = None
                exit_reason = None
                
                # Check stop loss first (priority)
                if low <= pos['stop']:
                    exit_price = pos['stop']
                    exit_reason = 'stoploss'
                # Check target
                elif high >= pos['target']:
                    exit_price = pos['target']
                    exit_reason = 'target'
                # Check max holding period
                elif current_date > pos['max_exit_date']:
                    exit_price = close
                    exit_reason = 'max_hold'
                
                if exit_price and exit_reason:
                    # Close position
                    entry_price = pos['entry_price']
                    qty = pos['qty']
                    pnl = (exit_price - entry_price) * qty
                    pnl_pct = (exit_price / entry_price - 1) * 100 if entry_price > 0 else 0
                    holding_days = (current_date - pos['entry_date'].date()).days
                    
                    trades.append(Trade(
                        symbol=symbol,
                        entry_date=pos['entry_date'],
                        entry_price=entry_price,
                        exit_date=current_dt.to_pydatetime(),
                        exit_price=exit_price,
                        qty=qty,
                        pnl=pnl,
                        pnl_pct=pnl_pct,
                        exit_reason=exit_reason,
                        holding_days=holding_days,
                    ))
                    symbols_to_remove.append(symbol)
            
            # Remove closed positions
            for symbol in symbols_to_remove:
                del active_positions[symbol]
            
            # Step 2: Scan for new signals (only if we have capacity)
            if len(active_positions) >= max_positions:
                continue
            
            for symbol in symbols:
                if symbol not in active_positions and symbol in capital_alloc and symbol in all_data:
                    if not can_open_position(symbol):
                        continue
                    
                    df = all_data[symbol]
                    # Need lookback data for signal generation
                    lookback_start = current_dt - timedelta(days=self.lookback_days)
                    hist_data = df[(df['date'] >= lookback_start) & (df['date'] <= current_dt)]
                    
                    if len(hist_data) < self.lookback_days:
                        continue
                    
                    # Generate signals up to previous day (to avoid lookahead bias)
                    prev_day = current_dt - pd.Timedelta(days=1)
                    hist_data = hist_data[hist_data['date'] <= prev_day]
                    
                    if len(hist_data) < self.lookback_days:
                        continue
                    
                    signals_df = self.generate_signals(hist_data)
                    
                    if signals_df is None or signals_df.empty:
                        continue
                    
                    # Check if latest signal is a buy
                    latest_signal = signals_df.iloc[-1]
                    if latest_signal.get('signal') != 1:
                        continue
                    
                    # Open position next day at open price
                    entry_day_data = df[df['date'].dt.date == current_date]
                    if entry_day_data.empty:
                        continue
                    
                    entry_price = entry_day_data.iloc[0]['open']
                    allocated_capital = capital_alloc.get(symbol, 0)
                    
                    if entry_price <= 0 or allocated_capital <= 0:
                        continue
                    
                    qty = int(allocated_capital / entry_price)
                    if qty <= 0:
                        continue
                    
                    target_price = entry_price * (1 + self.target_profit_pct)
                    stop_price = entry_price * (1 - self.stop_loss_pct)
                    max_exit_date = current_date + timedelta(days=self.max_holding_days)
                    
                    active_positions[symbol] = {
                        'entry_date': current_dt.to_pydatetime(),
                        'entry_price': entry_price,
                        'qty': qty,
                        'target': target_price,
                        'stop': stop_price,
                        'max_exit_date': max_exit_date,
                        'allocated_capital': allocated_capital,
                    }
        
        return trades

    def simulate_trades_daily_with_progress(
        self, 
        all_data: Dict[str, pd.DataFrame], 
        symbols: List[str], 
        capital_alloc: Dict[str, float],
        sorted_dates: List
    ) -> List[Trade]:
        """
        Simulate trading day-by-day with progress bar.
        
        Mimics live trading workflow:
        1. Each day, scan all stocks based on strategy using lookback data
        2. Allocate capital to signals respecting max_capital_allocation_per_day
        3. Execute trades at closing price on signal day
        4. Check existing positions for exit (TP/SL/max_hold)
        5. Close positions and free capital
        
        Capital allocation is done per-day based on available signals,
        not pre-allocated upfront. Uses industry/sector-based allocation logic.
        """
        trades = []
        
        # Track active positions: {symbol: {entry_date, entry_price, qty, target, stop, max_exit_date}}
        active_positions: Dict[str, Dict] = {}
        
        # Track used capital and available slots
        max_positions = self.position_weights.get('max_positions', len(symbols))
        max_per_sector = self.position_weights.get('max_per_sector', 1)
        
        if not sorted_dates:
            return trades
        
        # Track sector counts for current positions
        def get_sector_count(sector: str) -> int:
            return sum(1 for pos_sym, pos_info in active_positions.items() 
                      if self._get_sector(pos_sym) == sector)
        
        def can_open_position(symbol: str) -> bool:
            """Check if we can open a new position respecting limits."""
            if len(active_positions) >= max_positions:
                return False
            sector = self._get_sector(symbol)
            if get_sector_count(sector) >= max_per_sector:
                return False
            return True
        
        # Process each day with progress bar
        for current_date in tqdm(sorted_dates, desc="Simulating days", disable=not self.verbose):
            current_dt = pd.Timestamp(current_date)
            
            # Step 1: Check existing positions for exits (using close price)
            symbols_to_remove = []
            for symbol, pos in list(active_positions.items()):
                if symbol not in all_data:
                    continue
                df = all_data[symbol]
                day_data = df[df['date'].dt.date == current_date]
                
                if day_data.empty:
                    continue
                
                high = day_data.iloc[0]['high']
                low = day_data.iloc[0]['low']
                close = day_data.iloc[0]['close']
                
                exit_price = None
                exit_reason = None
                
                # Check stop loss first (priority)
                if low <= pos['stop']:
                    exit_price = pos['stop']
                    exit_reason = 'stoploss'
                # Check target
                elif high >= pos['target']:
                    exit_price = pos['target']
                    exit_reason = 'target'
                # Check max holding period
                elif current_date > pos['max_exit_date']:
                    exit_price = close
                    exit_reason = 'max_hold'
                
                if exit_price and exit_reason:
                    # Close position
                    entry_price = pos['entry_price']
                    qty = pos['qty']
                    pnl = (exit_price - entry_price) * qty
                    pnl_pct = (exit_price / entry_price - 1) * 100 if entry_price > 0 else 0
                    holding_days = (current_date - pos['entry_date'].date()).days
                    
                    trades.append(Trade(
                        symbol=symbol,
                        entry_date=pos['entry_date'],
                        entry_price=entry_price,
                        exit_date=current_dt.to_pydatetime(),
                        exit_price=exit_price,
                        qty=qty,
                        pnl=pnl,
                        pnl_pct=pnl_pct,
                        exit_reason=exit_reason,
                        holding_days=holding_days,
                    ))
                    symbols_to_remove.append(symbol)
            
            # Remove closed positions
            for symbol in symbols_to_remove:
                del active_positions[symbol]
            
            # Step 2: Scan ALL symbols for signals on this day (mimics live trading)
            # Only scan if we have capacity for new positions
            if len(active_positions) >= max_positions:
                continue
            
            # Collect all signals for the day first (like live trading scan)
            daily_signals = []
            for symbol in symbols:
                if symbol in active_positions:
                    continue  # Already have position
                if symbol not in all_data:
                    continue
                
                df = all_data[symbol]
                # Need lookback data for signal generation
                lookback_start = current_dt - timedelta(days=self.lookback_days)
                hist_data = df[(df['date'] >= lookback_start) & (df['date'] <= current_dt)]
                
                if len(hist_data) < self.lookback_days:
                    continue
                
                # Generate signals up to previous day (to avoid lookahead bias)
                prev_day = current_dt - pd.Timedelta(days=1)
                hist_data = hist_data[hist_data['date'] <= prev_day]
                
                if len(hist_data) < self.lookback_days:
                    continue
                
                signals_df = self.generate_signals(hist_data)
                
                if signals_df is None or signals_df.empty:
                    continue
                
                # Check if latest signal is a buy
                latest_signal = signals_df.iloc[-1]
                if latest_signal.get('signal') != 1:
                    continue
                
                # Store signal with strength for ranking
                daily_signals.append({
                    'symbol': symbol,
                    'strength': latest_signal.get('signal_strength', 0),
                    'sector': self._get_sector(symbol),
                })
            
            # Step 3: Allocate capital to signals based on sector weights (like live trading)
            allocated_signals = self._allocate_capital_to_daily_signals(daily_signals, capital_alloc)
            
            # Step 4: Execute trades at closing price for allocated signals
            for sig in allocated_signals:
                symbol = sig['symbol']
                if not can_open_position(symbol):
                    continue
                
                df = all_data[symbol]
                entry_day_data = df[df['date'].dt.date == current_date]
                if entry_day_data.empty:
                    continue
                
                # Execute at closing price (as mentioned in requirements)
                entry_price = entry_day_data.iloc[0]['close']
                allocated_capital = sig.get('allocated_capital', 0)
                
                if entry_price <= 0 or allocated_capital <= 0:
                    continue
                
                qty = int(allocated_capital / entry_price)
                if qty <= 0:
                    continue
                
                target_price = entry_price * (1 + self.target_profit_pct)
                stop_price = entry_price * (1 - self.stop_loss_pct)
                max_exit_date = current_date + timedelta(days=self.max_holding_days)
                
                active_positions[symbol] = {
                    'entry_date': current_dt.to_pydatetime(),
                    'entry_price': entry_price,
                    'qty': qty,
                    'target': target_price,
                    'stop': stop_price,
                    'max_exit_date': max_exit_date,
                    'allocated_capital': allocated_capital,
                }
        
        return trades
    
    def _allocate_capital_to_daily_signals(self, daily_signals: List[Dict], capital_alloc: Dict[str, float]) -> List[Dict]:
        """
        Allocate capital to daily signals based on sector weights.
        Mimics live trading capital allocation logic.
        
        Args:
            daily_signals: List of {symbol, strength, sector} dicts
            capital_alloc: Pre-computed capital allocation per symbol
            
        Returns:
            List of signals with 'allocated_capital' added
        """
        if not daily_signals:
            return []
        
        pw = self.position_weights
        if not pw or pw.get("method") != "sector_based":
            # Equal allocation fallback
            per_signal = self.max_capital_allocation_per_day / max(len(daily_signals), 1)
            for s in daily_signals:
                s['allocated_capital'] = per_signal
            return daily_signals
        
        sector_alloc = pw.get("sector_allocation", {})
        max_positions = pw.get("max_positions", len(daily_signals))
        max_per_sector = pw.get("max_per_sector", 1)
        
        # Group signals by sector
        sector_signals: Dict[str, List[Dict]] = {}
        for sig in daily_signals:
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
        
        # Allocate capital proportional to sector weight, capped by max_capital_allocation_per_day
        total_weight = sum(sector_alloc.get(s.get('sector', 'Unknown'), 0) for s in selected)
        if total_weight <= 0:
            per_signal = self.max_capital_allocation_per_day / max(len(selected), 1)
            for s in selected:
                s['allocated_capital'] = per_signal
        else:
            for s in selected:
                weight = sector_alloc.get(s.get('sector', 'Unknown'), 0)
                s['allocated_capital'] = self.max_capital_allocation_per_day * (weight / total_weight)
        
        return selected

    # ── Portfolio & equity curve ──────────────────────────────────────

    def build_equity_curve(self, all_trades: List[Trade], daily_prices: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        if not all_trades:
            return pd.DataFrame()

        all_dates = set()
        for sym, df in daily_prices.items():
            if "date" in df.columns:
                all_dates.update(df["date"].dt.date)
        sorted_dates = sorted(all_dates)

        if not sorted_dates:
            return pd.DataFrame()

        equity = []
        running_pnl = 0.0
        cash = self.initial_capital

        for d in sorted_dates:
            date_dt = datetime.combine(d, datetime.min.time())
            day_pnl = 0.0
            for t in all_trades:
                if t.exit_date and t.exit_date.date() == d:
                    day_pnl += t.pnl
            running_pnl += day_pnl
            equity.append({"date": date_dt, "equity": cash + running_pnl})

        return pd.DataFrame(equity)

    # ── Sector-wise metrics computation ───────────────────────────────

    def compute_sector_metrics(self, trades: List[Trade]) -> List[SectorMetrics]:
        """Compute per-sector performance metrics from trades."""
        if not trades:
            return []

        sector_trades: Dict[str, List[Trade]] = {}
        for t in trades:
            sector = self._get_sector(t.symbol)
            sector_trades.setdefault(sector, []).append(t)

        sector_metrics = []
        for sector, trds in sector_trades.items():
            wins = [t for t in trds if t.pnl > 0]
            losses = [t for t in trds if t.pnl <= 0]
            total_pnl = sum(t.pnl for t in trds)

            sm = SectorMetrics(
                sector=sector,
                total_trades=len(trds),
                winning_trades=len(wins),
                losing_trades=len(losses),
                total_pnl=total_pnl,
                win_rate_pct=(len(wins) / len(trds) * 100) if trds else 0,
                avg_pnl_per_trade=(total_pnl / len(trds)) if trds else 0,
                avg_holding_days=np.mean([t.holding_days for t in trds]) if trds else 0,
            )
            sector_metrics.append(sm)

        return sorted(sector_metrics, key=lambda x: x.total_pnl, reverse=True)

    # ── Metrics computation ───────────────────────────────────────────

    @staticmethod
    def compute_metrics(trades: List[Trade], equity_df: pd.DataFrame, initial_capital: float, sector_metrics: List[SectorMetrics] = None) -> BacktestMetrics:
        m = BacktestMetrics()
        m.initial_capital = initial_capital
        m.sector_metrics = sector_metrics or []

        if not trades or equity_df.empty:
            return m

        m.total_trades = len(trades)
        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]
        m.winning_trades = len(wins)
        m.losing_trades = len(losses)
        m.win_rate_pct = (len(wins) / len(trades) * 100) if trades else 0

        total_wins = sum(t.pnl for t in wins)
        total_losses = abs(sum(t.pnl for t in losses))
        m.profit_factor = (total_wins / total_losses) if total_losses > 0 else float("inf")
        m.avg_win_pct = np.mean([t.pnl_pct for t in wins]) if wins else 0
        m.avg_loss_pct = np.mean([t.pnl_pct for t in losses]) if losses else 0
        m.avg_holding_days = np.mean([t.holding_days for t in trades]) if trades else 0

        equity = equity_df["equity"].values
        m.final_equity = equity[-1]
        m.total_return_pct = (m.final_equity / initial_capital - 1) * 100

        daily_returns = np.diff(equity) / equity[:-1]
        if len(daily_returns) > 0 and daily_returns.std() > 0:
            m.sharpe_ratio = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252)
            downside = daily_returns[daily_returns < 0]
            if len(downside) > 0 and downside.std() > 0:
                m.sortino_ratio = (daily_returns.mean() / downside.std()) * np.sqrt(252)

        peak = np.maximum.accumulate(equity)
        drawdown = (equity - peak) / peak
        m.max_drawdown_pct = drawdown.min() * 100

        days = (equity_df["date"].iloc[-1] - equity_df["date"].iloc[0]).days
        if days > 0:
            m.annualized_return_pct = ((m.final_equity / initial_capital) ** (365 / days) - 1) * 100

        return m

    # ── Plotting ──────────────────────────────────────────────────────

    def plot_equity_curve(self, equity_df: pd.DataFrame, metrics: BacktestMetrics, filename: str):
        if equity_df.empty:
            return

        fig, (ax_eq, ax_dd) = plt.subplots(
            2, 1, figsize=(14, 9), gridspec_kw={"height_ratios": [3, 1]}
        )
        fig.patch.set_facecolor(self.COLOR_BG)

        dates = mdates.date2num(equity_df["date"])
        equity = equity_df["equity"].values
        peak = np.maximum.accumulate(equity)
        drawdown = (equity - peak) / peak * 100

        ax_eq.plot(dates, equity, color=self.COLOR_EQUITY, linewidth=1.5, label="Portfolio Equity")
        ax_eq.axhline(self.initial_capital, color=self.COLOR_GRID, linestyle="--", alpha=0.5)
        ax_eq.set_ylabel("Equity (₹)", color=self.COLOR_TEXT)
        ax_eq.set_title(
            f"Backtest: {self.strategy.name}  |  Return: {metrics.total_return_pct:.1f}%  |  "
            f"Sharpe: {metrics.sharpe_ratio:.2f}  |  Max DD: {metrics.max_drawdown_pct:.1f}%",
            color=self.COLOR_TEXT, fontsize=11
        )
        ax_eq.legend(loc="upper left", fontsize=9, facecolor=self.COLOR_BG,
                     edgecolor=self.COLOR_GRID, labelcolor=self.COLOR_TEXT)
        ax_eq.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
        plt.setp(ax_eq.xaxis.get_majorticklabels(), rotation=30, ha="right")

        ax_dd.fill_between(dates, drawdown, 0, color=self.COLOR_DD, alpha=0.4)
        ax_dd.plot(dates, drawdown, color=self.COLOR_DD, linewidth=1)
        ax_dd.set_ylabel("Drawdown %", color=self.COLOR_TEXT)
        ax_dd.set_xlabel("Date", color=self.COLOR_TEXT)

        for ax in (ax_eq, ax_dd):
            ax.set_facecolor(self.COLOR_BG)
            for spine in ax.spines.values():
                spine.set_color(self.COLOR_GRID)
            ax.tick_params(colors=self.COLOR_TEXT, labelsize=8)
            ax.grid(True, alpha=0.2, color=self.COLOR_GRID, linestyle="--")

        plt.tight_layout()
        filepath = os.path.join(self.output_dir, filename)
        plt.savefig(filepath, dpi=150, facecolor=self.COLOR_BG, bbox_inches="tight")
        plt.close(fig)
        if self.verbose:
            print(f"   💾 Equity curve: {filepath}")

    def plot_sector_breakdown(self, sector_metrics: List[SectorMetrics], filename: str):
        """Plot sector-wise P&L breakdown as a horizontal bar chart."""
        if not sector_metrics:
            return

        fig, ax = plt.subplots(figsize=(10, max(4, len(sector_metrics) * 0.6)))
        fig.patch.set_facecolor(self.COLOR_BG)
        ax.set_facecolor(self.COLOR_BG)

        sectors = [sm.sector for sm in sector_metrics]
        pnls = [sm.total_pnl for sm in sector_metrics]
        colors = ["#238636" if p >= 0 else "#f85149" for p in pnls]

        y_pos = np.arange(len(sectors))
        ax.barh(y_pos, pnls, color=colors, edgecolor=self.COLOR_GRID, height=0.6)
        ax.set_yticks(y_pos)
        ax.set_yticklabels(sectors, color=self.COLOR_TEXT, fontsize=9)
        ax.set_xlabel("Total P&L (₹)", color=self.COLOR_TEXT)
        ax.set_title(f"Sector-wise P&L Breakdown — {self.strategy.name}", color=self.COLOR_TEXT, fontsize=12)

        for spine in ax.spines.values():
            spine.set_color(self.COLOR_GRID)
        ax.tick_params(colors=self.COLOR_TEXT, labelsize=8)
        ax.grid(True, alpha=0.2, color=self.COLOR_GRID, linestyle="--", axis="x")
        ax.axvline(0, color=self.COLOR_TEXT, linewidth=0.5)

        # Add value labels
        for i, (p, sm) in enumerate(zip(pnls, sector_metrics)):
            label = f"₹{p:,.0f}  ({sm.total_trades} trades, {sm.win_rate_pct:.0f}% WR)"
            ax.text(p, i, label, va="center", ha="left" if p >= 0 else "right",
                    color=self.COLOR_TEXT, fontsize=8, fontweight="bold")

        plt.tight_layout()
        filepath = os.path.join(self.output_dir, filename)
        plt.savefig(filepath, dpi=150, facecolor=self.COLOR_BG, bbox_inches="tight")
        plt.close(fig)
        if self.verbose:
            print(f"   💾 Sector breakdown: {filepath}")

    # ── Main run ──────────────────────────────────────────────────────

    def _load_stock_list(self) -> Dict[str, str]:
        """Load symbol to sector mapping from config/default/stock_list.yaml"""
        stock_list_path = os.path.join(self.project_root, "config", "default", "stock_list.yaml")
        symbol_to_sector = {}
        
        if not os.path.exists(stock_list_path):
            return {}
        
        try:
            with open(stock_list_path, "r") as f:
                data = yaml.safe_load(f) or {}
            
            watchlists = data.get("watchlists", {})
            for watchlist_name, stocks in watchlists.items():
                if not isinstance(stocks, list):
                    continue
                for stock in stocks:
                    if not isinstance(stock, dict):
                        continue
                    # Extract symbol from fyers_symbol (e.g., "NSE:AUBANK-EQ" -> "aubank_eq")
                    fyers_sym = stock.get("fyers_symbol", "")
                    sector = stock.get("sector", "Unknown")
                    
                    if fyers_sym:
                        # Convert NSE:AUBANK-EQ to aubank_eq
                        symbol = fyers_sym.replace("NSE:", "").replace("-EQ", "").lower() + "_eq"
                        symbol_to_sector[symbol] = sector
        except Exception as e:
            if self.verbose:
                print(f"   ⚠️  Failed to load stock_list.yaml: {e}")
        
        return symbol_to_sector

    def _get_sector(self, symbol: str) -> str:
        """Lookup sector for a symbol from stock_list.yaml, fallback to cache or unknown."""
        # Primary: load from config/default/stock_list.yaml
        symbol_to_sector = self._load_stock_list()
        if symbol in symbol_to_sector:
            return symbol_to_sector[symbol]
        
        # Secondary: Try to load from cache file (legacy support)
        cache_path = os.path.join(self.project_root, "data", "sector_cache.json")
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r") as f:
                    cache = json.load(f)
                return cache.get(symbol, "Unknown")
            except Exception:
                pass
        
        # Fallback: try common patterns
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
        
        Note: This is now only used for reference/display purposes.
        Actual capital allocation happens daily in _allocate_capital_to_daily_signals()
        based on signals found each day.
        """
        pw = self.position_weights
        if not pw or pw.get("method") != "sector_based":
            # Equal allocation fallback
            return {sym: self.initial_capital / max(len(symbols), 1) for sym in symbols}

        sector_alloc = pw.get("sector_allocation", {})
        max_positions = pw.get("max_positions", len(symbols))
        max_per_sector = pw.get("max_per_sector", 1)

        # Group symbols by sector
        sector_symbols: Dict[str, List[str]] = {}
        for sym in symbols:
            sector = self._get_sector(sym)
            sector_symbols.setdefault(sector, []).append(sym)

        # Select symbols respecting max_per_sector
        selected_symbols = []
        for sector, syms in sector_symbols.items():
            selected = syms[:max_per_sector]
            selected_symbols.extend(selected)

        # Limit total positions
        if len(selected_symbols) > max_positions:
            # Sort by sector weight (higher weight first)
            def sector_weight(sym):
                return sector_alloc.get(self._get_sector(sym), 0)
            selected_symbols.sort(key=sector_weight, reverse=True)
            selected_symbols = selected_symbols[:max_positions]

        # Calculate capital per selected symbol based on sector weights
        total_weight = sum(
            sector_alloc.get(self._get_sector(sym), 0)
            for sym in selected_symbols
        )
        if total_weight <= 0:
            # Equal fallback for selected
            return {sym: self.initial_capital / max(len(selected_symbols), 1) for sym in selected_symbols}

        allocations = {}
        for sym in selected_symbols:
            weight = sector_alloc.get(self._get_sector(sym), 0)
            allocations[sym] = self.initial_capital * (weight / total_weight)

        return allocations

    def run(self, symbols: Optional[List[str]] = None) -> BacktestMetrics:
        bt_cfg = self.config.get("backtest", {})
        start_date = pd.to_datetime(bt_cfg.get("start_date", "2026-01-01"))
        end_date = pd.to_datetime(bt_cfg.get("end_date", "2026-06-04"))

        if symbols is None:
            symbols = self._resolve_watchlist()

        # Sector-aware capital allocation
        capital_alloc = self._allocate_capital(symbols)
        active_symbols = list(capital_alloc.keys())

        if self.verbose:
            print(f"\n🔬 Backtest: {self.strategy.name}")
            print(f"   Period: {start_date.date()} → {end_date.date()}")
            print(f"   Capital: ₹{self.initial_capital:,.0f}")
            print(f"   Max Daily Allocation: ₹{self.max_capital_allocation_per_day:,.0f}")
            print(f"   Symbols: {len(symbols)} total, {len(active_symbols)} active")
            print(f"   Target: {self.target_profit_pct*100:.1f}% | Stop: {self.stop_loss_pct*100:.1f}% | Max Hold: {self.max_holding_days}d")
            if self.position_weights.get("method") == "sector_based":
                print(f"   Allocation: Sector-based (max_pos={self.position_weights.get('max_positions')}, max_per_sector={self.position_weights.get('max_per_sector')})")
            print("=" * 60)

        all_trades: List[Trade] = []
        daily_prices: Dict[str, pd.DataFrame] = {}

        # Fetch data for ALL symbols first with progress bar (parallelized)
        num_cores = max(1, multiprocessing.cpu_count() - 1)  # Leave 1 core free
        
        if self.verbose:
            print(f"\n📥 Fetching data from database ({num_cores} cores)...")
        
        def fetch_symbol_data(sym):
            df = self.fetch_data(sym, start_date, end_date)
            return sym, df
        
        results = Parallel(n_jobs=num_cores)(
            delayed(fetch_symbol_data)(sym) 
            for sym in tqdm(active_symbols, desc="Fetching data", disable=not self.verbose)
        )
        
        for sym, df in results:
            if df is None or len(df) < self.lookback_days:
                if self.verbose:
                    print(f"   ⚠️ Insufficient data for lookback {sym}")
                continue
            daily_prices[sym] = df
        
        # Print sector and allocation info after data fetch
        if self.verbose:
            print("\n" + "=" * 60)
            for sym in daily_prices.keys():
                print(f"📈 {sym} (sector: {self._get_sector(sym)}, alloc: ₹{capital_alloc.get(sym, 0):,.0f})")
            print("=" * 60)

        # Run day-by-day simulation with progress bar (mimics live trading workflow)
        if daily_prices:
            all_dates = set()
            for sym, df in daily_prices.items():
                if 'date' in df.columns:
                    all_dates.update(df['date'].dt.date)
            sorted_dates = sorted(all_dates)
            
            if self.verbose:
                print(f"\n🔄 Simulating {len(sorted_dates)} trading days...")
            
            all_trades = self.simulate_trades_daily_with_progress(
                daily_prices, 
                list(daily_prices.keys()), 
                capital_alloc,
                sorted_dates
            )

            if self.verbose and all_trades:
                print(f"\n   ✅ Total Trades: {len(all_trades)}")
                print(f"   Win: {sum(1 for t in all_trades if t.pnl > 0)}")
                print(f"   P&L: ₹{sum(t.pnl for t in all_trades):,.0f}")

        # Compute sector-wise metrics
        sector_metrics = self.compute_sector_metrics(all_trades)

        equity_df = self.build_equity_curve(all_trades, daily_prices)
        metrics = self.compute_metrics(all_trades, equity_df, self.initial_capital, sector_metrics)
        metrics.final_equity = metrics.initial_capital + sum(t.pnl for t in all_trades)

        if self.verbose:
            metrics.print_summary()

        safe_name = self.strategy.name.lower().replace(" ", "_")
        date_suffix = f"{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}"

        if self.save_plots and not equity_df.empty:
            self.plot_equity_curve(
                equity_df, metrics,
                filename=f"{safe_name}_{date_suffix}.png"
            )

        if self.save_plots and sector_metrics:
            self.plot_sector_breakdown(
                sector_metrics,
                filename=f"{safe_name}_sector_breakdown_{date_suffix}.png"
            )

        if self.save_metrics:
            self._save_metrics_json(metrics, all_trades)

        return metrics

    def _resolve_watchlist(self) -> List[str]:
        """
        Resolve watchlist name to actual symbol list.
        
        Priority:
        1. If 'nifty_top_500' in watchlist, load from config/default/stock_list.yaml
        2. Otherwise return the watchlist as-is if it's already a list of symbols
        """
        watchlist = self.watchlist
        
        if "nifty_top_500" in watchlist:
            # Load all symbols from stock_list.yaml
            stock_list_path = os.path.join(self.project_root, "config", "default", "stock_list.yaml")
            if os.path.exists(stock_list_path):
                try:
                    with open(stock_list_path, "r") as f:
                        data = yaml.safe_load(f) or {}
                    
                    watchlists = data.get("watchlists", {})
                    nifty_stocks = watchlists.get("nifty_top_500", [])
                    
                    # Extract symbols from fyers_symbol format
                    symbols = []
                    for stock in nifty_stocks:
                        if isinstance(stock, dict):
                            fyers_sym = stock.get("fyers_symbol", "")
                            if fyers_sym:
                                # Convert NSE:AUBANK-EQ to aubank_eq
                                symbol = fyers_sym.replace("NSE:", "").replace("-EQ", "").lower() + "_eq"
                                symbols.append(symbol)
                    
                    if symbols:
                        return symbols
                except Exception as e:
                    if self.verbose:
                        print(f"   ⚠️  Failed to load nifty_top_500 from stock_list.yaml: {e}")
            
            # Fallback if stock_list.yaml not found or empty
            fallback_symbols = [
                "aubank_eq", "reliance_eq", "infy_eq", "hdfcbank_eq", "tcs_eq",
                "hcltech_eq", "wipro_eq", "lt_eq", "sunpharma_eq", "maruti_eq",
                "hindunilvr_eq", "itc_eq", "powergrid_eq", "ntpc_eq", "adaniports_eq"
            ]
            if self.verbose:
                print(f"   ⚠️  Using {len(fallback_symbols)} fallback symbols")
            return fallback_symbols
        
        return watchlist if isinstance(watchlist, list) else []

    def _save_metrics_json(self, metrics: BacktestMetrics, trades: List[Trade]):
        safe_name = self.strategy.name.lower().replace(" ", "_")
        filepath = os.path.join(self.output_dir, f"{safe_name}_metrics.json")
        payload = {
            "strategy": self.strategy.name,
            "timestamp": datetime.now().isoformat(),
            "metrics": metrics.to_dict(),
            "trades": [
                {
                    "symbol": t.symbol,
                    "entry": t.entry_date.isoformat() if t.entry_date else None,
                    "exit": t.exit_date.isoformat() if t.exit_date else None,
                    "entry_price": t.entry_price,
                    "exit_price": t.exit_price,
                    "pnl": t.pnl,
                    "pnl_pct": t.pnl_pct,
                    "reason": t.exit_reason,
                    "holding_days": t.holding_days,
                }
                for t in trades
            ],
        }
        with open(filepath, "w") as f:
            json.dump(payload, f, indent=2, default=str)
        if self.verbose:
            print(f"   💾 Metrics JSON: {filepath}")


# ═══════════════════════════════════════════════════════════════════════
# Config loader
# ═══════════════════════════════════════════════════════════════════════

def load_backtest_config(project_root: str) -> Dict[str, Any]:
    """
    Load and merge backtest configs:
        1. config/default/backtest.yaml  (defaults)
        2. config/backtest.user.yaml     (overrides)
    """
    default_path = os.path.join(project_root, "config", "default", "backtest.yaml")
    user_path = os.path.join(project_root, "config", "backtest.user.yaml")

    config = {}

    if os.path.exists(default_path):
        with open(default_path, "r") as f:
            config = yaml.safe_load(f) or {}

    if os.path.exists(user_path):
        with open(user_path, "r") as f:
            user_cfg = yaml.safe_load(f) or {}
        config = deep_merge(config, user_cfg)

    return config


# ═══════════════════════════════════════════════════════════════════════
# CLI Runner — runs when file is executed directly
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Auto-detect project root from this file's location
    _PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)

    parser = argparse.ArgumentParser(description="Backtest Engine")
    parser.add_argument("--strategy", "-s", default=None,
                        help="Override strategy name (default: reads from config/backtest.user.yaml)")
    parser.add_argument("--symbols", nargs="+", default=None,
                        help="Specific symbols to backtest")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress verbose output")
    args = parser.parse_args()

    # Load merged backtest config
    config = load_backtest_config(_PROJECT_ROOT)

    # Strategy name: CLI arg > config > default
    strategy_name = args.strategy
    if strategy_name is None:
        strategy_name = config.get("backtest", {}).get("strategy_name")
    if strategy_name is None:
        strategy_name = "volume_support_resistance"  # ultimate fallback

    # Override verbose if --quiet
    if args.quiet:
        if "backtest_service" not in config:
            config["backtest_service"] = {}
        config["backtest_service"]["verbose"] = False

    print("=" * 60)
    print("🔬 Backtest Engine")
    print("=" * 60)
    print(f"   Strategy: {strategy_name}")
    print(f"   Config:   config/default/backtest.yaml + config/backtest.user.yaml")
    print("=" * 60)

    # Load strategy
    StrategyClass = load_strategy_class(strategy_name, _PROJECT_ROOT)
    strategy = StrategyClass()

    # Run backtest
    engine = BacktestEngine(
        strategy=strategy,
        config=config,
        project_root=_PROJECT_ROOT,
    )

    metrics = engine.run(symbols=args.symbols)

    print("\n✅ Backtest complete!")