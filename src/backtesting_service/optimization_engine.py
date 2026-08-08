"""
Strategy Parameter Optimization Engine
======================================
Optimizes any strategy's parameters defined in its config.yaml.
Supports: grid, random, bayesian (Optuna), genetic, fast.
Saves all results to data/output/backtest_results/
"""

import os
import sys
import json
import yaml
import time
import pickle
import importlib.util
import types
import warnings
from typing import Dict, Any, List, Optional, Tuple, Callable
from datetime import datetime
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import pandas as pd

# Plotting
try:
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

# Optional Optuna for Bayesian
try:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    HAS_OPTUNA = True
except ImportError:
    HAS_OPTUNA = False

warnings.filterwarnings("ignore")


# ─────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────

@dataclass
class TrialResult:
    """Single optimization trial result."""
    trial_id: int
    params: Dict[str, Any]
    metrics: Dict[str, float]
    score: float
    elapsed_sec: float
    timestamp: str

    def to_dict(self) -> Dict:
        return {
            "trial_id": self.trial_id,
            **{f"param_{k}": v for k, v in self.params.items()},
            **{f"metric_{k}": v for k, v in self.metrics.items()},
            "score": self.score,
            "elapsed_sec": self.elapsed_sec,
            "timestamp": self.timestamp,
        }


# ─────────────────────────────────────────────────────────────────────
# Module loaders (bypass parent __init__.py)
# ─────────────────────────────────────────────────────────────────────

def _load_module_from_file(module_name: str, file_path: str):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _ensure_package(name: str):
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)
        sys.modules[name].__path__ = []


# ─────────────────────────────────────────────────────────────────────
# Config helpers
# ─────────────────────────────────────────────────────────────────────

def load_yaml(path: str) -> Dict:
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


def deep_merge(base: Dict, override: Dict) -> Dict:
    result = base.copy()
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result


# ─────────────────────────────────────────────────────────────────────
# Optimization Engine
# ─────────────────────────────────────────────────────────────────────

class StrategyOptimizer:
    """
    Strategy-agnostic parameter optimizer.
    """

    COLOR_BG = "#0d1117"
    COLOR_GRID = "#30363d"
    COLOR_TEXT = "#c9d1d9"
    COLOR_PRIMARY = "#58a6ff"
    COLOR_SECONDARY = "#f0883e"
    COLOR_BEST = "#3fb950"

    def __init__(
        self,
        project_root: str,
        opt_config_path: str,
        verbose: bool = True,
    ):
        self.project_root = project_root
        self.verbose = verbose
        self.opt_config = load_yaml(opt_config_path)

        # Resolve strategy info - only strategy_name required
        self.strategy_name = self.opt_config["optimization"]["strategy_name"]
        self.strategy_folder = f"{self.strategy_name}_strategy"
        self.strategy_config_path = os.path.join(
            project_root,
            f"src/strategy_service/strategies/{self.strategy_folder}/config.yaml"
        )

        # Load strategy config to get default params
        self.strategy_config = load_yaml(self.strategy_config_path)
        self.default_params = self.strategy_config.get("params", {})

        # Param space
        self.param_space = self.opt_config["optimization"]["param_space"]
        self.constraints = self.opt_config["optimization"].get("constraints", [])

        # Objective
        obj = self.opt_config["optimization"]["objective"]
        self.metric = obj["metric"]  # sharpe_ratio, total_return, max_drawdown, etc.
        self.direction = obj.get("direction", "maximize")

        # Algorithm
        algo = self.opt_config["optimization"]["algorithm"]
        self.algo_name = algo["name"]
        self.n_trials = algo.get("n_trials", 50)
        self.n_jobs = algo.get("n_jobs", 1)
        self.population_size = algo.get("population_size", 20)
        self.generations = algo.get("generations", 20)
        self.mutation_prob = algo.get("mutation_prob", 0.15)
        self.elite_ratio = algo.get("elite_ratio", 0.2)
        self.early_stop_patience = algo.get("early_stop_patience", 15)

        # Output
        out = self.opt_config["optimization"].get("output", {})
        self.save_all_results = out.get("save_all_results", True)
        self.save_plots = out.get("save_plots", True)
        self.output_dir = os.path.join(
            project_root, out.get("output_dir", "data/outputs/backtest_results")
        )
        self.run_id = f"{self.strategy_name}_{self.algo_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.run_dir = os.path.join(self.output_dir, self.run_id)
        os.makedirs(self.run_dir, exist_ok=True)

        # Results tracking
        self.results: List[TrialResult] = []
        self.best_result: Optional[TrialResult] = None
        self.trial_counter = 0

        # Load backtest engine
        self._load_backtest_engine()

    def _load_backtest_engine(self):
        """Load BacktestEngine directly from file."""
        bt_file = os.path.join(self.project_root, "src", "backtesting_service", "backtest_engine.py")
        if not os.path.exists(bt_file):
            raise FileNotFoundError(f"BacktestEngine not found: {bt_file}")
        bt_mod = _load_module_from_file("opt_backtest_engine", bt_file)
        self.BacktestEngine = bt_mod.BacktestEngine
        self.load_backtest_config = bt_mod.load_backtest_config

    def _load_strategy_class(self):
        """Load strategy class directly from file."""
        strategy_file = os.path.join(
            self.project_root, "src", "strategy_service", "strategies",
            self.strategy_folder, "strategy.py"
        )
        if not os.path.exists(strategy_file):
            raise FileNotFoundError(f"Strategy file not found: {strategy_file}")

        # Pre-load strategy_base
        base_file = os.path.join(self.project_root, "src", "strategy_service", "strategy_base.py")
        _load_module_from_file("src.strategy_service.strategy_base", base_file)
        _ensure_package("src.strategy_service")
        _ensure_package("src.strategy_service.strategies")
        _ensure_package(f"src.strategy_service.strategies.{self.strategy_folder}")

        mod = _load_module_from_file(
            f"src.strategy_service.strategies.{self.strategy_folder}.strategy",
            strategy_file
        )
        class_name = self.strategy_config.get("class_name", "VolumeSupportResistanceStrategy")
        if not hasattr(mod, class_name):
            available = [x for x in dir(mod) if not x.startswith("_")]
            raise AttributeError(f"Class '{class_name}' not found. Available: {available}")
        return getattr(mod, class_name)

    def _build_strategy(self, params: Dict[str, Any]):
        """Instantiate strategy with given params merged over defaults."""
        StrategyClass = self._load_strategy_class()
        merged = deep_merge(self.default_params, params)
        return StrategyClass(merged)

    def _build_backtest_config(self) -> Dict:
        """Load and merge backtest configs."""
        return self.load_backtest_config(self.project_root)

    def _check_constraints(self, params: Dict) -> bool:
        """Evaluate parameter constraints."""
        if not self.constraints:
            return True
        namespace = params.copy()
        for constraint in self.constraints:
            try:
                if not eval(constraint, {"__builtins__": {}}, namespace):
                    return False
            except Exception:
                return False
        return True

    def _sample_params(self, trial=None) -> Dict[str, Any]:
        """Sample parameters from param_space."""
        params = {}
        for name, spec in self.param_space.items():
            ptype = spec.get("type", "float")
            if trial is not None and HAS_OPTUNA:
                # Use Optuna's sampler
                if ptype == "int":
                    params[name] = trial.suggest_int(name, spec["low"], spec["high"])
                elif ptype == "float":
                    params[name] = trial.suggest_float(name, spec["low"], spec["high"])
                elif ptype == "categorical":
                    params[name] = trial.suggest_categorical(name, spec["choices"])
            else:
                # Random/manual sampling
                if ptype == "int":
                    params[name] = np.random.randint(spec["low"], spec["high"] + 1)
                elif ptype == "float":
                    params[name] = np.random.uniform(spec["low"], spec["high"])
                elif ptype == "categorical":
                    params[name] = np.random.choice(spec["choices"])
                else:
                    raise ValueError(f"Unknown param type: {ptype}")
        return params

    def _evaluate(self, params: Dict[str, Any]) -> Tuple[float, Dict[str, float], float]:
        """
        Run one backtest evaluation.
        Returns: (score, metrics_dict, elapsed_seconds)
        """
        start = time.time()
        self.trial_counter += 1
        trial_id = self.trial_counter

        try:
            strategy = self._build_strategy(params)
            config = self._build_backtest_config()

            engine = self.BacktestEngine(
                strategy=strategy,
                config=config,
                project_root=self.project_root,
            )
            metrics = engine.run()

            # Extract metric
            metric_map = {
                "sharpe_ratio": metrics.sharpe_ratio,
                "sortino_ratio": metrics.sortino_ratio,
                "total_return": metrics.total_return_pct,
                "max_drawdown": metrics.max_drawdown_pct,
                "win_rate": metrics.win_rate_pct,
                "profit_factor": metrics.profit_factor,
                "total_trades": metrics.total_trades,
            }

            raw_score = metric_map.get(self.metric, 0.0)

            # Handle direction
            if self.direction == "minimize":
                score = -raw_score
            else:
                score = raw_score

            metrics_dict = {
                "sharpe_ratio": metrics.sharpe_ratio,
                "sortino_ratio": metrics.sortino_ratio,
                "total_return_pct": metrics.total_return_pct,
                "annualized_return_pct": metrics.annualized_return_pct,
                "max_drawdown_pct": metrics.max_drawdown_pct,
                "win_rate_pct": metrics.win_rate_pct,
                "profit_factor": metrics.profit_factor,
                "avg_win_pct": metrics.avg_win_pct,
                "avg_loss_pct": metrics.avg_loss_pct,
                "total_trades": metrics.total_trades,
                "avg_holding_days": metrics.avg_holding_days,
            }

        except Exception as e:
            if self.verbose:
                print(f"   ⚠️  Trial {trial_id} failed: {e}")
            score = -np.inf if self.direction == "maximize" else np.inf
            metrics_dict = {}

        elapsed = time.time() - start

        result = TrialResult(
            trial_id=trial_id,
            params=params,
            metrics=metrics_dict,
            score=score,
            elapsed_sec=elapsed,
            timestamp=datetime.now().isoformat(),
        )
        self.results.append(result)

        # Track best
        is_better = False
        if self.best_result is None:
            is_better = True
        elif self.direction == "maximize" and score > self.best_result.score:
            is_better = True
        elif self.direction == "minimize" and score < self.best_result.score:
            is_better = True

        if is_better and np.isfinite(score):
            self.best_result = result
            if self.verbose:
                print(f"   🏆 New best! {self.metric}={score:.4f} | Params: {params}")

        return score, metrics_dict, elapsed

    # ── Algorithms ────────────────────────────────────────────────────

    def run_grid_search(self) -> pd.DataFrame:
        """Exhaustive grid search over param_space."""
        import itertools

        # Build value lists for each param
        grid_values = {}
        for name, spec in self.param_space.items():
            ptype = spec.get("type", "float")
            if ptype == "int":
                step = spec.get("step", max(1, (spec["high"] - spec["low"]) // 10))
                grid_values[name] = list(range(spec["low"], spec["high"] + 1, step))
            elif ptype == "float":
                n_points = spec.get("n_points", 5)
                grid_values[name] = np.linspace(spec["low"], spec["high"], n_points).tolist()
            elif ptype == "categorical":
                grid_values[name] = spec["choices"]

        keys = list(grid_values.keys())
        combos = list(itertools.product(*[grid_values[k] for k in keys]))
        total = len(combos)

        if self.verbose:
            print(f"\n🔍 Grid Search: {total} combinations")

        for i, combo in enumerate(combos):
            if self.verbose and (i + 1) % 10 == 0:
                print(f"   [{i+1}/{total}] ...")
            params = dict(zip(keys, combo))
            if not self._check_constraints(params):
                continue
            self._evaluate(params)

        return self._to_dataframe()

    def run_random_search(self) -> pd.DataFrame:
        """Random search over param_space."""
        if self.verbose:
            print(f"\n🎲 Random Search: {self.n_trials} trials")

        for i in range(self.n_trials):
            if self.verbose and (i + 1) % 10 == 0:
                print(f"   [{i+1}/{self.n_trials}] best={self.best_result.score:.4f if self.best_result else 'N/A'}")
            params = self._sample_params()
            if not self._check_constraints(params):
                continue
            self._evaluate(params)

        return self._to_dataframe()

    def run_fast_search(self) -> pd.DataFrame:
        """Fast random search with early stopping."""
        if self.verbose:
            print(f"\n⚡ Fast Search: max {self.n_trials} trials, patience={self.early_stop_patience}")

        best_score = -np.inf if self.direction == "maximize" else np.inf
        no_improve_count = 0

        for i in range(self.n_trials):
            params = self._sample_params()
            if not self._check_constraints(params):
                continue
            score, _, _ = self._evaluate(params)

            improved = False
            if self.direction == "maximize" and score > best_score:
                best_score = score
                improved = True
            elif self.direction == "minimize" and score < best_score:
                best_score = score
                improved = True

            if improved:
                no_improve_count = 0
                if self.verbose:
                    print(f"   [{i+1}] 🏆 New best {self.metric}={score:.4f}")
            else:
                no_improve_count += 1

            if no_improve_count >= self.early_stop_patience:
                if self.verbose:
                    print(f"   ⏹️  Early stop at trial {i+1} (no improvement for {self.early_stop_patience} trials)")
                break

        return self._to_dataframe()

    def run_bayesian(self) -> pd.DataFrame:
        """Bayesian optimization via Optuna."""
        if not HAS_OPTUNA:
            print("⚠️  Optuna not installed. Falling back to random search.")
            return self.run_random_search()

        if self.verbose:
            print(f"\n🧠 Bayesian Optimization: {self.n_trials} trials")

        def objective(trial):
            params = self._sample_params(trial)
            if not self._check_constraints(params):
                raise optuna.TrialPruned("Constraint violation")
            score, _, _ = self._evaluate(params)
            return score

        study = optuna.create_study(
            direction="maximize" if self.direction == "maximize" else "minimize"
        )
        study.optimize(objective, n_trials=self.n_trials, n_jobs=self.n_jobs, show_progress_bar=self.verbose)

        return self._to_dataframe()

    def run_genetic(self) -> pd.DataFrame:
        """Genetic algorithm optimization."""
        if self.verbose:
            print(f"\n🧬 Genetic Algorithm: pop={self.population_size}, gens={self.generations}")

        # Build bounds
        bounds = {}
        ptypes = {}
        for name, spec in self.param_space.items():
            ptype = spec.get("type", "float")
            ptypes[name] = ptype
            if ptype == "int":
                bounds[name] = (spec["low"], spec["high"])
            elif ptype == "float":
                bounds[name] = (spec["low"], spec["high"])
            elif ptype == "categorical":
                bounds[name] = (0, len(spec["choices"]) - 1)

        def decode(genome):
            params = {}
            for name in bounds:
                if ptypes[name] == "categorical":
                    idx = int(np.clip(round(genome[name]), bounds[name][0], bounds[name][1]))
                    params[name] = self.param_space[name]["choices"][idx]
                elif ptypes[name] == "int":
                    params[name] = int(round(np.clip(genome[name], bounds[name][0], bounds[name][1])))
                else:
                    params[name] = float(np.clip(genome[name], bounds[name][0], bounds[name][1]))
            return params

        def random_individual():
            ind = {}
            for name, (lo, hi) in bounds.items():
                if ptypes[name] == "categorical":
                    ind[name] = np.random.randint(lo, hi + 1)
                else:
                    ind[name] = np.random.uniform(lo, hi)
            return ind

        def crossover(a, b):
            child = {}
            for name in bounds:
                alpha = np.random.random()
                child[name] = alpha * a[name] + (1 - alpha) * b[name]
            return child

        def mutate(ind):
            for name, (lo, hi) in bounds.items():
                if np.random.random() < self.mutation_prob:
                    if ptypes[name] == "categorical":
                        ind[name] = np.random.randint(lo, hi + 1)
                    else:
                        sigma = (hi - lo) * 0.1
                        ind[name] = np.clip(ind[name] + np.random.normal(0, sigma), lo, hi)
            return ind

        # Initialize population
        population = [random_individual() for _ in range(self.population_size)]

        for gen in range(self.generations):
            # Evaluate
            scores = []
            for ind in population:
                params = decode(ind)
                if not self._check_constraints(params):
                    scores.append(-np.inf if self.direction == "maximize" else np.inf)
                    continue
                score, _, _ = self._evaluate(params)
                scores.append(score)

            # Sort
            sorted_idx = np.argsort(scores)[::-1] if self.direction == "maximize" else np.argsort(scores)
            population = [population[i] for i in sorted_idx]
            scores = [scores[i] for i in sorted_idx]

            if self.verbose:
                print(f"   Gen {gen+1}/{self.generations} | best={scores[0]:.4f} | avg={np.mean([s for s in scores if np.isfinite(s)]):.4f}")

            # Elite selection + crossover + mutation
            n_elite = max(1, int(self.elite_ratio * self.population_size))
            next_pop = population[:n_elite]
            while len(next_pop) < self.population_size:
                p1, p2 = np.random.choice(n_elite, size=2, replace=False)
                child = crossover(population[p1], population[p2])
                child = mutate(child)
                next_pop.append(child)
            population = next_pop

        return self._to_dataframe()

    # ── Results & Saving ──────────────────────────────────────────────

    def _to_dataframe(self) -> pd.DataFrame:
        """Convert results to DataFrame."""
        if not self.results:
            return pd.DataFrame()
        rows = [r.to_dict() for r in self.results]
        return pd.DataFrame(rows)

    def save_results(self):
        """Save all optimization outputs."""
        df = self._to_dataframe()
        if df.empty:
            print("⚠️  No results to save.")
            return

        # 1. Full results CSV
        csv_path = os.path.join(self.run_dir, "results.csv")
        df.to_csv(csv_path, index=False)
        if self.verbose:
            print(f"\n💾 Results CSV: {csv_path}")

        # 2. Best params YAML
        if self.best_result:
            best_path = os.path.join(self.run_dir, "best_params.yaml")
            best_data = {
                "strategy_name": self.strategy_name,
                "metric": self.metric,
                "direction": self.direction,
                "best_score": float(self.best_result.score),
                "best_params": self.best_result.params,
                "best_metrics": self.best_result.metrics,
                "trial_id": self.best_result.trial_id,
            }
            with open(best_path, "w") as f:
                yaml.dump(best_data, f, default_flow_style=False, sort_keys=False)
            if self.verbose:
                print(f"💾 Best params: {best_path}")

        # 3. Summary JSON
        summary = {
            "run_id": self.run_id,
            "strategy": self.strategy_name,
            "algorithm": self.algo_name,
            "metric": self.metric,
            "direction": self.direction,
            "n_trials": len(self.results),
            "best_score": float(self.best_result.score) if self.best_result else None,
            "best_params": self.best_result.params if self.best_result else None,
            "timestamp": datetime.now().isoformat(),
        }
        summary_path = os.path.join(self.run_dir, "summary.json")
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2, default=str)

        # 4. Plots
        if self.save_plots and HAS_MPL:
            self._plot_results(df)

    def _plot_results(self, df: pd.DataFrame):
        """Generate analysis plots."""
        if df.empty:
            return

        # Plot 1: Optimization history (score over trials)
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        fig.patch.set_facecolor(self.COLOR_BG)

        # History
        ax = axes[0, 0]
        ax.plot(df["trial_id"], df["score"], color=self.COLOR_PRIMARY, alpha=0.5, linewidth=0.8)
        ax.plot(df["trial_id"], df["score"].cummax() if self.direction == "maximize" else df["score"].cummin(),
                color=self.COLOR_BEST, linewidth=2, label="Best so far")
        ax.set_title("Optimization History", color=self.COLOR_TEXT)
        ax.set_xlabel("Trial", color=self.COLOR_TEXT)
        ax.set_ylabel(f"Score ({self.metric})", color=self.COLOR_TEXT)
        ax.legend()

        # Param distributions
        param_cols = [c for c in df.columns if c.startswith("param_")]
        n_params = min(len(param_cols), 6)  # Show up to 6 params
        n_rows = (n_params + 1) // 2  # 2 columns

        # Re-create figure with correct grid size
        fig.clf()
        fig, axes = plt.subplots(n_rows + 1, 2, figsize=(14, 3 * (n_rows + 1)))
        if n_rows == 0:
            axes = np.array([[axes]]) if not isinstance(axes, np.ndarray) else axes.reshape(1, -1)
        fig.patch.set_facecolor(self.COLOR_BG)

        # History plot (always in position 0,0)
        ax = axes[0, 0]
        ax.plot(df["trial_id"], df["score"], color=self.COLOR_PRIMARY, alpha=0.5, linewidth=0.8)
        ax.plot(df["trial_id"], df["score"].cummax() if self.direction == "maximize" else df["score"].cummin(),
                color=self.COLOR_BEST, linewidth=2, label="Best so far")
        ax.set_title("Optimization History", color=self.COLOR_TEXT)
        ax.set_xlabel("Trial", color=self.COLOR_TEXT)
        ax.set_ylabel(f"Score ({self.metric})", color=self.COLOR_TEXT)
        ax.legend()

        # Score distribution (position 0,1)
        ax = axes[0, 1]
        ax.hist(df["score"].replace([-np.inf, np.inf], np.nan).dropna(), bins=20,
                color=self.COLOR_SECONDARY, alpha=0.7, edgecolor=self.COLOR_GRID)
        ax.set_title("Score Distribution", color=self.COLOR_TEXT)
        ax.set_xlabel("Score", color=self.COLOR_TEXT)
        ax.set_ylabel("Count", color=self.COLOR_TEXT)

        # Param distributions
        for idx, col in enumerate(param_cols[:n_params]):
            row = (idx // 2) + 1
            col_idx = idx % 2
            if row < axes.shape[0]:
                ax = axes[row, col_idx]
                ax.hist(df[col].dropna(), bins=20, color=self.COLOR_SECONDARY, alpha=0.7, edgecolor=self.COLOR_GRID)
                ax.set_title(f"Distribution: {col.replace('param_', '')}", color=self.COLOR_TEXT)
                ax.set_xlabel("Value", color=self.COLOR_TEXT)
                ax.set_ylabel("Count", color=self.COLOR_TEXT)

        for ax in axes.flat:
            ax.set_facecolor(self.COLOR_BG)
            for spine in ax.spines.values():
                spine.set_color(self.COLOR_GRID)
            ax.tick_params(colors=self.COLOR_TEXT)
            ax.grid(True, alpha=0.2, color=self.COLOR_GRID, linestyle="--")

        plt.tight_layout()
        plot_path = os.path.join(self.run_dir, "optimization_analysis.png")
        plt.savefig(plot_path, dpi=150, facecolor=self.COLOR_BG, bbox_inches="tight")
        plt.close(fig)
        if self.verbose:
            print(f"💾 Analysis plot: {plot_path}")

        # Plot 2: Best run equity curve (if we re-run best)
        if self.best_result:
            self._plot_best_equity()

    def _plot_best_equity(self):
        """Re-run best params and plot equity curve."""
        try:
            strategy = self._build_strategy(self.best_result.params)
            config = self._build_backtest_config()
            engine = self.BacktestEngine(
                strategy=strategy, config=config, project_root=self.project_root, verbose=False
            )
            metrics = engine.run()

            # The engine should have equity curve data... if not, skip
            # For now, we plot a simple bar of metrics
            fig, ax = plt.subplots(figsize=(10, 6))
            fig.patch.set_facecolor(self.COLOR_BG)

            metric_names = ["total_return_pct", "sharpe_ratio", "max_drawdown_pct", "win_rate_pct"]
            values = [getattr(metrics, m, 0) for m in metric_names]
            colors = [self.COLOR_BEST if v >= 0 else self.COLOR_SECONDARY for v in values]
            bars = ax.bar([m.replace("_pct", "").replace("_", " ").title() for m in metric_names],
                          values, color=colors, edgecolor=self.COLOR_GRID)
            ax.axhline(0, color=self.COLOR_GRID, linewidth=0.5)
            ax.set_title(f"Best Run Metrics | {self.strategy_name}", color=self.COLOR_TEXT, fontsize=12)
            ax.set_ylabel("Value", color=self.COLOR_TEXT)

            for bar, val in zip(bars, values):
                ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
                        f"{val:.2f}", ha="center", va="bottom", color=self.COLOR_TEXT, fontsize=9)

            ax.set_facecolor(self.COLOR_BG)
            for spine in ax.spines.values():
                spine.set_color(self.COLOR_GRID)
            ax.tick_params(colors=self.COLOR_TEXT)
            ax.grid(True, alpha=0.2, color=self.COLOR_GRID, linestyle="--", axis="y")

            plt.tight_layout()
            plot_path = os.path.join(self.run_dir, "best_run_metrics.png")
            plt.savefig(plot_path, dpi=150, facecolor=self.COLOR_BG, bbox_inches="tight")
            plt.close(fig)
            if self.verbose:
                print(f"💾 Best run plot: {plot_path}")
        except Exception as e:
            if self.verbose:
                print(f"   ⚠️  Could not plot best run: {e}")

    # ── Main entry ──────────────────────────────────────────────────

    def run(self) -> pd.DataFrame:
        """Run the selected optimization algorithm."""
        if self.verbose:
            print("=" * 60)
            print("🔬 Strategy Parameter Optimization")
            print("=" * 60)
            print(f"   Strategy:  {self.strategy_name}")
            print(f"   Algorithm: {self.algo_name}")
            print(f"   Metric:    {self.metric} ({self.direction})")
            print(f"   Trials:    {self.n_trials}")
            print(f"   Output:    {self.run_dir}")
            print("=" * 60)

        if self.algo_name == "grid":
            df = self.run_grid_search()
        elif self.algo_name == "random":
            df = self.run_random_search()
        elif self.algo_name == "fast":
            df = self.run_fast_search()
        elif self.algo_name == "bayesian":
            df = self.run_bayesian()
        elif self.algo_name == "genetic":
            df = self.run_genetic()
        else:
            raise ValueError(f"Unknown algorithm: {self.algo_name}")

        # Save everything
        self.save_results()

        # Print summary
        if self.verbose and self.best_result:
            print("\n" + "=" * 60)
            print("🏆 OPTIMIZATION COMPLETE")
            print("=" * 60)
            print(f"   Best {self.metric}: {self.best_result.score:.4f}")
            print(f"   Trial ID: {self.best_result.trial_id}")
            print("   Best Parameters:")
            for k, v in self.best_result.params.items():
                print(f"      {k}: {v}")
            print("=" * 60)

        return df


# ═══════════════════════════════════════════════════════════════════════
# CLI Runner — runs when file is executed directly
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Strategy Parameter Optimizer")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "test"],
                        help="Command (default: run)")
    parser.add_argument("--config", "-c", default="config/optimization_config.yaml",
                        help="Path to optimization config YAML")
    parser.add_argument("--strategy", "-s", default=None,
                        help="Override strategy name")
    parser.add_argument("--algo", "-a", default=None,
                        choices=["grid", "random", "fast", "bayesian", "genetic"],
                        help="Override optimization algorithm")
    parser.add_argument("--trials", "-n", type=int, default=None,
                        help="Override number of trials")
    parser.add_argument("--metric", "-m", default=None,
                        help="Override objective metric (sharpe_ratio, total_return, max_drawdown, etc.)")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress verbose output")
    args = parser.parse_args()

    # Auto-detect project root from this file's location
    _PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)

    # Resolve config path
    config_path = args.config
    if not os.path.isabs(config_path):
        config_path = os.path.join(_PROJECT_ROOT, config_path)

    if not os.path.exists(config_path):
        print(f"❌ Config not found: {config_path}")
        print("   Create one from the example in src/optimization_service/optimization_config.yaml")
        sys.exit(1)

    # Load and apply CLI overrides
    cfg = load_yaml(config_path)
    if args.strategy:
        cfg["optimization"]["strategy_name"] = args.strategy
    if args.algo:
        cfg["optimization"]["algorithm"]["name"] = args.algo
    if args.trials:
        cfg["optimization"]["algorithm"]["n_trials"] = args.trials
    if args.metric:
        cfg["optimization"]["objective"]["metric"] = args.metric

    # Save temp config with overrides
    import tempfile
    fd, temp_path = tempfile.mkstemp(suffix=".yaml", prefix="opt_cfg_")
    with os.fdopen(fd, "w") as f:
        yaml.dump(cfg, f)

    try:
        optimizer = StrategyOptimizer(
            project_root=_PROJECT_ROOT,
            opt_config_path=temp_path,
            verbose=not args.quiet,
        )
        optimizer.run()
    finally:
        os.unlink(temp_path)

    print("\n✅ Optimization complete!")