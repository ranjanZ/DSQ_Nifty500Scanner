# Live Trading System - Troubleshooting & FAQ

## Common Issues & Solutions

### ❌ Engine won't start

**Issue:** `ModuleNotFoundError: No module named 'src.live_trading'`

**Solutions:**
```bash
# Make sure you're in correct directory
cd /workspaces/DSQ_Nifty500Scanner

# Install requirements
pip install -r requirements.txt

# Run using absolute import
python -m src.live_trading.engine

# Or with Python path
export PYTHONPATH="${PYTHONPATH}:/workspaces/DSQ_Nifty500Scanner"
python src/live_trading/engine.py
```

---

### ❌ No previous session found

**Issue:** "No previous sessions found, creating new session"

**Solutions:**
```python
from src.live_trading.state_manager import StateManager

# Check if state directory exists
manager = StateManager()

# List all sessions
sessions = manager.list_sessions()
print(f"Found sessions: {sessions}")

# Check state directory
import os
os.listdir("data/trading_state")
```

**Note:** This is normal on first run. State files are created during trading.

---

### ❌ Broker authentication fails

**Issue:** `Error: Invalid credentials` or `Authentication failed`

**Solutions:**
1. **Verify Credentials**
   ```python
   # Check fyers_auth.py
   from src.utils.fyers.fyers_auth import client_id, access_token
   print(f"Client ID: {client_id}")
   print(f"Access Token: {access_token[:20]}...")  # Show first 20 chars
   ```

2. **Update Fyers Credentials**
   Edit `src/utils/fyers/fyers_auth.py`:
   ```python
   client_id = "YOUR_CLIENT_ID"
   secret_key = "YOUR_SECRET_KEY"
   fyers_id = "YOUR_FYERS_ID"
   pin = "YOUR_PIN"
   totp_token = "YOUR_TOTP_TOKEN"
   ```

3. **Reset Token**
   Delete cached token and rerun:
   ```bash
   rm -rf logs/  # Clear old logs
   python -m src.live_trading.engine
   ```

---

### ❌ No signals being generated

**Issue:** "Scanning for signals... no signals detected"

**Solutions:**

1. **Check Data Retrieval**
   ```python
   from src.live_trading.engine import LiveTradingEngine
   
   engine = LiveTradingEngine()
   data = engine.get_historical_data("NSE:SBIN-EQ", days_back=30)
   
   if data is None:
       print("No data retrieved")
   else:
       print(f"Retrieved {len(data)} candles")
   ```

2. **Check Strategy**
   ```python
   import pandas as pd
   import numpy as np
   
   # Create test data
   dates = pd.date_range(start='2026-01-01', periods=100, freq='1H')
   close = np.random.randn(100).cumsum() + 100
   
   data = pd.DataFrame({
       'open': close,
       'high': close + np.abs(np.random.randn(100)),
       'low': close - np.abs(np.random.randn(100)),
       'close': close,
       'volume': np.random.randint(1000, 10000, 100)
   })
   
   # Test strategy
   signals = engine.strategy.generate_signals(data)
   print(signals.tail())
   ```

3. **Check Symbol List**
   ```python
   # Verify symbols are valid
   symbols = ["NSE:SBIN-EQ", "NSE:INFY-EQ", "NSE:ITC-EQ"]
   
   for symbol in symbols:
       data = engine.get_historical_data(symbol)
       if data is None:
           print(f"No data for {symbol}")
       else:
           print(f"✓ {symbol}: {len(data)} candles")
   ```

---

### ❌ Positions not syncing with broker

**Issue:** "Position found in local state but not in broker"

**Solutions:**

1. **Manual Sync**
   ```python
   from src.live_trading.engine import LiveTradingEngine
   
   engine = LiveTradingEngine()
   
   # Force sync
   result = engine.broker_sync.full_sync()
   print(f"Sync result: {result}")
   ```

2. **Check Sync Status**
   ```python
   status = engine.broker_sync.get_sync_status()
   
   print(f"Local positions: {status['local_positions']}")
   print(f"Broker positions: {status['broker_positions']}")
   print(f"Synced: {status['synced']}")
   ```

3. **Reconcile Specific Position**
   ```python
   matches, msg = engine.broker_sync.reconcile_position("NSE:SBIN-EQ")
   print(f"Reconciled: {matches}")
   print(f"Message: {msg}")
   ```

---

### ❌ Orders not executing

**Issue:** "Order placed but not executed" or "Order status remains PENDING"

**Solutions:**

1. **Check Order Status**
   ```python
   orders = engine.state_manager.get_all_orders()
   
   for order_id, order in orders.items():
       print(f"{order_id}: {order.status}")
       print(f"  Symbol: {order.symbol}")
       print(f"  Quantity: {order.quantity} @ {order.price}")
       print(f"  Filled: {order.filled_quantity}")
   ```

2. **Check Order History**
   ```python
   # Get recent orders
   orders = engine.broker_sync.get_broker_orders()
   
   for order_id, order in orders.items():
       print(f"{order_id}: {order.get('status')} - {order.get('message', '')}")
   ```

3. **Retry Order**
   ```python
   # If order not filled after some time
   order_id = "ORD_001"
   
   order = engine.state_manager.get_order(order_id)
   if order and order.status != "FILLED":
       # Cancel and retry
       engine.broker_sync.broker.cancel_order(order_id)
       # Place new order
       engine.place_buy_order(order.symbol, ...)
   ```

---

### ❌ State not recovering after crash

**Issue:** Lost positions after process crash

**Solutions:**

1. **Check State Files Exist**
   ```bash
   ls -la data/trading_state/
   ```

2. **Manually Load Session**
   ```python
   from src.live_trading.state_manager import StateManager
   
   manager = StateManager()
   sessions = manager.list_sessions()
   
   print(f"Sessions: {sessions}")
   
   # Load latest
   if sessions:
       session = manager.load_session(sessions[-1])
       print(f"Positions: {len(session.positions)}")
   ```

3. **Export & Backup Session**
   ```python
   manager.export_session("session_id", "backup/session_export.json")
   
   print("Session exported to backup/session_export.json")
   ```

---

### ❌ Market hours detection not working

**Issue:** "Not trading outside market hours" when it's market time

**Solutions:**

1. **Check Market Hours**
   ```python
   from src.live_trading.engine import LiveTradingEngine
   from datetime import datetime
   
   engine = LiveTradingEngine()
   
   now = datetime.now(engine.tz)
   is_open = engine.is_market_open()
   
   print(f"Current time: {now.strftime('%H:%M:%S')}")
   print(f"Market open: {is_open}")
   print(f"Market hours: {engine.trading_config['market_open']} - {engine.trading_config['market_close']}")
   ```

2. **Check Timezone**
   ```python
   import pytz
   from datetime import datetime
   
   # Verify IST
   tz = pytz.timezone('Asia/Kolkata')
   now = datetime.now(tz)
   
   print(f"IST Time: {now}")
   print(f"UTC Time: {datetime.utcnow()}")
   ```

3. **Check Config**
   ```yaml
   # In config/live_trading_config.yaml
   live_trading:
     market_open: "09:15"      # 09:15 AM IST
     market_close: "15:20"     # 3:20 PM IST (15:20 in 24h format)
     timezone: "Asia/Kolkata"
   ```

---

### ❌ High memory usage

**Issue:** Engine using too much memory

**Solutions:**

```python
# Monitor memory
import psutil
import os

pid = os.getpid()
process = psutil.Process(pid)
memory = process.memory_info().rss / 1024 / 1024  # MB

print(f"Memory usage: {memory:.2f} MB")
```

**Optimization:**
- Maximum state data in memory: ~1MB for 100 positions
- Logs are written to disk (not held in memory)
- State is loaded on demand

---

### ❌ Performance degradation over time

**Issue:** Engine slowing down after hours of trading

**Solutions:**

1. **Check Logs**
   ```bash
   # Check for errors
   grep "ERROR\|WARNING" logs/live_trading_*.log
   
   # Check file size
   ls -lh logs/live_trading_*.log
   ```

2. **Restart Engine**
   ```bash
   # Stop current engine (Ctrl+C)
   
   # Restart (will recover from state)
   python -m src.live_trading.engine
   ```

3. **Clean Old Logs**
   ```bash
   # Keep only recent logs
   ls -t logs/live_trading_*.log | tail -n +6 | xargs rm
   ```

---

## Frequently Asked Questions (FAQ)

### Q1: How do I run the system?

**A:**
```bash
# Interactive menu
python quick_start.py

# Direct start
python -m src.live_trading.engine

# With Python script
python -c "
from src.live_trading.engine import LiveTradingEngine
engine = LiveTradingEngine(recover=True)
engine.start()
"
```

---

### Q2: Will I lose trades if the process crashes?

**A:** No! The system:
1. Saves state to disk on every change
2. Automatically recovers on restart
3. Syncs with broker to verify positions
4. Updates state with any trades executed
5. Never duplicates trades

---

### Q3: How do I stop trading?

**A:**
```bash
# Press Ctrl+C to stop gracefully

# The engine will:
# 1. Perform final broker sync
# 2. Save final state
# 3. Print summary
# 4. Exit cleanly
```

---

### Q4: How do I check my profit/loss?

**A:**
```python
from src.live_trading.state_manager import StateManager

manager = StateManager()
sessions = manager.list_sessions()

# Load latest session
session = manager.load_session(sessions[-1])

# Check metrics
summary = manager.get_session_summary()

print(f"Total P&L: ${summary['total_pnl']}")
print(f"Return: {(summary['total_pnl'] / summary['capital_used']) * 100:.2f}%")
```

---

### Q5: Can I run multiple strategies simultaneously?

**A:** Not in the current implementation, but you can:
1. Run multiple engine instances with different configs
2. Each would trade different symbols or use different strategies
3. Each would maintain separate state files

```bash
# Terminal 1 - Strategy 1
python -c "
from src.live_trading.engine import LiveTradingEngine
engine1 = LiveTradingEngine(session_id='strategy1')
engine1.start()
"

# Terminal 2 - Strategy 2
python -c "
from src.live_trading.engine import LiveTradingEngine
engine2 = LiveTradingEngine(session_id='strategy2')
engine2.start()
"
```

---

### Q6: How do I customize the strategy?

**A:**
```python
from src.strategy.strategy_base import TradingStrategy

class MyStrategy(TradingStrategy):
    def __init__(self, params=None):
        super().__init__(name="MyStrategy", params=params)
    
    def generate_signals(self, data):
        # Your signal logic
        data['signal'] = 0  # 0: hold, 1: buy, -1: sell
        return data

# Use in engine
engine.strategy = MyStrategy()
```

---

### Q7: Can I use a different broker?

**A:** Yes, but you'll need to:
1. Create a new broker adapter class
2. Implement order placement/cancellation
3. Implement position tracking
4. Update broker sync logic

The state management is broker-agnostic.

---

### Q8: How do I export my trading data?

**A:**
```python
from src.live_trading.state_manager import StateManager

manager = StateManager()
manager.export_session("session_id", "exports/session.json")

# Or create custom export
import json

session = manager.load_session("session_id")
export = {
    'positions': [p.to_dict() for p in session.positions.values()],
    'orders': [o.to_dict() for o in session.orders.values()],
    'metrics': manager.get_session_summary()
}

with open("export.json", "w") as f:
    json.dump(export, f, indent=2)
```

---

### Q9: What happens if the broker API is down?

**A:** The engine will:
1. Detect connection error
2. Log the error
3. Retry automatically
4. On reconnection, perform full sync
5. Resume trading

---

### Q10: Is my data secure?

**A:** State files are stored as JSON files in `data/trading_state/`. 

**Security considerations:**
- Credentials stored separately in `src/utils/fyers/fyers_auth.py`
- Sensitive data not logged
- Consider encrypting state files in production
- Keep state directory protected with appropriate file permissions

```bash
# Secure the state directory
chmod 700 data/trading_state/
chmod 700 logs/
```

---

## Performance Tuning

### Reduce Log Verbosity

```python
# In engine.py
logger.setLevel(logging.WARNING)  # Show only warnings and errors
```

### Increase Scan Interval

```yaml
# In config/live_trading_config.yaml
data_refresh_interval: 120  # Scan every 2 minutes instead of 1
```

### Reduce Position Tracking

```yaml
max_positions: 1  # Trade only 1 position at a time
```

---

## Debug Mode

Enable debug output:

```python
from src.live_trading.engine import LiveTradingEngine
import logging

# Enable debug logging
logging.getLogger().setLevel(logging.DEBUG)

# Start engine
engine = LiveTradingEngine()
engine.start()
```

---

## Getting Help

1. **Check Logs**
   ```bash
   tail -f logs/live_trading_*.log
   ```

2. **Review Documentation**
   - LIVE_TRADING_README.md
   - STATE_MANAGEMENT_GUIDE.md
   - LIVE_TRADING_GUIDE.md

3. **Run Tests**
   ```bash
   python -m src.live_trading.test_state_management
   ```

4. **Check State**
   ```python
   from src.live_trading.state_manager import StateManager
   manager = StateManager()
   sessions = manager.list_sessions()
   ```

5. **Run Interactive Menu**
   ```bash
   python quick_start.py
   ```

---

**Last Updated:** May 9, 2026
**Version:** 1.0
