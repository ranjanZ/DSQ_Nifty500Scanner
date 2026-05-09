#!/usr/bin/env python3
"""
Parameter Optimization for BacktestEngine
Supports: grid, random, Bayesian (Optuna), genetic algorithms.
Caches data, handles constraints, checkpointing, and plots best portfolio curve.
Now also handles malformed dates (e.g., '2026-0-04' -> '2026-01-04').
"""

import os
import sys
import json
import pickle
import itertools
import logging
import argparse
import tempfile
import signal
import re
from typing import Dict, List, Any, Optional, Union

import numpy as np
import pandas as pd
import yaml
from tqdm import tqdm

# Optional plot
try:
    import matplotlib.pyplot as plt
    HAS_PLT = True
except ImportError:
    HAS_PLT = False

# Import your backtest engine (adjust if needed)
from src.backtesting.backtest_offline import BacktestEngine

# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Global flag for graceful interruption
_interrupted = False

def signal_handler(sig, frame):
    global _interrupted
    _interrupted = True
    print("\n⚠️ Interrupted by user. Saving partial results...")

signal.signal(signal.SIGINT, signal_handler)


# ----------------------------------------------------------------------
# Helper: constraints evaluation
# ----------------------------------------------------------------------
def check_constraints(params: Dict, constraints: List[str]) -> bool:
    """Return True if all constraints are satisfied."""
    if not constraints:
        return True
    namespace = params.copy()
    for constraint in constraints:
        try:
            if not eval(constraint, {"__builtins__": {}}, namespace):
                return False
        except Exception:
            return False
    return True


# ----------------------------------------------------------------------
# Helper: normalise date strings
# ----------------------------------------------------------------------
def normalise_date_str(date_str: str) -> str:
    """Convert any date string to YYYY-MM-DD, fixing common mistakes like month=0."""
    if not isinstance(date_str, str):
        date_str = str(date_str)
    # If already YYYY-MM-DD, validate and fix month/day zeros
    match = re.match(r'(\d{4})-(\d{1,2})-(\d{1,2})', date_str)
    if match:
        y, m, d = int(match[1]), int(match[2]), int(match[3])
        if m == 0:
            m = 1
        if d == 0:
            d = 1
        return f"{y:04d}-{m:02d}-{d:02d}"
    # Use pandas to parse (handles many formats)
    try:
        dt = pd.to_datetime(date_str)
        return dt.strftime('%Y-%m-%d')
    except Exception as e:
        raise ValueError(f"Could not parse date '{date_str}': {e}")


# ----------------------------------------------------------------------
# Helper: create temporary backtest config with overrides (fixed date handling)
# ----------------------------------------------------------------------
def create_temp_backtest_config(original_config_path: str, overrides: Dict[str, Any]) -> str:
    """Copy original backtest config, apply overrides, normalise dates, return temp file path."""
    with open(original_config_path, 'r') as f:
        config = yaml.safe_load(f)
    if 'backtest' not in config:
        config = {'backtest': config}
    # Apply overrides
    for key, value in overrides.items():
        config['backtest'][key] = value

    # Normalise dates in the final config
    for date_key in ['start_date', 'end_date']:
        if date_key in config['backtest']:
            raw = config['backtest'][date_key]
            config['backtest'][date_key] = normalise_date_str(raw)

    fd, temp_path = tempfile.mkstemp(suffix='.yaml', prefix='backtest_override_')
    with os.fdopen(fd, 'w') as f:
        yaml.dump(config, f, default_flow_style=False)
    return temp_path


# ----------------------------------------------------------------------
# Cached Backtest Engine (reuses data across parameter sets)
# ----------------------------------------------------------------------
class CachedBacktestEngine(BacktestEngine):
    _CACHE = {}

    def __init__(self, yaml_config_path: str, backtest_yaml_config_path: str,
                 param_overrides: Optional[Dict[str, Any]] = None,
                 force_reload: bool = False):
        # Load base configs
        with open(yaml_config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        with open(backtest_yaml_config_path, 'r') as f:
            original_backtest_cfg = yaml.safe_load(f)
            if 'backtest' in original_backtest_cfg:
                original_backtest_cfg = original_backtest_cfg['backtest']
            self.backtest_cfg = original_backtest_cfg

        self.overridden_cfg = self.backtest_cfg.copy()
        if param_overrides:
            for k, v in param_overrides.items():
                if k in self.overridden_cfg:
                    self.overridden_cfg[k] = v

        # Build cache key (make lists hashable)
        watchlist_key = self.overridden_cfg.get('watchlist', [])
        if isinstance(watchlist_key, list):
            watchlist_key = tuple(watchlist_key)
        # Also normalise dates for cache key (use same function)
        start_date_norm = normalise_date_str(self.overridden_cfg.get('start_date', ''))
        end_date_norm = normalise_date_str(self.overridden_cfg.get('end_date', ''))
        cache_key = (
            watchlist_key,
            start_date_norm,
            end_date_norm,
            self.overridden_cfg.get('lookback_days', 0),
            yaml_config_path,
            frozenset(param_overrides.items()) if param_overrides else None
        )

        if not force_reload and cache_key in self._CACHE:
            cached = self._CACHE[cache_key]
            self.data_dict = cached['data_dict']
            self.signals_by_date = cached['signals_by_date']
            self.trading_days = cached['trading_days']
            self.stock_meta = cached['stock_meta']
            self.lookback_days = cached['lookback_days']
            self.scanner = cached['scanner']
            self.strategy_name = cached['strategy_name']
            logger.debug("Using cached data and signals.")
        else:
            temp_config_path = create_temp_backtest_config(backtest_yaml_config_path, self.overridden_cfg)
            try:
                super().__init__(yaml_config_path, temp_config_path)
            finally:
                os.unlink(temp_config_path)

            self._CACHE[cache_key] = {
                'data_dict': self.data_dict,
                'signals_by_date': self.signals_by_date,
                'trading_days': self.trading_days,
                'stock_meta': self.stock_meta,
                'lookback_days': self.lookback_days,
                'scanner': self.scanner,
                'strategy_name': self.strategy_name,
            }
            logger.info("Cached data and signals for future runs.")

        cached = self._CACHE[cache_key]
        self.data_dict = cached['data_dict']
        self.signals_by_date = cached['signals_by_date']
        self.trading_days = cached['trading_days']
        self.stock_meta = cached['stock_meta']
        self.lookback_days = cached['lookback_days']
        self.scanner = cached['scanner']
        self.strategy_name = cached['strategy_name']

        # Set parameters from overridden config
        self.initial_capital = float(self.overridden_cfg.get('initial_capital', 100000))
        self.target_profit = float(self.overridden_cfg.get('target_profit_pct', 0.08))
        self.stop_loss = float(self.overridden_cfg.get('stop_loss_pct', 0.04))
        self.max_hold_days = int(self.overridden_cfg.get('max_holding_days', 7))
        self.num_positions = self.overridden_cfg.get('position_weights', {}).get('max_positions', 10)
        self.start_date = self.trading_days[0]
        self.end_date = self.trading_days[-1]

        # Reset runtime state
        self.open_trades = []
        self.closed_trades = []
        self.total_capital = self.initial_capital
        self.portfolio_values = []


# ----------------------------------------------------------------------
# Objective function with exception handling
# ----------------------------------------------------------------------
def objective(params: Dict[str, Any], config: Dict[str, Any],
              metric: str = "sharpe", return_engine: bool = False):
    """Run backtest, return metric (or engine if return_engine=True)."""
    try:
        engine = CachedBacktestEngine(
            yaml_config_path=config['yaml_config'],
            backtest_yaml_config_path=config['backtest_config'],
            param_overrides=params,
            force_reload=config.get('force_reload', False)
        )
        engine.run()
        if return_engine:
            return engine
        metrics = engine.metrics()
        if metric == "sharpe":
            return metrics.get('Sharpe Ratio', -np.inf)
        elif metric == "return":
            return metrics.get('Total Return (%)', -np.inf)
        elif metric == "profit_factor":
            return metrics.get('Profit Factor', -np.inf)
        elif metric == "composite":
            sharpe = metrics.get('Sharpe Ratio', 0)
            winrate = metrics.get('Win Rate (%)', 0) / 100
            dd = metrics.get('Max Drawdown (%)', 0) / 100
            return sharpe + winrate - dd
        else:
            raise ValueError(f"Unknown metric: {metric}")
    except Exception as e:
        logger.warning(f"Evaluation failed for {params}: {e}")
        if return_engine:
            return None
        return -np.inf


# ----------------------------------------------------------------------
# Optimizer class (grid, random, bayesian, genetic)
# ----------------------------------------------------------------------
class Optimizer:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.param_grid = config.get('param_grid', {})
        self.param_ranges = config.get('param_ranges', {})
        self.constraints = config.get('param_constraints', [])
        self.objective_metric = config.get('objective_metric', 'sharpe')
        self.output_dir = config.get('output_dir', '.')
        self.checkpoint_interval = config.get('checkpoint_interval', 5)
        os.makedirs(self.output_dir, exist_ok=True)
        self._cat_choices = {}
        self.results = []       # list of dicts {param: value, 'score': float}

    def _evaluate(self, params: Dict) -> float:
        if not check_constraints(params, self.constraints):
            return -np.inf
        return objective(params, self.config, self.objective_metric)

    def _save_checkpoint(self, filename: str):
        if not self.results:
            return
        df = pd.DataFrame(self.results).sort_values('score', ascending=False)
        checkpoint_path = os.path.join(self.output_dir, filename)
        df.to_csv(checkpoint_path, index=False)
        logger.debug(f"Checkpoint saved to {checkpoint_path}")

    def grid_search(self) -> pd.DataFrame:
        if not self.param_grid:
            raise ValueError("param_grid required for grid search")
        keys = list(self.param_grid.keys())
        values = list(self.param_grid.values())
        combos = list(itertools.product(*values))
        total = len(combos)
        self.results = []
        pbar = tqdm(combos, desc=f"Grid search (0/{total})")
        for i, combo in enumerate(pbar):
            pbar.set_description(f"Grid search ({i+1}/{total})")
            if _interrupted:
                print("\nStopping grid search early...")
                break
            params = dict(zip(keys, combo))
            score = self._evaluate(params)
            self.results.append({**params, 'score': score})
            if (i+1) % self.checkpoint_interval == 0:
                self._save_checkpoint(f"results_grid_partial.csv")
        self._save_checkpoint("results_grid_partial.csv")
        df = pd.DataFrame(self.results).sort_values('score', ascending=False)
        return df

    def random_search(self, n_iter: int = 50) -> pd.DataFrame:
        from sklearn.model_selection import ParameterSampler
        param_dist = {}
        for name, rng in self.param_ranges.items():
            if isinstance(rng, dict) and 'low' in rng and 'high' in rng:
                if rng.get('type') == 'int':
                    param_dist[name] = list(range(rng['low'], rng['high']+1))
                else:
                    param_dist[name] = np.linspace(rng['low'], rng['high'], 100).tolist()
            elif isinstance(rng, list):
                param_dist[name] = rng
            else:
                raise ValueError(f"Invalid range for {name}: {rng}")
        sampler = list(ParameterSampler(param_dist, n_iter=n_iter, random_state=42))
        total = len(sampler)
        self.results = []
        pbar = tqdm(sampler, desc=f"Random search (0/{total})")
        for i, params in enumerate(pbar):
            pbar.set_description(f"Random search ({i+1}/{total})")
            if _interrupted:
                print("\nStopping random search early...")
                break
            params_converted = {k: float(v) if isinstance(v, np.floating) else int(v) for k, v in params.items()}
            score = self._evaluate(params_converted)
            self.results.append({**params_converted, 'score': score})
            if (i+1) % self.checkpoint_interval == 0:
                self._save_checkpoint("results_random_partial.csv")
        self._save_checkpoint("results_random_partial.csv")
        df = pd.DataFrame(self.results).sort_values('score', ascending=False)
        return df

    def bayesian_optimization(self, n_trials: int = 50) -> pd.DataFrame:
        import optuna
        self.results = []
        total = n_trials

        def callback(study, trial):
            if _interrupted:
                study.stop()
            params = trial.params
            score = trial.value
            if score is not None:
                self.results.append({**params, 'score': score})
            if len(self.results) % self.checkpoint_interval == 0:
                self._save_checkpoint("results_bayesian_partial.csv")
            print(f"Bayesian: trial {trial.number+1}/{total} | score: {score if score is not None else 'pruned'}")

        def objective(trial):
            params = {}
            for name, rng in self.param_ranges.items():
                if isinstance(rng, dict):
                    if rng.get('type') == 'int':
                        params[name] = trial.suggest_int(name, rng['low'], rng['high'])
                    else:
                        params[name] = trial.suggest_float(name, rng['low'], rng['high'])
                elif isinstance(rng, list):
                    params[name] = trial.suggest_categorical(name, rng)
                else:
                    raise ValueError(f"Invalid range for {name}")
            if not check_constraints(params, self.constraints):
                raise optuna.TrialPruned(f"Constraint violation: {params}")
            return self._evaluate(params)

        study = optuna.create_study(direction='maximize')
        try:
            study.optimize(objective, n_trials=total, n_jobs=1, callbacks=[callback])
        except KeyboardInterrupt:
            print("\nBayesian optimization interrupted.")
        finally:
            self._save_checkpoint("results_bayesian_partial.csv")

        # Ensure all trials that completed are in results
        for trial in study.trials:
            if trial.value is not None and not any(r['score'] == trial.value for r in self.results if r.get('score') == trial.value):
                self.results.append({**trial.params, 'score': trial.value})
        df = pd.DataFrame(self.results).sort_values('score', ascending=False)
        return df

    def genetic_algorithm(self, population_size: int = 20, generations: int = 20,
                          mutation_prob: float = 0.1, elite_ratio: float = 0.2) -> pd.DataFrame:
        # Build bounds and types
        bounds = {}
        types = {}
        for name, rng in self.param_ranges.items():
            if isinstance(rng, dict):
                bounds[name] = (rng['low'], rng['high'])
                types[name] = 'int' if rng.get('type') == 'int' else 'float'
            elif isinstance(rng, list):
                bounds[name] = (0, len(rng)-1)
                types[name] = 'categorical'
                self._cat_choices[name] = rng
            else:
                raise ValueError(f"Invalid range for {name}")

        def decode(genome):
            params = {}
            for name in bounds:
                if types[name] == 'categorical':
                    idx = int(np.clip(genome[name], 0, len(self._cat_choices[name])-1))
                    params[name] = self._cat_choices[name][idx]
                elif types[name] == 'int':
                    params[name] = int(round(genome[name]))
                else:
                    params[name] = genome[name]
            return params

        def random_individual():
            ind = {}
            for name, (lo, hi) in bounds.items():
                if types[name] == 'categorical':
                    ind[name] = np.random.randint(lo, hi+1)
                else:
                    ind[name] = np.random.uniform(lo, hi)
            return ind

        def crossover(a, b):
            child = {}
            for name in bounds:
                child[name] = (a[name] + b[name]) / 2
            return child

        def mutate(ind):
            for name, (lo, hi) in bounds.items():
                if np.random.rand() < mutation_prob:
                    if types[name] == 'categorical':
                        ind[name] = np.random.randint(lo, hi+1)
                    else:
                        sigma = (hi - lo) * 0.1
                        ind[name] = np.clip(ind[name] + np.random.normal(0, sigma), lo, hi)
            return ind

        population = [random_individual() for _ in range(population_size)]
        best_overall = None
        best_score = -np.inf
        self.results = []
        total_evals = 0

        for gen in range(generations):
            if _interrupted:
                print(f"\nStopping genetic algorithm at generation {gen}...")
                break
            scores = []
            for ind in population:
                params = decode(ind)
                sc = self._evaluate(params)
                scores.append(sc)
                self.results.append({**params, 'score': sc})
                total_evals += 1
                if sc > best_score:
                    best_score = sc
                    best_overall = ind.copy()
            print(f"Gen {gen+1}/{generations} | best score this gen: {max(scores):.4f} | total evals: {total_evals}")
            sorted_idx = np.argsort(scores)[::-1]
            population = [population[i] for i in sorted_idx]
            scores = [scores[i] for i in sorted_idx]
            n_elite = max(1, int(elite_ratio * population_size))
            next_pop = population[:n_elite]
            while len(next_pop) < population_size:
                parents_idx = np.random.choice(population_size//2, size=2, replace=False)
                child = crossover(population[parents_idx[0]], population[parents_idx[1]])
                child = mutate(child)
                next_pop.append(child)
            population = next_pop
            if (gen+1) % self.checkpoint_interval == 0:
                self._save_checkpoint("results_genetic_partial.csv")

        if best_overall is not None:
            best_params = decode(best_overall)
            final_score = self._evaluate(best_params)
            if not any(r['score'] == final_score for r in self.results):
                self.results.append({**best_params, 'score': final_score})
        self._save_checkpoint("results_genetic_partial.csv")
        df = pd.DataFrame(self.results)
        if not df.empty:
            df = df.drop_duplicates(subset=[c for c in df.columns if c != 'score'], keep='first')
            df = df.sort_values('score', ascending=False)
        return df


# ----------------------------------------------------------------------
# Plotting function
# ----------------------------------------------------------------------
def plot_best_curve(best_params: Dict, config: Dict, trading_days: int):
    """Run backtest with best params and plot portfolio value over time."""
    if not HAS_PLT:
        print("matplotlib not installed; cannot plot.")
        return
    print("\n📊 Generating portfolio value curve for best parameters...")
    engine = objective(best_params, config, return_engine=True)
    if engine is None:
        print("Failed to run backtest for best parameters.")
        return
    if not hasattr(engine, 'portfolio_values') or not engine.portfolio_values:
        print("No portfolio values found.")
        return
    df = pd.DataFrame(engine.portfolio_values, columns=['date', 'portfolio_value'])
    plt.figure(figsize=(12, 6))
    plt.plot(df['date'], df['portfolio_value'], linewidth=2, color='blue')
    title = f'Portfolio Value Over Time (Trading Days: {trading_days})\nParams: '
    title += f'target={best_params["target_profit_pct"]:.3f}, stop={best_params["stop_loss_pct"]:.3f}, days={best_params["max_holding_days"]}'
    plt.title(title)
    plt.xlabel('Date')
    plt.ylabel('Portfolio Value (₹)')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plot_path = os.path.join(config.get('output_dir', '.'), 'best_portfolio_curve.png')
    plt.savefig(plot_path, dpi=150)
    print(f"✅ Plot saved to {plot_path}")
    plt.show()


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def load_optimization_config(config_path: str) -> Dict:
    with open(config_path, 'r') as f:
        if config_path.endswith('.yaml') or config_path.endswith('.yml'):
            return yaml.safe_load(f)
        else:
            return json.load(f)

def main():
    parser = argparse.ArgumentParser(description='Optimize BacktestEngine parameters')
    parser.add_argument('--config', type=str, default='config/optimization_config.yaml',
                        help='Path to configuration file (YAML/JSON)')
    parser.add_argument('--method', type=str, default='bayesian',
                        choices=['grid', 'random', 'bayesian', 'genetic'],
                        help='Optimization method')
    parser.add_argument('--trials', type=int, default=50,
                        help='Number of trials/generations')
    parser.add_argument('--checkpoint_interval', type=int, default=5,
                        help='Save partial results every N evaluations')
    args = parser.parse_args()

    if not os.path.exists(args.config):
        print(f"ERROR: Configuration file not found: {args.config}")
        sys.exit(1)

    config = load_optimization_config(args.config)
    config['method'] = args.method
    config['trials'] = args.trials
    config['checkpoint_interval'] = args.checkpoint_interval

    required = ['yaml_config', 'backtest_config']
    missing = [k for k in required if k not in config]
    if missing:
        print(f"ERROR: Missing required keys: {missing}")
        sys.exit(1)

    # Get trading days count (using a dummy engine)
    dummy = CachedBacktestEngine(config['yaml_config'], config['backtest_config'],
                                 param_overrides={}, force_reload=False)
    trading_days = len(dummy.trading_days)
    print(f"\n📅 Backtest period covers {trading_days} trading days.\n")

    optimizer = Optimizer(config)
    method = config['method']

    try:
        if method == 'grid':
            if 'param_grid' not in config:
                print("ERROR: param_grid required for grid search")
                sys.exit(1)
            results_df = optimizer.grid_search()
        elif method == 'random':
            results_df = optimizer.random_search(n_iter=config.get('trials', 50))
        elif method == 'bayesian':
            results_df = optimizer.bayesian_optimization(n_trials=config.get('trials', 50))
        elif method == 'genetic':
            pop = config.get('population_size', 20)
            gens = config.get('trials', 20)
            results_df = optimizer.genetic_algorithm(population_size=pop, generations=gens)
        else:
            print(f"ERROR: Unknown method: {method}")
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n⚠️ Optimization interrupted by user.")
        partial_file = os.path.join(optimizer.output_dir, f"results_{method}_partial.csv")
        if os.path.exists(partial_file):
            results_df = pd.read_csv(partial_file).sort_values('score', ascending=False)
            print(f"Loaded partial results from {partial_file}")
        else:
            results_df = pd.DataFrame(optimizer.results).sort_values('score', ascending=False) if optimizer.results else pd.DataFrame()
    else:
        output_file = os.path.join(optimizer.output_dir, f"results_{method}.csv")
        results_df.to_csv(output_file, index=False)
        print(f"\n✅ Final results saved to {output_file}")

    if not results_df.empty:
        best_row = results_df.iloc[0]
        best_params = {col: best_row[col] for col in results_df.columns if col != 'score'}
        print("\n🏆 Best parameters found:")
        print(f"Score ({optimizer.objective_metric}): {best_row['score']:.4f}")
        for k, v in best_params.items():
            print(f"  {k}: {v}")
        plot_best_curve(best_params, config, trading_days)
    else:
        print("No results were collected.")


if __name__ == "__main__":
    main()