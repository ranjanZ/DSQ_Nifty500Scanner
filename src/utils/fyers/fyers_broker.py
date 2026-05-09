import json
import requests
import sys, os, time
import pandas as pd
from fyers_apiv3 import fyersModel
from fyers_apiv3.FyersWebsocket import data_ws
from .fyers_auth import access_token, client_id, fyers
import pytz
import random
import datetime

cur_path = os.path.dirname(os.path.abspath(__file__))

class fyers_API:
    def __init__(self):
        self.fyers = fyers  # already authenticated FyersModel instance
        self.access_token = access_token
        self.client_id = client_id

    # ------------------------------------------------------------------
    # NEW: required by BrokerSync
    # ------------------------------------------------------------------
    def get_positions(self) -> dict:
        """
        Fetch open positions from Fyers and return a dict keyed by symbol.
        Each value contains:
            entry_price, quantity, capital_used, target_price, stop_loss_price
        """
        try:
            response = self.fyers.positions()
            # The response structure: {"netPositions": [...], "overall": {...}}
            net_positions = response.get("netPositions", [])
            positions = {}
            for pos in net_positions:
                symbol = pos["symbol"]            # e.g. "NSE:SBIN-EQ"
                buy_qty = pos.get("buyQty", 0)
                sell_qty = pos.get("sellQty", 0)
                net_qty = pos.get("netQty", 0)

                # Skip zero net quantity
                if net_qty == 0:
                    continue

                # Use buyAvg for long, sellAvg for short
                if net_qty > 0:
                    avg_price = pos.get("buyAvg", 0)
                else:
                    avg_price = pos.get("sellAvg", 0)

                # capital_used approximate
                capital_used = abs(net_qty * avg_price)

                # target/stop not provided by positions API; set to 0
                positions[symbol] = {
                    "entry_price": avg_price,
                    "quantity": net_qty,
                    "capital_used": capital_used,
                    "target_price": 0,
                    "stop_loss_price": 0
                }
            return positions
        except Exception as e:
            print(f"Error in get_positions: {e}")
            return {}

    def get_orders(self) -> dict:
        """
        Fetch all orders for the day from Fyers and return a dict keyed by orderId.
        Each value contains: status, filled_quantity, average_price
        """
        try:
            response = self.fyers.orderbook()          # ← corrected method name
            # The response typically has a key 'orderBook' containing the list
            order_list = response.get("orderBook", response.get("orders", []))
            orders = {}
            for order in order_list:
                order_id = order.get("id") or order.get("orderId")
                if order_id is None:
                    continue
                orders[order_id] = {
                    "status": order.get("status", "UNKNOWN"),
                    "filled_quantity": order.get("filledQty", 0),
                    "average_price": order.get("avgPrice", 0)
                }
            return orders
        except Exception as e:
            print(f"Error in get_orders: {e}")
            return {}

    # ------------------------------------------------------------------
    # Existing methods (unchanged)
    # ------------------------------------------------------------------
    def place_order(self):
        pass

    def place_stoploss_order(self):
        pass

    def get_his_candle_data(self, symbol="NSE:SBIN-EQ", fromdate='2023-10-10', todate='2023-10-15', interval="1"):
        re_run = True
        try:
            fyers = fyersModel.FyersModel(client_id=client_id, is_async=False, token=access_token,
                                          log_path=cur_path + "/logs/")
            data = {
                "symbol": symbol,
                "resolution": interval,
                "date_format": 1,
                "range_from": fromdate,
                "range_to": todate,
                "cont_flag": "1"
            }
            res = fyers.history(data=data)
            df = pd.DataFrame(res['candles'], columns=['time', 'open', 'high', 'low', 'close', 'volume'])
            df['time'] = df['time'].apply(pd.Timestamp, unit='s', tzinfo=pytz.timezone('Asia/Kolkata'))
            df['time'] = df['time'].apply(pd.Timestamp.isoformat)
            return df
        except Exception as e:
            print(res)
            print(f'Function get_his_candle_data gave error {e}')

    def get_funds(self) -> dict:
        """
        Fetch account balance, margin used, and available margin from Fyers.
        Iterates over all fund_limit items and matches by title.
        """
        try:
            response = self.fyers.funds()
            fund_data = response.get("fund_limit", [])

            equity_available = 0
            used_margin = 0
            available_margin = 0

            for item in fund_data:
                title = item.get("title", "").lower()
                amount = item.get("equityAmount", 0)   # the only numeric value field
                if "total balance" in title:
                    equity_available = amount
                elif "used margin" in title or "utilized" in title:
                    used_margin = amount
                elif "available margin" in title or "available" in title:
                    available_margin = amount

            balance = {
                "equity_available": equity_available,
                "used_margin": used_margin,
                "available_margin": available_margin,
                "net_pnl": response.get("netPnl", 0),
                "total_realized_pnl": response.get("totalRealizedPnl", 0),
                "total_unrealized_pnl": response.get("totalUnrealizedPnl", 0),
                "timestamp": datetime.datetime.now(pytz.timezone("Asia/Kolkata")).isoformat()
            }
            return balance
        except Exception as e:
            print(f"Error in get_funds: {e}")
            return {}


if __name__ == "__main__":
    symbol_list = ["NSE:NIFTY50-INDEX", "NSE:NIFTY2581424550CE", "NSE:NIFTY2581424500PE", "NSE:NIFTY2581423600PE"]
    fyers_API().get_his_candle_data(symbol=symbol_list[0], fromdate='2023-10-10', todate='2023-10-15', interval="1")
    fyers_API().get_funds()