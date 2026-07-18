"""
Strategy Chart Plotter
======================
Plots OHLCV candlesticks with buy/sell signals, volume bars, and up to 2 configurable indicators.
Saves charts to strategy_plots/ by default.
"""

import os
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

plt.rcParams['axes.unicode_minus'] = False


class StrategyChartPlotter:
    """Professional dark-themed chart plotter for trading strategies."""

    DEFAULT_PLOT_DIR = "strategy_plots"
    DEFAULT_DPI = 150

    COLOR_BG = "#0d1117"
    COLOR_GRID = "#30363d"
    COLOR_TEXT = "#c9d1d9"
    COLOR_BUY = "#3fb950"
    COLOR_SELL = "#f85149"
    COLOR_WICK_UP = "#238636"
    COLOR_WICK_DOWN = "#da3633"
    COLOR_VOL_UP = "#3fb950"
    COLOR_VOL_DOWN = "#f85149"

    def __init__(self, plot_dir: Optional[str] = None):
        self.plot_dir = plot_dir or self.DEFAULT_PLOT_DIR
        os.makedirs(self.plot_dir, exist_ok=True)

    def _style_axis(self, ax: plt.Axes, title: Optional[str] = None):
        ax.set_facecolor(self.COLOR_BG)
        for spine in ax.spines.values():
            spine.set_color(self.COLOR_GRID)
        ax.tick_params(colors=self.COLOR_TEXT, labelsize=8)
        ax.xaxis.label.set_color(self.COLOR_TEXT)
        ax.yaxis.label.set_color(self.COLOR_TEXT)
        ax.grid(True, alpha=0.25, color=self.COLOR_GRID, linestyle="--")
        if title:
            ax.set_title(title, color=self.COLOR_TEXT, fontsize=10, pad=8)

    def _plot_candles(self, ax: plt.Axes, df: pd.DataFrame):
        """Draw candlesticks using matplotlib bars."""
        df = df.copy()
        if "date" in df.columns and not np.issubdtype(df["date"].dtype, np.number):
            df["_x"] = mdates.date2num(pd.to_datetime(df["date"]))
        else:
            df["_x"] = np.arange(len(df))

        for _, row in df.iterrows():
            x = row["_x"]
            o, h, l, c = row["open"], row["high"], row["low"], row["close"]

            if c >= o:
                color = self.COLOR_WICK_UP
                bottom = o
                height = c - o
            else:
                color = self.COLOR_WICK_DOWN
                bottom = c
                height = o - c

            ax.bar(x, height, width=0.6, bottom=bottom, color=color, edgecolor=color, zorder=2)
            ax.plot([x, x], [l, h], color=color, linewidth=0.8, zorder=1)

        return df["_x"].values

    def _plot_volume(self, ax: plt.Axes, df: pd.DataFrame, x_vals: np.ndarray):
        """Draw volume bars colored by candle direction."""
        if "volume" not in df.columns:
            return

        vol = df["volume"].values
        # Color: green if close >= open, red otherwise
        colors = np.where(df["close"].values >= df["open"].values,
                          self.COLOR_VOL_UP, self.COLOR_VOL_DOWN)

        ax.bar(x_vals, vol, width=0.6, color=colors, alpha=0.7, zorder=2)
        self._style_axis(ax, title="Volume")
        ax.set_ylabel("Volume", color=self.COLOR_TEXT)

    def _plot_signals(self, ax: plt.Axes, df: pd.DataFrame, x_vals: np.ndarray):
        """Overlay buy (^) and sell (v) markers.
        Uses positional indexing since x_vals is positional (0..N-1)
        and df may have non-sequential label indices (e.g. sliced snapshots).
        """
        buy_mask = df["signal"].values == 1
        sell_mask = df["signal"].values == -1

        if buy_mask.any():
            buy_pos = np.where(buy_mask)[0]
            ax.scatter(
                x_vals[buy_pos],
                df["low"].iloc[buy_pos].values * 0.998,
                marker="^", s=120, c=self.COLOR_BUY,
                edgecolors="white", linewidths=1.0,
                label=f"Buy ({buy_mask.sum()})", zorder=5,
            )

        if sell_mask.any():
            sell_pos = np.where(sell_mask)[0]
            ax.scatter(
                x_vals[sell_pos],
                df["high"].iloc[sell_pos].values * 1.002,
                marker="v", s=120, c=self.COLOR_SELL,
                edgecolors="white", linewidths=1.0,
                label=f"Sell ({sell_mask.sum()})", zorder=5,
            )

        if "signal_strength" in df.columns:
            for pos in np.where(buy_mask)[0]:
                ax.annotate(
                    f"{df['signal_strength'].iloc[pos]:.1f}",
                    xy=(x_vals[pos], df["low"].iloc[pos] * 0.992),
                    fontsize=6, ha="center", color=self.COLOR_BUY, fontweight="bold",
                )

    def _plot_indicator(self, ax: plt.Axes, df: pd.DataFrame, x_vals: np.ndarray, cfg: Dict[str, Any]):
        """Plot a single indicator line."""
        col = cfg.get("column")
        if col not in df.columns:
            print(f"⚠️  Indicator column '{col}' not found — skipping.")
            return

        color = cfg.get("color", "#58a6ff")
        label = cfg.get("label", col)
        ls = cfg.get("line_style", "-")
        lw = cfg.get("line_width", 1.5)

        ax.plot(x_vals, df[col].values, color=color, label=label, linestyle=ls, linewidth=lw)
        self._style_axis(ax, title=label)
        ax.legend(loc="upper left", fontsize=8, facecolor=self.COLOR_BG,
                  edgecolor=self.COLOR_GRID, labelcolor=self.COLOR_TEXT)

    def plot(
        self,
        df: pd.DataFrame,
        strategy_name: str,
        indicators: Optional[List[Dict[str, Any]]] = None,
        title: Optional[str] = None,
        filename: Optional[str] = None,
        fig_size: Optional[Tuple[int, int]] = None,
        show: bool = False,
    ) -> str:
        indicators = indicators or []
        if len(indicators) > 2:
            print("⚠️  Max 2 indicators allowed — truncating to first 2.")
            indicators = indicators[:2]

        n_ind = len(indicators)
        has_volume = "volume" in df.columns

        # Layout: price + volume + up to 2 indicator panels
        # height_ratios: price=3, volume=1, each indicator=1
        if n_ind == 0:
            if has_volume:
                fig, (ax_price, ax_vol) = plt.subplots(
                    2, 1, figsize=fig_size or (14, 9), gridspec_kw={"height_ratios": [3, 1]}
                )
                ax_inds = []
            else:
                fig, ax_price = plt.subplots(1, 1, figsize=fig_size or (14, 7))
                ax_vol = None
                ax_inds = []
        elif n_ind == 1:
            if has_volume:
                fig, (ax_price, ax_vol, ax_i1) = plt.subplots(
                    3, 1, figsize=fig_size or (14, 11), gridspec_kw={"height_ratios": [3, 1, 1]}
                )
                ax_inds = [ax_i1]
            else:
                fig, (ax_price, ax_i1) = plt.subplots(
                    2, 1, figsize=fig_size or (14, 9), gridspec_kw={"height_ratios": [3, 1]}
                )
                ax_vol = None
                ax_inds = [ax_i1]
        else:
            if has_volume:
                fig, (ax_price, ax_vol, ax_i1, ax_i2) = plt.subplots(
                    4, 1, figsize=fig_size or (14, 13), gridspec_kw={"height_ratios": [3, 1, 1, 1]}
                )
                ax_inds = [ax_i1, ax_i2]
            else:
                fig, (ax_price, ax_i1, ax_i2) = plt.subplots(
                    3, 1, figsize=fig_size or (14, 11), gridspec_kw={"height_ratios": [3, 1, 1]}
                )
                ax_vol = None
                ax_inds = [ax_i1, ax_i2]

        fig.patch.set_facecolor(self.COLOR_BG)

        # Price panel
        x_vals = self._plot_candles(ax_price, df)
        self._plot_signals(ax_price, df, x_vals)

        buy_cnt = (df["signal"] == 1).sum()
        sell_cnt = (df["signal"] == -1).sum()
        chart_title = title or f"{strategy_name}  |  Buy: {buy_cnt}  |  Sell: {sell_cnt}"
        self._style_axis(ax_price, title=chart_title)
        ax_price.set_ylabel("Price", color=self.COLOR_TEXT)

        if buy_cnt or sell_cnt:
            ax_price.legend(
                loc="upper left", fontsize=8, facecolor=self.COLOR_BG,
                edgecolor=self.COLOR_GRID, labelcolor=self.COLOR_TEXT,
            )

        if "date" in df.columns:
            ax_price.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
            ax_price.xaxis.set_major_locator(mdates.AutoDateLocator())
            plt.setp(ax_price.xaxis.get_majorticklabels(), rotation=30, ha="right")

        # Volume panel
        if ax_vol is not None:
            self._plot_volume(ax_vol, df, x_vals)

        # Indicator panels
        for ax_i, ind_cfg in zip(ax_inds, indicators):
            self._plot_indicator(ax_i, df, x_vals, ind_cfg)

        plt.tight_layout()

        if filename is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = strategy_name.lower().replace(" ", "_")
            filename = f"{safe_name}_{ts}.png"

        filepath = os.path.join(self.plot_dir, filename)
        plt.savefig(filepath, dpi=self.DEFAULT_DPI, facecolor=self.COLOR_BG, bbox_inches="tight")
        print(f"💾 Chart saved: {os.path.abspath(filepath)}")

        if show:
            plt.show()
        else:
            plt.close(fig)

        return filepath


def load_chart_config(config_path: str) -> List[Dict[str, Any]]:
    import yaml
    with open(config_path, "r") as f:
        cfg = yaml.safe_load(f)
    return cfg.get("chart_display", {}).get("indicators", [])


def plot_signals(
    df: pd.DataFrame,
    strategy_name: str,
    config_path: Optional[str] = None,
    indicators: Optional[List[Dict[str, Any]]] = None,
    plot_dir: str = "strategy_plots",
    **kwargs,
) -> str:
    plotter = StrategyChartPlotter(plot_dir=plot_dir)
    if config_path and os.path.exists(config_path):
        indicators = load_chart_config(config_path)
    return plotter.plot(df, strategy_name, indicators=indicators, **kwargs)