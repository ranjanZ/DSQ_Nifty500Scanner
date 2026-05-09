import pandas as pd
import numpy as np
from typing import Dict, Any, List
import matplotlib.pyplot as plt
from strategy.strategy_base import TradingStrategy


class RSIWPatternStrategy(TradingStrategy):
    """
    RSI W-Pattern Strategy
    Buy signal when RSI crosses above the middle peak of W pattern
    """
    
    def __init__(self, params: Dict[str, Any] = None):
        # Default parameters
        default_params = {
            'rsi_period': 14,
            'oversold': 30,
            'overbought': 70,
            'min_improvement': 1.5,      # Min RSI improvement between bottoms
            'lookback_period': 30,       # How far back to look for pattern
            'tolerance_pct': 0.05,       # Tolerance for matching peaks/bottoms
        }
        
        if params:
            default_params.update(params)
        
        super().__init__(name="RSI_W_Pattern", params=default_params)
    
    def calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """Calculate RSI"""
        delta = prices.diff()
        gain = delta.where(delta > 0, 0).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))
    
    def find_pattern_points(self, rsi_values: pd.Series) -> Dict[str, Any]:
        """
        Find W pattern points in RSI:
        - First bottom (B1)
        - Middle peak (P)
        - Second bottom (B2)
        Returns positions and values
        """
        values = rsi_values.values
        n = len(values)
        
        if n < 10:
            return {'found': False, 'reason': 'Not enough data'}
        
        # Find local minima (bottoms) and maxima (peaks)
        bottoms = []
        peaks = []
        
        for i in range(2, n - 2):
            # Local minima (bottom)
            if (values[i] < values[i-1] and values[i] < values[i-2] and
                values[i] < values[i+1] and values[i] < values[i+2]):
                bottoms.append({'idx': i, 'value': values[i]})
            
            # Local maxima (peak)
            if (values[i] > values[i-1] and values[i] > values[i-2] and
                values[i] > values[i+1] and values[i] > values[i+2]):
                peaks.append({'idx': i, 'value': values[i]})
        
        if len(bottoms) < 2 or len(peaks) < 1:
            return {'found': False, 'reason': 'Not enough pattern points'}
        
        # Sort by index
        bottoms.sort(key=lambda x: x['idx'])
        peaks.sort(key=lambda x: x['idx'])
        
        # Find W pattern: Bottom-Peak-Bottom
        for i in range(len(bottoms) - 1):
            b1 = bottoms[i]
            b2 = bottoms[i + 1]
            
            # Find peak between these two bottoms
            middle_peaks = [p for p in peaks if b1['idx'] < p['idx'] < b2['idx']]
            
            if not middle_peaks:
                continue
            
            # Take the highest peak in between
            middle_peak = max(middle_peaks, key=lambda x: x['value'])
            
            # W pattern conditions:
            # 1. Second bottom should be higher than first (bullish)
            if b2['value'] <= b1['value']:
                continue
            
            # 2. Minimum improvement
            improvement = b2['value'] - b1['value']
            if improvement < self.params['min_improvement']:
                continue
            
            # 3. Check if bottoms are reasonable (not too low)
            if b1['value'] < self.params['oversold'] or b2['value'] < self.params['oversold']:
                continue
            
            return {
                'found': True,
                'b1': b1,
                'b2': b2,
                'middle_peak': middle_peak,
                'improvement': improvement,
                'pattern_length': b2['idx'] - b1['idx']
            }
        
        return {'found': False, 'reason': 'No valid W pattern found'}
    
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Generate signals when RSI crosses above the middle peak
        of a W pattern (completes the pattern)
        """
        df = data.copy()
        
        # Calculate RSI
        df['rsi'] = self.calculate_rsi(df['close'], self.params['rsi_period'])
        
        # Initialize signal columns
        df['signal'] = 0
        df['signal_strength'] = 0.0
        df['pattern_found'] = False
        
        # Skip early periods
        start_idx = max(self.params['rsi_period'] + 20, 30)
        
        for i in range(start_idx, len(df)):
            # Get RSI history up to current point
            rsi_history = df['rsi'].iloc[:i+1]
            
            # Find W pattern
            pattern = self.find_pattern_points(rsi_history)
            
            if not pattern['found']:
                continue
            
            # Get pattern points
            middle_peak = pattern['middle_peak']
            b2 = pattern['b2']  # Second bottom
            
            # Current RSI position relative to pattern
            current_pos = i
            b2_pos = b2['idx']
            
            # We're past the second bottom
            if current_pos > b2_pos:
                # Get RSI values after second bottom
                idx_start = b2_pos + 1
                idx_end = current_pos
                
                # Check if RSI has crossed above the middle peak since second bottom
                crossed_above_peak = False
                for j in range(idx_start, idx_end + 1):
                    if j < len(rsi_history):
                        if rsi_history.iloc[j] > middle_peak['value']:
                            # This is where it first crossed
                            if j == current_pos:  # Current candle is the cross
                                crossed_above_peak = True
                                break
                
                # Generate signal if just crossed above middle peak
                if crossed_above_peak:
                    # Calculate signal strength based on pattern quality
                    improvement = pattern['improvement']
                    strength = min(1.0, improvement / 5)  # Normalize
                    
                    df.at[df.index[i], 'signal'] = 1
                    df.at[df.index[i], 'signal_strength'] = strength
                    df.at[df.index[i], 'pattern_found'] = True
                    
                    # Store pattern details
                    df.at[df.index[i], 'b1_value'] = pattern['b1']['value']
                    df.at[df.index[i], 'b2_value'] = pattern['b2']['value']
                    df.at[df.index[i], 'middle_peak'] = middle_peak['value']
                    df.at[df.index[i], 'improvement'] = improvement
        
        return df
    
    def plot_signals(self, df: pd.DataFrame):
        """
        Plot RSI with W pattern and signals
        """
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), height_ratios=[2, 1])
        
        # 1. Price chart
        ax1.plot(df.index, df['close'], 'b-', linewidth=1.5, label='Price')
        
        # Mark buy signals
        buy_signals = df[df['signal'] == 1]
        if not buy_signals.empty:
            for idx, row in buy_signals.iterrows():
                ax1.scatter(idx, row['close'], 
                           color='gold', s=200, marker='^', 
                           edgecolors='black', linewidth=2, zorder=5)
        
        ax1.set_ylabel('Price', fontsize=12)
        ax1.set_title('RSI W-Pattern Strategy - Buy on Pattern Completion', fontsize=14, fontweight='bold')
        ax1.grid(True, alpha=0.3)
        ax1.legend(['Price', 'BUY Signal'], loc='upper left')
        
        # 2. RSI chart
        if 'rsi' in df.columns:
            ax2.plot(df.index, df['rsi'], 'purple', linewidth=2, label='RSI')
            
            # Mark pattern points and signals
            if not buy_signals.empty:
                # For each buy signal, show the W pattern
                for idx, row in buy_signals.tail(3).iterrows():  # Show last 3 patterns
                    if 'b1_value' in df.columns and 'b2_value' in df.columns and 'middle_peak' in df.columns:
                        # Draw W pattern lines
                        # Find pattern points in recent history
                        pattern_start_idx = max(0, df.index.get_loc(idx) - 40)
                        pattern_df = df.iloc[pattern_start_idx:df.index.get_loc(idx)+1]
                        
                        # Highlight the W shape
                        rsi_vals = pattern_df['rsi'].values
                        rsi_idx = pattern_df.index
                        
                        # Find the actual pattern points around the signal
                        if len(rsi_vals) > 10:
                            # Simple highlight of the W shape
                            ax2.plot(rsi_idx, rsi_vals, 'orange', linewidth=3, alpha=0.5)
                            
                            # Mark the signal point
                            ax2.plot(idx, row['rsi'], 'go', markersize=12, 
                                    markeredgecolor='black', linewidth=2,
                                    label='Pattern Complete' if idx == buy_signals.index[0] else "")
            
            # RSI reference lines
            ax2.axhline(y=50, color='gray', linestyle='--', alpha=0.5, label='Mid (50)')
            ax2.axhline(y=self.params['oversold'], color='red', linestyle='--', alpha=0.5)
            ax2.axhline(y=self.params['overbought'], color='green', linestyle='--', alpha=0.5)
            
            # Fill zones
            ax2.fill_between(df.index, 0, self.params['oversold'], alpha=0.1, color='red')
            ax2.fill_between(df.index, self.params['overbought'], 100, alpha=0.1, color='green')
            
            ax2.set_ylabel('RSI', fontsize=12)
            ax2.set_xlabel('Date', fontsize=12)
            ax2.set_ylim(0, 100)
            ax2.legend(loc='upper left')
            ax2.grid(True, alpha=0.3)
        
        # Statistics
        total_signals = len(buy_signals)
        if total_signals > 0:
            latest_signal = buy_signals.iloc[-1]
            stats_text = f"Total Buy Signals: {total_signals}\n"
            
            if 'b1_value' in latest_signal and 'b2_value' in latest_signal:
                stats_text += f"B1: {latest_signal['b1_value']:.1f}, B2: {latest_signal['b2_value']:.1f}\n"
                stats_text += f"Improvement: {latest_signal.get('improvement', 0):.1f}"
            
            ax1.text(0.02, 0.98, stats_text, transform=ax1.transAxes,
                    fontsize=10, verticalalignment='top',
                    bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))
        
        plt.tight_layout()
        plt.show()
    
    def explain_pattern(self, df: pd.DataFrame, signal_idx):
        """
        Explain the W pattern for a specific signal
        """
        if signal_idx not in df.index:
            return "Signal not found"
        
        signal_row = df.loc[signal_idx]
        
        if signal_row['signal'] != 1:
            return "Not a buy signal"
        
        explanation = "🔍 W-Pattern Analysis:\n"
        explanation += "=" * 30 + "\n"
        
        if 'b1_value' in df.columns and 'b2_value' in df.columns:
            explanation += f"First Bottom (B1): RSI {signal_row['b1_value']:.1f}\n"
            explanation += f"Second Bottom (B2): RSI {signal_row['b2_value']:.1f}\n"
            
            if 'middle_peak' in df.columns:
                explanation += f"Middle Peak: RSI {signal_row['middle_peak']:.1f}\n"
            
            if 'improvement' in df.columns:
                improvement = signal_row['improvement']
                explanation += f"Improvement (B2-B1): +{improvement:.1f}\n"
                explanation += f"Pattern Quality: {'Strong' if improvement > 3 else 'Moderate' if improvement > 1.5 else 'Weak'}\n"
        
        explanation += f"\nSignal Trigger:\n"
        explanation += f"RSI crossed above middle peak at {signal_row['rsi']:.1f}\n"
        explanation += f"Price: ₹{signal_row['close']:.2f}"
        
        return explanation

# Example usage
if __name__ == "__main__":
    from utils.db_utils import get_table_content
    from datetime import datetime, timedelta
    
    # Load data
    end_date = datetime.now()
    start_date = end_date - timedelta(days=200)
    
    data=get_table_content(
                db_name='spot_db_anamika',
                table_name="ablbl_eq",
                start_date=start_date,
                end_date=end_date
            )

    # Create strategy
    strategy = RSIWPatternStrategy({
        'rsi_period': 14,
        'neckline': 50,
        'lookback_period': 40
    })
    
    # Generate signals
    signals = strategy.generate_signals(data)
    
    # Plot
    strategy.plot_signals(signals)
    
    # Show summary
    buy_signals = signals[signals['signal'] == 1]
    print(f"📊 RSI W-Pattern Strategy")
    print(f"📈 Total candles: {len(signals)}")
    print(f"✅ Buy signals: {len(buy_signals)}")
    
    if not buy_signals.empty:
        print("\n📋 Buy Signals:")
        for idx, row in buy_signals.tail(5).iterrows():
            print(f"  {idx.date() if hasattr(idx, 'date') else idx}: "
                  f"Price: ₹{row['close']:.2f}, "
                  f"RSI: {row['rsi']:.1f}")
    
    # Latest signal
    if len(buy_signals) > 0:
        latest = buy_signals.iloc[-1]
        print(f"\n🎯 Latest BUY Signal:")
        print(f"  RSI crossed above 50 at ₹{latest['close']:.2f}")        