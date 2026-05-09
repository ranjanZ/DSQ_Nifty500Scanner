import pandas as pd
import numpy as np
import logging
import yaml
from datetime import timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.strategy.market_scanner import MarketScanner
from src.data_pipeline.db_utils import get_table_content

# Import the concrete strategy classes (add more as needed)
from src.strategy.crossover_strategy import MovingAverageCrossoverStrategy
from src.strategy.madam_strategy import SupportResistanceStrategy
# from src.strategy.volume_price_strategy import VolumePriceStrategy   # if you have one

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Map strategy names (from backtest_config.yaml) to their class
STRATEGY_CLASSES = {
    "MA_Crossover": MovingAverageCrossoverStrategy,
    "Support_Resistance": SupportResistanceStrategy,
    # "Volume_Price": VolumePriceStrategy,
}


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
    """Compact sector‑based selection and weighting (unchanged)."""
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

        # Create scanner with required watchlist and number of backtest days
        self.scanner = MarketScanner(
            yaml_config_path,
            watch_list=self.backtest_cfg['watchlist'],
            num_back_days=self.backtest_cfg['lookback_days']  # ensure enough historical data
        )
        self.strategy_name = self.backtest_cfg['strategy_name']

        # --- Instantiate and add the strategy directly (no factory) ---
        strategy_class = STRATEGY_CLASSES.get(self.strategy_name)
        if strategy_class is None:
            raise ValueError(f"Unknown strategy '{self.strategy_name}'. "
                             f"Available: {list(STRATEGY_CLASSES.keys())}")
        # Optionally read params from config (if defined)
        strategy_params = self.backtest_cfg.get('strategy_params', {})
        strategy_instance = strategy_class(params=strategy_params)
        self.scanner.add_strategy(self.strategy_name, strategy_instance)

        self.initial_capital = float(self.backtest_cfg['initial_capital'])
        self.target_profit   = float(self.backtest_cfg['target_profit_pct'])
        self.stop_loss       = float(self.backtest_cfg['stop_loss_pct'])
        self.max_hold_days   = int(self.backtest_cfg['max_holding_days'])
        self.lookback_days   = int(self.backtest_cfg['lookback_days'])
        self.num_positions   = self.backtest_cfg['position_weights']['max_positions']

        # Trading calendar
        self.trading_days = pd.bdate_range(
            start=pd.Timestamp(self.backtest_cfg['start_date']),
            end=pd.Timestamp(self.backtest_cfg['end_date'])
        )
        self.start_date = self.trading_days[0]
        self.end_date   = self.trading_days[-1]

        # Preload all data and precompute all signals (offline)
        self._load_all_data()
        self._precompute_signals()

    # ------------------------------------------------------------------
    # 1. Bulk data loading
    # ------------------------------------------------------------------
    def _load_all_data(self):
        """
        Load full OHLC data for all stocks for the entire backtest period
        in one batch per stock. Stores in self.data_dict {symbol: DataFrame}.
        """
        logger.info("Loading historical data for all stocks ...")
        stocks = self.scanner.get_stock_symbols()  # uses the watchlist from config
        self.data_dict = {}
        self.stock_meta = {}

        for stock in stocks:
            symbol = stock['symbol']
            table = self.scanner.get_table_name(symbol)
            fetch_start = self.start_date - timedelta(days=self.lookback_days)
            df = get_table_content(
                db_name=self.config['database_config']['db_name'],
                table_name=table,
                start_date=fetch_start,
                end_date=self.end_date
            )
            if df is not None and not df.empty:
                df = df.sort_values('time')
                df['time'] = pd.to_datetime(df['time'])
                df = df[['time', 'open', 'high', 'low', 'close', 'volume']]
                self.data_dict[symbol] = df
            else:
                self.data_dict[symbol] = None
            self.stock_meta[symbol] = stock

        logger.info(f"Loaded data for {sum(1 for v in self.data_dict.values() if v is not None)} stocks.")

    # ------------------------------------------------------------------
    # 2. Signal pre‑computation (parallelised with threads)
    # ------------------------------------------------------------------
    def _precompute_signals(self):
        """
        For each symbol, compute buy signals for every trading day
        using only data available up to that day.
        Stores result in self.signals_by_date = {date: [signal_dict, ...]}.
        """
        logger.info("Precomputing signals (parallel per symbol using threads) ...")
        self.signals_by_date: Dict[pd.Timestamp, List[dict]] = {d: [] for d in self.trading_days}

        def process_symbol(symbol):
            df = self.data_dict.get(symbol)
            if df is None or len(df) < 5:
                return []
            meta = self.stock_meta[symbol]
            results = []
            strategy = self.scanner.strategies[self.strategy_name]  # already added
            for date in self.trading_days:
                mask = df['time'] <= date
                historical = df[mask]
                if len(historical) < self.lookback_days // 2:
                    continue
                try:
                    signals_df = strategy.generate_signals(historical)

                    last_5 = signals_df.iloc[-5:]
                    latest = last_5.iloc[-1]   # latest row (may have signal 0)

                    # Buy signal only if numeric signal == 1
                    if latest['signal'] == 1:
                        results.append((
                            date,
                            {
                                'symbol': symbol,
                                'name': meta.get('name', symbol),
                                'close': float(latest['close']),
                                'open': float(latest['open']),
                                'sector': meta.get('sector', 'Unknown'),
                                'confidence': self.scanner._calculate_confidence(signals_df),
                            }
                        ))
                except Exception as e:
                    logger.debug(f"Signal error {symbol} on {date.date()}: {e}")
            return results

        symbols = list(self.data_dict.keys())
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(process_symbol, sym): sym for sym in symbols}
            for future in as_completed(futures):
                for date, signal in future.result():
                    self.signals_by_date[date].append(signal)

        total_signals = sum(len(v) for v in self.signals_by_date.values())
        logger.info(f"Precomputed {total_signals} total buy signals across all days.")

    # ------------------------------------------------------------------
    # 3. Backtest loop (purely in‑memory)
    # ------------------------------------------------------------------
    def run(self):
        pw_config = self.backtest_cfg['position_weights']
        self.total_capital = self.initial_capital
        self.open_trades: List[Trade] = []
        self.closed_trades: List[Trade] = []
        self.portfolio_values = []

        for date in self.trading_days:
            # a) Exit checks
            self.check_and_exit_trades(date)

            # b) New signals from precomputed dictionary
            if self.utilisation_pct() < 0.51:
                raw_signals = self.signals_by_date[date]
                if raw_signals:
                    selected = select_and_weight_signals(raw_signals, pw_config)
                    for signal in selected:
                        weight = signal.get('final_weight', 0)
                        if weight <= 0:
                            continue
                        entry_price = signal['open']
                        alloc_wanted = self.total_capital * weight
                        cash = self.available_cash()
                        alloc = min(alloc_wanted, cash)
                        if alloc <= 0:
                            continue
                        shares = int(alloc // entry_price)
                        if shares == 0:
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

            # c) Record EOD value
            self.portfolio_values.append((date, self.total_capital))
            logger.debug(f"{date.date()}: util={self.utilisation_pct():.2%}, open={len(self.open_trades)}")

        # Force‑close at end
        last_date = self.trading_days[-1]
        for trade in self.open_trades[:]:
            last_data = self.get_day_data(trade.symbol, last_date)
            if last_data is not None and not last_data.empty:
                self.close_trade(trade, last_data['close'].iloc[-1], last_date, 'end_of_backtest')
            else:
                logger.warning(f"No data to close {trade.symbol} on {last_date.date()}")

        self.results = pd.DataFrame(self.portfolio_values, columns=['date', 'portfolio_value'])
        return self.results

    # ------------------------------------------------------------------
    # Helpers (unchanged)
    # ------------------------------------------------------------------
    def get_day_data(self, symbol, date):
        """Return OHLC data for a specific day."""
        df = self.data_dict.get(symbol)
        if df is None:
            return None
        mask = (df['time'] <= date) & (df['time'].dt.date == date.date())
        day_data = df[mask]
        return day_data if not day_data.empty else df[df['time'] <= date].tail(1)

    def check_and_exit_trades(self, date):
        for trade in self.open_trades[:]:
            if date < trade.entry_date:
                continue
            day_data = self.get_day_data(trade.symbol, date)
            if day_data is None or day_data.empty:
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

    def close_trade(self, trade, exit_price, exit_date, reason):
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

    # Capital & metrics
    def utilised_capital(self):
        return sum(t.allocated_capital for t in self.open_trades)

    def available_cash(self):
        return self.total_capital - self.utilised_capital()

    def utilisation_pct(self):
        return self.utilised_capital() / self.total_capital if self.total_capital else 0.0

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
        trades_df.to_csv("data/backtesting/backtest_trades.csv", index=False)
        logger.info("Trade log saved to data/backtesting/backtest_trades.csv")