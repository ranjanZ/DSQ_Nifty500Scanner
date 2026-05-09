# Live Trading System - User Guide

This guide explains the live trading system for running strategies during Indian market hours using Fyers broker.

## System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    LiveTrader (Main)                      │
│  - Orchestrates trading during market hours (9:15-15:20) │
│  - Manages strategy execution                             │
│  - Coordinates all components                             │
└──────────────────────┬──────────────────────────────────┘
         │
    ┌────┴────┬────────────┬────────────┬─────────────┐
    │          │            │            │             │
    v          v            v            v             v
┌────────┐ ┌────────┐ ┌────────┐ ┌───────────┐ ┌─────────┐
│ Broker │ │Strategy│ │ Orders │ │ Portfolio │ │ Realtime│
│(Fyers) │ │Manager │ │Manager │ │ Manager   │ │  Data   │
└────────┘ └────────┘ └────────┘ └───────────┘ └─────────┘
```

## Components

### 1. LiveTrader (live_trader.py)
Main trading engine that coordinates all components.

**Key Features:**
- Market hours monitoring (9:15 AM - 3:20 PM IST)
- Strategy signal generation
- Position management
- Exit signal handling (stop loss, target, trailing stop)
- Portfolio statistics
- Telegram notifications

**Usage:**
```python
from src.backtesting.live_trader import LiveTrader

# Initialize
trader = LiveTrader(config_path="config/live_trading_config.yaml")

# Start trading
trader.start_trading()
```

### 2. PortfolioManager (live_trader.py)
Manages open positions and portfolio metrics.

**Features:**
- Track active positions
- Calculate P&L
- Monitor capital allocation
- Generate portfolio statistics

**Usage:**
```python
from src.backtesting.live_trader import PortfolioManager, Position

portfolio = PortfolioManager(initial_capital=50000)

# Add position
position = Position(
    symbol="NSE:SBIN-EQ",
    entry_price=500,
    entry_time=datetime.now(),
    quantity=10,
    capital_used=5000,
    entry_signal="BUY",
    target_price=525,
    stop_loss_price=485
)
portfolio.add_position(position)

# Get stats
stats = portfolio.get_portfolio_stats()
```

### 3. OrderManager (order_manager.py)
Handles order creation, placement, modification, and tracking.

**Features:**
- Create market/limit/stop/stop-limit orders
- Place orders with broker
- Modify and cancel orders
- Track order status
- Update filled quantities and prices

**Usage:**
```python
from src.backtesting.order_manager import OrderManager

manager = OrderManager()

# Create order
order = manager.create_order(
    symbol="NSE:SBIN-EQ",
    side="BUY",
    quantity=10,
    order_type="LIMIT",
    price=500
)

# Place order
manager.place_order(order)

# Modify order
manager.modify_order(order.order_id, quantity=12, price=505)

# Cancel order
manager.cancel_order(order.order_id)
```

### 4. RealtimeDataHandler (realtime_data.py)
Streams real-time price data via WebSocket.

**Features:**
- Subscribe to symbols
- Handle WebSocket connections
- Stream price updates
- Mock mode for testing

**Usage:**
```python
from src.backtesting.realtime_data import RealtimeDataHandler

handler = RealtimeDataHandler(symbols=["NSE:SBIN-EQ", "NSE:INFY-EQ"])

# Register callbacks
def on_price_update(data):
    print(f"Price update: {data}")

handler.register_on_price_update(on_price_update)

# Connect
handler.connect()

# Get prices
price = handler.get_price("NSE:SBIN-EQ")
```

### 5. Strategy Integration
Uses existing strategy framework (RSI W-Pattern strategy).

**Features:**
- Generate buy/sell signals
- Calculate technical indicators
- Flexible parameter configuration

## Configuration

Edit `config/live_trading_config.yaml` to customize:

```yaml
live_trading:
  market_open: "09:15"      # Market open time (IST)
  market_close: "15:20"     # Market close time (IST)
  
  initial_capital: 50000    # Initial capital
  max_positions: 3          # Max open positions
  
  target_profit_pct: 0.05   # 5% profit target
  stop_loss_pct: 0.02       # 2% stop loss
  
  strategy_type: "RSI_W_Pattern"
  
  # Notifications
  enable_telegram: true
  telegram_chat_id: "YOUR_CHAT_ID"
  telegram_bot_token: "YOUR_BOT_TOKEN"
```

## Market Hours (Indian Market - NSE)

- **Open Time:** 9:15 AM IST
- **Close Time:** 3:20 PM IST (15:20)
- **Trading Days:** Monday - Friday
- **Excludes:** Weekends and market holidays

## Installation & Setup

### 1. Prerequisites

```bash
# Fyers broker account
# App ID and Client ID from Fyers
# API credentials (stored in src/utils/fyers/fyers_auth.py)
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Broker Credentials

Edit `src/utils/fyers/fyers_auth.py`:

```python
client_id = "YOUR_CLIENT_ID"
secret_key = "YOUR_SECRET_KEY"
fyers_id = "YOUR_FYERS_ID"
pin = "YOUR_PIN"
totp_token = "YOUR_TOTP_TOKEN"
```

### 4. Configure Live Trading

Edit `config/live_trading_config.yaml` with your parameters.

## Running the System

### Option 1: Direct Execution

```bash
cd /workspaces/DSQ_Nifty500Scanner

# Run live trading
python -m src.backtesting.live_trader

# Run tests
python -m src.backtesting.test_live_trading

# Run examples
python -m src.backtesting.live_examples
```

### Option 2: Using Python Script

```python
from src.backtesting.live_trader import LiveTrader

trader = LiveTrader()
trader.start_trading()
```

## Testing

### 1. Run Test Suite

```bash
python src/backtesting/test_live_trading.py
```

**Tests cover:**
- ✓ Portfolio management (add/close positions)
- ✓ Order management (create/place/modify/cancel)
- ✓ Real-time data streaming
- ✓ Market hours checking
- ✓ Signal generation
- ✓ Strategy integration

### 2. Run Examples

```bash
python src/backtesting/live_examples.py
```

**Examples include:**
1. Simple live trading
2. Real-time data streaming
3. Order management
4. Portfolio management
5. Market hours scheduling
6. Strategy integration

## Trading Flow

```
1. Market Opens (9:15 AM)
   └─> LiveTrader detects market open
   └─> Initializes strategy and data streams

2. Signal Scanning (Every 60 seconds)
   └─> Fetch historical data for symbols
   └─> Generate trading signals
   └─> Identify buy signals

3. Position Entry
   └─> Check if position slots available
   └─> Create Position object
   └─> Add to portfolio
   └─> Send buy order to Fyers

4. Monitor Positions (Continuous)
   └─> Check real-time prices
   └─> MonitorStop Loss levels
   └─> Monitor Target levels
   └─> Check trailing stops

5. Position Exit
   └─> Close position when exit condition met
   └─> Update portfolio
   └─> Record P&L

6. Market Closes (3:20 PM)
   └─> Generate portfolio report
   └─> Close all positions
   └─> Stop trading
```

## Position Management

### Buy Signal Generation
```python
trader.generate_trading_signals(symbols)
# Returns: {"symbol": {"signal": 1, "price": 500, "strength": 0.8}}
```

### Position Entry
```python
trader.place_buy_order(symbol, quantity, price, signal_info)
```

### Exit Signals
1. **Stop Loss Hit**: Price <= Entry Price × (1 - Stop Loss %)
2. **Target Hit**: Price >= Entry Price × (1 + Target %)
3. **Trailing Stop**: Price <= Highest Price × (1 - Trailing Stop %)

## Portfolio Tracking

Monitor your portfolio in real-time:

```python
stats = portfolio.get_portfolio_stats()

print(f"Total Capital: ${stats['total_value']}")
print(f"Open Positions: {stats['num_open_positions']}")
print(f"Closed P&L: ${stats['closed_pnl']}")
print(f"Return: {stats['total_return_pct']}%")
```

## Error Handling & Logging

All activity is logged to `logs/live_trading.log`:

```
2026-05-09 10:15:30 - LiveTrader - INFO - Market opened
2026-05-09 10:16:00 - LiveTrader - INFO - Signal found for NSE:SBIN-EQ: 1
2026-05-09 10:16:05 - LiveTrader - INFO - Added position: NSE:SBIN-EQ @500
```

## Safety Features

1. **Position Limits**: Maximum open positions enforcement
2. **Capital Limits**: Per-position capital allocation limits
3. **Stop Loss**: Automatic stop loss on all positions
4. **Market Hours**: Trading only during market hours
5. **Order Validation**: Order quantity and price validation

## Performance Monitoring

Monitor key metrics:

```python
# Portfolio P&L
stats['total_value']
stats['closed_pnl']
stats['total_return_pct']

# Position tracking
stats['num_open_positions']
stats['active_capital']
stats['available_capital']

# Order tracking
orders = manager.get_pending_orders()
filled_orders = manager.get_filled_orders()
```

## Notifications

### Telegram Alerts

Configure in `config/live_trading_config.yaml`:

```yaml
enable_telegram: true
telegram_chat_id: "YOUR_CHAT_ID"
telegram_bot_token: "YOUR_BOT_TOKEN"
```

Receives alerts for:
- Buy signals executed
- Sell signals executed
- Stop loss hits
- Target hits
- Errors

## Advanced Usage

### Custom Strategy

Create custom strategy class:

```python
from src.strategy.strategy_base import TradingStrategy

class CustomStrategy(TradingStrategy):
    def __init__(self, params=None):
        super().__init__(name="CustomStrategy", params=params)
    
    def generate_signals(self, data):
        # Your logic here
        data['signal'] = 0  # 0: hold, 1: buy, -1: sell
        return data
```

### Custom Orders

Create specialized orders:

```python
order = manager.create_order(
    symbol="NSE:SBIN-EQ",
    side="BUY",
    quantity=10,
    order_type="STOP_LIMIT",
    price=505,
    stop_price=495,
    metadata={"strategy": "Custom", "reason": "Breakout"}
)
```

## Troubleshooting

### Issue: Market Hours Not Detected

```python
from src.backtesting.live_trader import LiveTrader
trader = LiveTrader()

# Check current time
print(f"Current time: {datetime.now(trader.tz)}")
print(f"Market open: {trader.is_market_open()}")
```

### Issue: No Signals Generated

```python
# Check data retrieval
data = trader.get_historical_data("NSE:SBIN-EQ")
print(f"Data points: {len(data)}")

# Check strategy
signals = trader.strategy.generate_signals(data)
print(signals.tail())
```

### Issue: Orders Not Placed

```python
# Check portfolio capital
stats = portfolio.get_portfolio_stats()
print(f"Available capital: ${stats['available_capital']}")

# Check order validation
manager.print_orders_summary()
```

## Performance Optimization

1. **Data Caching**: Historical data is cached
2. **Interval-based Scanning**: Signal scan every 60 seconds
3. **Threading**: Background WebSocket connections
4. **Resource Management**: Proper cleanup and disconnection

## Security Notes

1. **Credentials**: Store securely in environment variables
2. **Authentication**: Fyers OAuth + TOTP
3. **Orders**: Validate before placement
4. **Logging**: Sensitive data is not logged

## Support & Documentation

- Fyers API: https://docs.fy.com/
- Strategy Base: See `src/strategy/strategy_base.py`
- Configuration: See `config/live_trading_config.yaml`
- Tests: See `src/backtesting/test_live_trading.py`

## Future Enhancements

- [ ] Multiple strategy support
- [ ] Advanced risk management
- [ ] AI-based signal generation
- [ ] Option trading support
- [ ] Algorithmic execution
- [ ] Live performance dashboard

---

**Last Updated:** May 9, 2026
**Version:** 1.0
**Maintained by:** DSQ Trading System
