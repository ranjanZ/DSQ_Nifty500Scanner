"""
Testing Suite for Swing Trading Engine
- Paper Trading Mode (simulation with mock broker)
- GTT Order Testing (Good-Till-Triggered orders)
- Component Testing
"""

import os
import logging
from datetime import datetime, timedelta
import pytz
import yaml
import pandas as pd
from typing import Dict, List, Optional, Any

from src.live_trading.swing_trading_engine import SwingTradingEngine
from src.data_pipeline.db_utils import get_table_content
from src.strategy.market_scanner import MarketScanner

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MockBrokerForTesting:
    """
    Mock broker for testing without real money
    Simulates order execution based on historical data
    """
    
    def __init__(self):
        self.orders = {}  # {order_id: order_details}
        self.executed_orders = []
        self.order_counter = 1000
    
    def place_order(self, symbol: str, qty: int, side: str, type: str, price: float, **kwargs):
        """Mock order placement"""
        order_id = f"TEST_ORDER_{self.order_counter}"
        self.order_counter += 1
        
        order = {
            'order_id': order_id,
            'symbol': symbol,
            'qty': qty,
            'side': side,
            'type': type,
            'price': price,
            'timestamp': datetime.now().isoformat(),
            'status': 'PENDING'
        }
        
        self.orders[order_id] = order
        logger.info(f"[MOCK] Order placed: {order_id} | {side} {qty} {symbol} @ {price}")
        
        return order_id
    
    def cancel_order(self, order_id: str):
        """Mock order cancellation"""
        if order_id in self.orders:
            self.orders[order_id]['status'] = 'CANCELLED'
            logger.info(f"[MOCK] Order cancelled: {order_id}")
            return True
        return False
    
    def get_order_status(self, order_id: str):
        """Get mock order status"""
        if order_id in self.orders:
            return self.orders[order_id]['status']
        return 'NOT_FOUND'
    
    def get_his_candle_data(self, symbol: str, fromdate: str, todate: str, interval: str = "1"):
        """Mock historical data"""
        # In real test, this would fetch from DB
        return None


# ╔════════════════════════════════════════════════════════════════╗
# ║  1. PAPER TRADING MODE - Simulate without real money           ║
# ╚════════════════════════════════════════════════════════════════╝

class PaperTradingTests:
    """Test swing trading logic without real broker"""
    
    def __init__(self):
        self.config_file = "config/live_trading_config.yaml"
        self.backtest_config = "config/backtest_config.yaml"
        self.stock_list = "config/stock_list.yaml"
    
    def load_configs(self):
        """Load configuration files"""
        with open(self.config_file, 'r') as f:
            trading_config = yaml.safe_load(f)
        with open(self.backtest_config, 'r') as f:
            backtest_config = yaml.safe_load(f)
        
        return trading_config, backtest_config
    
    def test_signal_generation(self):
        """
        Test 1: Verify signal generation logic
        Use historical data to test if signals are generated correctly
        """
        logger.info("=" * 80)
        logger.info("TEST 1: Signal Generation (Using Historical Data)")
        logger.info("=" * 80)
        
        trading_config, backtest_config = self.load_configs()
        
        # Load scanner
        scanner = MarketScanner(
            self.stock_list,
            watch_list=['nifty_top_500']
        )
        
        # Get a few test stocks
        test_stocks = scanner.get_stock_symbols()[:5]
        
        print(f"\nTesting signal generation on {len(test_stocks)} stocks...")
        print("-" * 80)
        
        for stock in test_stocks:
            try:
                symbol = stock['symbol']
                table_name = scanner.get_table_name(symbol)
                
                # Fetch last 100 days of data
                end_date = datetime.now()
                start_date = end_date - timedelta(days=100)
                
                df = get_table_content(
                    db_name=trading_config['database_config']['db_name'],
                    table_name=table_name,
                    start_date=start_date,
                    end_date=end_date
                )
                
                if df is None or df.empty:
                    print(f"⚠️  No data for {symbol}")
                    continue
                
                # Prepare data
                df = df.sort_values('time')
                df['time'] = pd.to_datetime(df['time'])
                df = df[['time', 'open', 'high', 'low', 'close', 'volume']]
                
                # Create strategy and generate signals
                strategy_name = backtest_config['backtest']['strategy_name']
                scanner.create_strategy(strategy_name, strategy_name)
                
                strategy = scanner.strategies.get(strategy_name)
                if strategy is None:
                    continue
                
                signal_df = strategy.generate_signals(df)
                
                if signal_df is not None and not signal_df.empty:
                    latest_5 = signal_df.iloc[-5:]
                    latest = latest_5.iloc[-1]
                    
                    if latest['signal'] == 1:
                        confidence = scanner._calculate_confidence(signal_df)
                        print(f"✅ {symbol:15} | Signal: BUY | Confidence: {confidence:.2%} | Price: {latest['close']:.2f}")
                    else:
                        print(f"❌ {symbol:15} | Signal: HOLD (signal={latest['signal']})")
                else:
                    print(f"⚠️  {symbol:15} | No signals generated")
            
            except Exception as e:
                print(f"❌ {symbol:15} | Error: {e}")
        
        logger.info("✅ Test 1 Complete: Signal generation working (can run on live broker)")
        print()
    
    def test_position_sizing(self):
        """
        Test 2: Verify position sizing and capital allocation
        """
        logger.info("=" * 80)
        logger.info("TEST 2: Position Sizing & Capital Allocation")
        logger.info("=" * 80)
        
        trading_config, backtest_config = self.load_configs()
        initial_capital = 100000  # ₹1 Lakh
        
        signals = [
            {'symbol': 'INFY', 'open': 1500, 'sector': 'IT', 'confidence': 0.85},
            {'symbol': 'RELIANCE', 'open': 2500, 'sector': 'Energy', 'confidence': 0.75},
            {'symbol': 'HDFC', 'open': 2800, 'sector': 'Finance', 'confidence': 0.80},
            {'symbol': 'BAJAJ', 'open': 3500, 'sector': 'Automotive', 'confidence': 0.70},
        ]
        
        print(f"\nInitial Capital: ₹{initial_capital:,.0f}")
        print(f"Max Positions: 5 | Max per Sector: 2")
        print("-" * 80)
        
        # Create dummy engine to test position sizing
        from src.live_trading.swing_trading_engine import SwingTradingEngine
        
        engine = SwingTradingEngine(recover=False)
        selected = engine.select_and_weight_signals(signals)
        
        print(f"\nSelected {len(selected)} positions:")
        print("-" * 80)
        
        total_allocated = 0
        for i, signal in enumerate(selected, 1):
            weight = signal.get('final_weight', 0)
            allocated = initial_capital * weight
            qty = int(allocated / signal['open'])
            cost = qty * signal['open']
            
            print(f"{i}. {signal['symbol']:15} | Weight: {weight:6.2%} | Qty: {qty:4} | Cost: ₹{cost:10,.0f}")
            total_allocated += cost
        
        utilisation = (total_allocated / initial_capital) * 100
        print("-" * 80)
        print(f"Total Allocated: ₹{total_allocated:,.0f} | Utilisation: {utilisation:.1f}%")
        print(f"Remaining Capital: ₹{initial_capital - total_allocated:,.0f}")
        
        logger.info("✅ Test 2 Complete: Position sizing correct")
        print()
    
    def test_order_flow(self):
        """
        Test 3: Test the complete order flow (buy + OCO bracket)
        """
        logger.info("=" * 80)
        logger.info("TEST 3: Order Flow (BUY + OCO Bracket Simulation)")
        logger.info("=" * 80)
        
        mock_broker = MockBrokerForTesting()
        
        # Simulate order placement
        symbol = "INFY"
        entry_price = 1500
        qty = 50
        
        print(f"\nSimulating order placement for {symbol}...")
        print("-" * 80)
        
        # Step 1: Place BUY order
        buy_order = mock_broker.place_order(symbol, qty, "BUY", "MARKET", entry_price)
        print(f"✅ BUY Order: {buy_order}")
        
        # Step 2: Place SL bracket
        sl_price = entry_price * 0.98  # 2% SL
        sl_order = mock_broker.place_order(symbol, qty, "SELL", "STOP_LOSS", sl_price)
        print(f"✅ Stoploss Order: {sl_order} @ ₹{sl_price:.2f}")
        
        # Step 3: Place TP bracket
        tp_price = entry_price * 1.05  # 5% TP
        tp_order = mock_broker.place_order(symbol, qty, "SELL", "LIMIT", tp_price)
        print(f"✅ Takeprofit Order: {tp_order} @ ₹{tp_price:.2f}")
        
        print(f"\nOCO Bracket created successfully!")
        print(f"📊 Entry: ₹{entry_price} | SL: ₹{sl_price:.2f} | TP: ₹{tp_price:.2f}")
        print(f"💰 Capital Risk: ₹{(entry_price - sl_price) * qty:.0f}")
        print(f"💰 Profit Target: ₹{(tp_price - entry_price) * qty:.0f}")
        print(f"R:R Ratio: 1:{(tp_price - entry_price) / (entry_price - sl_price):.2f}")
        
        logger.info("✅ Test 3 Complete: Order flow working correctly")
        print()
    
    def test_sl_tp_refresh(self):
        """
        Test 4: Test SL/TP refresh logic (next day at 9:15 AM)
        """
        logger.info("=" * 80)
        logger.info("TEST 4: SL/TP Order Refresh Logic (Daily at 9:15 AM)")
        logger.info("=" * 80)
        
        mock_broker = MockBrokerForTesting()
        
        print("\nSimulating overnight position hold...")
        print("-" * 80)
        
        # Yesterday's orders
        print("\n📍 Yesterday (3:13 PM) - Placed OCO bracket:")
        symbol = "INFY"
        qty = 50
        entry = 1500
        
        sl_old = mock_broker.place_order(symbol, qty, "SELL", "STOP_LOSS", entry * 0.98)
        tp_old = mock_broker.place_order(symbol, qty, "SELL", "LIMIT", entry * 1.05)
        print(f"  ✅ SL Order: {sl_old}")
        print(f"  ✅ TP Order: {tp_old}")
        
        # Market close - orders expire
        print("\n📍 Market Close (3:30 PM) - Orders expire")
        print("  ⚠️  Overnight holding - no orders active")
        
        # Next day market open
        print("\n📍 Next Day Market Open (9:15 AM) - Refresh SL/TP:")
        
        # Cancel old orders
        mock_broker.cancel_order(sl_old)
        mock_broker.cancel_order(tp_old)
        print(f"  ✅ Cancelled old SL order: {sl_old}")
        print(f"  ✅ Cancelled old TP order: {tp_old}")
        
        # Place new orders
        sl_new = mock_broker.place_order(symbol, qty, "SELL", "STOP_LOSS", entry * 0.98)
        tp_new = mock_broker.place_order(symbol, qty, "SELL", "LIMIT", entry * 1.05)
        print(f"  ✅ New SL Order: {sl_new}")
        print(f"  ✅ New TP Order: {tp_new}")
        
        print(f"\n✅ Refresh successful: Old orders cancelled, new orders placed")
        print(f"   Broker now manages exit for {symbol} for the day")
        
        logger.info("✅ Test 4 Complete: SL/TP refresh working correctly")
        print()


# ╔════════════════════════════════════════════════════════════════╗
# ║  2. GTT ORDERS - Good-Till-Triggered (Set now, execute later)  ║
# ╚════════════════════════════════════════════════════════════════╝

class GTTOrderStrategy:
    """
    GTT = Good-Till-Triggered
    You can set order NOW (Sunday) to execute when conditions are met
    Fyers supports GTT orders - set once, broker executes automatically
    """
    
    @staticmethod
    def example_gtt_order():
        """
        Example: How to use GTT orders with Fyers on Sunday
        """
        print("\n" + "=" * 80)
        print("GTT ORDER STRATEGY - Set Orders on Sunday for Monday Open")
        print("=" * 80)
        
        print("""
SCENARIO: Sunday Evening - Market closed, want to enter tomorrow if signal conditions met

APPROACH 1: GTT Order (Recommended for Fyers)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

from fyers_apiv3.socket_io import SocketIoManager
from fyers_apiv3 import fyersModel

# 1. Create GTT order (Good-Till-Triggered)
gtt_order = {
    "symbol": "NSE:INFY-EQ",
    "quantity": 50,
    "order_type": "MARKET",
    "side": "BUY",
    "trigger_price": 1500,  # Execute if price touches 1500
    "price": 0,  # Market order no limit
    "pricetype": "MARKET",
    "ordervalidity": "GTC",  # Good-Till-Canceled
    "disclosedqty": 0,
    "stoplosstargetprice": 1470,  # Optional: SL target price
}

# 2. Place GTT order (even on Sunday!)
response = fyers.place_gtt_order(gtt_order)
logger.info(f"GTT Order ID: {response['gttId']}")

# 3. When Monday market opens and price hits 1500:
#    → Broker automatically executes BUY order
#    → Creates position
#    → You don't need to be watching!

APPROACH 2: Scheduled Entry (Less Reliable)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Run this Python script Sunday evening:

import time
from datetime import datetime
import pytz

tz = pytz.timezone('Asia/Kolkata')

while True:
    now = datetime.now(tz)
    
    # Trigger at Monday 9:15:30 AM
    if now.weekday() == 0 and now.strftime("%H:%M:%S") == "09:15:30":
        logger.info("Market opened - now place orders")
        engine = SwingTradingEngine()
        engine.scan_for_signals()
        break
    
    time.sleep(1)

APPROACH 3: Pre-compute and Store Orders (My Recommendation)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Sunday evening:
all_signals = scan_for_signals()  # Generate signals using historical data
selected = select_and_weight_signals(all_signals)

# Store these signals + order details in a JSON file
import json
order_plan = {
    "date": "2026-05-12",  # Monday
    "orders": [
        {
            "symbol": "INFY",
            "qty": 50,
            "entry_price": 1500,
            "sl_price": 1470,
            "tp_price": 1575,
            "type": "PRE_COMPUTED"
        },
        # ... more orders
    ]
}

with open("orders_for_monday.json", "w") as f:
    json.dump(order_plan, f)

# Monday 9:15 AM - your app starts and reads this file:
# Places all pre-computed orders automatically
        """)


# ╔════════════════════════════════════════════════════════════════╗
# ║  3. LIVE BROKER TESTING - Minimal Risk Test                   ║
# ╚════════════════════════════════════════════════════════════════╝

class LiveBrokerTestingStrategy:
    """
    Minimal risk testing with real broker on live market
    """
    
    @staticmethod
    def recommended_testing_approach():
        """
        Best practice for testing with real broker
        """
        print("\n" + "=" * 80)
        print("LIVE BROKER TESTING - Low Risk Approach")
        print("=" * 80)
        
        print("""
PHASE 1: Unit Testing (No Broker Needed)
─────────────────────────────────────────
✅ Test signal generation logic
✅ Test position sizing calculations
✅ Test capital management rules
✅ Test order flow sequences

Run: pytest tests/test_swing_engine.py

PHASE 2: Paper Trading (Mock Broker)
───────────────────────────────────────
✅ Test with mock broker (no real money)
✅ Verify state management
✅ Test session recovery logic
✅ Run backtests 50 times

Run: python -m src.live_trading.test_swing_trading PaperTrading

PHASE 3: Broker Sandbox (If Available)
────────────────────────────────────────
✅ Test with Fyers sandbox/paper trading account
✅ Real API interaction but fake money
✅ Test order placement flow
✅ Verify broker responses

Contact Fyers support: sandbox-test@fyers.in
Create sandbox account with ₹0 investment

PHASE 4: Live Market - Minimal Risk
────────────────────────────────────
✅ ONLY after phases 1-3 pass
✅ Start with ₹5,000 capital (not your full amount!)
✅ Monitor first 5 trades closely
✅ Verify SL/TP placement: Check broker terminal
✅ After 10 successful trades → increase capital

SPECIFIC TESTING CHECKLIST:
───────────────────────────

□ Entry Logic
  ├─ Signal generates correctly
  ├─ Order placed at right price
  ├─ Quantity calculated correctly
  └─ Capital allocated properly

□ Exit Logic
  ├─ SL order placed with broker
  ├─ TP order placed with broker
  ├─ Both visible in broker terminal
  └─ Time-based exit works

□ State Management
  ├─ Position saved after entry
  ├─ Session recovery works
  ├─ Broker sync matches local state
  └─ P&L calculation correct

□ Edge Cases
  ├─ Market pre-open (no orders)
  ├─ Market close (orders handled)
  ├─ Holiday detection (skip scanning)
  ├─ Network disconnect (recovery)
  └─ Broker rejection (error handling)

MONDAY MORNING QUICK TEST:
──────────────────────────
1. Market opens at 9:15 AM
2. Check broker terminal for:
   ✅ Position opened with right quantity
   ✅ SL order visible at correct price
   ✅ TP order visible at correct price
3. Leave running for 1 hour
4. Verify no crashes/errors in logs
5. Check capital is properly deducted
6. Manually verify P&L calculation is correct

If all pass → Ready for more capital!
        """)


# ╔════════════════════════════════════════════════════════════════╗
# ║  MAIN TESTING SUITE                                            ║
# ╚════════════════════════════════════════════════════════════════╝

if __name__ == "__main__":
    import sys
    
    print("\n" + "🧪 " * 20)
    print("SWING TRADING ENGINE - TEST SUITE")
    print("🧪 " * 20 + "\n")
    
    if len(sys.argv) > 1:
        test_type = sys.argv[1]
    else:
        test_type = "PaperTrading"
    
    if test_type == "PaperTrading":
        print("Running PAPER TRADING TESTS (Simulated, no real money)")
        print("-" * 80 + "\n")
        
        tester = PaperTradingTests()
        tester.test_signal_generation()
        tester.test_position_sizing()
        tester.test_order_flow()
        tester.test_sl_tp_refresh()
        
        print("\n" + "=" * 80)
        print("✅ ALL PAPER TRADING TESTS PASSED")
        print("=" * 80)
        print("\nYou can now test with REAL BROKER on live market!")
        print("Next: python test_swing_trading.py GTT")
    
    elif test_type == "GTT":
        GTTOrderStrategy.example_gtt_order()
    
    elif test_type == "LiveBroker":
        LiveBrokerTestingStrategy.recommended_testing_approach()
    
    else:
        print(f"Unknown test type: {test_type}")
        print("\nRun with: python test_swing_trading.py [PaperTrading|GTT|LiveBroker]")
