import json
import requests
import sys,os,time
import pandas as pd
from fyers_apiv3 import fyersModel
from fyers_apiv3.FyersWebsocket import data_ws
#from src.utils.fyers.fyers_auth import access_token, client_id, fyers
from .fyers_auth import access_token, client_id, fyers

import pytz
import random
import sys
import datetime



cur_path=os.path.dirname(os.path.abspath(__file__))



class fyers_API:
    def __init__(self,):
        self.fyers=fyers
        self.access_token=access_token
        self.client_id=client_id


    def place_order(self,):
        pass

    def place_stoploss_order(self,):
        pass


    #get historical candle data
    def get_his_candle_data(self,symbol="NSE:SBIN-EQ",fromdate='2023-10-10',todate='2023-10-15',interval="1"):   
        re_run=True
        try:
            fyers = fyersModel.FyersModel(client_id=client_id, is_async=False, token=access_token, log_path=cur_path+"/logs/")

            data = {
            "symbol":symbol,
            "resolution":interval,
            "date_format":1,
            "range_from":fromdate,
            "range_to":todate,
            "cont_flag":"1"
            }


            res = fyers.history(data=data)
            data = pd.DataFrame(res['candles'],columns = ['time','open','high','low','close','volume'])
            data['time'] = data['time'].apply(pd.Timestamp, unit='s', tzinfo=pytz.timezone('Asia/Kolkata'))
            data['time'] = data['time'].apply(pd.Timestamp.isoformat)

            return(data) 

        except Exception as e:
            print(res)
            print(f'Function x gave error {e}')



if __name__=="__main__":

    symbol_list=["NSE:NIFTY50-INDEX","NSE:NIFTY2581424550CE","NSE:NIFTY2581424500PE","NSE:NIFTY2581423600PE"]








