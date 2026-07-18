"""
Backtest Runner
===============
Run backtests for any strategy from the command line.

Usage:
    python -m src.backtesting_service test --strategy volume_support_resistance
    python src/backtesting_service/__main__.py test --strategy volume_support_resistance
"""

import sys
import os
import argparse
import importlib.util
import types

# ── Auto-detect project root ──
_THIS_FILE = os.path.abspath(__file__)
_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(
        os.path.dirname(_THIS_FILE)
    )
)

if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def _load_module_from_file(module_name: str, file_path: str):
    """Load a module directly from file path."""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


def load_strategy(strategy_name: str):
    """Load a strategy class by name."""
    strategy_map = {
        "volume_support_resistance": (
            "src.strategy_service.strategies.volume_support_resistance_strategy.strategy",
            "VolumeSupportResistanceStrategy",
            "src/strategy_service/strategies/volume_support_resistance_strategy/strategy.py"
        ),
        "support_resistance": (
            "src.strategy_service.strategies.volume_support_resistance_strategy.strategy",
            "VolumeSupportResistanceStrategy",
            "src/strategy_service/strategies/volume_support_resistance_strategy/strategy.py"
        ),
    }

    # Try to auto-discover if not in map
    if strategy_name not in strategy_map:
        # Look for strategy folder
        strategies_dir = os.path.join(_PROJECT_ROOT, "src", "strategy_service", "strategies")
        for folder in os.listdir(strategies_dir):
            folder_path = os.path.join(strategies_dir, folder)
            if os.path.isdir(folder_path) and strategy_name.replace("_", "") in folder.replace("_", ""):
                strategy_file = os.path.join(folder_path, "strategy.py")
                if os.path.exists(strategy_file):
                    # Try to extract class name from config
                    config_file = os.path.join(folder_path, "config.yaml")
                    class_name = None
                    if os.path.exists(config_file):
                        import yaml
                        with open(config_file, "r") as f:
                            cfg = yaml.safe_load(f)
                        class_name = cfg.get("class_name")
                    if not class_name:
                        # Guess from folder name
                        parts = folder.split("_")
                        class_name = "".join(p.capitalize() for p in parts) + "Strategy"

                    mod_name = f"src.strategy_service.strategies.{folder}.strategy"
                    strategy_map[strategy_name] = (mod_name, class_name, strategy_file)
                    break

    if strategy_name not in strategy_map:
        raise ValueError(f"Strategy '{strategy_name}' not found. Known: {list(strategy_map.keys())}")

    mod_name, class_name, file_path = strategy_map[strategy_name]

    # Pre-load strategy_base for relative imports
    base_file = os.path.join(_PROJECT_ROOT, "src", "strategy_service", "strategy_base.py")
    _load_module_from_file("src.strategy_service.strategy_base", base_file)

    # Ensure parent packages exist
    for pkg in ["src.strategy_service.strategies"]:
        if pkg not in sys.modules:
            sys.modules[pkg] = types.ModuleType(pkg)
            sys.modules[pkg].__path__ = []

    mod = _load_module_from_file(mod_name, os.path.join(_PROJECT_ROOT, file_path))
    return getattr(mod, class_name)


def run_backtest(strategy_name: str, symbols: list = None):
    """Run backtest for a strategy."""
    from backtest_engine import BacktestEngine, load_backtest_config

    # Load config
    config = load_backtest_config(_PROJECT_ROOT)

    # Load strategy
    StrategyClass = load_strategy(strategy_name)
    strategy = StrategyClass()

    # Run engine
    engine = BacktestEngine(
        strategy=strategy,
        config=config,
        project_root=_PROJECT_ROOT,
    )
    metrics = engine.run(symbols=symbols)
    return metrics


def main():
    parser = argparse.ArgumentParser(description="Backtest Runner")
    parser.add_argument("command", choices=["test", "run"], help="Command to run")
    parser.add_argument("--strategy", "-s", default="volume_support_resistance",
                        help="Strategy name (folder name or alias)")
    parser.add_argument("--symbols", nargs="+", default=None,
                        help="Override symbols to backtest")
    args = parser.parse_args()

    if args.command in ("test", "run"):
        run_backtest(args.strategy, symbols=args.symbols)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()