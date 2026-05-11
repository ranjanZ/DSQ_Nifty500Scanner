import json
import requests
import sys, os, time
import pandas as pd
from fyers_apiv3 import fyersModel
from fyers_apiv3.FyersWebsocket import data_ws
from src.utils.fyers.fyers_auth import access_token, client_id, fyers

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

    def place_order(self, symbol: str, qty: int, side: str, type: str = "MARKET",
                    price: float = 0.0, product_type: str = "INTRADAY") -> str:
        """
        Place an order with Fyers broker.
        type: "MARKET" (type=2) or "LIMIT" (type=1)
        """
        try:
            # Fyers type codes: 1=LIMIT, 2=MARKET
            order_type = 2 if type.upper() == "MARKET" else 1
            side_int = 1 if side.upper() == "BUY" else -1

            order_data = {
                "symbol": symbol,
                "qty": qty,
                "type": order_type,
                "side": side_int,
                "productType": product_type,
                "limitPrice": price if type.upper() == "LIMIT" else 0,
                "stopPrice": 0,
                "validity": "DAY",
                "disclosedQty": 0,
                "offlineOrder": False,
                "stopLoss": 0,      # ✅ required field (even if 0)
                "takeProfit": 0     # ✅ required field
            }

            logger.debug(f"Placing {side} order: {symbol} | Qty: {qty} | Type: {type}")
            response = self.fyers.place_order(data=order_data)

            if response and response.get('s') == 'ok':
                order_id = response.get('id', '')
                logger.info(f"✅ Order placed: {order_id}")
                return order_id
            else:
                logger.error(f"❌ Order failed: {response}")
                return None

        except Exception as e:
            logger.error(f"❌ Error placing order: {e}")
            return None

    def cancel_order(self, order_id: str):
        try:
            # WRONG: self.fyers.cancel_order(id=order_id)
            # RIGHT:
            response = self.fyers.cancel_order(data={"id": order_id})
            return response
        except Exception as e:
            logger.error(f"❌ Error: {e}")



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

    def get_quotes(self, symbol: str) -> dict:
        """Get live quotes (LTP) for a symbol"""
        try:
            # Change [symbol] to just symbol
            response = self.fyers.quotes({"symbols": symbol}) 
            
            # Check if the specific symbol data within the response is valid
            if response and response.get('s') == 'ok':
                # Check for inner error code -300
                if response['d'][0]['v'].get('s') == 'error':
                    logger.error(f"❌ Invalid symbol format: {response['d'][0]['v'].get('errmsg')}")
                    return {}
                    
                logger.debug(f"✅ Got quotes for {symbol}")
                return response
            else:
                logger.error(f"❌ Quote failed for {symbol}: {response}")
                return {}
        except Exception as e:
            logger.error(f"❌ Error fetching quotes for {symbol}: {e}")
            return {}

    def round_to_tick(self, price):
        """Round price/points to the nearest 0.05 tick"""
        return round(float(price) * 20) / 20

    def create_gtt(self, symbol: str, qty: int, sl_price: float, tp_price: float):
        """
        Places a GTT OCO (Stop-loss + Take-profit) for Swing positions
        """
        try:
            # GTT OCO Payload for Fyers V3
            gtt_data = {
                "symbol": symbol,
                "qty": qty,
                "side": -1,             # Sell to exit a Buy position
                "type": 2,              # 2 = OCO (Stop-loss and Take-profit)
                "condition": 1,         # 1 = Price-based trigger
                "stopPrice": self.round_to_tick(sl_price),   # SL Trigger
                "limitPrice": self.round_to_tick(sl_price),  # SL Execution
                "targetPrice": self.round_to_tick(tp_price)  # TP Trigger/Execution
            }
            
            # In V3, the method is place_gtt, not create_gtt
            response = self.fyers.place_gtt(data=gtt_data)
            return response
        except Exception as e:
            logger.error(f"❌ GTT Error: {e}")
            return None


    def place_true_oco(self, symbol: str, qty: int, side: str, entry_price: float, 
                    sl_points: float, tp_points: float) -> dict:
        try:
            side_int = 1 if side.upper() == "BUY" else -1
            
            # ⚠️ CRITICAL: Round points to 0.05 tick size
            sl_points = self.round_to_tick(sl_points)
            tp_points = self.round_to_tick(tp_points)
            entry_price = self.round_to_tick(entry_price)

            order_data = {
                "symbol": symbol,
                "qty": qty,
                "type": 1,
                "side": side_int,
                "productType": "BO",
                "limitPrice": entry_price,
                "stopPrice": 0,
                "validity": "DAY",
                "offlineOrder": False,
                "stopLoss": sl_points, 
                "takeProfit": tp_points
            }

            response = self.fyers.place_order(data=order_data)
            
            # Add 'parent' key manually so your test suite doesn't crash
            if response and response.get('s') == 'ok':
                response['parent'] = response.get('id')
            else:
                response['parent'] = None
                
            return response
        except Exception as e:
            logger.error(f"❌ Error: {e}")
            return {'s': 'error', 'parent': None}

    def place_swing_oco(self, symbol: str, qty: int, side: str, entry_price: float,
                        sl_price: float, tp_price: float) -> dict:
        try:
            # 1. MARKET entry order (type=2, limitPrice=0)
            entry_data = {
                "symbol": symbol,
                "qty": qty,
                "type": 1,
                "side": 1 if side.upper() == "BUY" else -1,
                "productType": "CNC",
                "limitPrice": entry_price,
                "validity": "DAY",
                "offlineOrder": False
            }
            entry_res = self.fyers.place_order(data=entry_data)

            if entry_res.get('s') != 'ok':
                logger.error(f"Entry order failed: {entry_res}")
                return {"entry": entry_res, "gtt": None}

            # 2. Exit side
            exit_side = -1 if side.upper() == "BUY" else 1
            is_buy = (side.upper() == "BUY")

            # 3. Validate SL/TP levels
            if is_buy:
                if not (sl_price < entry_price < tp_price):
                    raise ValueError(f"BUY: SL({sl_price}) < Entry({entry_price}) < TP({tp_price})")
            else:
                if not (sl_price > entry_price > tp_price):
                    raise ValueError(f"SELL: SL({sl_price}) > Entry({entry_price}) > TP({tp_price})")

            # 4. Round prices to tick size (0.05 – adjust if API expects 0.10)
            tick = 0.1   # Change to 0.10 if needed
            def round_tick(p):
                return round(p / tick) * tick

            sl_round = round_tick(sl_price)
            tp_round = round_tick(tp_price)

            # 5. Build OCO legs: leg1_trigger > leg2_price
            if is_buy:
                # BUY: target (higher) is leg1, SL (lower) is leg2
                leg1_price = tp_round
                leg1_trigger = tp_round
                leg2_price = sl_round
                leg2_trigger = sl_round
            else:
                # SELL: SL (higher) is leg1, target (lower) is leg2
                leg1_price = sl_round
                leg1_trigger = sl_round
                leg2_price = tp_round
                leg2_trigger = tp_round

            gtt_data = {
                "side": exit_side,
                "symbol": symbol,
                "productType": "CNC",
                "orderInfo": {
                    "leg1": {
                        "price": leg1_price,
                        "triggerPrice": leg1_trigger,
                        "qty": qty
                    },
                    "leg2": {
                        "price": leg2_price,
                        "triggerPrice": leg2_trigger,
                        "qty": qty
                    }
                }
            }

            gtt_res = self.fyers.place_gtt_order(data=gtt_data)
            return {"entry": entry_res, "gtt": gtt_res}

        except Exception as e:
            logger.error(f"❌ Swing order error: {e}")
            return None
        
        
if __name__ == "__main__":
    from src.utils.fyers.fyers_broker import *
    print("✅ Fyers API initialized")
    print("👉 Make sure your app has ALGO permissions and IP whitelisted.\n")

    api = fyers_API()

    # 1. Test get_his_candle_data
    print("\n1. Testing get_his_candle_data()...")
    df = api.get_his_candle_data("NSE:SBIN-EQ", "2025-04-01", "2025-04-10", "D")
    if not df.empty:
        print(f"   Retrieved {len(df)} candles. Sample:\n{df.head(2)}")
    else:
        print("   ❌ No data or error.")

    # 2. Test get_quotes
    print("\n2. Testing get_quotes()...")
    quotes = api.get_quotes("NSE:SBIN-EQ")
    if quotes and 'd' in quotes:
        ltp = quotes['d'][0]['v']['lp']
        print(f"   LTP of SBIN: {ltp}")
    else:
        print("   ❌ Quote failed.")

    # 3. Test place_order (small quantity, market)
    #    Only run if you confirm (dangerous)
    print("\n3. Testing place_order (MARKET) with tiny quantity...")
    symbol_test = "NSE:SBIN-EQ"
    qty_test = 1
    if input(f"Place {qty_test} share MARKET BUY order for {symbol_test}? (y/N): ").lower() == 'y':
        order_id = api.place_order(symbol_test, qty_test, "BUY", "MARKET")
        if order_id:
            print(f"   Order placed: {order_id}")
            # Cancel it immediately (optional)
            if input("Cancel the order? (y/N): ").lower() == 'y':
                api.cancel_order(order_id)
        else:
            print("   ❌ Order failed.")
    else:
        print("   Skipped.")

    # 4. Test stoploss order (simulated)
    print("\n4. Testing place_stoploss_order (limit order with trigger)...")
    if input("Place a SELL STOP_LOSS_LIMIT order for 1 share NSE:SBIN-EQ (trigger 10% below LTP)? (y/N): ").lower() == 'y':
        ltp = quotes['d'][0]['v']['lp'] if quotes and 'd' else 500
        trigger = round(ltp * 0.90, 2)
        sl_id = api.place_stoploss_order(symbol_test, 1, trigger, trigger)
        if sl_id:
            print(f"   Stop-loss order placed: {sl_id}")
            if input("Cancel it? (y/N): ").lower() == 'y':
                api.cancel_order(sl_id)
        else:
            print("   ❌ SL order failed.")
    else:
        print("   Skipped.")

    # 5. Test OCO bracket emulation
    print("\n5. Testing OCO bracket (entry + SL + TP)...")
    if input("Place OCO bracket for 1 share (BUY) with SL -5%, TP +5%? (y/N): ").lower() == 'y':
        ltp = quotes['d'][0]['v']['lp'] if quotes and 'd' else 500
        entry_price = ltp
        sl_price = round(entry_price * 0.95, 2)
        tp_price = round(entry_price * 1.05, 2)
        result = api.place_true_oco(symbol_test, 1, "BUY", entry_price, sl_price, tp_price)
        result = api.place_swing_oco(symbol_test, 1, "BUY", entry_price, sl_price, tp_price)

        print(f"   OCO result: {result}")
        if result['parent']:
            print("   Cancelling all orders from this bracket...")
            for k, oid in result.items():
                if oid:
                    api.cancel_order(oid)
    else:
        print("   Skipped.")


    ltp = quotes['d'][0]['v']['lp'] if quotes and 'd' else 500
    entry_price = ltp
    sl_price = round(entry_price * 0.9991, 2)
    tp_price = round(entry_price * 1.0009, 2)
    result = api.place_swing_oco(symbol_test, 1, "BUY", entry_price, sl_price, tp_price)


    print("\n✅ Test suite finished.")






