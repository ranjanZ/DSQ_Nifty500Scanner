# Backtesting Agent Service

A LangGraph-based intelligent backtesting agent that processes natural language queries to run trading strategy backtests.

## Architecture

```
agent_service/
├── mcp_host/              # MCP Host (LangGraph Agent)
│   ├── __init__.py
│   └── backtest_agent.py  # Main agent with tool integration
└── ui/                    # Streamlit UI
    ├── __init__.py
    └── backtest_ui.py     # Interactive web interface
```

## Features

### 1. Natural Language Query Processing
- Uses LangGraph with Ollama (gemma2:2b model)
- Processes user queries in plain English
- Automatically extracts parameters (symbol, strategy, dates, etc.)

### 2. MCP Tool Integration
- **Data Service MCP**: Fetch historical market data
- **Backtest Service MCP**: Run swing/intraday backtests
- Tools available:
  - `get_backtest_options_tool` - Get available strategies and parameters
  - `list_strategies_tool` - List all trading strategies
  - `fetch_market_data_tool` - Fetch OHLCV data
  - `run_backtest_tool` - Execute backtest
  - `check_symbol_data_tool` - Verify data availability

### 3. Streamlit UI
- **Natural Language Query Tab**: Chat interface for backtesting
- **Quick Backtest Tab**: Manual parameter configuration
- **Results Tab**: Visual metrics and trade history
- **Strategy Info Tab**: Strategy documentation

## Installation

```bash
# Install dependencies
pip install langgraph langchain-core langchain-ollama
pip install streamlit pandas
pip install mcp  # For MCP server functionality

# Ensure Ollama is running
ollama serve
ollama pull gemma2:2b
```

## Usage

### 1. Start MCP Servers (Optional)

```bash
# Data Service MCP
python -m src.mcp_server.data_mcp_server

# Backtest Service MCP (in another terminal)
python -m src.mcp_server.backtest_mcp_server
```

### 2. Run the Agent Directly

```bash
python -m src.agent_service.mcp_host.backtest_agent
```

### 3. Launch Streamlit UI

```bash
streamlit run src/agent_service/ui/backtest_ui.py
```

## Example Queries

```
- What strategies are available for backtesting?
- Show me the backtest options
- Backtest crossover strategy on RELIANCE from 2024-01-01 to 2024-06-30
- Run a backtest for RSI strategy on NIFTY with 100000 capital
- Check if data is available for SBIN
- Compare swing vs intraday backtest for volume strategy
```

## Configuration

Environment variables (optional):

```bash
OLLAMA_MODEL=gemma2:2b
OLLAMA_BASE_URL=http://localhost:11434
```

## Agent Workflow

1. **User Input**: Natural language query
2. **LLM Processing**: gemma2:2b analyzes intent
3. **Tool Selection**: Agent chooses appropriate MCP tools
4. **Execution**: Tools fetch data and run backtests
5. **Response**: Formatted results with metrics

## State Management

The agent uses LangGraph's state management:

```python
class AgentState(TypedDict):
    messages: Sequence[BaseMessage]
    query: str
    symbol: Optional[str]
    strategy: Optional[str]
    start_date: Optional[str]
    end_date: Optional[str]
    initial_capital: Optional[float]
    backtest_result: Optional[Dict]
    error: Optional[str]
```

## API Reference

### BacktestAgent Class

```python
from src.agent_service.mcp_host import BacktestAgent

agent = BacktestAgent()

# Process natural language query
result = agent.process_query(
    "Backtest crossover on RELIANCE from 2024-01-01 to 2024-06-30"
)

# Quick backtest without NLP
result = agent.quick_backtest(
    symbol="RELIANCE",
    strategy="crossover",
    start_date="2024-01-01",
    end_date="2024-06-30",
    initial_capital=100000
)
```

## Troubleshooting

### Ollama Connection Issues
```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags

# Pull model if not available
ollama pull gemma2:2b

# Restart Ollama service
ollama serve
```

### MCP Server Issues
```bash
# Test MCP wrapper directly
python -c "from src.mcp_server.backtest_mcp_server import BacktestServiceWrapper; w = BacktestServiceWrapper(); print(w.get_available_strategies())"
```

### Streamlit Issues
```bash
# Clear cache
streamlit cache clear

# Run with verbose logging
streamlit run src/agent_service/ui/backtest_ui.py --logger.debug
```
