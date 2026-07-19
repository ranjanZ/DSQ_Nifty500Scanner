"""
Portfolio State Manager
=======================
Persists daily portfolio snapshots (holdings + closed positions) to disk.
Used by LiveTradingService to:
  1. Resume state after restart (know which stocks are held)
  2. Track historical realized / unrealized P&L per day
  3. Prevent duplicate positions in the same stock

File: data/outputs/portfolio_state.json
"""

import os
import json
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional, Set
from dataclasses import dataclass, asdict

logger = logging.getLogger("PortfolioStateManager")


@dataclass
class Holding:
    symbol: str
    quantity: int
    average_price: float
    current_value: float = 0.0
    unrealized_pnl: float = 0.0
    entry_time: Optional[str] = None


@dataclass
class ClosedPosition:
    symbol: str
    quantity: int
    entry_price: float
    exit_price: float
    realised_pnl: float
    exit_time: Optional[str] = None
    type: str = "delivery_sell"


@dataclass
class DailySnapshot:
    date: str
    holdings: List[Holding]
    closed_positions: List[ClosedPosition]
    updated_at: str


class PortfolioStateManager:
    """
    Manages persistent portfolio state across days.

    Structure on disk:
    {
      "portfolio_history": {
        "2026-07-19": { date, holdings[], closed_positions[], updated_at },
        "2026-07-20": { ... }
      },
      "latest_date": "2026-07-20"
    }
    """

    def __init__(self, project_root: str = "."):
        self.project_root = project_root
        self.output_dir = os.path.join(project_root, "data","portfolio_state")
        os.makedirs(self.output_dir, exist_ok=True)
        self.state_path = os.path.join(self.output_dir, "portfolio_state.json")

        self.portfolio_history: Dict[str, Dict[str, Any]] = {}
        self._latest_date: Optional[str] = None
        self._today_holdings: List[Holding] = []
        self._today_closed: List[ClosedPosition] = []

    # ── Persistence ─────────────────────────────────────────────────────

    def load_state(self) -> bool:
        """Load state from disk. Returns True if file existed."""
        if not os.path.exists(self.state_path):
            logger.info("No existing portfolio state found")
            return False

        try:
            with open(self.state_path, "r") as f:
                data = json.load(f)

            self.portfolio_history = data.get("portfolio_history", {})
            self._latest_date = data.get("latest_date")

            # Restore today's working arrays from latest snapshot
            if self._latest_date and self._latest_date in self.portfolio_history:
                snap = self.portfolio_history[self._latest_date]
                self._today_holdings = [
                    Holding(**h) for h in snap.get("holdings", [])
                ]
                self._today_closed = [
                    ClosedPosition(**c) for c in snap.get("closed_positions", [])
                ]

            logger.info(f"Loaded state: {len(self._today_holdings)} holdings, "
                        f"{len(self._today_closed)} closed, latest={self._latest_date}")
            return True
        except Exception as e:
            logger.error(f"Failed to load state: {e}")
            return False

    def save_state(self):
        """Flush current working state to disk."""
        today = datetime.now().strftime("%Y-%m-%d")

        snapshot = {
            "date": today,
            "holdings": [asdict(h) for h in self._today_holdings],
            "closed_positions": [asdict(c) for c in self._today_closed],
            "updated_at": datetime.now().isoformat()
        }

        self.portfolio_history[today] = snapshot
        self._latest_date = today

        payload = {
            "portfolio_history": self.portfolio_history,
            "latest_date": self._latest_date
        }

        try:
            with open(self.state_path, "w") as f:
                json.dump(payload, f, indent=2, default=str)
            logger.info(f"💾 State saved: {len(self._today_holdings)} holdings, "
                        f"{len(self._today_closed)} closed")
        except Exception as e:
            logger.error(f"Failed to save state: {e}")

    # ── Holdings API ────────────────────────────────────────────────────

    def get_held_symbols(self) -> Set[str]:
        """Return set of symbols currently in holdings."""
        return {h.symbol for h in self._today_holdings}

    def is_held(self, symbol: str) -> bool:
        return any(h.symbol == symbol for h in self._today_holdings)

    def add_holding(self, symbol: str, quantity: int, average_price: float,
                    current_value: Optional[float] = None,
                    entry_time: Optional[str] = None):
        """Record a new buy / add to existing holding."""
        for h in self._today_holdings:
            if h.symbol == symbol:
                # Average down / up
                total_cost = (h.quantity * h.average_price) + (quantity * average_price)
                h.quantity += quantity
                h.average_price = total_cost / h.quantity
                h.current_value = current_value or h.current_value
                h.entry_time = entry_time or h.entry_time
                logger.info(f"Updated holding {symbol}: qty={h.quantity}, avg={h.average_price:.2f}")
                return

        self._today_holdings.append(Holding(
            symbol=symbol,
            quantity=quantity,
            average_price=average_price,
            current_value=current_value or (quantity * average_price),
            unrealized_pnl=0.0,
            entry_time=entry_time
        ))
        logger.info(f"Added holding {symbol}: qty={quantity}, avg={average_price:.2f}")

    def update_holding_ltp(self, symbol: str, ltp: float):
        """Update current_value and unrealized_pnl for a held symbol."""
        for h in self._today_holdings:
            if h.symbol == symbol:
                h.current_value = ltp * h.quantity
                h.unrealized_pnl = h.current_value - (h.average_price * h.quantity)
                return True
        return False

    def update_all_holdings(self, ltp_lookup: Dict[str, float]):
        """Batch update all holdings with latest prices."""
        for h in self._today_holdings:
            if h.symbol in ltp_lookup:
                ltp = ltp_lookup[h.symbol]
                h.current_value = ltp * h.quantity
                h.unrealized_pnl = h.current_value - (h.average_price * h.quantity)

    def close_holding(self, symbol: str, exit_price: float, exit_time: Optional[str] = None) -> Optional[ClosedPosition]:
        """Move a holding to closed_positions. Returns the closed record."""
        for i, h in enumerate(self._today_holdings):
            if h.symbol == symbol:
                realized = (exit_price - h.average_price) * h.quantity
                closed = ClosedPosition(
                    symbol=symbol,
                    quantity=h.quantity,
                    entry_price=h.average_price,
                    exit_price=exit_price,
                    realised_pnl=realized,
                    exit_time=exit_time or datetime.now().isoformat(),
                    type="delivery_sell"
                )
                self._today_closed.append(closed)
                self._today_holdings.pop(i)
                logger.info(f"Closed {symbol}: realised_pnl=₹{realized:,.2f}")
                return closed
        return None

    # ── Daily rollover ──────────────────────────────────────────────────

    def rollover_day(self, new_date: str):
        """
        Start a new trading day.
        Carry forward open holdings (reset unrealized_pnl, update entry_time if needed).
        """
        if self._latest_date and self._latest_date != new_date:
            # Save yesterday first
            self.save_state()
            logger.info(f"Rollover: {self._latest_date} → {new_date}")

        self._today_closed = []
        # Keep holdings, they carry forward
        for h in self._today_holdings:
            h.unrealized_pnl = 0.0  # reset for new day

        self._latest_date = new_date

    # ── Queries ─────────────────────────────────────────────────────────

    def get_today_snapshot(self) -> Dict[str, Any]:
        today = datetime.now().strftime("%Y-%m-%d")
        return {
            "date": today,
            "holdings": [asdict(h) for h in self._today_holdings],
            "closed_positions": [asdict(c) for c in self._today_closed],
            "updated_at": datetime.now().isoformat()
        }

    def get_historical_pnl(self) -> Dict[str, float]:
        """Aggregate realized P&L per day."""
        result = {}
        for date, snap in self.portfolio_history.items():
            total = sum(c.get("realised_pnl", 0) for c in snap.get("closed_positions", []))
            result[date] = total
        return result

    def get_total_realized_pnl(self) -> float:
        return sum(c.realised_pnl for c in self._today_closed)

    def get_total_unrealized_pnl(self) -> float:
        return sum(h.unrealized_pnl for h in self._today_holdings)