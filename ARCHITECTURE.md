# Trading System Architecture

## Overview

This is a modular, service-based trading system designed for scalability and maintainability. Each service has a single responsibility and communicates through well-defined interfaces.

## Service Structure

```
src/
├── broker_service/          # Broker connectivity layer
│   ├── broker_base.py       # Abstract base class & registry
│   └── fyers/
│       └── fyers_broker_impl.py  # Fyers implementation
│
├── strategy_service/        # Trading strategies
│   ├── strategy_base.py     # Base strategy class
│   └── strategies/
│       ├── __init__.py      # Strategy registry
│       ├── madam_strategy.py    # Support/Resistance strategy
│       ├── rsi_w_strategy.py    # RSI W-Pattern strategy
│       └── crossover_strategy.py # MA Crossover strategy
│
├── data_service/            # Data access layer
│   └── __init__.py          # DataService class
│
├── backtesting_service/     # Backtesting & optimization
│   ├── backtest_service.py  # Backtest engine
│   └── optimization_service.py  # Parameter optimization
│
├── live_trading_service/    # Live trading execution
│   └── __init__.py          # LiveTradingService class
│
└── agent_service/           # Telegram integration
    └── __init__.py          # AgentService class
```

## Services

### 1. Broker Service
- **Purpose**: Abstract broker connectivity
- **Features**:
  - Multiple broker support (Fyers implemented)
  - Unified API for order management
  - Market data access
  - Account information
  
**Usage**:
```python
from src.broker_service.fyers.fyers_broker_impl import FyersBroker

broker = FyersBroker()
broker.connect()
ltp = broker.get_ltp("NSE:SBIN-EQ")
broker.place_order({...})
```

### 2. Strategy Service
- **Purpose**: Trading signal generation
- **Strategies**:
  - `Support_Resistance`: S/R levels with volume confirmation
  - `RSI_W_Pattern`: RSI W-pattern detection
  - `MA_Crossover`: Moving average crossover
  
**Usage**:
```python
from src.strategy_service.strategies import get_strategy

strategy = get_strategy('Support_Resistance', params={...})
signals = strategy.generate_signals(dataframe)
```

### 3. Data Service
- **Purpose**: Unified data access
- **Sources**: Database, Broker API
- **Features**:
  - Historical OHLCV data
  - Stock list management
  - Data validation

**Usage**:
```python
from src.data_service import DataService

service = DataService(config)
df = service.get_historical_data("SBIN", "2024-01-01", "2024-12-31")
```

### 4. Backtesting Service
- **Purpose**: Strategy validation
- **Features**:
  - Historical backtesting
  - Parameter optimization (Bayesian)
  - Performance metrics
  - Sector-based position sizing

**Usage**:
```python
from src.backtesting_service import BacktestEngine

engine = BacktestEngine()
results = engine.run_backtest()
```

### 5. Live Trading Service
- **Purpose**: Real-time execution
- **Features**:
  - Market hours monitoring
  - Signal scanning
  - Position management
  - Risk management (target/stoploss)

**Usage**:
```python
from src.live_trading_service import LiveTradingService

service = LiveTradingService()
service.initialize()
service.start()
```

### 6. Agent Service
- **Purpose**: Telegram notifications
- **Features**:
  - Trade alerts
  - Daily summaries
  - System alerts

**Usage**:
```python
from src.agent_service import AgentService

agent = AgentService()
agent.connect()
agent.send_trade_notification("BUY", "SBIN", 750.50, 100)
```

## Configuration

### Environment Variables (.env)
```bash
# Fyers Credentials
FYERS_CLIENT_ID=your_client_id
FYERS_ACCESS_TOKEN=your_access_token

# Telegram
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Database
DB_NAME=spot_db_anamika
```

### YAML Configuration
- `config/live_trading_config.yaml` - Live trading parameters
- `config/backtest_config.yaml` - Backtest settings
- `config/optimization_config.yaml` - Optimization parameters
- `config/stock_list.yaml` - Stock watchlists

## Testing

Each service has a `__main__` entry point for testing:

```bash
# Test individual services
python -m src.broker_service.fyers.fyers_broker_impl test
python -m src.strategy_service.strategies test
python -m src.data_service test
python -m src.backtesting_service test
python -m src.live_trading_service test
python -m src.agent_service test
```

## Adding New Strategies

1. Create new strategy class inheriting from `TradingStrategy`
2. Implement `generate_signals()` method
3. Register in `strategy_service/strategies/__init__.py`

```python
from src.strategy_service.strategy_base import TradingStrategy

class MyStrategy(TradingStrategy):
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        # Your logic here
        return df
```

## Adding New Brokers

1. Create new broker class inheriting from `BrokerBase`
2. Implement all abstract methods
3. Use `@register_broker("name")` decorator

```python
from src.broker_service.broker_base import BrokerBase, register_broker

@register_broker("zerodha")
class ZerodhaBroker(BrokerBase):
    def connect(self): ...
    def place_order(self, params): ...
    # etc.
```

## Design Principles

1. **Separation of Concerns**: Each service has one responsibility
2. **Loose Coupling**: Services communicate through interfaces
3. **Extensibility**: Easy to add new brokers/strategies
4. **Testability**: Each component can be tested independently
5. **Configuration-Driven**: Behavior controlled by config files

## Scalability

- **Horizontal**: Run multiple instances for different strategies
- **Vertical**: Add more brokers/strategies without code changes
- **Data**: Switch between DB/broker data sources seamlessly
- **Notifications**: Extend agent service for multiple channels

## Security

- Credentials stored in environment variables
- No hardcoded secrets
- IP whitelisting handled at broker level
