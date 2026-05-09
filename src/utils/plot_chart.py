import pandas as pd

def plot_signals(df: pd.DataFrame):
    """Candlestick plot with volume EMA and S/R levels - ALL DATA"""
    import mplfinance as mpf
    import pandas as pd
    
    # Convert index if needed
    plot_df = df.copy()
    if not isinstance(plot_df.index, pd.DatetimeIndex):
        plot_df.index = pd.to_datetime(plot_df.index)
    
    # Use ALL data
    plot_data = plot_df.copy()
    
    # Prepare addplots
    apds = []
    
    # 1. Volume EMA line
    if 'volume_ema' in plot_data.columns:
        apds.append(mpf.make_addplot(plot_data['volume_ema'], 
                                    panel=1,  # Volume panel
                                    color='orange',
                                    width=1.5,
                                    label='Volume EMA'))
    
    # 2. Support levels (horizontal lines - use last day's levels for entire plot)
    if 'support_levels' in plot_data.columns:
        # Get last day's support levels
        last_support = plot_data['support_levels'].iloc[-1]
        for level in last_support[:3]:  # Top 3 support levels
            # Create horizontal line across entire timeline
            line = pd.Series([level] * len(plot_data), index=plot_data.index)
            apds.append(mpf.make_addplot(line, 
                                        color='blue', 
                                        linestyle='--',
                                        alpha=0.5,
                                        label=f'Support ${level:.2f}'))
    
    # 3. Resistance levels (horizontal lines - use last day's levels for entire plot)
    if 'resistance_levels' in plot_data.columns:
        # Get last day's resistance levels
        last_resistance = plot_data['resistance_levels'].iloc[-1]
        for level in last_resistance[:3]:  # Top 3 resistance levels
            # Create horizontal line across entire timeline
            line = pd.Series([level] * len(plot_data), index=plot_data.index)
            apds.append(mpf.make_addplot(line, 
                                        color='red', 
                                        linestyle='--',
                                        alpha=0.5,
                                        label=f'Resistance ${level:.2f}'))
    
    # 4. Buy signals
    if 'signal' in plot_data.columns:
        buy_signals = plot_data[plot_data['signal'] == 1]
        if not buy_signals.empty:
            # Create markers at high price
            markers = pd.Series(index=plot_data.index, dtype=float)
            for idx in buy_signals.index:
                markers[idx] = buy_signals.loc[idx, 'high'] * 1.005  # Slightly above high
            
            apds.append(mpf.make_addplot(markers, 
                                        type='scatter',
                                        markersize=100,
                                        marker='^',
                                        color='gold',
                                        edgecolors='black',
                                        label='Buy Signal'))
    
    # Plot ALL data
    mpf.plot(plot_data[['open', 'high', 'low', 'close', 'volume']], 
            type='candle',
            volume=True,
            style='yahoo',
            addplot=apds,
            title=f'Support/Resistance Strategy (Full Data)',
            ylabel='Price',
            ylabel_lower='Volume',
            figsize=(16, 10))  # Larger figure for more data