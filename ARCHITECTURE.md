# Architecture Documentation

## Service-Based Trading System Architecture

This document describes the modular, service-based architecture of the trading system.

## Directory Structure

```
/workspace/
├── config/                          # Configuration files
│   ├── config.default.yaml         # Default template (DO NOT EDIT)
│   ├── config.yaml                 # Main configuration (user edits)
│   ├── strategy.user.yaml          # Strategy overrides
│   ├── backtest.user.yaml          # Backtest overrides
│   └── live.user.yaml              # Live trading overrides
│
├── data/                            # Data storage
│   ├── session/                    # Trading session data
│   ├── trading_state/              # Persistent trading state
│   └── market_data.db              # Historical market data (optional)
│
├── plots/                           # Visualization outputs
│   ├── backtest/                   # Backtest result plots
│   ├── optimization/               # Optimization charts
│   └── live/                       # Live trading visualizations
│
├── logs/                            # Log files
│   └── trading_system.log
│
├── optimization_results/            # Optimization outputs
│   ├── best_portfolio_curve.png
│   └── results_*.csv
│
└── src/                             # Source code
    ├── broker_service/             # Broker integration layer
    │   ├── broker_base.py          # Abstract base class
    │   └── fyers/                  # Fyers broker implementation
    │       ├── __init__.py
    │       └── fyers_broker_impl.py
    │
    ├── data_service/               # Data access layer
    │   └── data_service.py
    │
    ├── strategy_service/           # Strategy management
    │   ├── strategy_base.py        # Abstract strategy base
    │   └── strategies/             # Individual strategies
    │       ├── __init__.py
    │       ├── madam_strategy/     # Support/Resistance
    │       │   ├── __init__.py
    │       │   └── config.yaml
    │       ├── rsi_w_strategy/     # RSI W-Pattern
    │       │   ├── __init__.py
    │       │   └── config.yaml
    │       └── crossover_strategy/ # MA Crossover
    │           ├── __init__.py
    │           └── config.yaml
    │
    ├── backtesting_service/        # Backtesting engine
    │   ├── backtest_service.py
    │   └── optimization_service.py
    │
    ├── live_trading_service/       # Live trading orchestrator
    │   └── live_trading_service.py
    │
    └── agent_service/              # Telegram integration
        └── agent_service.py
```

## Service Descriptions

### 1. Broker Service (`broker_service/`)
**Purpose**: Unified interface for broker interactions
- **broker_base.py**: Abstract base class with registry pattern
- **fyers/**: Fyers broker implementation
  - Supports: Order placement, position management, market data
  - Authentication via environment variables

**Adding a new broker**:
1. Create folder under `broker_service/<broker_name>/`
2. Implement `broker_base.BrokerBase` abstract class
3. Register in broker_base.py BROKER_REGISTRY

### 2. Data Service (`data_service/`)
**Purpose**: Unified data access layer
- Fetches data from broker or database
- Caching mechanism for performance
- Supports multiple timeframes

### 3. Strategy Service (`strategy_service/`)
**Purpose**: Strategy management and implementation

**Structure**:
- Each strategy has its own folder with:
  - `__init__.py`: Strategy implementation
  - `config.yaml`: Strategy-specific configuration

**Available Strategies**:
1. **SupportResistance** (`madam_strategy/`)
   - Uses KDE for support/resistance levels
   - Volume confirmation
   - Sector-specific allocation

2. **RSI_WPattern** (`rsi_w_strategy/`)
   - RSI-based with W-pattern detection
   - Mean reversion strategy

3. **MA_Crossover** (`crossover_strategy/`)
   - Moving average crossover signals
   - Configurable fast/slow periods

**Strategy Configuration**:
Each strategy's `config.yaml` contains:
- Strategy parameters
- Sector-specific investment allocation
- Symbol lists per sector
- Backtest settings
- Optimization parameter ranges
- Live trading overrides

### 4. Backtesting Service (`backtesting_service/`)
**Purpose**: Historical strategy testing and optimization

**Features**:
- Event-driven backtesting engine
- Sector allocation enforcement
- Commission and slippage modeling
- Comprehensive metrics calculation

**Optimization Service**:
- Bayesian optimization
- Grid search support
- Multiple metrics: Sharpe ratio, total return, max drawdown
- Parallel processing

**Outputs**:
- Plots saved to `plots/backtest/`
- Metrics saved to `data/backtest_metrics.csv`
- Optimization results in `optimization_results/`

### 5. Live Trading Service (`live_trading_service/`)
**Purpose**: Real-time trading execution

**Features**:
- Utilizes broker service for order execution
- Real-time risk management
- Position tracking
- Market hours enforcement
- State persistence

### 6. Agent Service (`agent_service/`)
**Purpose**: Telegram bot integration

**Features**:
- Trade alerts
- P&L updates
- Error notifications
- Daily summaries
- Interactive commands (/status, /positions, /pnl, etc.)

## Configuration System

### Multi-Level Configuration

1. **Default Config** (`config/config.default.yaml`)
   - Template with all default values
   - DO NOT EDIT - version controlled

2. **Main Config** (`config/config.yaml`)
   - User's active configuration
   - Copy from default and modify

3. **Service-Specific Overrides**:
   - `strategy.user.yaml`: Strategy selection
   - `backtest.user.yaml`: Backtest parameters
   - `live.user.yaml`: Live trading settings

4. **Strategy-Specific Config**:
   - Located in each strategy folder
   - Contains sector allocation and symbol lists
   - Parameter optimization ranges

### Configuration Loading Order
1. Load `config.default.yaml`
2. Override with `config.yaml`
3. Apply service-specific user configs
4. Load strategy-specific config based on active strategy

## Environment Variables

Create `.env` file from `.env.example`:
```bash
cp .env.example .env
```

Required variables:
- `FYERS_CLIENT_ID`: Fyers client ID
- `FYERS_SECRET_KEY`: Fyers secret key
- `FYERS_ACCESS_TOKEN`: Fyers access token (auto-generated)
- `TELEGRAM_BOT_TOKEN`: Telegram bot token
- `TELEGRAM_CHAT_ID`: Telegram chat ID

## Testing

Each service has a `__main__` entry point for testing:

```bash
# Test strategy service
python -m src.strategy_service.strategy_base test

# Test broker service
python -m src.broker_service.fyers.fyers_broker_impl test

# Test backtest service
python -m src.backtesting_service.backtest_service test

# Test live trading service
python -m src.live_trading_service.live_trading_service test

# Test agent service
python -m src.agent_service.agent_service test
```

## Usage Examples

### Run Backtest
```python
from src.backtesting_service.backtest_service import BacktestService
from src.strategy_service.strategies import get_strategy

# Load strategy with its config
strategy = get_strategy("SupportResistance")

# Initialize backtest
backtest = BacktestService(
    strategy=strategy,
    initial_capital=100000,
    save_plots=True
)

# Run backtest
results = backtest.run(start_date="2023-01-01", end_date="2024-01-01")
```

### Run Optimization
```python
from src.backtesting_service.optimization_service import OptimizationService

optimizer = OptimizationService(
    strategy_name="SupportResistance",
    method="bayesian",
    n_iterations=50
)

best_params = optimizer.optimize()
```

### Run Live Trading
```python
from src.live_trading_service.live_trading_service import LiveTradingService

live = LiveTradingService(
    strategy_name="SupportResistance",
    broker="fyers"
)

live.start()
```

## Adding New Strategies

1. Create folder: `src/strategy_service/strategies/<strategy_name>/`
2. Add `__init__.py` with strategy class extending `TradingStrategy`
3. Add `config.yaml` with:
   - Parameters
   - Sector allocation
   - Optimization ranges
4. Update `src/strategy_service/strategies/__init__.py`:
   ```python
   from .<strategy_name> import <ClassName>
   STRATEGY_REGISTRY['<StrategyName>'] = <ClassName>
   ```

## Scalability Benefits

1. **Modularity**: Each service is independent and testable
2. **Extensibility**: Easy to add new brokers, strategies, or services
3. **Maintainability**: Clear separation of concerns
4. **Configurability**: Multi-level configuration system
5. **Testability**: Each component can be tested in isolation
6. **Deployment Ready**: Services can be containerized separately

## Best Practices

1. **Never edit** `config.default.yaml` - always use `config.yaml`
2. **Use environment variables** for sensitive data (API keys, tokens)
3. **Keep strategy configs** self-contained in their folders
4. **Run tests** before deploying changes: `python -m src.<service> test`
5. **Check logs** in `logs/trading_system.log` for debugging
6. **Monitor plots** in respective `plots/` subdirectories
