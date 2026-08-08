# AI-Powered Backtesting Agent System

An intelligent trading backtesting platform that uses **LangGraph agents** and **MCP (Model Context Protocol)** servers to process natural language queries and execute comprehensive trading strategy backtests.

## 🚀 Features

### 1. Natural Language Backtesting
- Ask questions like: *"Backtest crossover strategy on RELIANCE from 2024-01-01 to 2024-06-30"*
- AI-powered intent recognition using **Ollama (gemma2:2b)**
- Automatic parameter extraction (symbol, dates, strategy, capital)

### 2. MCP Server Architecture
- **Data Service MCP**: Extract market data for any symbol, any timeframe
- **Backtest Service MCP**: Run swing and intraday backtests with multiple strategies
- Tool-based architecture for seamless LLM integration

### 3. Dual Backtesting Engines
- **Swing Trading Service**: Portfolio-based swing trading with sector allocation
- **Intraday Trading Service**: High-frequency intraday strategies using vectorbt

### 4. Streamlit UI
- 💬 **Natural Language Query Tab**: Chat interface for backtesting
- ⚡ **Quick Backtest Tab**: Manual configuration with all options visible
- 📊 **Results Tab**: Interactive metrics, equity curves, trade history
- ℹ️ **Strategy Info Tab**: Strategy documentation and parameters

### 5. LangGraph Agent
- Stateful multi-step reasoning
- Tool selection and orchestration
- Error handling and recovery
- Context-aware responses

---

## 📁 Project Structure

```
workspace/
├── src/
│   ├── agent_service/              # LangGraph Agent & Streamlit UI
│   │   ├── mcp_host/
│   │   │   └── backtest_agent.py   # Main agent with tool integration
│   │   └── ui/
│   │       └── backtest_ui.py      # Streamlit web interface
│   │
│   ├── mcp_server/                 # MCP Servers
│   │   ├── data_mcp_server.py      # Data extraction service
│   │   └── backtest_mcp_server.py  # Backtest execution service
│   │
│   ├── backtesting_swing_service/  # Swing trading backtests
│   │   └── backtest_engine.py
│   │
│   ├── backtesting_intraday_service/ # Intraday backtests
│   │   └── backtest_engine.py
│   │
│   ├── strategy_service/           # Trading strategies
│   │   └── strategies/
│   │
│   ├── data_service/               # Market data handlers
│   │
│   └── broker_service/             # Broker integrations
│
├── config/                         # Configuration files
│   ├── backtest.user.yaml          # User backtest overrides
│   ├── default/
│   │   └── stock_list.yaml         # 500+ stocks with sectors
│   └── config.yaml
│
├── data/
│   └── outputs/backtesting/        # Results & plots
│
├── requirements.txt                # All dependencies
├── README.md                       # This file
└── README_BACKTESTING.md           # Detailed backtesting guide
```

---

## 🛠️ Installation

### 1. Install Dependencies

```bash
cd /workspace
pip install -r requirements.txt
```

### 2. Setup Ollama

```bash
# Install Ollama (if not already installed)
curl -fsSL https://ollama.com/install.sh | sh

# Start Ollama server
ollama serve

# Pull the required model
ollama pull gemma2:2b
```

### 3. Verify Installation

```bash
# Check Ollama is running
curl http://localhost:11434/api/tags

# Test Python imports
python -c "import langgraph; import streamlit; import mcp; print('✅ All packages installed')"
```

---

## 🚀 Quick Start

### Option 1: Launch Streamlit UI (Recommended)

```bash
streamlit run src/agent_service/ui/backtest_ui.py
```

This opens a web interface at `http://localhost:8501` with:
- Natural language query chatbot
- Quick backtest configuration form
- Results visualization
- Strategy information

### Option 2: Run Agent Directly

```bash
python -m src.agent_service.mcp_host.backtest_agent
```

### Option 3: Run MCP Servers Separately

```bash
# Terminal 1: Data Service MCP
python -m src.mcp_server.data_mcp_server

# Terminal 2: Backtest Service MCP
python -m src.mcp_server.backtest_mcp_server

# Terminal 3: Run agent or UI
streamlit run src/agent_service/ui/backtest_ui.py
```

---

## 💬 Example Queries

Try these in the Streamlit UI or agent:

```
1. "What strategies are available for backtesting?"
2. "Show me the backtest options"
3. "Backtest crossover strategy on RELIANCE from 2024-01-01 to 2024-06-30"
4. "Run a backtest for RSI strategy on NIFTY with 100000 capital"
5. "Check if data is available for SBIN"
6. "Compare swing vs intraday backtest for volume strategy"
7. "List all available symbols"
8. "Get current price of TCS"
9. "Fetch historical data for HDFCBANK with daily timeframe"
10. "Run intraday backtest on momentum strategy"
```

---

## 🔧 Configuration

### Environment Variables (Optional)

Create a `.env` file in `/workspace`:

```bash
OLLAMA_MODEL=gemma2:2b
OLLAMA_BASE_URL=http://localhost:11434
DATA_SOURCE=postgresql
DB_NAME=spot_db_anamika
DB_USER=postgres
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=5432
```

### Backtest Configuration

Edit `config/backtest.user.yaml`:

```yaml
backtest:
  strategy_name: "volume_support_resistance"
  start_date: "2024-01-01"
  end_date: "2024-12-31"
  initial_capital: 100000
  target_profit_pct: 0.08
  stop_loss_pct: 0.04
  max_holding_days: 7
  watchlist: ["aubank_eq", "reliance_eq", "infy_eq"]
  
  position_weights:
    method: "sector_based"
    max_positions: 7
    max_per_sector: 1
```

---

## 📊 MCP Tools Reference

### Data Service Tools

| Tool | Description | Parameters |
|------|-------------|------------|
| `fetch_historical_data` | Get OHLCV data for symbol | symbol, timeframe, start_date, end_date |
| `get_current_price` | Get latest price | symbol |
| `list_available_symbols` | List all tradable symbols | - |
| `check_data_availability` | Verify data exists | symbol, timeframe |

### Backtest Service Tools

| Tool | Description | Parameters |
|------|-------------|------------|
| `run_single_backtest` | Execute backtest | symbol, strategy, start_date, end_date, capital, mode |
| `list_backtest_strategies` | List all strategies | - |
| `get_strategy_details` | Get strategy info | strategy_name |
| `get_backtest_configuration_options` | Get all options | - |

---

## 🧠 Agent Workflow

```
User Query (Natural Language)
        ↓
LangGraph Agent (gemma2:2b)
        ↓
Intent Recognition & Parameter Extraction
        ↓
Tool Selection (MCP Tools)
        ↓
Execute Tools (Data + Backtest Services)
        ↓
Format Results
        ↓
Response to User
```

### Agent State Management

```python
class AgentState(TypedDict):
    messages: Sequence[BaseMessage]
    query: str
    symbol: Optional[str]
    strategy: Optional[str]
    start_date: Optional[str]
    end_date: Optional[str]
    initial_capital: Optional[float]
    backtest_mode: Optional[str]  # 'swing' or 'intraday'
    backtest_result: Optional[Dict]
    error: Optional[str]
```

---

## 📈 Backtesting Options

### Available Strategies (Examples)
- Crossover Strategy
- RSI Strategy
- Volume Support/Resistance
- Momentum Strategy
- Mean Reversion
- Breakout Strategy

### Backtest Modes
- **Swing Trading**: Multi-day positions with portfolio management
- **Intraday**: Same-day entry/exit with high-frequency analysis

### Configurable Parameters
- Symbol (any NSE/BSE stock)
- Date range
- Initial capital
- Target profit %
- Stop loss %
- Max holding period
- Position sizing method
- Sector allocation limits

---

## 📝 API Usage

### Programmatic Access

```python
from src.agent_service.mcp_host import BacktestAgent

# Initialize agent
agent = BacktestAgent()

# Process natural language query
result = agent.process_query(
    "Backtest crossover on RELIANCE from 2024-01-01 to 2024-06-30"
)
print(result)

# Quick backtest without NLP
result = agent.quick_backtest(
    symbol="RELIANCE",
    strategy="crossover",
    start_date="2024-01-01",
    end_date="2024-06-30",
    initial_capital=100000,
    mode="swing"
)
```

### MCP Client Usage

```python
from mcp import ClientSession
import asyncio

async def use_mcp_tools():
    async with ClientSession(...) as session:
        # List tools
        tools = await session.list_tools()
        
        # Call data tool
        data = await session.call_tool(
            "fetch_historical_data",
            {"symbol": "RELIANCE", "timeframe": "daily"}
        )
        
        # Call backtest tool
        result = await session.call_tool(
            "run_single_backtest",
            {
                "symbol": "RELIANCE",
                "strategy": "crossover",
                "start_date": "2024-01-01",
                "end_date": "2024-06-30"
            }
        )
```

---

## 🔍 Troubleshooting

### Ollama Connection Issues

```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags

# Restart Ollama
ollama serve

# Pull model if missing
ollama pull gemma2:2b
```

### MCP Server Issues

```bash
# Test Data Service wrapper
python -c "from src.mcp_server.data_mcp_server import DataServiceWrapper; w = DataServiceWrapper(); print(w.list_available_symbols())"

# Test Backtest Service wrapper
python -c "from src.mcp_server.backtest_mcp_server import BacktestServiceWrapper; w = BacktestServiceWrapper(); print(w.get_available_strategies())"
```

### Streamlit Issues

```bash
# Clear cache
streamlit cache clear

# Run with debug logging
streamlit run src/agent_service/ui/backtest_ui.py --logger.debug
```

### Database Connection

```bash
# Check PostgreSQL status
sudo systemctl status postgresql

# Start if needed
sudo systemctl start postgresql

# Verify database
psql -U postgres -l | grep spot_db_anamika
```

---

## 📚 Documentation

- **[README_BACKTESTING.md](./README_BACKTESTING.md)**: Complete backtesting guide
- **[src/agent_service/README.md](./src/agent_service/README.md)**: Agent service details
- **[config/backtest.user.yaml](./config/backtest.user.yaml)**: Configuration reference

---

## 🎯 Use Cases

### 1. Strategy Research
```
"Compare RSI vs Crossover strategy on banking stocks for Q1 2024"
```

### 2. Parameter Optimization
```
"Backtest volume strategy with different stop loss levels: 2%, 4%, 6%"
```

### 3. Sector Analysis
```
"Run backtests on top 10 IT stocks with momentum strategy"
```

### 4. Risk Assessment
```
"What's the maximum drawdown for swing trading with 5% stop loss?"
```

### 5. Educational
```
"Explain how the crossover strategy works and show an example backtest"
```

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Submit a pull request

---

## 📄 License

MIT License - See LICENSE file for details

---

## 🙏 Acknowledgments

- **LangGraph** - Agent orchestration framework
- **Ollama** - Local LLM inference
- **Streamlit** - Web UI framework
- **MCP** - Model Context Protocol
- **vectorbt** - Backtesting library

---

## 📞 Support

For issues or questions:
1. Check this README
2. Review [README_BACKTESTING.md](./README_BACKTESTING.md)
3. Check agent service docs: [src/agent_service/README.md](./src/agent_service/README.md)
4. Verify configuration files in `config/`
5. Ensure Ollama and PostgreSQL are running

---

**Built with ❤️ for algorithmic trading enthusiasts**
