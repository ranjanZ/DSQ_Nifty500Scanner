"""
Test & Plot module for Volume Support/Resistance Strategy.

Run from ANY directory:
    python /path/to/DSQ_Nifty500Scanner/src/strategy_service/strategies/volume_support_resistance_strategy/__main__.py test
    python -m src.strategy_service.strategies.volume_support_resistance_strategy test
"""

import sys
import os
import importlib.util

# ── Auto-detect project root ──
_THIS_FILE = os.path.abspath(__file__)
_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(
        os.path.dirname(
            os.path.dirname(
                os.path.dirname(_THIS_FILE)
            )
        )
    )
)

if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def _load_module_from_file(module_name: str, file_path: str):
    """Load a module directly from file path — bypasses all parent __init__.py."""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


def run_test():
    """Test the Volume Support Resistance Strategy with DB data + snapshots."""
    print("🚀 Testing Volume Support/Resistance Strategy")
    print(f"📁 Project root: {_PROJECT_ROOT}")
    print("=" * 60)

    try:
        import pandas as pd
        import numpy as np
        import yaml
        from datetime import datetime, timedelta

        # ── Load config ──
        config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
        with open(config_path, "r") as f:
            cfg = yaml.safe_load(f)

        ds_cfg = cfg.get("data_source", {})
        snap_cfg = cfg.get("chart_display", {}).get("snapshot", {})
        params = cfg.get("params", {})

        symbol = ds_cfg.get("symbol", "aubank_eq")
        db_name = ds_cfg.get("db_name", "spot_db_anamika")
        days_back = ds_cfg.get("days_back", 120)
        num_back_signals = ds_cfg.get("num_back_signals", 30)

        snap_enabled = snap_cfg.get("enabled", True)
        snap_window = snap_cfg.get("window", 25)
        max_snapshots = snap_cfg.get("max_snapshots", 3)
        output_dir = snap_cfg.get("output_dir", "data/outputs/strategy_plots")
        output_dir = os.path.join(_PROJECT_ROOT, output_dir)
        os.makedirs(output_dir, exist_ok=True)

        # ── Load ALL modules directly from file — never touch parent __init__.py ──

        # 1. strategy_base (needed by strategy.py's relative import)
        base_file = os.path.join(_PROJECT_ROOT, "src", "strategy_service", "strategy_base.py")
        _load_module_from_file("src.strategy_service.strategy_base", base_file)

        # 2. strategy.py (the actual strategy class)
        strategy_file = os.path.join(
            _PROJECT_ROOT, "src", "strategy_service", "strategies",
            "volume_support_resistance_strategy", "strategy.py"
        )
        strategy_mod = _load_module_from_file(
            "src.strategy_service.strategies.volume_support_resistance_strategy.strategy",
            strategy_file
        )
        VolumeSupportResistanceStrategy = strategy_mod.VolumeSupportResistanceStrategy

        # 3. chart_plotter.py
        plotter_file = os.path.join(
            _PROJECT_ROOT, "src", "strategy_service", "utils", "chart_plotter.py"
        )
        plotter_mod = _load_module_from_file(
            "src.strategy_service.utils.chart_plotter", plotter_file
        )
        plot_signals = plotter_mod.plot_signals

        # 4. db_utils.py — loaded directly from known path at src/data_service/db_utils.py
        db_utils_file = os.path.join(_PROJECT_ROOT, "src", "data_service", "db_utils.py")
        db_utils_mod = _load_module_from_file("src.data_service.db_utils", db_utils_file)
        get_table_content = db_utils_mod.get_table_content

        # ── 1. Init strategy ──
        strategy = VolumeSupportResistanceStrategy(params)
        print(f"✅ Strategy initialized: {strategy.name}")
        print(f"   Parameters: {strategy.params}")

        # ── 2. Fetch data from DB ──
        print(f"\n📡 Fetching data from DB: {db_name}.{symbol}")
        data = None

        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days_back)
            data = get_table_content(
                db_name=db_name,
                table_name=symbol,
                start_date=start_date,
                end_date=end_date,
            )
    

            if data is None or len(data) == 0:
                print("⚠️  No data returned from DB.")
                data = None
            else:
                print(f"   ✅ Loaded {len(data)} rows from DB")
                data.rename(columns={'time': 'date'}, inplace=True)
        except Exception as e:
            print(f"   ⚠️  DB fetch failed: {e}")
            data = None

        if data is None:
            # Synthetic fallback
            print("   🧪 Generating synthetic data...")
            dates = pd.date_range(start="2024-01-01", periods=150, freq="D")
            np.random.seed(42)
            base = 1000
            prices = [base]
            for _ in range(1, 150):
                prices.append(prices[-1] + np.random.randn() * 8)
            data = pd.DataFrame({
                "date": dates,
                "open": prices,
                "high": [p + abs(np.random.randn() * 5) + 2 for p in prices],
                "low":  [p - abs(np.random.randn() * 5) - 2 for p in prices],
                "close": prices,
                "volume": np.random.randint(3000, 18000, 150),
            })
            data.loc[75:78, "volume"] = (data.loc[75:78, "volume"] * 2.5).astype(int)
            data.loc[110:113, "volume"] = (data.loc[110:113, "volume"] * 2.2).astype(int)

        print(f"📊 Data loaded: {len(data)} candles")
        if "date" in data.columns:
            print(f"   Range: {data['date'].min()} → {data['date'].max()}")

        # ── 3. Generate signals ──
        print("\n🔍 Generating signals...")
        signals = strategy.generate_signals(data, num_back_signals=num_back_signals)

        buy_cnt = (signals["signal"] == 1).sum()
        sell_cnt = (signals["signal"] == -1).sum()
        print(f"✅ Signals — Buy: {buy_cnt} | Sell: {sell_cnt}")

        if (signals["signal"] != 0).any():
            print("\n📈 Signal details:")
            print(
                signals[signals["signal"] != 0][
                    ["date", "close", "signal", "signal_strength", "volume_ratio"]
                ].to_string(index=False)
            )
        else:
            print("\n⚠️  No signals generated.")

        # ── 4. Plot snapshots around signals ──
        if snap_enabled and buy_cnt > 0:
            print(f"\n🎨 Generating up to {max_snapshots} snapshot(s) (±{snap_window} candles)...")

            signal_indices = signals[signals["signal"] == 1].index.tolist()
            snapshots_to_plot = signal_indices[:max_snapshots]

            for idx, sig_idx in enumerate(snapshots_to_plot, start=1):
                start_i = max(0, sig_idx - snap_window)
                end_i = min(len(signals), sig_idx + snap_window + 1)
                snap_df = signals.iloc[start_i:end_i].copy()

                sig_date = snap_df.loc[sig_idx, "date"] if "date" in snap_df.columns else f"idx_{sig_idx}"
                snap_title = f"{strategy.name} — {symbol} — Signal {idx} @ {sig_date}"
                snap_file = f"{symbol}_snapshot_{idx}.png"

                plot_signals(
                    snap_df,
                    strategy_name=strategy.name,
                    config_path=config_path,
                    plot_dir=output_dir,
                    filename=snap_file,
                    title=snap_title,
                    show=False,
                )
                print(f"   💾 Snapshot {idx}: {snap_file}")

        # Also save a full-overview chart (last 60 candles)
        print("\n🎨 Generating overview chart...")
        overview_df = signals.tail(60).copy()
        plot_signals(
            overview_df,
            strategy_name=strategy.name,
            config_path=config_path,
            plot_dir=output_dir,
            filename=f"{symbol}_overview.png",
            title=f"{strategy.name} — {symbol} — Last 60 candles",
            show=False,
        )
        print(f"   💾 Overview: {symbol}_overview.png")
        print(f"\n📁 All charts saved to: {output_dir}")

        print("\n" + "=" * 60)
        print("✅ Test completed successfully!")
        return True

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        success = run_test()
        sys.exit(0 if success else 1)
    else:
        print("Volume Support/Resistance Strategy")
        print("Usage:")
        print("  python -m src.strategy_service.strategies.volume_support_resistance_strategy test")
        print("  python src/strategy_service/strategies/volume_support_resistance_strategy/__main__.py test")