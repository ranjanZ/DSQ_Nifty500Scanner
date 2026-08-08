"""
MCP Host for Agent Service
===========================
LangGraph-based agent that coordinates multiple MCP tools including:
- Data Service MCP (for fetching market data)
- Backtest Service MCP (for running backtests)

This host processes natural language queries and orchestrates tool calls.
Uses OLLAMA with gemma2:2b model.
"""

import os
import sys
import json
import logging
from typing import TypedDict, Annotated, Sequence, List, Dict, Any, Optional
from datetime import datetime, timedelta

# LangGraph imports
try:
    from langgraph.graph import StateGraph, END
    from langgraph.prebuilt import ToolNode
    HAS_LANGGRAPH = True
except ImportError:
    HAS_LANGGRAPH = False
    print("⚠️  LangGraph not installed. Install with: pip install langgraph")

# LangChain imports - define stubs if not available
try:
    from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage
    from langchain_core.tools import tool, Tool
    from langchain_ollama import ChatOllama
    HAS_LANGCHAIN = True
except ImportError:
    HAS_LANGCHAIN = False
    print("⚠️  LangChain not installed. Install with: pip install langchain-core langchain-ollama")
    
    # Define stub classes for when LangChain is not installed
    class BaseMessage:
        pass
    class HumanMessage(BaseMessage):
        def __init__(self, content=""):
            self.content = content
    class AIMessage(BaseMessage):
        def __init__(self, content="", tool_calls=None):
            self.content = content
            self.tool_calls = tool_calls or []
    class SystemMessage(BaseMessage):
        def __init__(self, content=""):
            self.content = content
    class ToolMessage(BaseMessage):
        pass
    def tool(func):
        return func
    class Tool:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

logger = logging.getLogger(__name__)

# Configuration
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma2:2b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# Path resolution
_CUR_FILE = os.path.abspath(__file__)
_CUR_DIR = os.path.dirname(_CUR_FILE)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_CUR_DIR))

if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ═══════════════════════════════════════════════════════════════════════
# State Definition
# ═══════════════════════════════════════════════════════════════════════

class AgentState(TypedDict):
    """State for the backtesting agent."""
    messages: Annotated[Sequence[BaseMessage], lambda x, y: x + y]
    query: str
    symbol: Optional[str]
    strategy: Optional[str]
    start_date: Optional[str]
    end_date: Optional[str]
    initial_capital: Optional[float]
    interval: Optional[str]
    backtest_type: Optional[str]
    backtest_result: Optional[Dict[str, Any]]
    data_result: Optional[Dict[str, Any]]
    error: Optional[str]


# ═══════════════════════════════════════════════════════════════════════
# Tool Definitions
# ═══════════════════════════════════════════════════════════════════════

class MCPToolWrapper:
    """Wrapper to call MCP server tools via direct Python imports."""
    
    def __init__(self):
        self._data_wrapper = None
        self._backtest_wrapper = None
    
    @property
    def data_wrapper(self):
        if self._data_wrapper is None:
            try:
                from src.mcp_server.data_mcp_server import DataServiceWrapper
                self._data_wrapper = DataServiceWrapper()
                logger.info("Data MCP wrapper initialized")
            except Exception as e:
                logger.error(f"Failed to initialize Data MCP wrapper: {e}")
                self._data_wrapper = None
        return self._data_wrapper
    
    @property
    def backtest_wrapper(self):
        if self._backtest_wrapper is None:
            try:
                from src.mcp_server.backtest_mcp_server import BacktestServiceWrapper
                self._backtest_wrapper = BacktestServiceWrapper()
                logger.info("Backtest MCP wrapper initialized")
            except Exception as e:
                logger.error(f"Failed to initialize Backtest MCP wrapper: {e}")
                self._backtest_wrapper = None
        return self._backtest_wrapper
    
    def fetch_data(self, symbol: str, start_date: str, end_date: str, interval: str = "1D") -> Dict[str, Any]:
        """Fetch historical data for a symbol."""
        if self.data_wrapper is None:
            return {"error": "Data service not available"}
        
        result = self.data_wrapper.get_historical_data(symbol, start_date, end_date, interval)
        return result
    
    def get_available_strategies(self) -> List[str]:
        """Get list of available strategies."""
        if self.backtest_wrapper is None:
            return []
        return self.backtest_wrapper.get_available_strategies()
    
    def get_backtest_options(self) -> Dict[str, Any]:
        """Get backtest configuration options."""
        if self.backtest_wrapper is None:
            return {"error": "Backtest service not available"}
        return self.backtest_wrapper.get_backtest_options()
    
    def run_backtest(
        self,
        symbol: str,
        strategy: str,
        start_date: str,
        end_date: str,
        initial_capital: float = 100000,
        interval: str = "1D",
        backtest_type: str = "swing"
    ) -> Dict[str, Any]:
        """Run a backtest."""
        if self.backtest_wrapper is None:
            return {"error": "Backtest service not available"}
        
        return self.backtest_wrapper.run_backtest(
            symbol=symbol,
            strategy_name=strategy,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            interval=interval,
            backtest_type=backtest_type
        )
    
    def check_data_availability(self, symbol: str) -> Dict[str, Any]:
        """Check if data is available for a symbol."""
        if self.data_wrapper is None:
            return {"error": "Data service not available"}
        
        return {
            "symbol": symbol,
            "has_data": True,  # Simplified - actual implementation would check DB
            "message": "Data availability check"
        }


# Global tool wrapper
_tool_wrapper = None

def get_tool_wrapper():
    global _tool_wrapper
    if _tool_wrapper is None:
        _tool_wrapper = MCPToolWrapper()
    return _tool_wrapper


# Define LangChain tools
@tool
def get_backtest_options_tool() -> Dict[str, Any]:
    """Get all available backtesting options including strategies, timeframes, and parameters."""
    wrapper = get_tool_wrapper()
    return wrapper.get_backtest_options()


@tool
def list_strategies_tool() -> List[str]:
    """List all available trading strategies for backtesting."""
    wrapper = get_tool_wrapper()
    return wrapper.get_available_strategies()


@tool
def fetch_market_data_tool(
    symbol: str,
    start_date: str,
    end_date: str,
    interval: str = "1D"
) -> Dict[str, Any]:
    """
    Fetch historical market data for a symbol.
    
    Args:
        symbol: Instrument symbol (e.g., "NIFTY", "RELIANCE")
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        interval: Timeframe ("1m", "5m", "15m", "1h", "1D", etc.)
    """
    wrapper = get_tool_wrapper()
    return wrapper.fetch_data(symbol, start_date, end_date, interval)


@tool
def run_backtest_tool(
    symbol: str,
    strategy: str,
    start_date: str,
    end_date: str,
    initial_capital: float = 100000,
    interval: str = "1D",
    backtest_type: str = "swing"
) -> Dict[str, Any]:
    """
    Run a backtest for a single instrument with specified strategy.
    
    Args:
        symbol: Instrument symbol (e.g., "NIFTY", "RELIANCE", "SBIN")
        strategy: Strategy name to test
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        initial_capital: Initial capital for backtest (default: 100000)
        interval: Timeframe for the backtest
        backtest_type: Type of backtest ("swing" or "intraday")
    
    Returns:
        Dictionary with backtest results including returns, sharpe ratio, win rate, etc.
    """
    wrapper = get_tool_wrapper()
    return wrapper.run_backtest(
        symbol=symbol,
        strategy=strategy,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        interval=interval,
        backtest_type=backtest_type
    )


@tool
def check_symbol_data_tool(symbol: str) -> Dict[str, Any]:
    """Check if historical data is available for a symbol."""
    wrapper = get_tool_wrapper()
    return wrapper.check_data_availability(symbol)


# Create tool list
ALL_TOOLS = [
    get_backtest_options_tool,
    list_strategies_tool,
    fetch_market_data_tool,
    run_backtest_tool,
    check_symbol_data_tool
]


# ═══════════════════════════════════════════════════════════════════════
# Agent Logic
# ═══════════════════════════════════════════════════════════════════════

def create_agent():
    """Create the LangGraph agent with tools."""
    
    if not HAS_LANGGRAPH or not HAS_LANGCHAIN:
        logger.error("LangGraph or LangChain not available")
        return None
    
    # Initialize LLM
    try:
        llm = ChatOllama(
            model=OLLAMA_MODEL,
            base_url=OLLAMA_BASE_URL,
            temperature=0.1
        )
        logger.info(f"✅ Connected to Ollama with model: {OLLAMA_MODEL}")
    except Exception as e:
        logger.error(f"❌ Failed to connect to Ollama: {e}")
        return None
    
    # Bind tools to LLM
    llm_with_tools = llm.bind_tools(ALL_TOOLS)
    
    # Define node functions
    def agent_node(state: AgentState) -> AgentState:
        """Agent node that decides which tool to call."""
        messages = state["messages"]
        
        # Add system message if not present
        if not any(isinstance(m, SystemMessage) for m in messages):
            system_msg = SystemMessage(
                content="""You are a backtesting assistant that helps users test trading strategies.
                
                You have access to these tools:
                1. get_backtest_options_tool - Get available strategies and backtest parameters
                2. list_strategies_tool - List all available trading strategies
                3. fetch_market_data_tool - Fetch historical market data
                4. run_backtest_tool - Run a backtest with specified parameters
                5. check_symbol_data_tool - Check if data exists for a symbol
                
                When a user asks to backtest a strategy:
                1. First understand what they want to test (symbol, strategy, dates)
                2. If needed, fetch data to verify availability
                3. Run the backtest with appropriate parameters
                4. Present results clearly with key metrics
                
                Always be helpful and explain your reasoning."""
            )
            messages = [system_msg] + list(messages)
        
        response = llm_with_tools.invoke(messages)
        return {"messages": [response]}
    
    def should_continue(state: AgentState) -> str:
        """Determine if we should continue with tool calls or end."""
        messages = state["messages"]
        last_message = messages[-1] if messages else None
        
        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            return "tools"
        return "end"
    
    # Build graph
    workflow = StateGraph(AgentState)
    
    # Add nodes
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", ToolNode(ALL_TOOLS))
    
    # Set entry point
    workflow.set_entry_point("agent")
    
    # Add conditional edges
    workflow.add_conditional_edges(
        source="agent",
        condition=should_continue,
        mapping={
            "tools": "tools",
            "end": END
        }
    )
    
    # Add edge from tools back to agent
    workflow.add_edge("tools", "agent")
    
    # Compile
    app = workflow.compile()
    logger.info("✅ Agent graph compiled successfully")
    
    return app


# ═══════════════════════════════════════════════════════════════════════
# Main Interface
# ═══════════════════════════════════════════════════════════════════════

class BacktestAgent:
    """High-level interface for the backtesting agent."""
    
    def __init__(self):
        self.app = create_agent()
        self.tool_wrapper = get_tool_wrapper()
    
    def process_query(self, query: str, verbose: bool = True) -> Dict[str, Any]:
        """
        Process a natural language query and execute backtest.
        
        Args:
            query: Natural language query from user
            verbose: Whether to print intermediate steps
        
        Returns:
            Dictionary with results and conversation history
        """
        if self.app is None:
            return {
                "success": False,
                "error": "Agent not initialized. Check Ollama connection.",
                "query": query
            }
        
        # Initialize state
        initial_state = {
            "messages": [HumanMessage(content=query)],
            "query": query,
            "symbol": None,
            "strategy": None,
            "start_date": None,
            "end_date": None,
            "initial_capital": None,
            "interval": None,
            "backtest_type": None,
            "backtest_result": None,
            "data_result": None,
            "error": None
        }
        
        # Run agent
        try:
            if verbose:
                print("\n" + "="*60)
                print(f"🤖 Processing query: {query}")
                print("="*60)
            
            final_state = self.app.invoke(initial_state)
            
            # Extract results
            messages = final_state.get("messages", [])
            last_message = messages[-1] if messages else None
            
            result = {
                "success": True,
                "query": query,
                "response": last_message.content if last_message else "",
                "messages": [str(m) for m in messages],
                "backtest_result": final_state.get("backtest_result"),
                "data_result": final_state.get("data_result")
            }
            
            if verbose:
                print("\n✅ Query processed successfully")
                print(f"\n📝 Response:\n{result['response']}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error processing query: {e}")
            import traceback
            error_trace = traceback.format_exc()
            
            result = {
                "success": False,
                "error": str(e),
                "traceback": error_trace,
                "query": query
            }
            
            if verbose:
                print(f"\n❌ Error: {e}")
            
            return result
    
    def quick_backtest(
        self,
        symbol: str,
        strategy: str,
        start_date: str,
        end_date: str,
        initial_capital: float = 100000
    ) -> Dict[str, Any]:
        """Quick backtest without natural language processing."""
        if self.tool_wrapper.backtest_wrapper is None:
            return {"error": "Backtest service not available"}
        
        return self.tool_wrapper.backtest_wrapper.run_backtest(
            symbol=symbol,
            strategy_name=strategy,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital
        )


# ═══════════════════════════════════════════════════════════════════════
# Main Entry Point
# ═══════════════════════════════════════════════════════════════════════

def main():
    """Test the agent with sample queries."""
    print("=" * 60)
    print("🤖 Backtesting Agent Service")
    print("=" * 60)
    print(f"Model: {OLLAMA_MODEL}")
    print(f"Ollama URL: {OLLAMA_BASE_URL}")
    print("=" * 60)
    
    # Initialize agent
    agent = BacktestAgent()
    
    if agent.app is None:
        print("\n❌ Failed to initialize agent")
        print("\nTroubleshooting:")
        print("1. Make sure Ollama is running: ollama serve")
        print("2. Pull the model: ollama pull gemma2:2b")
        print("3. Install dependencies: pip install langgraph langchain-core langchain-ollama")
        return
    
    # Test queries
    test_queries = [
        "What strategies are available for backtesting?",
        "Show me the backtest options",
    ]
    
    for query in test_queries:
        result = agent.process_query(query, verbose=True)
        print("\n" + "-"*60)
    
    print("\n" + "="*60)
    print("✅ Agent ready for queries")
    print("="*60)
    
    # Interactive mode
    print("\nEnter your queries (type 'quit' to exit):\n")
    
    while True:
        try:
            query = input("👤 You: ").strip()
            if query.lower() in ['quit', 'exit', 'q']:
                print("\n👋 Goodbye!")
                break
            
            if not query:
                continue
            
            result = agent.process_query(query, verbose=False)
            
            print(f"\n🤖 Agent: {result.get('response', 'No response')}")
            print()
            
        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!")
            break
        except Exception as e:
            print(f"\n❌ Error: {e}\n")


if __name__ == '__main__':
    main()
