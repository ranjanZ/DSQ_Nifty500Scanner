# Backtesting Service - Complete Setup & Usage Guide

## Overview

This guide explains how to run backtests for the **Volume Support/Resistance Strategy** using the existing infrastructure. The system:

1. ✅ **Reads data from PostgreSQL database** (`spot_db_anamika`)
2. ✅ **Uses `config/backtest.user.yaml`** for user overrides
3. ✅ **Uses `config/default/stock_list.yaml`** for sector mapping (NOT cache files)
4. ✅ **Implements swing trading with portfolio management** (sector-based allocation, max positions)

---

## Prerequisites

### 1. Install Dependencies

```bash
cd /workspace
pip install -r requirements.txt
```

Required packages:
- `pandas`, `numpy` - Data manipulation
- `matplotlib` - Plotting
- `pyyaml` - Config loading
- `scikit-learn` - KDE for support/resistance levels
- `psycopg2-binary` - PostgreSQL connection

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
  
  initial_capital: 10000
  target_profit_pct: 0.08           # 8% target
  stop_loss_pct: 0.04               # 4% stop loss
  max_holding_days: 7               # Swing trading horizon

  # Portfolio Management
  position_weights:
    method: "sector_based"
    max_positions: 7                # Max concurrent positions
    max_per_sector: 1               # Only 1 stock per sector
    sector_allocation:
      "Financial Services": 0.3
      "Capital Goods": 0.2
      "Healthcare": 0.2
      # ... other sectors
```

### 2. Stock List: `config/default/stock_list.yaml`

Contains **500+ stocks** with sector mappings:
```yaml
watchlists:
  nifty_top_500:
    - name: "AU SMALL FINANCE BANK LTD"
      fyers_symbol: NSE:AUBANK-EQ
      sector: Financial Services
    - name: "RELIANCE INDUSTRIES LIMITED"
      fyers_symbol: NSE:RELIANCE-EQ
      sector: Oil Gas & Consumable Fuels
```

The backtest engine automatically converts:
- `NSE:AUBANK-EQ` → `aubank_eq` (database table name)
- Maps to sector: `Financial Services`

### 3. Strategy Config: `src/strategy_service/strategies/volume_support_resistance_strategy/config.yaml`

Strategy-specific parameters:
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

### Method 2: Specify Custom Symbols

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

---

## Swing Trading Workflow with Portfolio Management

### Daily Scan Process

1. **Strategy Scans All Stocks** (e.g., Nifty 500)
   ```python
   # Each day, strategy generates buy signals
   signals = strategy.generate_signals(df)
   ```

2. **Rank Signals by Strength**
   - Volume ratio
   - KDE level confluence
   - Pivot point alignment

3. **Portfolio Management Filters**
   ```yaml
   max_positions: 7        # Only take top 7 signals
   max_per_sector: 1       # Diversify across sectors
   ```

4. **Sector-Based Capital Allocation**
   ```python
   # Example allocation (₹10,000 capital)
   Financial Services: 30% → ₹3,000
   Capital Goods: 20%      → ₹2,000
   Healthcare: 20%         → ₹2,000
   # ... etc
   ```

5. **Position Sizing**
   ```python
   # For each selected stock
   qty = capital_allocated / entry_price
   ```

6. **Exit Rules**
   - **Target**: 8% profit
   - **Stop Loss**: 4% loss
   - **Max Hold**: 7 days (swing trading)

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
- Trade statistics

### 2. Equity Curve Plot
```
data/outputs/backtesting/volumesupportresistance_equity_curve.png
```

Shows:
- Equity growth over time
- Drawdown periods
- Benchmark comparison

### 3. Sector Breakdown Plot
```
data/outputs/backtesting/volumesupportresistance_sector_breakdown.png
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
   Capital: ₹10,000
   Symbols: 5 total, 3 active
   Target: 8.0% | Stop: 4.0% | Max Hold: 7d
   Allocation: Sector-based (max_pos=7, max_per_sector=1)
============================================================

📈 aubank_eq (sector: Financial Services, alloc: ₹10,000)
   ✓ Loaded 250 candles
   ✓ Generated 15 signals
   ✓ Executed 12 trades

📈 reliance_eq (sector: Oil Gas & Consumable Fuels, alloc: ₹0)
   ⚠️  Insufficient data

📈 infy_eq (sector: Information Technology, alloc: ₹0)
   ⚠️  Insufficient data

============================================================
📊 BACKTEST RESULTS
============================================================
   Initial Capital:     ₹10,000
   Final Equity:        ₹12,450
   Total Return:        24.50%
   Annualized Return:   24.50%
   Sharpe Ratio:        1.85
   Sortino Ratio:       2.31
   Max Drawdown:        8.20%
   Win Rate:            66.67%
   Profit Factor:       2.15
   Avg Win:             5.20%
   Avg Loss:            -3.10%
   Total Trades:        12
   Avg Holding Days:    4.5
============================================================

📂 SECTOR-WISE BREAKDOWN
------------------------------------------------------------
Sector                              Trades    Win%    P&L (₹)    Avg P&L
------------------------------------------------------------
Financial Services                      8      75.0      2,100        263
Capital Goods                           3      66.7        650        217
Healthcare                              1      0.0         -300       -300
------------------------------------------------------------
============================================================
   💾 Metrics JSON: /workspace/data/outputs/backtesting/volumesupportresistance_metrics.json

✅ Backtest complete!
```

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

### Issue: Wrong sector allocation

**Check**: Verify `config/default/stock_list.yaml` has correct sector mappings

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
| **Portfolio Mgmt** | Sector-based allocation, max positions |
| **Swing Trading** | 7-day max hold, 8% target, 4% stop |
| **Output** | JSON metrics + PNG plots |

---

## Quick Start Checklist

- [ ] PostgreSQL running with stock data
- [ ] `config/backtest.user.yaml` configured (historical dates!)
- [ ] `config/default/stock_list.yaml` exists (already provided)
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
