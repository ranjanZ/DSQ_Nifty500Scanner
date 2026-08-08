# Backtesting Service - Complete Setup & Usage Guide

## Overview

This guide explains how to run backtests for the **Volume Support/Resistance Strategy** using the existing infrastructure. The system:

1. ✅ **Reads data from PostgreSQL database** (`spot_db_anamika`)
2. ✅ **Uses `config/backtest.user.yaml`** for user overrides
3. ✅ **Uses `config/default/stock_list.yaml`** for sector mapping (500+ stocks, NOT cache files)
4. ✅ **Implements swing trading with portfolio management** (sector-based allocation, max positions)
5. ✅ **Day-by-day simulation** - Mimics live trading workflow where:
   - Each day scans all stocks for signals
   - Opens positions respecting portfolio limits (max 7 positions, 1 per sector)
   - Closes positions on target/stop/max-hold
   - **Frees capital when positions close** for new opportunities
   - Repeats for every trading day in the backtest period
6. ✅ **Progress bars** - Shows real-time progress during data fetching and simulation
7. ✅ **Parallel processing** - Uses all CPU cores minus 1 for faster execution

---

## Prerequisites

### 1. Install Dependencies

```bash
cd /workspace
pip install -r requirements.txt
pip install tqdm joblib  # For progress bars and parallelization
```

Required packages:
- `pandas`, `numpy` - Data manipulation
- `matplotlib` - Plotting
- `pyyaml` - Config loading
- `scikit-learn` - KDE for support/resistance levels
- `psycopg2-binary` - PostgreSQL connection
- `tqdm` - Progress bars
- `joblib` - Parallel processing

### 2. Database Setup

Ensure PostgreSQL is running with stock data tables:

```bash
# Check if PostgreSQL is running
sudo systemctl status postgresql

# If not running, start it
sudo systemctl start postgresql
```

Database configuration:
- **Database name**: `spot_db_anamika`
- **Table format**: `{symbol}_eq` (e.g., `aubank_eq`, `reliance_eq`)
- **Required columns**: `date`, `open`, `high`, `low`, `close`, `volume`

---

## Configuration Files

### 1. User Overrides: `config/backtest.user.yaml`

```yaml
backtest:
  strategy_name: "volume_support_resistance"   # Strategy to test
  
  start_date: "2024-01-01"          # Historical dates (NOT future!)
  end_date: "2024-12-31"
  
  initial_capital: 100000           # ₹1,00,000 for proper swing trading
  target_profit_pct: 0.08           # 8% target
  stop_loss_pct: 0.04               # 4% stop loss
  max_holding_days: 7               # Swing trading horizon
  
  # Watchlist options:
  # - ["nifty_top_500"] - loads all 500 stocks from config/default/stock_list.yaml
  # - ["aubank_eq", "reliance_eq", "infy_eq"] - specific symbols (faster for testing)
  watchlist: ["aubank_eq", "reliance_eq", "infy_eq", "hdfcbank_eq", "tcs_eq"]

  # Portfolio Management - mimics live trading
  position_weights:
    method: "sector_based"
    max_positions: 7                # Max concurrent positions
    max_per_sector: 1               # Only 1 stock per sector at a time
    sector_allocation:
      "Financial Services": 0.30
      "Capital Goods": 0.20
      "Healthcare": 0.15
      # ... other sectors (must sum to 1.0)
```

### 2. Stock List: `config/default/stock_list.yaml`

Contains **500+ stocks** with sector mappings. The backtest engine automatically converts:
- `NSE:AUBANK-EQ` → `aubank_eq` (database table name)
- Maps to sector: `Financial Services`

**Note**: No separate cache file needed - sector data is loaded directly from `stock_list.yaml`.

### 3. Strategy Config

Strategy-specific parameters in `src/strategy_service/strategies/volume_support_resistance_strategy/config.yaml`:
```yaml
params:
  volume_ema_period: 20
  volume_threshold: 1.3
  kde_bandwidth: 0.2
  num_levels: 10
  use_pivot_points: true
```

---

## How to Run Backtests

### Method 1: Run with Default Symbols (from config)

```bash
cd /workspace
python src/backtesting_service/backtest_engine.py --strategy volume_support_resistance
```

### Method 2: Specify Custom Symbols (Faster for Testing)

```bash
python src/backtesting_service/backtest_engine.py \
  --strategy volume_support_resistance \
  --symbols aubank_eq reliance_eq hdfcbank_eq infy_eq
```

### Method 3: Override Dates via Command Line

```bash
python src/backtesting_service/backtest_engine.py \
  --strategy volume_support_resistance \
  --start-date 2024-01-01 \
  --end-date 2024-06-30 \
  --capital 50000
```

### Method 4: Run as Module

```bash
python -m src.backtesting_service.backtest_engine \
  --strategy volume_support_resistance
```

### Method 5: Test All Nifty 500 Stocks (SLOW - requires full DB)

Edit `config/backtest.user.yaml`:
```yaml
watchlist: ["nifty_top_500"]
```

Then run:
```bash
python src/backtesting_service/backtest_engine.py --strategy volume_support_resistance
```

⚠️ **Warning**: This will attempt to load 500+ stocks from the database. Only use if you have complete historical data.

---

## Swing Trading Workflow with Portfolio Management

### Daily Scan Process (Mimics Live Trading)

The backtest engine now simulates **day-by-day trading** exactly like the live trading service:

#### 1. Each Trading Day:
   - Scan ALL stocks in watchlist for buy signals
   - Check existing positions for exit conditions
   - Close positions that hit target/stop/max-hold
   - **Free up capital and slots** when positions close
   - Open new positions with available capital

#### 2. Portfolio Limits Enforced Daily:
```yaml
max_positions: 7        # Maximum 7 concurrent positions
max_per_sector: 1       # Only 1 stock per sector at a time
```

#### 3. Capital Flow Example:
```
Day 1: Scan → Open 3 positions (₹30k, ₹25k, ₹20k) → Capital used: ₹75k
Day 2: Position 1 hits target (+8%) → Closed, capital freed
       Scan → Open 2 new positions with freed capital
Day 3: Position 2 hits stop (-4%) → Closed, capital freed
       Position 4 reaches max hold (7 days) → Exit at market
       Scan → Open new positions...
```

#### 4. Exit Priority:
   - **Stop Loss** (first priority) - Protects capital
   - **Target Profit** - Takes profits
   - **Max Holding Period** (7 days) - Ensures swing trading discipline

### Example Day-by-Day Simulation

```python
# Pseudo-code of what happens internally
for each trading_day in backtest_period:
    # Step 1: Check exits on existing positions
    for symbol, position in active_positions:
        if low <= stop_loss:
            close_position(exit_reason='stoploss')
            free_capital_and_slot()
        elif high >= target:
            close_position(exit_reason='target')
            free_capital_and_slot()
        elif days_held >= max_holding_days:
            close_position(exit_reason='max_hold')
            free_capital_and_slot()
    
    # Step 2: Scan for new signals (only if slots available)
    if len(active_positions) < max_positions:
        for symbol in watchlist:
            if can_open_position(symbol):  # Respects sector limits
                signal = generate_signal(symbol)
                if signal == BUY:
                    open_position(symbol)
```

---

## Output Files

After running a backtest, check these files:

### 1. Metrics JSON
```
data/outputs/backtesting/volumesupportresistance_metrics.json
```

Contains:
- Total return, Sharpe ratio, Sortino ratio
- Max drawdown, win rate, profit factor
- Sector-wise breakdown
- Trade statistics (entry/exit dates, P&L, holding periods)

### 2. Equity Curve Plot
```
data/outputs/backtesting/volumesupportresistance_20240101_20241231.png
```

Shows:
- Equity growth over time
- Drawdown periods
- Key metrics in title

### 3. Sector Breakdown Plot
```
data/outputs/backtesting/volumesupportresistance_sector_breakdown_20240101_20241231.png
```

Shows:
- P&L by sector
- Number of trades per sector
- Win rate per sector

---

## Progress Bars & Parallelization

The backtest engine now includes:

### 1. Progress Bars
- **Data Fetching**: Shows progress while loading stocks from database
- **Day-by-Day Simulation**: Shows progress through trading days

Example output:
```
📥 Fetching data from database (7 cores)...
Fetching data: 100%|██████████| 500/500 [00:45<00:00, 11.0it/s]

🔄 Simulating 252 trading days...
Simulating days: 100%|██████████| 252/252 [00:18<00:00, 14.0it/s]
```

### 2. Multi-Core Processing
- Automatically uses `CPU_COUNT - 1` cores for data fetching
- Leaves 1 core free for system responsiveness
- Uses `joblib.Parallel` for parallel database queries

Example on 8-core system:
```
📥 Fetching data from database (7 cores)...
```

### 3. Performance Estimates
- **5 symbols, 1 year**: ~2-5 seconds
- **100 symbols, 1 year**: ~15-30 seconds  
- **500 symbols, 1 year**: ~1-2 minutes (with parallel fetching)

---

## Troubleshooting

### Issue: "Insufficient data" for all symbols
**Cause**: PostgreSQL is not running or tables don't exist

**Solution**:
```bash
# Start PostgreSQL
sudo systemctl start postgresql

# Verify database exists
psql -U postgres -l | grep spot_db_anamika

# Check if table exists
psql -U postgres -d spot_db_anamika -c "\dt aubank_eq"
```

### Issue: Wrong number of symbols loaded
**Cause**: Using `nifty_top_500` watchlist without complete database

**Solution**: Use specific symbols for testing:
```yaml
watchlist: ["aubank_eq", "reliance_eq", "infy_eq"]
```

### Issue: Backtest completes instantly (0 trades)
**Possible causes**:
1. No database connection (see above)
2. Date range in future (use historical dates)
3. Strategy not generating signals (check strategy config)

**Solution**:
```yaml
# Use historical dates, NOT future dates!
start_date: "2024-01-01"
end_date: "2024-12-31"
```

### Issue: Slow performance with many symbols
**Solution**: Enable parallel processing (already enabled by default):
```python
# Uses CPU_COUNT - 1 cores automatically
num_cores = max(1, multiprocessing.cpu_count() - 1)
```

---

## Advanced Usage

### Custom Capital Allocation

Edit `config/backtest.user.yaml`:
```yaml
position_weights:
  method: "sector_based"
  max_positions: 10       # More concurrent positions
  max_per_sector: 2       # Allow 2 stocks per sector
  sector_allocation:
    "Financial Services": 0.40
    "Technology": 0.30
    # ... adjust weights as needed
```

### Adjust Swing Trading Parameters

```yaml
backtest:
  target_profit_pct: 0.10    # 10% target instead of 8%
  stop_loss_pct: 0.05        # 5% stop instead of 4%
  max_holding_days: 10       # Hold up to 10 days
  lookback_days: 150         # More history for signals
```

### Export Trade Log

The metrics JSON includes all trades. Extract with:
```bash
jq '.trades[] | select(.pnl > 0)' \
  data/outputs/backtesting/volumesupportresistance_metrics.json
```

---

## Live Trading Integration

This backtest engine mirrors the live trading workflow:

1. **Same signal generation** as live service
2. **Same portfolio management** rules
3. **Same exit logic** (target/stop/max-hold)
4. **Same capital allocation** methodology

To transition from backtest to live:
1. Validate strategy with backtest
2. Run paper trading (same code, fake money)
3. Deploy to live with small capital
4. Monitor and adjust parameters

---

## Support

For issues or questions:
1. Check this README first
2. Review `config/backtest.user.yaml` settings
3. Verify database connectivity
4. Check strategy-specific config in `src/strategy_service/strategies/`

### 3. Sector Breakdown Plot
```
data/outputs/backtesting/volumesupportresistance_sector_breakdown_20240101_20241231.png
```

Displays:
- P&L by sector
- Number of trades per sector
- Win rates by sector

---

## Sample Output

```
============================================================
🔬 Backtest Engine
============================================================
   Strategy: volume_support_resistance
   Config:   config/default/backtest.yaml + config/backtest.user.yaml
============================================================

🔬 Backtest: VolumeSupportResistance
   Period: 2024-01-01 → 2024-12-31
   Capital: ₹1,00,000
   Symbols: 5 total, 3 active
   Target: 8.0% | Stop: 4.0% | Max Hold: 7d
   Allocation: Sector-based (max_pos=7, max_per_sector=1)
============================================================

📈 aubank_eq (sector: Financial Services, alloc: ₹78,947)
   ⚠️  Insufficient data (PostgreSQL not running)

📈 reliance_eq (sector: Oil Gas & Consumable Fuels, alloc: ₹0)
   ⚠️  Insufficient data

📈 infy_eq (sector: Information Technology, alloc: ₹21,053)
   ⚠️  Insufficient data

============================================================
📊 BACKTEST RESULTS
============================================================
   Initial Capital:     ₹1,00,000
   Final Equity:        ₹1,00,000
   Total Return:        0.00%
   ...
   Total Trades:        0
============================================================
```

**Note**: Zero trades shown because PostgreSQL is not running. Once database is connected with historical data, you'll see actual trades.

---

## Troubleshooting

### Issue: "Connection refused" to PostgreSQL

**Solution**: Start PostgreSQL server
```bash
sudo systemctl start postgresql
```

### Issue: "No data found for symbol"

**Solutions**:
1. Check if table exists in database:
   ```sql
   \c spot_db_anamika
   \dt *aubank_eq*
   ```

2. Verify table has data:
   ```sql
   SELECT COUNT(*) FROM aubank_eq;
   ```

3. Check date range:
   ```sql
   SELECT MIN(date), MAX(date) FROM aubank_eq;
   ```

### Issue: "Insufficient data" warning

**Cause**: Not enough historical candles for strategy calculations.

**Solution**: 
- Increase `lookback_days` in config
- Ensure database has at least 100+ days of data

### Issue: Future dates in backtest

**Problem**: Using dates like `2026-01-01` (future)

**Solution**: Use historical dates only:
```yaml
start_date: "2024-01-01"
end_date: "2024-12-31"
```

### Issue: Wrong number of symbols

**Problem**: Backtest shows "5 total" when you expected different count

**Solution**: Check `config/backtest.user.yaml`:
- `watchlist` defines which symbols to test
- Set to specific symbols for faster testing: `["aubank_eq", "reliance_eq"]`
- Set to `["nifty_top_500"]` for full scan (500+ stocks)

### Issue: Backtest completes instantly (1 second)

**Cause**: PostgreSQL not running or no data available

**Solution**: 
1. Start PostgreSQL: `sudo systemctl start postgresql`
2. Verify data exists in database tables
3. Check logs for "Insufficient data" warnings

---

## Advanced Usage

### 1. Test Multiple Strategies

```bash
# Volume Support/Resistance
python src/backtesting_service/backtest_engine.py --strategy volume_support_resistance

# Add more strategies as needed
python src/backtesting_service/backtest_engine.py --strategy your_new_strategy
```

### 2. Optimize Parameters

Use the optimization engine:
```bash
python src/backtesting_service/optimization_engine.py \
  --strategy volume_support_resistance \
  --param volume_threshold --range 1.0,2.0 --steps 10
```

### 3. Export Trade Log

```python
import json
with open('data/outputs/backtesting/volumesupportresistance_metrics.json') as f:
    metrics = json.load(f)
    print(json.dumps(metrics['trades'], indent=2))
```

---

## Key Features Summary

| Feature | Implementation |
|---------|---------------|
| **Data Source** | PostgreSQL (`spot_db_anamika`) |
| **Config System** | `backtest.user.yaml` + `default/backtest.yaml` |
| **Sector Mapping** | `config/default/stock_list.yaml` (500+ stocks) |
| **Portfolio Mgmt** | Sector-based allocation, max 7 positions, 1 per sector |
| **Swing Trading** | Day-by-day simulation, 7-day max hold, 8% target, 4% stop |
| **Capital Flow** | Freed when positions close (like live trading) |
| **Output** | JSON metrics + PNG plots |

---

## Quick Start Checklist

- [ ] PostgreSQL running with stock data
- [ ] `config/backtest.user.yaml` configured (historical dates!)
- [ ] `config/default/stock_list.yaml` exists (already provided with 500+ stocks)
- [ ] Dependencies installed (`pip install -r requirements.txt`)
- [ ] Run backtest: `python src/backtesting_service/backtest_engine.py --strategy volume_support_resistance`
- [ ] Check results in `data/outputs/backtesting/`

---

## Support

For issues:
1. Check logs for error messages
2. Verify database connection
3. Ensure dates are historical (not future)
4. Confirm stock tables exist in database
