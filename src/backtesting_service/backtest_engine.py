"""
Backtest Engine
===============
Strategy-agnostic backtesting framework.
Reads config from config/default/backtest.yaml + config/backtest.user.yaml
Saves equity curves to data/outputs/backtesting_plots/
"""

import os
import json
import yaml
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict

plt.rcParams['axes.unicode_minus'] = False


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
    benchmark_return_pct: float = 0.0  # buy & hold of first symbol

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

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
        """
        Parameters
        ----------
        strategy : TradingStrategy instance
            Must have .generate_signals(df, num_back_signals) method.
        config : dict
            Merged backtest config (default + user overrides).
        project_root : str
            Project root path for resolving relative paths.
        db_getter : callable or None
            Function(db_name, table_name, start_date, end_date) -> DataFrame.
            If None, tries to import from src.data_service.db_utils.
        """
        self.strategy = strategy
        self.config = config
        self.project_root = project_root
        self.db_getter = db_getter

        bt_cfg = config.get("backtest", {})
        self.initial_capital = bt_cfg.get("initial_capital", 10000)
        self.target_profit_pct = bt_cfg.get("target_profit_pct", 0.08)
        self.stop_loss_pct = bt_cfg.get("stop_loss_pct", 0.04)
        self.max_holding_days = bt_cfg.get("max_holding_days", 7)
        self.lookback_days = bt_cfg.get("lookback_days", 100)
        self.position_weights = bt_cfg.get("position_weights", {})
        self.watchlist = bt_cfg.get("watchlist", ["nifty_top_500"])

        svc_cfg = config.get("backtest_service", {})
        self.save_plots = svc_cfg.get("save_plots", True)
        self.save_metrics = svc_cfg.get("save_metrics", True)
        self.verbose = svc_cfg.get("verbose", True)

        self.output_dir = os.path.join(project_root, "data", "outputs", "backtesting_plots")
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
        """Fetch OHLCV data for a symbol."""
        getter = self._get_db_getter()
        if getter is None:
            if self.verbose:
                print(f"   ⚠️  No DB getter available for {symbol}")
            return None

        # Add lookback buffer
        fetch_start = start_date - timedelta(days=self.lookback_days + 30)
        try:
            df = getter(
                db_name="spot_db_anamika",  # default DB; override via config if needed
                table_name=symbol,
                start_date=fetch_start,
                end_date=end_date,
            )
            if df is None or len(df) == 0:
                return None

            # Normalize date column
            if "time" in df.columns and "date" not in df.columns:
                df = df.copy()
                df["date"] = pd.to_datetime(df["time"])
            elif "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])
            else:
                df = df.copy()
                df["date"] = pd.to_datetime(df.index)

            # Filter to backtest period
            df = df[df["date"] >= start_date].reset_index(drop=True)
            return df
        except Exception as e:
            if self.verbose:
                print(f"   ⚠️  Failed to fetch {symbol}: {e}")
            return None

    # ── Signal generation ─────────────────────────────────────────────

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Run strategy and return signal DataFrame."""
        # Need enough history for lookback
        if len(df) < self.lookback_days:
            return df

        signals = self.strategy.generate_signals(df, num_back_signals=len(df))
        return signals

    # ── Trade simulation ──────────────────────────────────────────────

    def simulate_trades(self, df: pd.DataFrame, symbol: str, capital_per_trade: float) -> List[Trade]:
        """
        Simulate trades for a single symbol.
        Entry on signal==1 at next candle open.
        Exit on target profit, stop loss, or max holding days.
        """
        trades = []
        if "signal" not in df.columns or (df["signal"] == 1).sum() == 0:
            return trades

        i = 0
        n = len(df)
        while i < n - 1:
            if df.loc[df.index[i], "signal"] == 1:
                # Entry at next candle's open (or current close if last candle)
                entry_idx = min(i + 1, n - 1)
                entry_price = df.loc[df.index[entry_idx], "open"]
                entry_date = df.loc[df.index[entry_idx], "date"]

                target_price = entry_price * (1 + self.target_profit_pct)
                stop_price = entry_price * (1 - self.stop_loss_pct)
                max_exit_idx = min(entry_idx + self.max_holding_days, n - 1)

                qty = int(capital_per_trade / entry_price) if entry_price > 0 else 0
                if qty == 0:
                    i += 1
                    continue

                exit_price = None
                exit_date = None
                exit_reason = "max_hold"
                exit_idx = max_exit_idx

                # Scan forward for exit
                for j in range(entry_idx + 1, max_exit_idx + 1):
                    high = df.loc[df.index[j], "high"]
                    low = df.loc[df.index[j], "low"]

                    if low <= stop_price:
                        exit_price = stop_price
                        exit_date = df.loc[df.index[j], "date"]
                        exit_reason = "stoploss"
                        exit_idx = j
                        break
                    elif high >= target_price:
                        exit_price = target_price
                        exit_date = df.loc[df.index[j], "date"]
                        exit_reason = "target"
                        exit_idx = j
                        break

                if exit_price is None:
                    # Exit at close of max holding day
                    exit_price = df.loc[df.index[exit_idx], "close"]
                    exit_date = df.loc[df.index[exit_idx], "date"]

                pnl = (exit_price - entry_price) * qty
                pnl_pct = (exit_price / entry_price - 1) * 100 if entry_price > 0 else 0
                holding_days = (exit_date - entry_date).days if exit_date and entry_date else 0

                trades.append(Trade(
                    symbol=symbol,
                    entry_date=entry_date,
                    entry_price=entry_price,
                    exit_date=exit_date,
                    exit_price=exit_price,
                    qty=qty,
                    pnl=pnl,
                    pnl_pct=pnl_pct,
                    exit_reason=exit_reason,
                    holding_days=holding_days,
                ))

                i = exit_idx + 1  # Skip ahead; no overlapping trades on same symbol
            else:
                i += 1

        return trades

    # ── Portfolio & equity curve ──────────────────────────────────────

    def build_equity_curve(self, all_trades: List[Trade], daily_prices: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        """
        Build daily equity curve from trades.
        Assumes non-overlapping trades per symbol (engine enforces this).
        """
        if not all_trades:
            return pd.DataFrame()

        # Collect all trading days from price data
        all_dates = set()
        for sym, df in daily_prices.items():
            if "date" in df.columns:
                all_dates.update(df["date"].dt.date)
        sorted_dates = sorted(all_dates)

        if not sorted_dates:
            return pd.DataFrame()

        # Map each trade to its active date range
        equity = []
        cash = self.initial_capital
        # Track open position value per day
        for d in sorted_dates:
            date_dt = datetime.combine(d, datetime.min.time())
            position_value = 0.0

            for t in all_trades:
                if t.entry_date.date() <= d:
                    if t.exit_date is None or t.exit_date.date() > d:
                        # Position open — mark to market
                        sym = t.symbol
                        if sym in daily_prices:
                            day_df = daily_prices[sym]
                            day_row = day_df[day_df["date"].dt.date == d]
                            if not day_row.empty:
                                mtm_price = day_row["close"].values[0]
                                position_value += (mtm_price - t.entry_price) * t.qty
                    elif t.exit_date.date() == d:
                        # Closed today — realized P&L already in cash
                        pass

            total_equity = cash + position_value
            equity.append({"date": date_dt, "equity": total_equity})

        # Actually, simpler: process trades chronologically
        # Reset and do chronological P&L accumulation
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

    # ── Metrics computation ───────────────────────────────────────────

    @staticmethod
    def compute_metrics(trades: List[Trade], equity_df: pd.DataFrame, initial_capital: float) -> BacktestMetrics:
        m = BacktestMetrics()
        m.initial_capital = initial_capital

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

        # Equity curve metrics
        equity = equity_df["equity"].values
        m.final_equity = equity[-1]
        m.total_return_pct = (m.final_equity / initial_capital - 1) * 100

        # Daily returns
        daily_returns = np.diff(equity) / equity[:-1]
        if len(daily_returns) > 0 and daily_returns.std() > 0:
            m.sharpe_ratio = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252)
            downside = daily_returns[daily_returns < 0]
            if len(downside) > 0 and downside.std() > 0:
                m.sortino_ratio = (daily_returns.mean() / downside.std()) * np.sqrt(252)

        # Max drawdown
        peak = np.maximum.accumulate(equity)
        drawdown = (equity - peak) / peak
        m.max_drawdown_pct = drawdown.min() * 100

        # Annualized return
        days = (equity_df["date"].iloc[-1] - equity_df["date"].iloc[0]).days
        if days > 0:
            m.annualized_return_pct = ((m.final_equity / initial_capital) ** (365 / days) - 1) * 100

        return m

    # ── Plotting ──────────────────────────────────────────────────────

    def plot_equity_curve(self, equity_df: pd.DataFrame, metrics: BacktestMetrics, filename: str):
        """Save equity curve plot."""
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

        # Equity
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

        # Drawdown
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

    # ── Main run ──────────────────────────────────────────────────────

    def run(self, symbols: Optional[List[str]] = None) -> BacktestMetrics:
        """
        Run full backtest across symbols.

        Parameters
        ----------
        symbols : list[str] | None
            If None, uses watchlist from config.

        Returns
        -------
        BacktestMetrics
        """
        bt_cfg = self.config.get("backtest", {})
        start_date = pd.to_datetime(bt_cfg.get("start_date", "2026-01-01"))
        end_date = pd.to_datetime(bt_cfg.get("end_date", "2026-06-04"))

        if symbols is None:
            symbols = self._resolve_watchlist()

        if self.verbose:
            print(f"\n🔬 Backtest: {self.strategy.name}")
            print(f"   Period: {start_date.date()} → {end_date.date()}")
            print(f"   Capital: ₹{self.initial_capital:,.0f}")
            print(f"   Symbols: {len(symbols)}")
            print(f"   Target: {self.target_profit_pct*100:.1f}% | Stop: {self.stop_loss_pct*100:.1f}% | Max Hold: {self.max_holding_days}d")
            print("=" * 60)

        all_trades: List[Trade] = []
        daily_prices: Dict[str, pd.DataFrame] = {}

        # Capital per trade (naive equal split; sector weights can be added later)
        capital_per_trade = self.initial_capital / max(len(symbols), 1)

        for sym in symbols:
            if self.verbose:
                print(f"\n📈 {sym}")

            df = self.fetch_data(sym, start_date, end_date)
            if df is None or len(df) < self.lookback_days:
                if self.verbose:
                    print(f"   ⚠️  Insufficient data")
                continue

            daily_prices[sym] = df
            signals_df = self.generate_signals(df)
            trades = self.simulate_trades(signals_df, sym, capital_per_trade)
            all_trades.extend(trades)

            if self.verbose and trades:
                print(f"   ✅ Trades: {len(trades)}  " +
                      f"Win: {sum(1 for t in trades if t.pnl>0)}  " +
                      f"P&L: ₹{sum(t.pnl for t in trades):,.0f}")

        # Build equity curve
        equity_df = self.build_equity_curve(all_trades, daily_prices)
        metrics = self.compute_metrics(all_trades, equity_df, self.initial_capital)
        metrics.final_equity = metrics.initial_capital + sum(t.pnl for t in all_trades)

        if self.verbose:
            metrics.print_summary()

        # Save outputs
        if self.save_plots and not equity_df.empty:
            safe_name = self.strategy.name.lower().replace(" ", "_")
            self.plot_equity_curve(
                equity_df, metrics,
                filename=f"{safe_name}_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.png"
            )

        if self.save_metrics:
            self._save_metrics_json(metrics, all_trades)

        return metrics

    def _resolve_watchlist(self) -> List[str]:
        """Resolve watchlist names to actual symbol lists."""
        # For now, return a default set. In production, this would query a symbol registry.
        watchlist = self.watchlist
        if "nifty_top_500" in watchlist:
            # Placeholder: in real system, fetch from DB or file
            return ["aubank_eq", "reliance_eq", "infy_eq", "hdfcbank_eq", "tcs_eq"]
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


# ── Config loader ───────────────────────────────────────────────────

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
        if isinstance(config, dict) and "backtest" in config:
            config = config  # keep as-is
        elif isinstance(config, dict) and "backtest" not in config:
            # Maybe wrapped under a key
            pass

    if os.path.exists(user_path):
        with open(user_path, "r") as f:
            user_cfg = yaml.safe_load(f) or {}
        # Deep merge
        _deep_merge(config, user_cfg)

    return config


def _deep_merge(base: Dict, override: Dict):
    """Recursively merge override into base."""
    for key, val in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(val, dict):
            _deep_merge(base[key], val)
        else:
            base[key] = val