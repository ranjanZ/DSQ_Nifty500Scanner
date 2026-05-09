import pandas as pd
import numpy as np
import logging
import yaml
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
import threading

from strategy.market_scanner import MarketScanner
from data_pipeline.db_utils import get_table_content

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global thread-local storage for DB connections (if needed, otherwise just rely on connection pooling)
# We'll assume get_table_content is thread-safe (uses its own connections).
# If not, wrap it with a connection per thread.

@dataclass
class Trade:
    symbol: str
    entry_date: pd.Timestamp
    exit_date: Optional[pd.Timestamp] = None
    entry_price: float = 0.0
    exit_price: float = 0.0
    allocated_capital: float = 0.0
    shares: int = 0
    exit_reason: Optional[str] = None
    pnl: float = 0.0
    return_pct: float = 0.0
    status: str = "open"


def select_and_weight_signals(signals, config):
    """
    Compact sector-based selection and weighting.
    (Same as before, no changes needed)
    """
    max_pos, max_per_sector = config['max_positions'], config['max_per_sector']
    sector_weights = config['sector_allocation']
    redistribute = config.get('redistribute_unused', True)
    
    sectors = {}
    for s in signals:
        sectors.setdefault(s['sector'], []).append(s)
    for sec in sectors:
        sectors[sec] = sorted(sectors[sec], key=lambda x: x.get('confidence', 0), reverse=True)[:max_per_sector]
    
    priority, others = [], []
    for sec, stocks in sectors.items():
        w = sector_weights.get(sec, 0)
        for s in stocks: s['sector_weight'] = w
        (priority if w > 0 else others).extend(stocks)
    
    if not priority:
        final = sorted(others, key=lambda x: x.get('confidence', 0), reverse=True)[:max_pos]
        for s in final: s['final_weight'] = 1.0 / len(final) if final else 0
        return final
    
    sec_map = {}
    for s in priority:
        sec_map.setdefault(s['sector'], []).append(s)
    total_w = sum(sector_weights[sec] for sec in sec_map)
    final = []
    for sec, stocks in sec_map.items():
        pw = (sector_weights[sec] / total_w) / len(stocks)
        for s in stocks: s['final_weight'] = pw
        final.extend(stocks)
    
    remaining = max_pos - len(final)
    if remaining > 0 and others and redistribute:
        fillers = sorted(others, key=lambda x: x.get('confidence', 0), reverse=True)[:remaining]
        for s in fillers: s['final_weight'] = 0.0
        final.extend(fillers)
    
    if len(final) > max_pos:
        final = sorted(final, key=lambda x: (x['final_weight'], x.get('confidence', 0)), reverse=True)[:max_pos]
        tw = sum(s['final_weight'] for s in final)
        if tw > 0:
            for s in final: s['final_weight'] /= tw
    return final


class BacktestEngine:
    def __init__(self, yaml_config_path: str = "config/stock_list.yaml",
                 backtest_yaml_config_path: str = "config/backtest_config.yaml"):
        with open(yaml_config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        with open(backtest_yaml_config_path, 'r') as f:
            self.backtest_cfg = yaml.safe_load(f)['backtest']

        self.scanner = MarketScanner(yaml_config_path, watch_list=self.backtest_cfg['watchlist'])
        self.strategy_name = self.backtest_cfg['strategy_name']
        self.scanner.create_strategy(self.strategy_name, self.strategy_name, params=None)

        self.initial_capital = float(self.backtest_cfg['initial_capital'])
        self.target_profit   = float(self.backtest_cfg['target_profit_pct'])
        self.stop_loss       = float(self.backtest_cfg['stop_loss_pct'])
        self.max_hold_days   = int(self.backtest_cfg['max_holding_days'])
        self.num_positions   = self.backtest_cfg['position_weights']['max_positions']

        # State
        self.total_capital   = self.initial_capital
        self.open_trades: List[Trade] = []
        self.closed_trades: List[Trade] = []
        self.portfolio_values = []

        # Trading calendar
        self.trading_days = pd.bdate_range(
            start=self.backtest_cfg['start_date'],
            end=self.backtest_cfg['end_date']
        )

        # Per-day data cache to avoid repeated DB calls within the same day
        self._day_cache: Dict[Tuple[str, pd.Timestamp], pd.DataFrame] = {}
        self._cache_lock = threading.Lock()  # for thread safety when parallel scanning

        # Thread pool for parallel scanning (number of workers = min(32, stocks+4))
        self._executor = ThreadPoolExecutor(max_workers=16)  # adjust based on DB load

        logger.info(f"Backtest period: {self.trading_days[0].date()} → {self.trading_days[-1].date()} "
                    f"({len(self.trading_days)} trading days), "
                    f"parallel workers: {self._executor._max_workers}")

    # ------------------------------------------------------------------
    # Data helpers (with caching)
    # ------------------------------------------------------------------
    def _fetch_data(self, symbol: str, end_date: pd.Timestamp) -> Optional[pd.DataFrame]:
        """Actual DB query, called once per (symbol, end_date) pair."""
        table_name = self.scanner.get_table_name(symbol)
        start_date = end_date - timedelta(days=self.backtest_cfg['lookback_days'])
        df = get_table_content(
            db_name=self.config['database_config']['db_name'],
            table_name=table_name,
            start_date=start_date,
            end_date=end_date
        )
        if df is None or df.empty:
            return None
        df = df.sort_values('time')
        df['time'] = pd.to_datetime(df['time'])
        column_mapping = {'open': 'open', 'high': 'high', 'low': 'low',
                          'close': 'close', 'volume': 'volume'}
        df = df.rename(columns=column_mapping)
        return df[['time'] + list(column_mapping.values())]

    def get_data_for_date(self, symbol: str, end_date: pd.Timestamp) -> Optional[pd.DataFrame]:
        """
        Historical data up to end_date, cached per (symbol, end_date).
        Thread-safe.
        """
        key = (symbol, end_date)
        with self._cache_lock:
            if key in self._day_cache:
                return self._day_cache[key].copy() if self._day_cache[key] is not None else None

        df = self._fetch_data(symbol, end_date)
        with self._cache_lock:
            self._day_cache[key] = df.copy() if df is not None else None
        return df

    def get_day_data(self, symbol: str, date: pd.Timestamp) -> Optional[pd.DataFrame]:
        """Return OHLC data for a specific trading day (from cache)."""
        df = self.get_data_for_date(symbol, date)
        if df is None or df.empty:
            return None
        day_data = df[df['time'].dt.date == date.date()]
        return day_data if not day_data.empty else df.tail(1)

    # ------------------------------------------------------------------
    # Signal scanning – parallelized
    # ------------------------------------------------------------------
    def _scan_one_stock(self, stock: dict, date: pd.Timestamp) -> Optional[dict]:
        """
        Generate a buy signal for one stock on the given date.
        Returns signal dict or None. Thread-safe.
        """
        try:
            df = self.get_data_for_date(stock['symbol'], date)
            if df is None or len(df) < 5:
                return None

            strategy = self.scanner.strategies[self.strategy_name]
            signals_df = strategy.generate_signals(df)

            last_5 = signals_df.iloc[-5:]
            if any(last_5['signal'] != 0):
                latest_signal_row = last_5[last_5['signal'] != 0].iloc[-1]
            else:
                latest_signal_row = last_5.iloc[-1]

            if latest_signal_row['signal'] == 1:
                return {
                    'symbol': stock['symbol'],
                    'name': stock['name'],
                    'close': float(latest_signal_row['close']),
                    'open': float(latest_signal_row['open']),
                    'sector': stock['sector'],
                    'confidence': self.scanner._calculate_confidence(signals_df),
                }
        except Exception as e:
            logger.debug(f"Error scanning {stock['symbol']} on {date.date()}: {e}")
        return None

    def scan_on_date(self, date: pd.Timestamp) -> List[Dict]:
        """Parallel scan of up to 200 stocks for buy signals."""
        stocks = self.scanner.get_stock_symbols()[:200]
        signals = []

        # Parallel execution
        futures = {self._executor.submit(self._scan_one_stock, stock, date): stock for stock in stocks}
        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                signals.append(result)

        logger.info(f"{date.date()}: Found {len(signals)} raw signals "
                    f"(util={self.utilisation_pct():.2%})")
        return signals

    # ------------------------------------------------------------------
    # Capital & utilisation
    # ------------------------------------------------------------------
    def utilised_capital(self) -> float:
        return sum(t.allocated_capital for t in self.open_trades)

    def available_cash(self) -> float:
        return self.total_capital - self.utilised_capital()

    def utilisation_pct(self) -> float:
        if self.total_capital == 0:
            return 0.0
        return self.utilised_capital() / self.total_capital

    # ------------------------------------------------------------------
    # Trade execution
    # ------------------------------------------------------------------
    def check_and_exit_trades(self, date: pd.Timestamp):
        for trade in self.open_trades[:]:
            if date < trade.entry_date:
                continue
            day_data = self.get_day_data(trade.symbol, date)
            if day_data is None:
                continue

            high = day_data['high'].max()
            low  = day_data['low'].min()
            close = day_data['close'].iloc[-1]

            exit_price = None
            exit_reason = None

            stop_price = trade.entry_price * (1 - self.stop_loss)
            if low <= stop_price:
                exit_price = stop_price
                exit_reason = 'stop_loss'

            if exit_price is None:
                target_price = trade.entry_price * (1 + self.target_profit)
                if high >= target_price:
                    exit_price = target_price
                    exit_reason = 'target'

            if exit_price is None:
                holding_days = len(pd.bdate_range(start=trade.entry_date, end=date)) - 1
                if holding_days >= self.max_hold_days:
                    exit_price = close
                    exit_reason = 'time_exit'

            if exit_price is not None:
                self.close_trade(trade, exit_price, date, exit_reason)

    def close_trade(self, trade: Trade, exit_price: float, exit_date: pd.Timestamp, reason: str):
        trade.exit_price = exit_price
        trade.exit_date = exit_date
        trade.exit_reason = reason
        trade.status = "closed"
        trade.pnl = (exit_price - trade.entry_price) * trade.shares
        trade.return_pct = (exit_price / trade.entry_price - 1)

        self.total_capital += trade.pnl
        self.open_trades.remove(trade)
        self.closed_trades.append(trade)

        logger.info(f"🔴 EXIT {trade.symbol} on {exit_date.date()} "
                    f"reason={reason} price={exit_price:.2f} pnl={trade.pnl:.2f}")

    # ------------------------------------------------------------------
    # Main loop – sector‑based allocation
    # ------------------------------------------------------------------
    def run(self):
        pw_config = self.backtest_cfg['position_weights']

        for i, date in enumerate(self.trading_days):
            # 1. Clear per-day cache to free memory
            with self._cache_lock:
                self._day_cache.clear()

            # 2. Check exits
            self.check_and_exit_trades(date)

            # 3. Scan for new signals (parallel) if we have room
            if self.utilisation_pct() < 0.51:
                raw_signals = self.scan_on_date(date)
                if raw_signals:
                    selected = select_and_weight_signals(raw_signals, pw_config)

                    for signal in selected:
                        weight = signal.get('final_weight', 0)
                        if weight <= 0:
                            continue

                        entry_price = signal['open']   # no look‑ahead, using today's open
                        alloc_wanted = self.total_capital * weight
                        cash = self.available_cash()
                        alloc = min(alloc_wanted, cash)

                        if alloc <= 0:
                            logger.warning(f"⚠️  Insufficient cash for {signal['symbol']}")
                            continue

                        shares = int(alloc // entry_price)
                        if shares == 0:
                            logger.warning(f"⚠️  Cannot afford even 1 share of {signal['symbol']}")
                            continue

                        used_capital = shares * entry_price
                        trade = Trade(
                            symbol=signal['symbol'],
                            entry_date=date,
                            entry_price=entry_price,
                            allocated_capital=used_capital,
                            shares=shares,
                            status="open"
                        )
                        self.open_trades.append(trade)
                        logger.info(f"✅ ENTERED {signal['symbol']} on {date.date()} "
                                    f"price={entry_price:.2f} shares={shares} allocated={used_capital:.2f}")

            # 4. Record EOD portfolio value
            self.portfolio_values.append((date, self.total_capital))
            logger.debug(f"{date.date()}: utilisation={self.utilisation_pct():.2%}, "
                         f"open trades={len(self.open_trades)}")

        # Force‑close open trades at end
        last_date = self.trading_days[-1]
        for trade in self.open_trades[:]:
            last_data = self.get_data_for_date(trade.symbol, last_date)
            if last_data is not None and not last_data.empty:
                self.close_trade(trade, last_data['close'].iloc[-1], last_date, 'end_of_backtest')
            else:
                logger.warning(f"Cannot close {trade.symbol} – no data on {last_date.date()}")

        self.results = pd.DataFrame(self.portfolio_values, columns=['date', 'portfolio_value'])
        return self.results

    # ------------------------------------------------------------------
    # Performance metrics (unchanged)
    # ------------------------------------------------------------------
    def metrics(self) -> Dict:
        if not hasattr(self, 'results') or self.results.empty:
            return {}

        returns = self.results['portfolio_value'].pct_change().dropna()
        total_return = (self.results['portfolio_value'].iloc[-1] / self.initial_capital - 1) * 100
        returns_std = returns.std()
        sharpe = (returns.mean() / returns_std * np.sqrt(252)) if returns_std and returns_std > 0 else 0.0
        max_drawdown = (self.results['portfolio_value'] / self.results['portfolio_value'].cummax() - 1).min() * 100

        trades_df = pd.DataFrame([t.__dict__ for t in self.closed_trades])
        if trades_df.empty:
            return {
                'Total Return (%)': round(total_return, 2),
                'Sharpe Ratio': round(sharpe, 2),
                'Max Drawdown (%)': round(max_drawdown, 2),
                'Win Rate (%)': 0.0,
                'Avg Win': 0.0,
                'Avg Loss': 0.0,
                'Profit Factor': 0.0,
                'Total Trades': 0
            }

        win_rate = (trades_df['pnl'] > 0).mean() * 100
        win_trades = trades_df[trades_df['pnl'] > 0]
        loss_trades = trades_df[trades_df['pnl'] < 0]
        avg_win = win_trades['pnl'].mean() if not win_trades.empty else 0.0
        avg_loss = loss_trades['pnl'].mean() if not loss_trades.empty else 0.0

        if not loss_trades.empty and loss_trades['pnl'].sum() != 0:
            profit_factor = win_trades['pnl'].sum() / abs(loss_trades['pnl'].sum())
        elif not loss_trades.empty:
            profit_factor = float('inf') if not win_trades.empty else 0.0
        else:
            profit_factor = float('inf') if not win_trades.empty else 0.0

        return {
            'Total Return (%)': round(total_return, 2),
            'Sharpe Ratio': round(sharpe, 2),
            'Max Drawdown (%)': round(max_drawdown, 2),
            'Win Rate (%)': round(win_rate, 2),
            'Avg Win': round(avg_win, 2),
            'Avg Loss': round(avg_loss, 2),
            'Profit Factor': round(profit_factor, 2) if profit_factor != float('inf') else profit_factor,
            'Total Trades': len(self.closed_trades)
        }


# ----------------------------------------------------------------------
if __name__ == "__main__":
    engine = BacktestEngine("config/stock_list.yaml")
    results = engine.run()

    print("\n📈 Backtest Performance Summary")
    print("=" * 40)
    for k, v in engine.metrics().items():
        print(f"{k}: {v}")

    if engine.closed_trades:
        trades_df = pd.DataFrame([t.__dict__ for t in engine.closed_trades])
        trades_df.to_csv("data/backtest_trades.csv", index=False)
        logger.info("Trade log saved to backtest_trades.csv")