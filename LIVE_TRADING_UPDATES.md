# Live Trading Engine Updates

## Summary of Changes
Updated the live trading engine to use the same intelligent stock selection and trading rules from `backtest_offline.py`.

## Key Changes

### 1. **Stock Selection from Backtest** ✅
- Integrated `MarketScanner` to select stocks from `nifty_top_500` watchlist
- Implemented `select_and_weight_signals()` using sector-based allocation
- Scans ALL stocks for signals, then selects and weights them by sector
- Uses same signal generation strategy as backtest

### 2. **Capital Management (50% Fund Check)** ✅
- Added `can_open_position()` method that checks if capital utilization < 50%
- Live trading will ONLY open new positions if MORE than 50% of capital is available
- Added capital tracking methods:
  - `get_available_capital()` - free capital
  - `get_used_capital()` - allocated to positions
  - `get_total_capital()` - total trading capital
  - `get_utilisation_pct()` - current utilization %

### 3. **Broker Order Execution** ✅
- Implemented `place_order()` in `fyers_broker.py` with actual broker API calls
- Implemented `cancel_order()` for order cancellation
- Implemented `place_stoploss_order()` for stop-loss orders
- Implemented `get_positions()` and `get_orders()` for broker sync
- Updated `place_buy_order()` to execute orders through broker BEFORE state update
- If broker order fails, position is NOT added to state
- All orders now have order IDs tracked for reconciliation

### 4. **Exit Rules (from Backtest)** ✅
Implemented all exit rules from backtest_offline.py:
1. **Stop Loss** - Exits if price drops by stop_loss_pct (default 2%)
2. **Target Hit** - Exits if price rises by target_profit_pct (default 5%)
3. **Trailing Stop** - Exits if price drops from highest achieved price by trailing_stop_pct
4. **Time-based Exit** - Exits after max_holding_days (default 7 days)

### 5. **Sell Order Execution** ✅
- Updated `close_position()` to execute actual SELL orders through broker
- Sells only execute AFTER broker confirms the order
- P&L calculation happens after successful sell

## Configuration

### Live Trading Config (`config/live_trading_config.yaml`)
```yaml
live_trading:
  initial_capital: 50000
  max_positions: 3
  target_profit_pct: 0.05      # 5% profit target
  stop_loss_pct: 0.02          # 2% stop loss
  max_holding_days: 7          # Exit after 7 days
  trailing_stop_pct: 0.01      # 1% trailing stop
  timezone: "Asia/Kolkata"
  market_open: "09:15"
  market_close: "15:20"
```

### Backtest Config (`config/backtest_config.yaml`)
Strategy parameters are used for signal generation:
```yaml
backtest:
  strategy_name: "Volume_Price_Strategy"
  target_profit_pct: 0.08       # Can be different from live
  stop_loss_pct: 0.04           # Can be different from live
  max_holding_days: 7
  position_weights:
    method: "sector_based"
    max_positions: 7
    max_per_sector: 1
    sector_allocation: {...}
  lookback_days: 100
  watchlist: ["nifty_top_500"]
```

## Daily Trading Flow

1. **Market Opens** → Sync with broker
2. **Every Hour** → Full stock scan:
   - Load 100-day historical data for 200 stocks
   - Generate signals using configured strategy
   - Select and weight signals by sector
3. **Check 50% Rule** → Only open positions if >50% capital free
4. **Place Orders** → 
   - For each selected signal, place BUY order through broker
   - Wait for broker confirmation (order ID)
   - Add position to state ONLY after broker confirms
5. **Continuous** (every 5 seconds) → 
   - Check exit signals for all positions
   - Exit if: stop loss hit, target reached, trailing stop hit, or max days exceeded
   - Execute SELL orders through broker
6. **Every 5 Minutes** → Periodic sync with broker (reconciliation)
7. **Market Closes** → Print final status

## Data Flow

```
scan_for_signals_with_history()
  ↓
  For each stock:
    - Load 100-day history from database
    - Generate signals using strategy
    - Calculate confidence score
  ↓
select_and_weight_signals()
  ↓
  Group by sector
  Sort by confidence within each sector
  Apply sector-based weights
  Normalize final weights
  ↓
place_buy_order() [×N]
  ↓
  Check capital (>50% free?)
  Check max positions?
  Calculate quantity based on weight
  Execute BUY order through broker
  Add to state manager
  ↓
Positions held with continuous monitoring:
  check_exit_signals()
  ↓
  For each position:
    Check stop loss
    Check target
    Check trailing stop  
    Check time exit
  ↓
close_position()
  ↓
  Execute SELL order through broker
  Update P&L
  Remove from state manager
```

## Key Differences from Previous Implementation

| Aspect | Before | After |
|--------|--------|-------|
| Stock Selection | Hardcoded list (5 symbols) | Intelligent selection from 200+ stocks |
| Signal Weighting | None | Sector-based allocation |
| Capital Check | None | >50% free capital required |
| Broker Orders | Not executed | Full execution with order IDs |
| Exit Rules | Basic 2 rules | 4 comprehensive rules |
| Fund Management | No tracking | Full tracking and constraints |

## Testing the New Implementation

### 1. Enable Telegram Notifications (optional)
Update `config/live_trading_config.yaml`:
```yaml
enable_telegram: true
telegram_chat_id: "YOUR_CHAT_ID"
telegram_bot_token: "YOUR_BOT_TOKEN"
```

### 2. Run Live Trading Engine
```bash
python -m src.live_trading.engine
```

### 3. Monitor Logs
```bash
tail -f logs/live_trading_*.log
```

### 4. Check State/Positions
State is automatically saved to `data/trading_state/`

## Important Notes

⚠️ **PRODUCTION CHECKLIST:**
- [ ] Verify Fyers API credentials are set correctly
- [ ] Test with small capital first (₹5,000-₹10,000)
- [ ] Verify database connection for stock data
- [ ] Ensure PostgreSQL is running with stock data tables
- [ ] Test order placement in market simulator before going live
- [ ] Set up proper error handling and alerts
- [ ] Monitor capital utilization daily
- [ ] Review closed trades weekly

## Troubleshooting

### Orders Not Going to Broker
1. Check Fyers API credentials in `fyers_auth.py`
2. Verify API authorization token is valid
3. Check logs for specific Fyers API errors
4. Verify symbol format (should be "NSE:SYMBOL-EQ")

### Stock Data Not Loading
1. Check database connection in `stock_list.yaml`
2. Verify PostgreSQL is running
3. Check if tables exist for stocks being scanned
4. Verify date range has data

### Capital Not Increasing
1. Verify positions are being closed (check exit signals)
2. Check P&L calculation in position close
3. Review broker sync for discrepancies

### Max Positions Reached
1. Check max_positions config setting
2. Close some existing positions manually
3. Review which positions are profitable/loss-making
