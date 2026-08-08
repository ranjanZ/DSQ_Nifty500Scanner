"""
Intraday Backtest Engine
========================
Single instrument intraday backtesting framework.
Uses vectorbt for fast and efficient backtesting.

Run directly:
    python src/backtesting_intraday_service/backtest_engine.py
    python src/backtesting_intraday_service/backtest_engine.py --symbol NSE:NIFTY-EQ --strategy sma_crossover
"""

import os
import sys
import argparse
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict

try:
    import vectorbt as vbt
    HAS_VECTORBT = True
except ImportError:
    HAS_VECTORBT = False
    print("⚠️  vectorbt not installed. Install with: pip install vectorbt")


# ═══════════════════════════════════════════════════════════════════════
# Data structures
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class IntradayMetrics:
    """Computed intraday backtest performance metrics."""
    total_return_pct: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    win_rate_pct: float = 0.0
    profit_factor: float = 0.0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    avg_trade_duration_minutes: float = 0.0
    initial_capital: float = 0.0
    final_equity: float = 0.0
    pnl: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    def print_summary(self):
        print("\n" + "=" * 60)
        print("📊 INTRADAY BACKTEST RESULTS")
        print("=" * 60)
        print(f"   Symbol:              {getattr(self, 'symbol', 'N/A')}")
        print(f"   Initial Capital:     ₹{self.initial_capital:,.0f}")
        print(f"   Final Equity:        ₹{self.final_equity:,.0f}")
        print(f"   Total P&L:           ₹{self.pnl:,.0f}")
        print(f"   Total Return:        {self.total_return_pct:.2f}%")
        print(f"   Sharpe Ratio:        {self.sharpe_ratio:.3f}")
        print(f"   Sortino Ratio:       {self.sortino_ratio:.3f}")
        print(f"   Max Drawdown:        {self.max_drawdown_pct:.2f}%")
        print(f"   Win Rate:            {self.win_rate_pct:.2f}%")
        print(f"   Profit Factor:       {self.profit_factor:.3f}")
        print(f"   Avg Win:             {self.avg_win_pct:.2f}%")
        print(f"   Avg Loss:            {self.avg_loss_pct:.2f}%")
        print(f"   Total Trades:        {self.total_trades}")
        print(f"   Avg Duration (min):  {self.avg_trade_duration_minutes:.1f}")
        print("=" * 60)


# ═══════════════════════════════════════════════════════════════════════
# Strategy Base Class
# ═══════════════════════════════════════════════════════════════════════

class IntradayStrategy:
    """Base class for intraday strategies."""
    
    def __init__(self, params: Dict[str, Any] = None):
        self.params = params or {}
    
    def generate_signals(self, df: pd.DataFrame) -> Tuple[pd.Series, pd.Series]:
        """
        Generate entry signals.
        
        Returns:
            entries: Boolean Series for long entries
            exits: Boolean Series for long exits
        """
        raise NotImplementedError("Subclasses must implement generate_signals")


class SMAStrategy(IntradayStrategy):
    """Simple Moving Average Crossover Strategy for intraday."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'fast_window': 9,
            'slow_window': 21,
        }
        default_params.update(params or {})
        super().__init__(default_params)
    
    def generate_signals(self, df: pd.DataFrame) -> Tuple[pd.Series, pd.Series]:
        close = df['close']
        fast_ma = close.rolling(window=self.params['fast_window']).mean()
        slow_ma = close.rolling(window=self.params['slow_window']).mean()
        
        # Long entry: fast MA crosses above slow MA
        entries = (fast_ma > slow_ma) & (fast_ma.shift(1) <= slow_ma.shift(1))
        
        # Long exit: fast MA crosses below slow MA
        exits = (fast_ma < slow_ma) & (fast_ma.shift(1) >= slow_ma.shift(1))
        
        return entries, exits


class RSIOverSoldStrategy(IntradayStrategy):
    """RSI Oversold/Overbought Strategy for intraday."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'rsi_window': 14,
            'oversold_level': 30,
            'overbought_level': 70,
        }
        default_params.update(params or {})
        super().__init__(default_params)
    
    def generate_signals(self, df: pd.DataFrame) -> Tuple[pd.Series, pd.Series]:
        close = df['close']
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=self.params['rsi_window']).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=self.params['rsi_window']).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        # Long entry: RSI crosses above oversold level
        entries = (rsi > self.params['oversold_level']) & (rsi.shift(1) <= self.params['oversold_level'])
        
        # Long exit: RSI crosses below overbought level
        exits = (rsi < self.params['overbought_level']) & (rsi.shift(1) >= self.params['overbought_level'])
        
        return entries, exits


class BreakoutStrategy(IntradayStrategy):
    """Price Breakout Strategy for intraday."""
    
    def __init__(self, params: Dict[str, Any] = None):
        default_params = {
            'lookback_window': 20,
            'volume_multiplier': 1.5,
        }
        default_params.update(params or {})
        super().__init__(default_params)
    
    def generate_signals(self, df: pd.DataFrame) -> Tuple[pd.Series, pd.Series]:
        high = df['high']
        low = df['low']
        volume = df['volume']
        
        highest_high = high.rolling(window=self.params['lookback_window']).max()
        lowest_low = low.rolling(window=self.params['lookback_window']).min()
        avg_volume = volume.rolling(window=self.params['lookback_window']).mean()
        
        # Long entry: Price breaks above highest high with volume confirmation
        entries = (high > highest_high.shift(1)) & (volume > avg_volume * self.params['volume_multiplier'])
        
        # Long exit: Price breaks below lowest low
        exits = (low < lowest_low.shift(1))
        
        return entries, exits


STRATEGY_MAP = {
    'sma_crossover': SMAStrategy,
    'rsi_oversold': RSIOverSoldStrategy,
    'breakout': BreakoutStrategy,
}


def get_strategy(strategy_name: str, params: Dict[str, Any] = None) -> IntradayStrategy:
    """Get strategy instance by name."""
    if strategy_name not in STRATEGY_MAP:
        available = list(STRATEGY_MAP.keys())
        raise ValueError(f"Strategy '{strategy_name}' not found. Available: {available}")
    
    return STRATEGY_MAP[strategy_name](params)


# ═══════════════════════════════════════════════════════════════════════
# Backtest Engine
# ═══════════════════════════════════════════════════════════════════════

class IntradayBacktestEngine:
    """
    Single instrument intraday backtest engine using vectorbt.
    
    Usage:
        engine = IntradayBacktestEngine(config)
        metrics = engine.run(symbol="NSE:NIFTY-EQ", strategy="sma_crossover")
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.initial_capital = self.config.get('initial_capital', 1000000)
        self.transaction_cost_pct = self.config.get('transaction_cost_pct', 0.0003)  # 0.03%
        self.slippage_pct = self.config.get('slippage_pct', 0.0001)  # 0.01%
        self.verbose = self.config.get('verbose', True)
        
        if not HAS_VECTORBT:
            raise ImportError("vectorbt is required for IntradayBacktestEngine")
    
    def fetch_data(self, symbol: str, start_date: str, end_date: str, 
                   timeframe: str = "5m") -> Optional[pd.DataFrame]:
        """
        Fetch intraday data for a single symbol.
        
        Args:
            symbol: Instrument symbol (e.g., "NSE:NIFTY-EQ")
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            timeframe: Timeframe ("1m", "5m", "15m", "1h", etc.)
        
        Returns:
            DataFrame with OHLCV data
        """
        try:
            # Try to fetch from data_service
            from src.data_service.data_service import DataService
            
            ds = DataService()
            df = ds.get_historical_data(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                interval=timeframe,
                source="db"
            )
            
            if df is not None and not df.empty:
                # Ensure proper column names
                if 'time' in df.columns:
                    df['date'] = pd.to_datetime(df['time'])
                    df.set_index('date', inplace=True)
                
                required_cols = ['open', 'high', 'low', 'close', 'volume']
                if all(col in df.columns for col in required_cols):
                    if self.verbose:
                        print(f"✅ Fetched {len(df)} records for {symbol}")
                    return df
            
            if self.verbose:
                print(f"⚠️  No data found for {symbol}")
            return None
            
        except Exception as e:
            if self.verbose:
                print(f"❌ Error fetching data: {e}")
            return None
    
    def run(self, symbol: str, strategy_name: str, start_date: str, end_date: str,
            strategy_params: Dict[str, Any] = None, timeframe: str = "5m") -> IntradayMetrics:
        """
        Run intraday backtest for a single instrument.
        
        Args:
            symbol: Instrument symbol
            strategy_name: Strategy name (e.g., "sma_crossover")
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            strategy_params: Strategy-specific parameters
            timeframe: Data timeframe
        
        Returns:
            IntradayMetrics object
        """
        if self.verbose:
            print(f"\n🚀 Starting Intraday Backtest")
            print(f"   Symbol:       {symbol}")
            print(f"   Strategy:     {strategy_name}")
            print(f"   Period:       {start_date} to {end_date}")
            print(f"   Timeframe:    {timeframe}")
        
        # Fetch data
        df = self.fetch_data(symbol, start_date, end_date, timeframe)
        
        if df is None or len(df) < 50:
            if self.verbose:
                print("❌ Insufficient data for backtest")
            return IntradayMetrics(initial_capital=self.initial_capital, final_equity=self.initial_capital)
        
        # Get strategy
        strategy = get_strategy(strategy_name, strategy_params)
        
        # Generate signals
        entries, exits = strategy.generate_signals(df)
        
        # Run backtest with vectorbt
        close = df['close']
        
        # Create portfolio using vectorbt's Portfolio.from_signals
        pf = vbt.Portfolio.from_signals(
            close=close,
            entries=entries,
            exits=exits,
            init_cash=self.initial_capital,
            fees=self.transaction_cost_pct,
            slippage=self.slippage_pct,
            freq=timeframe
        )
        
        # Calculate metrics
        total_return = pf.total_return()
        sharpe = pf.sharpe_ratio()
        sortino = pf.sortino_ratio()
        max_dd = pf.max_drawdown()
        total_trades = pf.total_trades()
        
        # Get trade statistics
        trades = pf.trades.records
        if len(trades) > 0:
            winning_trades = sum(1 for t in trades if t['pnl'] > 0)
            losing_trades = sum(1 for t in trades if t['pnl'] <= 0)
            
            wins = [t['pnl'] for t in trades if t['pnl'] > 0]
            losses = [t['pnl'] for t in trades if t['pnl'] <= 0]
            
            avg_win = np.mean(wins) if wins else 0
            avg_loss = abs(np.mean(losses)) if losses else 0
            
            win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
            profit_factor = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float('inf')
            
            # Calculate average trade duration
            durations = [t['duration'] for t in trades if pd.notna(t['duration'])]
            avg_duration = np.mean(durations) / 60 if durations else 0  # Convert to minutes
        else:
            winning_trades = 0
            losing_trades = 0
            avg_win = 0
            avg_loss = 0
            win_rate = 0
            profit_factor = 0
            avg_duration = 0
        
        final_equity = pf.value()[-1] if hasattr(pf.value(), '__getitem__') else pf.value()
        pnl = final_equity - self.initial_capital
        
        metrics = IntradayMetrics(
            symbol=symbol,
            total_return_pct=total_return * 100,
            sharpe_ratio=sharpe if np.isfinite(sharpe) else 0,
            sortino_ratio=sortino if np.isfinite(sortino) else 0,
            max_drawdown_pct=max_dd * 100,
            win_rate_pct=win_rate,
            profit_factor=profit_factor if np.isfinite(profit_factor) else 0,
            avg_win_pct=(avg_win / self.initial_capital * 100) if avg_win else 0,
            avg_loss_pct=(avg_loss / self.initial_capital * 100) if avg_loss else 0,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            avg_trade_duration_minutes=avg_duration,
            initial_capital=self.initial_capital,
            final_equity=final_equity,
            pnl=pnl
        )
        
        if self.verbose:
            metrics.print_summary()
        
        return metrics


# ═══════════════════════════════════════════════════════════════════════
# CLI Entry Point
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description='Intraday Backtest Engine')
    parser.add_argument('--symbol', type=str, default='NSE:NIFTY-EQ',
                       help='Symbol to backtest (e.g., NSE:NIFTY-EQ)')
    parser.add_argument('--strategy', type=str, default='sma_crossover',
                       help='Strategy name (sma_crossover, rsi_oversold, breakout)')
    parser.add_argument('--start-date', type=str, default='2024-01-01',
                       help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, default='2024-12-31',
                       help='End date (YYYY-MM-DD)')
    parser.add_argument('--timeframe', type=str, default='5m',
                       help='Timeframe (1m, 5m, 15m, 1h)')
    parser.add_argument('--initial-capital', type=float, default=1000000,
                       help='Initial capital')
    parser.add_argument('--verbose', action='store_true', default=True,
                       help='Verbose output')
    
    args = parser.parse_args()
    
    config = {
        'initial_capital': args.initial_capital,
        'verbose': args.verbose,
    }
    
    engine = IntradayBacktestEngine(config)
    
    # Example strategy params
    strategy_params = None
    if args.strategy == 'sma_crossover':
        strategy_params = {'fast_window': 9, 'slow_window': 21}
    elif args.strategy == 'rsi_oversold':
        strategy_params = {'rsi_window': 14, 'oversold_level': 30, 'overbought_level': 70}
    elif args.strategy == 'breakout':
        strategy_params = {'lookback_window': 20, 'volume_multiplier': 1.5}
    
    metrics = engine.run(
        symbol=args.symbol,
        strategy_name=args.strategy,
        start_date=args.start_date,
        end_date=args.end_date,
        strategy_params=strategy_params,
        timeframe=args.timeframe
    )


if __name__ == '__main__':
    main()
