import pandas as pd



nse_data_500=pd.read_csv("../data/ind_nifty500list.csv")
data=pd.read_csv("../data/NSE_CM.csv")

data.columns = ['col'+str(i) for i in range(21)]
data.rename(columns={
   'col1': 'company_name',
    'col5': 'isin_code',
    'col9': 'fyers_symbol'
}, inplace=True)


data=data[['company_name','isin_code','fyers_symbol']]
df=pd.merge(nse_data_500,data,left_on="ISIN Code",right_on="isin_code",how="left")


df=df[['company_name','Industry','Symbol','ISIN Code','fyers_symbol']]


