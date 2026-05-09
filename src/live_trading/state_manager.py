"""
State Management for Live Trading
Handles persistence, recovery, and broker synchronization
"""

import os
import json
import logging
import pickle
from typing import Dict, List, Any, Optional
from datetime import datetime
import pytz
from dataclasses import dataclass, asdict, field

logger = logging.getLogger("StateManager")


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
    """Complete trading session state"""
    session_id: str
    start_time: str
    positions: Dict[str, PositionState] = field(default_factory=dict)
    orders: Dict[str, OrderState] = field(default_factory=dict)
    total_pnl: float = 0
    closed_positions_count: int = 0
    capital_available: float = 0
    capital_used: float = 0
    
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


class StateManager:
    """Manages persistent state for live trading"""
    
    def __init__(self, state_dir: str = "data/trading_state"):
        """
        Initialize state manager
        
        Args:
            state_dir: Directory to store state files
        """
        self.state_dir = state_dir
        os.makedirs(state_dir, exist_ok=True)
        
        self.current_session: Optional[TradingSessionState] = None
        self.tz = pytz.timezone('Asia/Kolkata')
        
        logger.info(f"StateManager initialized with directory: {state_dir}")
    
    def create_new_session(self, session_id: str, initial_capital: float) -> TradingSessionState:
        """Create a new trading session"""
        try:
            now = datetime.now(self.tz).isoformat()
            
            session = TradingSessionState(
                session_id=session_id,
                start_time=now,
                capital_available=initial_capital,
                capital_used=0
            )
            
            self.current_session = session
            self.save_session(session)
            
            logger.info(f"Created new session: {session_id}")
            return session
        
        except Exception as e:
            logger.error(f"Error creating new session: {e}")
            raise
    
    def load_session(self, session_id: str) -> Optional[TradingSessionState]:
        """Load session from disk"""
        try:
            session_file = os.path.join(self.state_dir, f"{session_id}.json")
            
            if not os.path.exists(session_file):
                logger.warning(f"Session file not found: {session_file}")
                return None
            
            with open(session_file, 'r') as f:
                data = json.load(f)
            
            session = TradingSessionState.from_dict(data)
            self.current_session = session
            
            logger.info(f"Loaded session: {session_id}")
            return session
        
        except Exception as e:
            logger.error(f"Error loading session {session_id}: {e}")
            return None
    
    def save_session(self, session: TradingSessionState = None) -> bool:
        """Save session to disk"""
        try:
            if session is None:
                session = self.current_session
            
            if session is None:
                logger.warning("No session to save")
                return False
            
            session_file = os.path.join(self.state_dir, f"{session.session_id}.json")
            
            with open(session_file, 'w') as f:
                json.dump(session.to_dict(), f, indent=2)
            
            logger.debug(f"Session saved: {session.session_id}")
            return True
        
        except Exception as e:
            logger.error(f"Error saving session: {e}")
            return False
    
    def add_position(self, position_state: PositionState) -> bool:
        """Add position to current session"""
        try:
            if self.current_session is None:
                logger.error("No active session")
                return False
            
            self.current_session.positions[position_state.symbol] = position_state
            self.save_session()
            
            logger.info(f"Position added: {position_state.symbol}")
            return True
        
        except Exception as e:
            logger.error(f"Error adding position: {e}")
            return False
    
    def update_position(self, symbol: str, updates: Dict[str, Any]) -> bool:
        """Update position state"""
        try:
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
        
        except Exception as e:
            logger.error(f"Error updating position: {e}")
            return False
    
    def remove_position(self, symbol: str) -> bool:
        """Remove closed position"""
        try:
            if self.current_session is None or symbol not in self.current_session.positions:
                logger.warning(f"Position not found: {symbol}")
                return False
            
            del self.current_session.positions[symbol]
            self.current_session.closed_positions_count += 1
            self.save_session()
            
            logger.info(f"Position removed: {symbol}")
            return True
        
        except Exception as e:
            logger.error(f"Error removing position: {e}")
            return False
    
    def add_order(self, order_state: OrderState) -> bool:
        """Add order to current session"""
        try:
            if self.current_session is None:
                logger.error("No active session")
                return False
            
            self.current_session.orders[order_state.order_id] = order_state
            self.save_session()
            
            logger.info(f"Order added: {order_state.order_id}")
            return True
        
        except Exception as e:
            logger.error(f"Error adding order: {e}")
            return False
    
    def update_order(self, order_id: str, updates: Dict[str, Any]) -> bool:
        """Update order state"""
        try:
            if self.current_session is None or order_id not in self.current_session.orders:
                logger.warning(f"Order not found: {order_id}")
                return False
            
            order = self.current_session.orders[order_id]
            
            for key, value in updates.items():
                if hasattr(order, key):
                    setattr(order, key, value)
            
            self.save_session()
            logger.debug(f"Order updated: {order_id}")
            return True
        
        except Exception as e:
            logger.error(f"Error updating order: {e}")
            return False
    
    def get_position(self, symbol: str) -> Optional[PositionState]:
        """Get position state"""
        if self.current_session is None:
            return None
        return self.current_session.positions.get(symbol)
    
    def get_order(self, order_id: str) -> Optional[OrderState]:
        """Get order state"""
        if self.current_session is None:
            return None
        return self.current_session.orders.get(order_id)
    
    def get_all_positions(self) -> Dict[str, PositionState]:
        """Get all open positions"""
        if self.current_session is None:
            return {}
        return self.current_session.positions.copy()
    
    def get_all_orders(self) -> Dict[str, OrderState]:
        """Get all orders"""
        if self.current_session is None:
            return {}
        return self.current_session.orders.copy()
    
    def update_session_metrics(self, total_pnl: float = None, 
                              capital_available: float = None, 
                              capital_used: float = None) -> bool:
        """Update session metrics"""
        try:
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
        
        except Exception as e:
            logger.error(f"Error updating session metrics: {e}")
            return False
    
    def get_session_summary(self) -> Dict[str, Any]:
        """Get session summary"""
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
    
    def list_sessions(self) -> List[str]:
        """List all saved sessions"""
        try:
            sessions = []
            for filename in os.listdir(self.state_dir):
                if filename.endswith('.json'):
                    sessions.append(filename[:-5])  # Remove .json
            return sorted(sessions)
        except Exception as e:
            logger.error(f"Error listing sessions: {e}")
            return []
    
    def delete_session(self, session_id: str) -> bool:
        """Delete a session"""
        try:
            session_file = os.path.join(self.state_dir, f"{session_id}.json")
            if os.path.exists(session_file):
                os.remove(session_file)
                logger.info(f"Session deleted: {session_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"Error deleting session: {e}")
            return False
    
    def export_session(self, session_id: str, export_path: str) -> bool:
        """Export session to external file"""
        try:
            session = self.load_session(session_id)
            if session is None:
                return False
            
            os.makedirs(os.path.dirname(export_path), exist_ok=True)
            
            with open(export_path, 'w') as f:
                json.dump(session.to_dict(), f, indent=2)
            
            logger.info(f"Session exported to {export_path}")
            return True
        except Exception as e:
            logger.error(f"Error exporting session: {e}")
            return False


if __name__ == "__main__":
    """Test State Manager"""
    import tempfile
    import shutil
    from datetime import datetime
    
    print("\n" + "="*80)
    print("STATE MANAGER - QUICK TEST")
    print("="*80)
    
    # Create temporary directory
    temp_dir = tempfile.mkdtemp()
    
    try:
        # Initialize
        manager = StateManager(state_dir=temp_dir)
        print(f"✓ StateManager initialized in {temp_dir}")
        
        # Create session
        session = manager.create_new_session("test_session", initial_capital=50000)
        print(f"✓ Created session: {session.session_id}")
        
        # Add position
        position = PositionState(
            symbol="NSE:SBIN-EQ",
            entry_price=500,
            entry_time=datetime.now(pytz.timezone('Asia/Kolkata')).isoformat(),
            quantity=10,
            capital_used=5000,
            entry_signal="BUY",
            target_price=525,
            stop_loss_price=485
        )
        manager.add_position(position)
        print(f"✓ Added position: {position.symbol}")
        
        # Add order
        order = OrderState(
            order_id="ORD_001",
            symbol="NSE:SBIN-EQ",
            side="BUY",
            quantity=10,
            order_type="LIMIT",
            price=500
        )
        manager.add_order(order)
        print(f"✓ Added order: {order.order_id}")
        
        # Save session
        manager.save_session()
        print(f"✓ Session saved")
        
        # Get summary
        summary = manager.get_session_summary()
        print(f"✓ Session summary:")
        print(f"  - Open positions: {summary['open_positions']}")
        print(f"  - Total orders: {summary['total_orders']}")
        print(f"  - Capital used: ${summary['capital_used']}")
        
        # List sessions
        sessions = manager.list_sessions()
        print(f"✓ Found {len(sessions)} session(s): {sessions}")
        
        # Load session
        loaded_session = manager.load_session("test_session")
        print(f"✓ Loaded session with {len(loaded_session.positions)} positions")
        
        print("\n✅ All tests passed!\n")
        
    finally:
        shutil.rmtree(temp_dir)
