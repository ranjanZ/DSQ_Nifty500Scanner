# Live Trading System - State Management Guide

Complete guide to the new live trading system with state management and broker synchronization.

## Overview

The new `src/live_trading` module provides:

- **State Management**: Save and recover trading state
- **Broker Synchronization**: Sync with broker to handle crashes and reconnections
- **Session Management**: Track multiple trading sessions
- **Position Tracking**: Persistent position states
- **Order Tracking**: Order lifecycle management
- **Recovery**: Automatic recovery from crashes

## Architecture

```
LiveTradingEngine (Main)
    ├── StateManager (State Persistence)
    ├── BrokerSync (Broker Synchronization)
    ├── Strategy (Signal Generation)
    ├── Fyers Broker (Order Execution)
    └── Logging (Full Audit Trail)
```

## Components

### 1. StateManager (`state_manager.py`)

Manages all persistent state for live trading.

**Key Features:**
- Session creation and loading
- Position state persistence
- Order state tracking
- Session metrics
- Multi-session management

**Usage:**

```python
from src.live_trading.state_manager import StateManager, PositionState, OrderState

# Initialize
manager = StateManager(state_dir="data/trading_state")

# Create new session
session = manager.create_new_session("session_1", initial_capital=50000)

# Add position
position = PositionState(
    symbol="NSE:SBIN-EQ",
    entry_price=500,
    entry_time=datetime.now(tz).isoformat(),
    quantity=10,
    capital_used=5000,
    entry_signal="BUY",
    target_price=525,
    stop_loss_price=485
)
manager.add_position(position)

# Save state
manager.save_session()

# Load session
session = manager.load_session("session_1")
```

**Data Structures:**

```python
@dataclass
class PositionState:
    symbol: str              # Trading symbol
    entry_price: float       # Entry price
    entry_time: str         # ISO format timestamp
    quantity: int           # Position quantity
    capital_used: float     # Capital allocated
    entry_signal: str       # Entry signal info
    target_price: float     # Profit target
    stop_loss_price: float  # Stop loss level
    highest_price: float    # Highest price reached
    status: str             # OPEN, CLOSED
    pnl: float             # Profit/Loss
    pnl_pct: float         # P&L percentage

@dataclass
class OrderState:
    order_id: str           # Unique order ID
    symbol: str             # Trading symbol
    side: str              # BUY or SELL
    quantity: int          # Order quantity
    order_type: str        # MARKET, LIMIT, STOP, STOP_LIMIT
    price: float           # Order price
    stop_price: float      # Stop price for stop orders
    status: str            # OPEN, FILLED, CANCELLED
    filled_quantity: int   # Filled quantity
    average_price: float   # Filled average price
    metadata: Dict         # Additional metadata
```

### 2. BrokerSync (`broker_sync.py`)

Synchronizes state with the broker.

**Key Features:**
- Position synchronization
- Order synchronization
- Conflict detection
- State reconciliation
- Full sync capability

**Usage:**

```python
from src.live_trading.broker_sync import BrokerSync

# Initialize
sync = BrokerSync(broker=broker_api, state_manager=state_manager)

# Full sync
result = sync.full_sync()

# Sync positions only
pos_success, pos_changes = sync.sync_positions()

# Sync orders only
ord_success, ord_changes = sync.sync_orders()

# Reconcile specific position
matches, message = sync.reconcile_position("NSE:SBIN-EQ")

# Get sync status
status = sync.get_sync_status()
```

**Sync Results:**

```python
{
    'positions': {
        'added': ['NSE:SYMBOL'],        # Found in broker, added to local
        'updated': ['NSE:SYMBOL'],      # Quantity/price mismatch fixed
        'removed': ['NSE:SYMBOL'],      # Found in local but not broker
        'conflicts': ['NSE:SYMBOL']     # Conflicts detected
    },
    'orders': {
        'filled': ['ORD_001'],          # Orders that got filled
        'cancelled': ['ORD_002'],       # Orders that were cancelled
        'pending': ['ORD_003'],         # Orders still pending
        'conflicts': ['ORD_004']        # Conflicts detected
    },
    'success': True
}
```

### 3. LiveTradingEngine (`engine.py`)

Main trading engine with state management.

**Key Features:**
- Market hours monitoring
- Strategy signal generation
- Position management
- Exit signal handling
- Automatic state recovery
- Periodic broker sync
- Complete audit logging

**Usage:**

```python
from src.live_trading.engine import LiveTradingEngine

# Initialize (recovers from previous session if available)
engine = LiveTradingEngine(
    config_path="config/live_trading_config.yaml",
    recover=True  # Enable recovery
)

# Start trading
engine.start()

# Or manually control:
engine.trading_active.set()
engine.run_trading_loop()
engine.stop()
```

**Recovery Flow:**

```
1. Engine starts
2. Checks for previous sessions
3. If found, loads last session
4. Syncs with broker
5. Reconciles any conflicts
6. Resumes trading
7. On shutdown, saves final state
```

## State Files

States are saved as JSON files in `data/trading_state/`:

```
data/trading_state/
├── session_20260509_100000_a1b2c3d4.json
├── session_20260509_110000_e5f6g7h8.json
└── session_20260509_120000_i9j0k1l2.json
```

**File Format:**

```json
{
  "session_id": "session_20260509_100000_a1b2c3d4",
  "start_time": "2026-05-09T10:00:00+05:30",
  "positions": {
    "NSE:SBIN-EQ": {
      "symbol": "NSE:SBIN-EQ",
      "entry_price": 500,
      "entry_time": "2026-05-09T10:15:00+05:30",
      "quantity": 10,
      "capital_used": 5000,
      "entry_signal": "...",
      "target_price": 525,
      "stop_loss_price": 485,
      "highest_price": 505,
      "status": "OPEN",
      "pnl": 50,
      "pnl_pct": 1.0
    }
  },
  "orders": {
    "ORD_1001": {
      "order_id": "ORD_1001",
      "symbol": "NSE:SBIN-EQ",
      "side": "BUY",
      "quantity": 10,
      "order_type": "LIMIT",
      "price": 500,
      "status": "FILLED",
      "filled_quantity": 10,
      "average_price": 502
    }
  },
  "total_pnl": 50,
  "closed_positions_count": 1,
  "capital_available": 45000,
  "capital_used": 5000
}
```

## Configuration

Edit `config/live_trading_config.yaml`:

```yaml
live_trading:
  market_open: "09:15"
  market_close: "15:20"
  timezone: "Asia/Kolkata"
  initial_capital: 50000
  max_positions: 3
  max_position_size: 5000
  target_profit_pct: 0.05
  stop_loss_pct: 0.02
  trailing_stop_pct: 0.01
  data_refresh_interval: 60      # Scan every 60s
  strategy_type: "RSI_W_Pattern"
```

## Running the System

### Start Live Trading Engine

```bash
cd /workspaces/DSQ_Nifty500Scanner

# Simple run (recovers from last session)
python -m src.live_trading.engine

# Or use custom config
python -c "
from src.live_trading.engine import LiveTradingEngine
engine = LiveTradingEngine('config/live_trading_config.yaml')
engine.start()
"
```

### Run Tests

```bash
# Run comprehensive test suite
python -m src.live_trading.test_state_management

# Or specific tests
python -c "
from src.live_trading.test_state_management import test_state_manager
test_state_manager()
"
```

### Programmatic Usage

```python
from src.live_trading import LiveTradingEngine, StateManager

# Initialize
engine = LiveTradingEngine(recover=True)

# Check recovery
print(f"Session: {engine.session_id}")
print(f"Positions: {len(engine.state_manager.get_all_positions())}")

# Start
engine.start()

# Graceful shutdown
engine.stop()
```

## Recovery Scenarios

### Scenario 1: Simple Disconnect

```
1. Connection lost
2. Engine detects and logs
3. Attempts reconnection
4. On next start: loads saved session
5. Syncs with broker
6. Resumes trading
```

### Scenario 2: Process Crash

```
1. Process crashes unexpectedly
2. State was last saved (before crash)
3. On restart: loads last session
4. Reconciles with broker
5. Detects any trades executed while down
6. Updates local state
7. Continues trading
```

### Scenario 3: Broker Disconnection

```
1. Broker API down
2. Engine waits and retries
3. On reconnection: full sync
4. Detects any missing positions/orders
5. Updates state
6. Continues
```

### Scenario 4: Network Issues

```
1. Order sent but no confirmation received
2. State saved with order as "PENDING"
3. On sync: check broker order status
4. Update local state accordingly
5. No duplicate orders sent
```

## Monitoring

### Check Session Status

```python
from src.live_trading.state_manager import StateManager

manager = StateManager()
manager.load_session("session_20260509_100000_a1b2c3d4")

summary = manager.get_session_summary()
print(f"Open positions: {summary['open_positions']}")
print(f"Total P&L: ${summary['total_pnl']:.2f}")
```

### Check Sync Status

```python
from src.live_trading.broker_sync import BrokerSync

sync.get_sync_status()
# Returns:
# {
#   'local_positions': 3,
#   'broker_positions': 3,
#   'synced': True
# }
```

### View Trading Log

```bash
tail -f logs/live_trading_20260509_100000.log
```

## Best Practices

1. **Regular Syncs**: Engine syncs every 5 minutes automatically
2. **State Saves**: State saved on every position/order change
3. **Recovery**: Always enables recovery to prevent loss of state
4. **Monitoring**: Check logs for warnings/errors
5. **Testing**: Run tests before live trading
6. **Backups**: Backup `data/trading_state` directory

## Troubleshooting

### Issue: State not recovering

```python
# List available sessions
from src.live_trading.state_manager import StateManager
manager = StateManager()
sessions = manager.list_sessions()
print(sessions)

# Manually load specific session
session = manager.load_session(sessions[-1])
```

### Issue: Broker out of sync

```python
# Force full sync
sync = BrokerSync(broker=engine.broker, state_manager=engine.state_manager)
result = sync.full_sync()
print(result)

# Check reconciliation
matches, msg = sync.reconcile_position("NSE:SBIN-EQ")
print(f"Reconciled: {matches}, Message: {msg}")
```

### Issue: Position not closed

```python
# Check position status
pos = engine.state_manager.get_position("NSE:SBIN-EQ")
print(f"Status: {pos.status}")
print(f"P&L: {pos.pnl}")

# Manually close if needed
engine.close_position("NSE:SBIN-EQ", current_price, "MANUAL")
```

## Performance Considerations

- **State File Size**: ~1KB per position/order
- **Save Latency**: <10ms per save
- **Sync Time**: ~1-2 seconds for full sync
- **Memory**: Uses minimal memory (state loaded on demand)

## Security

- **Credentials**: Stored separately in `fyers_auth.py`
- **State Files**: JSON (plaintext) - consider encrypting sensitive data
- **Logging**: Full audit trail in logs
- **Recovery**: Only restores from local state files

## Future Enhancements

- [ ] Encrypted state storage
- [ ] Database backend (PostgreSQL)
- [ ] Real-time state synchronization
- [ ] Advanced conflict resolution
- [ ] State versioning
- [ ] Distributed state management

---

**Last Updated:** May 9, 2026
**Version:** 1.0
