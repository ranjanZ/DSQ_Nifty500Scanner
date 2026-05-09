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
import logging

logger = logging.getLogger(__name__)

cur_path=os.path.dirname(os.path.abspath(__file__))



class fyers_API:
    def __init__(self,):
        self.fyers=fyers
        self.access_token=access_token
        self.client_id=client_id


    def place_order(self, symbol: str, qty: int, side: str, type: str = "MARKET", price: float = 0.0) -> str:
        """
        Place an order with Fyers broker
        
        Args:
            symbol: Trading symbol (e.g., "NSE:SBIN-EQ")
            qty: Quantity to trade
            side: "BUY" or "SELL"
            type: "MARKET" or "LIMIT"
            price: Price for limit orders
        
        Returns:
            Order ID if successful, None otherwise
        """
        try:
            if type == "MARKET":
                order_type = 1  # MARKET ORDER
            else:
                order_type = 2  # LIMIT ORDER
            
            # Convert side to Fyers format
            side_int = 1 if side.upper() == "BUY" else -1
            
            order_data = {
                "symbol": symbol,
                "qty": qty,
                "type": order_type,
                "side": side_int,
                "productType": "MIS",  # Intraday
                "limitPrice": price if type == "LIMIT" else 0,
                "stopPrice": 0,
                "disclosedQty": 0,
                "offlineOrder": "False",
                "orderTag": "live_trading"
            }
            
            logger.debug(f"Placing {side} order: {symbol} | Qty: {qty} | Type: {type} | Price: {price}")
            
            # Place order via Fyers
            response = self.fyers.place_order(data=order_data)
            
            if response and response.get('s') == 'ok':
                order_id = response.get('id', '')
                logger.info(f"Order successfully placed: {order_id} | {side} {qty} {symbol} @ {price}")
                return order_id
            else:
                logger.error(f"Order placement failed: {response}")
                return None
        
        except Exception as e:
            logger.error(f"Error placing order for {symbol}: {e}")
            return None

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an existing order"""
        try:
            response = self.fyers.cancel_order(id=order_id)
            
            if response and response.get('s') == 'ok':
                logger.info(f"Order cancelled successfully: {order_id}")
                return True
            else:
                logger.error(f"Order cancellation failed: {response}")
                return False
        
        except Exception as e:
            logger.error(f"Error cancelling order {order_id}: {e}")
            return False

    def place_stoploss_order(self, symbol: str, qty: int, price: float, stop_price: float) -> str:
        """Place a stop-loss order"""
        try:
            order_data = {
                "symbol": symbol,
                "qty": qty,
                "type": 2,  # LIMIT ORDER
                "side": -1,  # SELL
                "productType": "MIS",
                "limitPrice": price,
                "stopPrice": stop_price,
                "disclosedQty": 0,
                "offlineOrder": "False",
                "orderTag": "stoploss"
            }
            
            logger.debug(f"Placing stop-loss order: {symbol} | Qty: {qty} | Price: {price} | Stop: {stop_price}")
            
            response = self.fyers.place_order(data=order_data)
            
            if response and response.get('s') == 'ok':
                order_id = response.get('id', '')
                logger.info(f"Stop-loss order placed: {order_id}")
                return order_id
            else:
                logger.error(f"Stop-loss placement failed: {response}")
                return None
        
        except Exception as e:
            logger.error(f"Error placing stop-loss for {symbol}: {e}")
            return None
    
    def get_positions(self) -> dict:
        """Get current positions from broker"""
        try:
            response = self.fyers.get_positions()
            
            if response and response.get('s') == 'ok':
                positions = {}
                for pos in response.get('netPositions', []):
                    symbol = pos.get('symbol', '')
                    positions[symbol] = pos
                logger.debug(f"Fetched {len(positions)} positions from broker")
                return positions
            else:
                logger.error(f"Failed to fetch positions: {response}")
                return {}
        
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return {}
    
    def get_orders(self) -> dict:
        """Get current orders from broker"""
        try:
            response = self.fyers.get_orders()
            
            if response and response.get('s') == 'ok':
                orders = {}
                for order in response.get('orderBook', []):
                    order_id = order.get('id', '')
                    orders[order_id] = order
                logger.debug(f"Fetched {len(orders)} orders from broker")
                return orders
            else:
                logger.error(f"Failed to fetch orders: {response}")
                return {}
        
        except Exception as e:
            logger.error(f"Error fetching orders: {e}")
            return {}


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








