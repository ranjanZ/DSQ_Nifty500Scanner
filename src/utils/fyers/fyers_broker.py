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
import logging

logger = logging.getLogger(__name__)

cur_path = os.path.dirname(os.path.abspath(__file__))


class fyers_API:
    def __init__(self):
        self.fyers = fyers
        self.access_token = access_token
        self.client_id = client_id

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
                order_type = 1
            else:
                order_type = 2
            
            side_int = 1 if side.upper() == "BUY" else -1
            
            order_data = {
                "symbol": symbol,
                "qty": qty,
                "type": order_type,
                "side": side_int,
                "productType": "MIS",
                "limitPrice": price if type == "LIMIT" else 0,
                "stopPrice": 0,
                "disclosedQty": 0,
                "offlineOrder": "False",
                "orderTag": "live_trading"
            }
            
            logger.debug(f"Placing {side} order: {symbol} | Qty: {qty} | Type: {type} | Price: {price}")
            
            response = self.fyers.place_order(data=order_data)
            
            if response and response.get('s') == 'ok':
                order_id = response.get('id', '')
                logger.info(f"✅ Order placed: {order_id} | {side} {qty} {symbol} @ {price}")
                return order_id
            else:
                logger.error(f"❌ Order failed: {response}")
                return None
        
        except Exception as e:
            logger.error(f"❌ Error placing order for {symbol}: {e}")
            return None

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an existing order"""
        try:
            response = self.fyers.cancel_order(id=order_id)
            
            if response and response.get('s') == 'ok':
                logger.info(f"✅ Order cancelled: {order_id}")
                return True
            else:
                logger.error(f"❌ Cancel failed: {response}")
                return False
        
        except Exception as e:
            logger.error(f"❌ Error cancelling order {order_id}: {e}")
            return False

    def place_stoploss_order(self, symbol: str, qty: int, price: float, stop_price: float) -> str:
        """Place a stop-loss order"""
        try:
            order_data = {
                "symbol": symbol,
                "qty": qty,
                "type": 2,
                "side": -1,
                "productType": "MIS",
                "limitPrice": price,
                "stopPrice": stop_price,
                "disclosedQty": 0,
                "offlineOrder": "False",
                "orderTag": "stoploss"
            }
            
            logger.debug(f"Placing stop-loss: {symbol} | Qty: {qty} | Price: {price} | Stop: {stop_price}")
            
            response = self.fyers.place_order(data=order_data)
            
            if response and response.get('s') == 'ok':
                order_id = response.get('id', '')
                logger.info(f"✅ Stop-loss placed: {order_id}")
                return order_id
            else:
                logger.error(f"❌ Stop-loss failed: {response}")
                return None
        
        except Exception as e:
            logger.error(f"❌ Error placing stop-loss for {symbol}: {e}")
            return None
    
    def get_positions(self) -> dict:
        """Get current positions from broker"""
        try:
            response = self.fyers.positions()
            
            if response and response.get('s') == 'ok':
                positions = {}
                for pos in response.get('netPositions', []):
                    symbol = pos.get('symbol', '')
                    buy_avg = pos.get('buyAvg', 0)
                    sell_avg = pos.get('sellAvg', 0)
                    net_qty = pos.get('netQty', 0)
                    entry_price = buy_avg if net_qty > 0 else sell_avg
                    
                    positions[symbol] = {
                        "entry_price": entry_price,
                        "quantity": net_qty,
                        "capital_used": abs(net_qty * entry_price),
                        "raw": pos
                    }
                logger.debug(f"✅ Fetched {len(positions)} positions from broker")
                return positions
            else:
                logger.error(f"❌ Failed to fetch positions: {response}")
                return {}
        
        except Exception as e:
            logger.error(f"❌ Error fetching positions: {e}")
            return {}

    def get_orders(self) -> dict:
        """Get current orders from broker"""
        try:
            response = self.fyers.orderbook()
            
            if response and response.get('s') == 'ok':
                orders = {}
                order_list = response.get('orderBook', response.get('orders', []))
                for order in order_list:
                    order_id = order.get('id') or order.get('orderId')
                    if order_id is None:
                        continue
                    orders[order_id] = {
                        "status": order.get("status", "UNKNOWN"),
                        "filled_quantity": order.get("filledQty", 0),
                        "average_price": order.get("avgPrice", 0),
                        "symbol": order.get("symbol", ""),
                        "raw": order
                    }
                logger.debug(f"✅ Fetched {len(orders)} orders from broker")
                return orders
            else:
                logger.error(f"❌ Failed to fetch orders: {response}")
                return {}
        
        except Exception as e:
            logger.error(f"❌ Error fetching orders: {e}")
            return {}

    def get_his_candle_data(self, symbol="NSE:SBIN-EQ", fromdate='2023-10-10', todate='2023-10-15', interval="1"):
        """Get historical candle data from Fyers broker"""
        try:
            fyers_model = fyersModel.FyersModel(
                client_id=self.client_id,
                is_async=False,
                token=self.access_token,
                log_path=cur_path + "/logs/"
            )

            data = {
                "symbol": symbol,
                "resolution": interval,
                "date_format": 1,
                "range_from": fromdate,
                "range_to": todate,
                "cont_flag": "1"
            }

            logger.debug(f"Fetching candles: {symbol} | {fromdate} to {todate}")
            
            response = fyers_model.history(data=data)
            
            if response is None or 'candles' not in response:
                logger.warning(f"No candle data for {symbol}")
                return None
            
            df = pd.DataFrame(
                response['candles'],
                columns=['time', 'open', 'high', 'low', 'close', 'volume']
            )
            
            df['time'] = df['time'].apply(pd.Timestamp, unit='s', tzinfo=pytz.timezone('Asia/Kolkata'))
            df['time'] = df['time'].apply(pd.Timestamp.isoformat)
            
            logger.debug(f"✅ Fetched {len(df)} candles for {symbol}")
            return df

        except Exception as e:
            logger.error(f"❌ Error fetching candles for {symbol}: {e}")
            return None

    def get_funds(self) -> dict:
        """Get account balance and margin information"""
        try:
            response = self.fyers.funds()
            fund_data = response.get("fund_limit", [])

            equity_available = 0
            used_margin = 0
            available_margin = 0

            for item in fund_data:
                title = item.get("title", "").lower()
                amount = item.get("equityAmount", 0)
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
            logger.error(f"❌ Error fetching funds: {e}")
            return {}


if __name__ == "__main__":
    api = fyers_API()
    print("✅ Fyers API initialized")
    symbol_list = ["NSE:NIFTY50-INDEX", "NSE:NIFTY2581424550CE", "NSE:NIFTY2581424500PE", "NSE:NIFTY2581423600PE"]
    fyers_API().get_his_candle_data(symbol=symbol_list[0], fromdate='2023-10-10', todate='2023-10-15', interval="1")
    fyers_API().get_funds()
    fyers_API().get_orders()