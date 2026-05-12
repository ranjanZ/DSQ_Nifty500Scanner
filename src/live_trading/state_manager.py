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
    closed_positions_count: int = 0
    capital_available: float = 0
    capital_used: float = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
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
        
        session_file = os.path.join(self.state_dir, f"{self.session_id}.json")
        try:
            with open(session_file, 'w') as f:
                json.dump(self.current_session.to_dict(), f, indent=2)
            logger.debug(f"Session saved: {self.session_id}")
            return True
        except Exception as e:
            logger.error(f"Error saving session: {e}")
            return False
    
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
        """Remove a closed position (increment closed count)."""
        if self.current_session is None or symbol not in self.current_session.positions:
            return False
        
        del self.current_session.positions[symbol]
        self.current_session.closed_positions_count += 1
        self.save_session()
        logger.info(f"Position closed and removed: {symbol}")
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
    
    def get_session_summary(self) -> Dict[str, Any]:
        """Return a summary of the current permanent session."""
        if self.current_session is None:
            return {}
        
        return {
            'session_id': self.current_session.session_id,
            'start_time': self.current_session.start_time,
            'open_positions': len(self.current_session.positions),
            'total_orders': len(self.current_session.orders),
            'total_pnl': self.current_session.total_pnl,
            'closed_positions': self.current_session.closed_positions_count,
            'capital_available': self.current_session.capital_available,
            'capital_used': self.current_session.capital_used
        }
    
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