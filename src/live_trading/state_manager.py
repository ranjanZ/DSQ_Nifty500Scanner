"""
Permanent State Management for Live Trading
- Single persistent session (never loses data)
- All changes saved instantly to disk
- State directory: data/session/
"""

import os
import json
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime
import pytz
from dataclasses import dataclass, asdict, field
from typing import Dict, Any, List

logger = logging.getLogger("StateManager")

# ----------------------------------------------------------------------
# Data Models (unchanged from original, but fully retained)
# ----------------------------------------------------------------------

@dataclass
class PositionState:
    """Persistent position state"""
    symbol: str
    entry_price: float
    entry_time: str
    quantity: int
    capital_used: float
    entry_signal: str
    target_price: float
    stop_loss_price: float
    highest_price: float = 0
    order_id: str = None
    status: str = "OPEN"
    pnl: float = 0
    pnl_pct: float = 0
    exit_price: Optional[float] = None        # Exit price when closed
    exit_time: Optional[str] = None          # Exit time when closed
    exit_reason: Optional[str] = None        # Why it was closed (SL, TP, TIME_LIMIT, etc)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'PositionState':
        return PositionState(**data)


@dataclass
class OrderState:
    """Persistent order state"""
    order_id: str
    symbol: str
    side: str
    quantity: int
    order_type: str
    price: float = 0
    stop_price: float = 0
    status: str = "OPEN"
    filled_quantity: int = 0
    average_price: float = 0
    created_time: str = None
    executed_time: str = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'OrderState':
        return OrderState(**data)


@dataclass
class TradingSessionState:
    """Complete trading session state (single permanent session)"""
    session_id: str
    start_time: str
    positions: Dict[str, PositionState] = field(default_factory=dict)
    orders: Dict[str, OrderState] = field(default_factory=dict)
    total_pnl: float = 0
    capital_available: float = 0
    capital_used: float = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    portfolio_history: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data['positions'] = {k: v.to_dict() if isinstance(v, PositionState) else v 
                            for k, v in data['positions'].items()}
        data['orders'] = {k: v.to_dict() if isinstance(v, OrderState) else v 
                         for k, v in data['orders'].items()}
        return data
    
    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'TradingSessionState':
        data = data.copy()
        data['positions'] = {k: PositionState.from_dict(v) if isinstance(v, dict) else v 
                            for k, v in data.get('positions', {}).items()}
        data['orders'] = {k: OrderState.from_dict(v) if isinstance(v, dict) else v 
                         for k, v in data.get('orders', {}).items()}
        # Remove deprecated fields (now stored in portfolio_history)
        data.pop('closed_positions', None)
        data.pop('closed_positions_count', None)
        return TradingSessionState(**data)


# ----------------------------------------------------------------------
# Permanent State Manager – always loads/creates the same session
# ----------------------------------------------------------------------

class StateManager:
    """
    Manages a SINGLE, PERMANENT trading session.
    - All data is persisted to disk immediately.
    - On initialization, it loads the existing session from data/session/,
      or creates a new one if none exists.
    - No data is ever lost when the program restarts.
    """
    
    # Default permanent session ID
    DEFAULT_SESSION_ID = "permanent"
    
    def __init__(self, state_dir: str = "data/session", session_id: str = None):
        """
        Initialize the permanent state manager.
        
        Args:
            state_dir: Directory to store the session file (default: data/session)
            session_id: Optional custom session ID (default: "permanent")
        """
        self.state_dir = state_dir
        self.session_id = session_id or self.DEFAULT_SESSION_ID
        os.makedirs(state_dir, exist_ok=True)
        
        self.tz = pytz.timezone('Asia/Kolkata')
        self.current_session: Optional[TradingSessionState] = None
        
        # Automatically load existing session or create a new one
        self._load_or_create_session()
        
        logger.info(f"StateManager initialized with session: {self.session_id} at {self.state_dir}")
    
    def _load_or_create_session(self):
        """Load existing session from disk, or create a new one if not found."""
        session_file = os.path.join(self.state_dir, f"{self.session_id}.json")
        
        if os.path.exists(session_file):
            try:
                with open(session_file, 'r') as f:
                    data = json.load(f)
                self.current_session = TradingSessionState.from_dict(data)
                logger.info(f"Loaded existing permanent session: {self.session_id}")
            except Exception as e:
                logger.error(f"Error loading session – creating new one: {e}")
                self._create_new_session()
        else:
            self._create_new_session()
    
    def _create_new_session(self, initial_capital: float = 0):
        """Create a brand new permanent session (overwrites any existing)."""
        now = datetime.now(self.tz).isoformat()
        self.current_session = TradingSessionState(
            session_id=self.session_id,
            start_time=now,
            capital_available=initial_capital,
            capital_used=0
        )
        self.save_session()
        logger.info(f"Created new permanent session: {self.session_id} with capital {initial_capital}")
    
    def save_session(self) -> bool:
        """Save the current session to disk."""
        if self.current_session is None:
            logger.warning("No session to save")
            return False
        

        print(f"++++++++++++++++++++++Portfolio history contains {len(self.current_session.portfolio_history)} snapshots.")
        self.current_session.portfolio_history = self.fill_entry_times(self.current_session.portfolio_history)

        session_file = os.path.join(self.state_dir, f"{self.session_id}.json")
        try:
            with open(session_file, 'w') as f:
                json.dump(self.current_session.to_dict(), f, indent=2)
            logger.debug(f"Session saved: {self.session_id}")
            return True
        except Exception as e:
            logger.error(f"Error saving session: {e}")
            return False
    
    def get_session_file(self, session_id: str = None) -> str:
        """Return the file path for a given session ID."""
        sid = session_id or self.session_id
        return os.path.join(self.state_dir, f"{sid}.json")
    
    def list_sessions(self) -> List[str]:
        """List all saved session IDs."""
        if not os.path.isdir(self.state_dir):
            return []
        sessions = [name[:-5] for name in os.listdir(self.state_dir) if name.endswith('.json')]
        sessions.sort(key=lambda x: os.path.getmtime(self.get_session_file(x)))
        return sessions
    
    def load_session(self, session_id: str) -> Optional[TradingSessionState]:
        """Load a saved session from disk."""
        session_file = self.get_session_file(session_id)
        if not os.path.exists(session_file):
            logger.warning(f"Session not found: {session_id}")
            return None
        try:
            with open(session_file, 'r') as f:
                data = json.load(f)
            session = TradingSessionState.from_dict(data)
            self.current_session = session
            self.session_id = session_id
            logger.info(f"Loaded session: {session_id}")
            return session
        except Exception as e:
            logger.error(f"Error loading session {session_id}: {e}")
            return None
    
    def create_new_session(self, session_id: str = None, initial_capital: float = 0) -> Optional[TradingSessionState]:
        """Create a new trading session and persist it to disk."""
        if session_id:
            self.session_id = session_id
        self._create_new_session(initial_capital)
        return self.current_session
    
    # ------------------------------------------------------------------
    # Public API – same as original StateManager but without multiple sessions
    # ------------------------------------------------------------------
    
    def reset_session(self, initial_capital: float = 0):
        """
        Completely reset the permanent session (all positions/orders cleared).
        Use with caution – this cannot be undone.
        """
        self._create_new_session(initial_capital)
        logger.warning(f"Permanent session reset with capital {initial_capital}")
    
    def add_position(self, position_state: PositionState) -> bool:
        """Add a new open position."""
        if self.current_session is None:
            return False
        self.current_session.positions[position_state.symbol] = position_state
        self.save_session()
        logger.info(f"Position added: {position_state.symbol}")
        return True
    
    def update_position(self, symbol: str, updates: Dict[str, Any]) -> bool:
        """Update an existing position."""
        if self.current_session is None or symbol not in self.current_session.positions:
            logger.warning(f"Position not found: {symbol}")
            return False
        
        position = self.current_session.positions[symbol]
        for key, value in updates.items():
            if hasattr(position, key):
                setattr(position, key, value)
        self.save_session()
        logger.debug(f"Position updated: {symbol}")
        return True
    
    def remove_position(self, symbol: str) -> bool:
        """Archive a closed position to trade history and remove from open positions."""
        if self.current_session is None or symbol not in self.current_session.positions:
            return False
        
        position = self.current_session.positions[symbol]
        
        # Remove from open positions (closed_positions now tracked in portfolio_history via broker sync)
        del self.current_session.positions[symbol]
        self.current_session.total_pnl += position.pnl
        self.save_session()
        logger.info(f"Position CLOSED & ARCHIVED: {symbol} | P&L: {position.pnl:.2f} ({position.pnl_pct:.2f}%)")
        return True
    
    def add_order(self, order_state: OrderState) -> bool:
        """Add an order."""
        if self.current_session is None:
            return False
        self.current_session.orders[order_state.order_id] = order_state
        self.save_session()
        logger.info(f"Order added: {order_state.order_id}")
        return True
    
    def update_order(self, order_id: str, updates: Dict[str, Any]) -> bool:
        """Update an existing order."""
        if self.current_session is None or order_id not in self.current_session.orders:
            return False
        
        order = self.current_session.orders[order_id]
        for key, value in updates.items():
            if hasattr(order, key):
                setattr(order, key, value)
        self.save_session()
        logger.debug(f"Order updated: {order_id}")
        return True
    
    def get_position(self, symbol: str) -> Optional[PositionState]:
        """Retrieve a position by symbol."""
        if self.current_session is None:
            return None
        return self.current_session.positions.get(symbol)
    
    def get_order(self, order_id: str) -> Optional[OrderState]:
        """Retrieve an order by ID."""
        if self.current_session is None:
            return None
        return self.current_session.orders.get(order_id)
    
    def get_all_positions(self) -> Dict[str, PositionState]:
        """Get all open positions."""
        if self.current_session is None:
            return {}
        return self.current_session.positions.copy()
    
    def get_all_current_holdings(self) -> Dict[str, PositionState]:
        

        print(f"++++++++++++++++++++++Portfolio history contains {len(self.current_session.portfolio_history)} snapshots.")
        self.current_session.portfolio_history = self.fill_entry_times(self.current_session.portfolio_history)
        currwnt_date=datetime.now().strftime("%Y-%m-%d")
        return self.current_session.portfolio_history.get(currwnt_date, {}).get('holdings', {})




    def get_all_orders(self) -> Dict[str, OrderState]:
        """Get all orders."""
        if self.current_session is None:
            return {}
        return self.current_session.orders.copy()
    
    def update_session_metrics(self, total_pnl: float = None, 
                              capital_available: float = None, 
                              capital_used: float = None) -> bool:
        """Update session-level metrics (PNL, capital)."""
        if self.current_session is None:
            return False
        
        if total_pnl is not None:
            self.current_session.total_pnl = total_pnl
        if capital_available is not None:
            self.current_session.capital_available = capital_available
        if capital_used is not None:
            self.current_session.capital_used = capital_used
        
        self.save_session()
        return True


    def fill_entry_times(self,pos_history: Dict[str, Any]) -> Dict[str, Any]:
        """
        Fill missing entry_time for holdings and closed_positions using data from previous days.
        
        For each date (in chronological order):
        - Maintain a map of symbol -> most recent non-null entry_time seen so far.
        - For holdings with entry_time == None, assign the value from the map.
        - For holdings with non-null entry_time, update the map.
        - For closed_positions, attempt to add an 'entry_time' field using the map
            (if a matching symbol is found).
        
        Args:
            pos_history: Dictionary with dates as keys, each containing 'holdings' and 'closed_positions'.
            
        Returns:
            A new dictionary with the same structure, but with entry_time fields filled where possible.
        """
        # Sort dates in ascending order
        sorted_dates = sorted(pos_history.keys())
        
        # Map symbol -> latest known entry_time (string)
        entry_time_map: Dict[str, str] = {}
        
        # Create a deep copy to avoid mutating the original
        import copy
        result = copy.deepcopy(pos_history)
        
        for date in sorted_dates:
            day_data = result[date]
            
            # Process holdings: fill missing entry_time
            for holding in day_data.get("holdings", []):
                symbol = holding["symbol"]
                if holding.get("entry_time") is not None:
                    # Update map with this non-null entry_time
                    entry_time_map[symbol] = holding["entry_time"]
                else:
                    # Try to fill from map
                    if symbol in entry_time_map:
                        holding["entry_time"] = entry_time_map[symbol]
                    # else remains None (no previous entry found)
            
            # Process closed_positions: add entry_time if possible
            for closed in day_data.get("closed_positions", []):
                symbol = closed["symbol"]
                # Only add entry_time if we have a recorded entry_time for that symbol
                if symbol in entry_time_map and "entry_time" not in closed:
                    closed["entry_time"] = entry_time_map[symbol]
                # If entry_time already exists (maybe from earlier logic), leave it
        
        return result


    def update_portfolio_snapshot(self, portfolio_data: Dict[str, Any], date: str = None) -> bool:
        """Store a daily portfolio snapshot keyed by date."""
        if self.current_session is None:
            return False
        if date is None:
            date = datetime.now(self.tz).strftime("%Y-%m-%d")
        snapshot = {
            'date': date,
            'holdings': portfolio_data.get('holdings', []),
            'closed_positions': portfolio_data.get('closed_positions', []),
            'updated_at': datetime.now(self.tz).isoformat()
        }
        self.current_session.portfolio_history[date] = snapshot



        self.save_session()
        return True



    def get_portfolio_snapshot(self, date: str = None) -> Dict[str, Any]:
        if self.current_session is None:
            return {}
        if date is None:
            date = datetime.now(self.tz).strftime("%Y-%m-%d")


        return self.current_session.portfolio_history.get(date, {})
    
    def get_portfolio_history(self) -> Dict[str, Any]:
        if self.current_session is None:
            return {}

        return self.current_session.portfolio_history.copy()
    
    def get_session_summary(self) -> Dict[str, Any]:
        """Return a summary of the current permanent session."""
        if self.current_session is None:
            return {}
        
        # Calculate total closed positions from portfolio_history
        total_closed = 0
        for snapshot in self.current_session.portfolio_history.values():
            total_closed += len(snapshot.get('closed_positions', []))
        
        return {
            'session_id': self.current_session.session_id,
            'start_time': self.current_session.start_time,
            'open_positions': len(self.current_session.positions),
            'total_orders': len(self.current_session.orders),
            'total_pnl': self.current_session.total_pnl,
            'closed_positions': total_closed,  # From portfolio_history
            'portfolio_snapshots': len(self.current_session.portfolio_history),
            'capital_available': self.current_session.capital_available,
            'capital_used': self.current_session.capital_used
        }
    
    def get_closed_positions(self) -> List[Dict[str, Any]]:
        """Get list of all closed positions from portfolio history."""
        if self.current_session is None:
            return []
        closed_trades = []
        for snapshot in self.current_session.portfolio_history.values():
            closed_trades.extend(snapshot.get('closed_positions', []))
        return closed_trades
    
    def export_session(self, export_path: str) -> bool:
        """Export the permanent session to an external JSON file."""
        if self.current_session is None:
            return False
        try:
            os.makedirs(os.path.dirname(export_path), exist_ok=True)
            with open(export_path, 'w') as f:
                json.dump(self.current_session.to_dict(), f, indent=2)
            logger.info(f"Session exported to {export_path}")
            return True
        except Exception as e:
            logger.error(f"Export failed: {e}")
            return False


# ----------------------------------------------------------------------
# Quick demonstration (run this file to test)
# ----------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile
    import shutil
    
    print("\n" + "="*80)
    print("PERMANENT STATE MANAGER - PERSISTENCE TEST")
    print("="*80)
    
    # Use a temporary directory for testing
    test_dir = tempfile.mkdtemp()
    
    try:
        # Simulate first run – create manager (new permanent session)
        print("\n--- FIRST RUN (creating session) ---")
        manager1 = StateManager(state_dir=test_dir)
        
        # Add some data
        pos = PositionState(
            symbol="NSE:RELIANCE-EQ",
            entry_price=2500,
            entry_time=datetime.now(pytz.timezone('Asia/Kolkata')).isoformat(),
            quantity=5,
            capital_used=12500,
            entry_signal="BUY",
            target_price=2650,
            stop_loss_price=2420
        )
        manager1.add_position(pos)
        manager1.update_session_metrics(capital_available=87500, capital_used=12500)
        
        print(f"Added position. Open positions: {len(manager1.get_all_positions())}")
        print(f"Capital available: {manager1.get_session_summary()['capital_available']}")
        
        # Now simulate program restart – create a new manager instance
        print("\n--- SECOND RUN (reloading session) ---")
        manager2 = StateManager(state_dir=test_dir)
        
        # Data should still be there
        print(f"Open positions after reload: {len(manager2.get_all_positions())}")
        pos2 = manager2.get_position("NSE:RELIANCE-EQ")
        if pos2:
            print(f"Position found: {pos2.symbol} @ {pos2.entry_price}")
        else:
            print("ERROR: Position lost!")
        
        summary = manager2.get_session_summary()
        print(f"Session summary: {summary}")
        
        print("\n✅ Permanent session works – data survives program restarts!")
        
    finally:
        shutil.rmtree(test_dir)
        print("\nTest directory cleaned up.")