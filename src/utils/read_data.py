import pandas as pd



volume_gainers=pd.read_csv("./data/LA-Volume-Gainers-20-Aug-2025.csv")
top_20_gainers=pd.read_csv("./data/T20-GL-gainers-allSec-20-Aug-2025.csv")
Bulk_deals=pd.read_csv("./data/Large-deals-BULK-20-Aug-2025.csv")
Block_deals=pd.read_csv("./data/Large-deals-BLOCK-20-Aug-2025.csv")




def clean_columns(df):
    df.columns = df.columns.str.replace(r'\s*\\n\s*', ' ', regex=True).str.strip().str.lower()
    return df

# Apply to all DataFrames
volume_gainers = clean_columns(volume_gainers)
top_20_gainers = clean_columns(top_20_gainers)
Bulk_deals = clean_columns(Bulk_deals)
Block_deals = clean_columns(Block_deals)





common_symbols = pd.merge(Bulk_deals, volume_gainers, on='symbol', how='inner')
common_symbols = pd.merge(Bulk_deals, top_20_gainers, on='symbol', how='inner')



# If you only want the symbols themselves (not the full data)
common_symbols_list = list(set(Bulk_deals['symbol']).intersection(set(volume_gainers['symbol'])))
