"""
Streamlit UI for Backtesting Agent
===================================
Interactive UI that allows users to:
1. Enter natural language queries for backtesting
2. View available strategies and backtest options
3. Run backtests and visualize results
4. See detailed metrics and trade history

Usage:
    streamlit run src/agent_service/ui/backtest_ui.py
"""

import os
import sys
import json
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

# Streamlit
try:
    import streamlit as st
    HAS_STREAMLIT = True
except ImportError:
    HAS_STREAMLIT = False
    print("⚠️  Streamlit not installed. Install with: pip install streamlit")
    sys.exit(1)

# Path resolution
_CUR_FILE = os.path.abspath(__file__)
_CUR_DIR = os.path.dirname(_CUR_FILE)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_CUR_DIR)))

if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# Page configuration
st.set_page_config(
    page_title="Backtesting Agent",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1E88E5;
        text-align: center;
        margin-bottom: 1rem;
    }
    .sub-header {
        font-size: 1.2rem;
        color: #666;
        text-align: center;
        margin-bottom: 2rem;
    }
    .metric-card {
        background-color: #f0f2f6;
        padding: 1rem;
        border-radius: 0.5rem;
        text-align: center;
    }
    .stButton>button {
        width: 100%;
        background-color: #1E88E5;
        color: white;
        font-weight: bold;
    }
    .success-box {
        padding: 1rem;
        background-color: #d4edda;
        border-left: 4px solid #28a745;
        border-radius: 0.3rem;
        margin: 1rem 0;
    }
    .error-box {
        padding: 1rem;
        background-color: #f8d7da;
        border-left: 4px solid #dc3545;
        border-radius: 0.3rem;
        margin: 1rem 0;
    }
</style>
""", unsafe_allow_html=True)


# Initialize session state
if 'agent' not in st.session_state:
    st.session_state.agent = None
if 'backtest_result' not in st.session_state:
    st.session_state.backtest_result = None
if 'query_history' not in st.session_state:
    st.session_state.query_history = []


def initialize_agent():
    """Initialize the backtesting agent."""
    try:
        from src.agent_service.mcp_host.backtest_agent import BacktestAgent
        return BacktestAgent()
    except Exception as e:
        st.error(f"Failed to initialize agent: {e}")
        return None


def get_backtest_options():
    """Get available backtest options."""
    try:
        from src.mcp_server.backtest_mcp_server import BacktestServiceWrapper
        wrapper = BacktestServiceWrapper()
        return wrapper.get_backtest_options()
    except Exception as e:
        return {"error": str(e)}


def run_backtest_direct(
    symbol: str,
    strategy: str,
    start_date: str,
    end_date: str,
    initial_capital: float
):
    """Run backtest directly without agent."""
    try:
        from src.mcp_server.backtest_mcp_server import BacktestServiceWrapper
        wrapper = BacktestServiceWrapper()
        return wrapper.run_backtest(
            symbol=symbol,
            strategy_name=strategy,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital
        )
    except Exception as e:
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# Main UI
# ═══════════════════════════════════════════════════════════════════════

def main():
    # Header
    st.markdown('<h1 class="main-header">📊 Backtesting Agent</h1>', unsafe_allow_html=True)
    st.markdown('<p class="sub-header">Test trading strategies with natural language queries</p>', unsafe_allow_html=True)
    
    # Sidebar
    with st.sidebar:
        st.header("⚙️ Configuration")
        
        # Agent initialization
        if st.session_state.agent is None:
            if st.button("🚀 Initialize Agent", use_container_width=True):
                with st.spinner("Initializing..."):
                    st.session_state.agent = initialize_agent()
                    if st.session_state.agent:
                        st.success("✅ Agent initialized!")
                    else:
                        st.error("❌ Failed to initialize")
        else:
            st.success("✅ Agent Ready")
            if st.button("🔄 Reset Agent", use_container_width=True):
                st.session_state.agent = None
                st.session_state.backtest_result = None
                st.rerun()
        
        st.divider()
        
        # Quick stats
        st.subheader("📈 Quick Stats")
        options = get_backtest_options()
        if "error" not in options:
            strategies = options.get('strategies', [])
            st.metric("Available Strategies", len(strategies))
            
            backtest_types = options.get('backtest_types', [])
            st.write(f"**Backtest Types:** {', '.join(backtest_types)}")
        else:
            st.warning("Could not load options")
        
        st.divider()
        
        # Query history
        if st.session_state.query_history:
            st.subheader("📝 Recent Queries")
            for i, query in enumerate(st.session_state.query_history[-5:], 1):
                st.text(f"{i}. {query[:30]}...")
    
    # Main content area
    tab1, tab2, tab3, tab4 = st.tabs([
        "💬 Natural Language Query",
        "⚡ Quick Backtest",
        "📊 Results",
        "ℹ️ Strategy Info"
    ])
    
    # Tab 1: Natural Language Query
    with tab1:
        st.header("Natural Language Query")
        st.write("Describe what you want to backtest in plain English.")
        
        # Example queries
        with st.expander("📋 Example Queries"):
            st.code("""
- What strategies are available?
- Show me backtest options
- Backtest crossover strategy on RELIANCE from 2024-01-01 to 2024-06-30
- Run a backtest for RSI strategy on NIFTY with 100000 capital
- Check if data is available for SBIN
            """)
        
        query_input = st.text_area(
            "Your Query:",
            height=100,
            placeholder="E.g., Backtest crossover strategy on RELIANCE from 2024-01-01 to 2024-06-30"
        )
        
        col1, col2 = st.columns([3, 1])
        with col1:
            run_query_btn = st.button("🚀 Run Query", use_container_width=True, type="primary")
        with col2:
            clear_chat = st.button("🗑️ Clear", use_container_width=True)
        
        if clear_chat:
            st.session_state.query_history = []
            st.session_state.backtest_result = None
            st.rerun()
        
        if run_query_btn and query_input:
            if st.session_state.agent is None:
                st.error("Please initialize the agent first from the sidebar.")
            else:
                with st.spinner("🤖 Processing your query..."):
                    result = st.session_state.agent.process_query(query_input, verbose=False)
                    
                    # Add to history
                    st.session_state.query_history.append(query_input)
                    
                    if result.get('success'):
                        st.success("✅ Query processed successfully!")
                        
                        # Display response
                        st.markdown("### 🤖 Agent Response:")
                        st.write(result.get('response', 'No response'))
                        
                        # Store backtest result if available
                        if result.get('backtest_result'):
                            st.session_state.backtest_result = result['backtest_result']
                            st.info("💾 Backtest result saved. Check the Results tab.")
                    else:
                        st.error(f"❌ Error: {result.get('error', 'Unknown error')}")
    
    # Tab 2: Quick Backtest
    with tab2:
        st.header("Quick Backtest")
        st.write("Manually configure and run a backtest.")
        
        # Get available strategies
        options = get_backtest_options()
        strategies = options.get('strategies', []) if "error" not in options else []
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Instrument & Strategy")
            qb_symbol = st.text_input("Symbol", value="RELIANCE", help="Instrument symbol")
            qb_strategy = st.selectbox(
                "Strategy",
                options=strategies,
                index=0 if strategies else 0,
                help="Select trading strategy"
            )
            qb_type = st.selectbox(
                "Backtest Type",
                options=options.get('backtest_types', ['swing', 'intraday']),
                index=0
            )
        
        with col2:
            st.subheader("Parameters")
            default_start = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
            default_end = datetime.now().strftime('%Y-%m-%d')
            
            qb_start = st.date_input("Start Date", value=datetime.strptime(default_start, '%Y-%m-%d'))
            qb_end = st.date_input("End Date", value=datetime.strptime(default_end, '%Y-%m-%d'))
            qb_capital = st.number_input("Initial Capital", value=100000, min_value=10000, step=10000)
        
        qb_interval = st.selectbox(
            "Timeframe",
            options=options.get('supported_intervals', {}).get(qb_type, ['1D']),
            index=0
        )
        
        if st.button("▶️ Run Backtest", type="primary", use_container_width=True):
            with st.spinner("Running backtest..."):
                result = run_backtest_direct(
                    symbol=qb_symbol,
                    strategy=qb_strategy,
                    start_date=qb_start.strftime('%Y-%m-%d'),
                    end_date=qb_end.strftime('%Y-%m-%d'),
                    initial_capital=qb_capital
                )
                
                if result.get('success'):
                    st.session_state.backtest_result = result
                    st.success("✅ Backtest completed!")
                    st.rerun()
                else:
                    st.error(f"❌ Backtest failed: {result.get('error', 'Unknown error')}")
    
    # Tab 3: Results
    with tab3:
        st.header("Backtest Results")
        
        if st.session_state.backtest_result is None:
            st.info("👆 Run a backtest to see results here.")
        else:
            result = st.session_state.backtest_result
            
            # Key metrics
            st.subheader("📊 Performance Metrics")
            
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                total_return = result.get('total_return_pct', 0)
                delta_color = "normal" if total_return >= 0 else "inverse"
                st.metric(
                    "Total Return",
                    f"{total_return:.2f}%",
                    delta=f"{total_return:.2f}%" if total_return != 0 else None,
                    delta_color=delta_color
                )
            
            with col2:
                sharpe = result.get('sharpe_ratio', 0)
                st.metric("Sharpe Ratio", f"{sharpe:.3f}")
            
            with col3:
                win_rate = result.get('win_rate_pct', 0)
                st.metric("Win Rate", f"{win_rate:.2f}%")
            
            with col4:
                total_trades = result.get('total_trades', 0)
                st.metric("Total Trades", total_trades)
            
            col5, col6 = st.columns(2)
            with col5:
                max_dd = result.get('max_drawdown_pct', 0)
                st.metric(
                    "Max Drawdown",
                    f"{max_dd:.2f}%",
                    delta=f"{max_dd:.2f}%" if max_dd != 0 else None,
                    delta_color="inverse"
                )
            
            with col6:
                final_equity = result.get('final_equity', result.get('initial_capital', 100000))
                initial = result.get('initial_capital', 100000)
                st.metric("Final Equity", f"₹{final_equity:,.0f}", delta=f"₹{final_equity-initial:,.0f}")
            
            st.divider()
            
            # Sample trades
            sample_trades = result.get('sample_trades', [])
            if sample_trades:
                st.subheader("📝 Sample Trades")
                
                trades_df = pd.DataFrame(sample_trades)
                
                # Format columns
                if 'entry_date' in trades_df.columns:
                    trades_df['entry_date'] = pd.to_datetime(trades_df['entry_date']).dt.strftime('%Y-%m-%d')
                if 'exit_date' in trades_df.columns:
                    trades_df['exit_date'] = pd.to_datetime(trades_df['exit_date']).dt.strftime('%Y-%m-%d')
                
                # Color code PnL
                def color_pnl(val):
                    if isinstance(val, (int, float)):
                        return 'color: green' if val > 0 else 'color: red' if val < 0 else ''
                    return ''
                
                styled_df = trades_df.style.applymap(color_pnl, subset=['pnl', 'pnl_pct'])
                st.dataframe(styled_df, use_container_width=True)
            
            # Full metrics
            st.divider()
            st.subheader("📈 Detailed Metrics")
            
            metrics = result.get('metrics', {})
            if metrics:
                with st.expander("View All Metrics", expanded=False):
                    st.json(metrics)
    
    # Tab 4: Strategy Info
    with tab4:
        st.header("Strategy Information")
        
        options = get_backtest_options()
        strategy_details = options.get('strategy_details', {})
        
        if strategy_details:
            selected_strategy = st.selectbox(
                "Select Strategy",
                options=list(strategy_details.keys())
            )
            
            if selected_strategy:
                info = strategy_details[selected_strategy]
                
                col1, col2 = st.columns([2, 1])
                
                with col1:
                    st.subheader(f"📖 {selected_strategy}")
                    
                    if info.get('description'):
                        st.write(info['description'])
                    
                    st.write(f"**Class Name:** `{info.get('class_name', 'N/A')}`")
                    st.write(f"**Category:** {info.get('category', 'General')}")
                    st.write(f"**Timeframe:** {info.get('timeframe', 'Auto')}")
                
                with col2:
                    st.subheader("Parameters")
                    params = info.get('parameters', {})
                    if params:
                        for param, value in params.items():
                            st.code(f"{param}: {value}")
                    else:
                        st.info("No parameters defined")
        else:
            st.warning("No strategy information available")


if __name__ == '__main__':
    main()
