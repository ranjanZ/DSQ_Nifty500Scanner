# Trading System Architecture

## New Service-Based Structure

This repository has been restructured into a modular, service-based architecture for better maintainability, scalability, and ease of navigation.

## 📁 Directory Structure

```
/workspace/
├── config/
│   ├── services/
│   │   └── main_config.yaml      # Centralized configuration for all services
│   ├── backtest_config.yaml
│   ├── live_trading_config.yaml
│   ├── optimization_config.yaml
│   └── stock_list.yaml
├── src/
│   ├── broker_service/            # 1. Broker Service
│   │   ├── broker_base.py         # Abstract base class + Factory
│   │   ├── fyers/
│   │   │   └── fyers_broker_impl.py
│   │   └── zerodha/
│   │       └── zerodha_broker_impl.py (placeholder)
│   │
│   ├── data_service/              # 2. Data Service
│   │   └── data_service.py        # Unified data access layer
│   │
│   ├── backtesting_service/       # 3. Backtesting Service
│   │   ├── backtest_service.py    # Main backtest engine
│   │   └── optimization_service.py # Parameter optimization
│   │
│   ├── live_trading_service/      # 4. Live Trading Service
│   │   └── live_trading_service.py # Real-time trading execution
│   │
│   ├── strategy_service/          # 5. Strategy Service
│   │   ├── strategy_base.py       # Base strategy class
│   │   ├── strategy_service.py    # Strategy management
│   │   └── madam_strategy.py      # Support/Resistance strategy
│   │
│   └── agent_service/             # 6. Agent Service (Telegram)
│       └── agent_service.py       # Bot integration & notifications
│
├── .env.example                    # Environment variables template
└── requirements.txt
```

## 🔧 Services Overview

### 1. Broker Service (`src/broker_service/`)
- **Purpose**: Unified interface for multiple brokers
- **Features**:
  - Abstract base class (`BrokerBase`) with common interface
  - Factory pattern for easy broker switching
  - Currently supports: Fyers (implemented), Zerodha (placeholder)
  - Easy to add new brokers

**Usage**:
```python
from src.broker_service.broker_base import BrokerFactory

# Create broker instance
broker = BrokerFactory.create_broker("fyers")
broker.connect()

# Place order
order_id = broker.place_order(symbol="NSE:RELIANCE-EQ", qty=10, side="BUY")
```

**Test**: `python -m src.broker_service.broker_base test`

---

### 2. Data Service (`src/data_service/`)
- **Purpose**: Centralized data access layer
- **Features**:
  - Unified interface for historical and real-time data
  - Supports multiple data sources (broker, database)
  - Caching support
  - Data normalization

**Usage**:
```python
from src.data_service.data_service import DataService

service = DataService()
df = service.get_historical_data("RELIANCE", "2024-01-01", "2024-12-31")
```

**Test**: `python -m src.data_service.data_service test`

---

### 3. Backtesting Service (`src/backtesting_service/`)
- **Purpose**: Run backtests on historical data
- **Features**:
  - Strategy performance evaluation
  - Multiple metrics (Sharpe ratio, max drawdown, etc.)
  - Integration with optimization service

**Sub-module: Optimization Service**
- Grid search optimization
- Bayesian optimization
- Parameter tuning

**Usage**:
```python
from src.backtesting_service.backtest_service import BacktestService

service = BacktestService()
results = service.run_backtest(
    strategy_name="SupportResistance",
    symbols=["RELIANCE", "TCS"],
    start_date="2024-01-01",
    end_date="2024-12-31"
)
```

**Test**: 
- `python -m src.backtesting_service.backtest_service test`
- `python -m src.backtesting_service.optimization_service test`

---

### 4. Live Trading Service (`src/live_trading_service/`)
- **Purpose**: Execute trades in real-time
- **Features**:
  - Market hours detection
  - Position management
  - Order execution via broker service
  - Risk management (target, stop loss)

**Usage**:
```python
from src.live_trading_service.live_trading_service import LiveTradingService
from src.broker_service.broker_base import BrokerFactory

broker = BrokerFactory.create_broker("fyers")
service = LiveTradingService(broker=broker)
service.initialize()
service.start_trading()
```

**Test**: `python -m src.live_trading_service.live_trading_service test`

---

### 5. Strategy Service (`src/strategy_service/`)
- **Purpose**: Manage and execute trading strategies
- **Features**:
  - Strategy registration and selection
  - Signal generation
  - Multiple strategy support
  - Integration with backtest and live trading

**Available Strategies**:
- SupportResistance (Madam Strategy)
- MA Crossover
- RSI-based strategies

**Usage**:
```python
from src.strategy_service.strategy_service import StrategyService
from src.strategy_service.madam_strategy import SupportResistanceStrategy

service = StrategyService()
strategy = SupportResistanceStrategy()
service.register_strategy("SupportResistance", strategy)
service.set_active_strategy("SupportResistance")
signals = service.generate_signals(data)
```

**Test**: `python -m src.strategy_service.strategy_service test`

---

### 6. Agent Service (`src/agent_service/`)
- **Purpose**: Telegram bot for notifications and control
- **Features**:
  - Trade alerts
  - P&L updates
  - Status commands
  - Interactive controls

**Commands**:
- `/start` - Start the bot
- `/status` - Get trading status
- `/positions` - View open positions
- `/pnl` - View P&L summary
- `/help` - Show help

**Usage**:
```python
from src.agent_service.agent_service import AgentService

agent = AgentService()
agent.initialize()
agent.send_trade_alert("BUY", "RELIANCE", 10, 2500.00)
agent.start_polling()
```

**Test**: `python -m src.agent_service.agent_service test`

---

## ⚙️ Configuration

All services are configured via YAML files:

### Main Config: `config/services/main_config.yaml`
Centralized configuration for all services including:
- Broker settings
- Strategy parameters
- Trading parameters
- Notification settings

### Environment Variables: `.env`
Copy `.env.example` to `.env` and configure:
```bash
# Fyers API
FYERS_CLIENT_ID=your_client_id
FYERS_SECRET_KEY=your_secret_key
FYERS_ACCESS_TOKEN=your_access_token

# Telegram
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

---

## 🚀 Getting Started

### 1. Setup Environment
```bash
cp .env.example .env
# Edit .env with your credentials
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Test Each Service
```bash
# Test individual services
python -m src.broker_service.broker_base test
python -m src.data_service.data_service test
python -m src.backtesting_service.backtest_service test
python -m src.backtesting_service.optimization_service test
python -m src.strategy_service.strategy_service test
python -m src.live_trading_service.live_trading_service test
python -m src.agent_service.agent_service test
```

### 4. Run Live Trading (Example)
```python
from src.broker_service.broker_base import BrokerFactory
from src.live_trading_service.live_trading_service import LiveTradingService
from src.strategy_service.strategy_service import StrategyService
from src.agent_service.agent_service import AgentService

# Initialize broker
broker = BrokerFactory.create_broker("fyers")
broker.connect()

# Initialize strategy service
strategy_service = StrategyService()
# ... register strategies ...

# Initialize live trading
trading = LiveTradingService(broker=broker, strategy_service=strategy_service)
trading.initialize()

# Initialize Telegram agent
agent = AgentService()
agent.initialize()
agent.set_trading_service(trading)

# Start trading
trading.start_trading()
```

---

## 🎯 Benefits of This Architecture

### ✅ Maintainability
- Each service is independent and focused
- Easy to locate and modify code
- Clear separation of concerns

### ✅ Scalability
- Add new brokers without changing other services
- Add new strategies easily
- Scale services independently

### ✅ Testability
- Each service can be tested independently
- Mock dependencies easily
- `__main__` test functions for quick validation

### ✅ Flexibility
- Switch brokers via configuration
- Enable/disable features via config
- Hot-swap strategies

### ✅ Extensibility
- Add new data sources
- Add new notification channels (Discord, Slack)
- Add new optimization algorithms

---

## 📝 Migration Notes

The old structure in `src/utils/`, `src/live_trading/`, `src/strategy/`, and `src/backtesting/` still exists for backward compatibility but should be gradually migrated to the new service structure.

Key changes:
- `src/utils/fyers/fyers_broker.py` → `src/broker_service/fyers/fyers_broker_impl.py`
- `src/live_trading/engine.py` → `src/live_trading_service/live_trading_service.py`
- `src/strategy/strategy_base.py` → `src/strategy_service/strategy_base.py`
- `src/backtesting/` → `src/backtesting_service/`

---

## 🤝 Contributing

When adding new features:
1. Create them as part of the appropriate service
2. Add `run_test()` function with `__main__` entry point
3. Update `main_config.yaml` if new configuration is needed
4. Add tests and documentation

---

## 📄 License

[Your License Here]
