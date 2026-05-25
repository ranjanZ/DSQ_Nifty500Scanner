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
import re
from collections import defaultdict

logger = logging.getLogger(__name__)

cur_path = os.path.dirname(os.path.abspath(__file__))



def _normalize_symbol(symbol: str) -> str:
    """
    Convert exchange-specific symbol to a canonical stock name.
    Examples:
        'NSE:BHARTIARTL-EQ' -> 'BHARTIARTL'
        'BSE:BHARTIARTL-A'  -> 'BHARTIARTL'
        'NSE:ASHOKLEY-EQ'   -> 'ASHOKLEY'
        'BSE:BIKAJI-A'      -> 'BIKAJI'
    """
    if not symbol:
        return ''
    # Remove exchange prefix (NSE:, BSE:, etc.)
    if ':' in symbol:
        symbol = symbol.split(':', 1)[1]
    # Remove common suffixes like -EQ, -A, -EQ, -BE, etc.
    symbol = re.sub(r'-(EQ|A|BE|SW|SM)$', '', symbol)
    return symbol


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


    def get_all_portfolio_data(self) -> dict:
        from collections import defaultdict
        import time

        # Fetch raw data
        h = self.fyers.holdings()
        holdings_raw = h.get('holdings', []) if h.get('s') == 'ok' else []
        time.sleep(0.5)

        t = self.fyers.tradebook()
        trades_raw = t.get('tradeBook', []) if t.get('s') == 'ok' else []
        time.sleep(0.5)

        # Aggregate trades using normalized symbol
        agg = defaultdict(lambda: {
            'buy_qty': 0, 'buy_val': 0.0, 'buy_ts': [],
            'sell_qty': 0, 'sell_val': 0.0, 'sell_ts': []
        })

        for trade in trades_raw:
            raw_sym = trade.get('symbol')
            if not raw_sym:
                continue
            norm_sym = _normalize_symbol(raw_sym)
            side = str(trade.get('side', '')).upper()
            qty = int(trade.get('tradedQty', 0))
            price = float(trade.get('tradePrice', 0))
            ts = trade.get('orderDateTime')

            if side in ('BUY', '1'):
                agg[norm_sym]['buy_qty'] += qty
                agg[norm_sym]['buy_val'] += qty * price
                if ts:
                    agg[norm_sym]['buy_ts'].append(ts)
            elif side in ('SELL', '-1'):
                agg[norm_sym]['sell_qty'] += qty
                agg[norm_sym]['sell_val'] += qty * price
                if ts:
                    agg[norm_sym]['sell_ts'].append(ts)

        # Current holdings (remainingQuantity > 0)
        holdings = []
        for hrec in holdings_raw:
            raw_sym = hrec.get('symbol')
            if not raw_sym:
                continue
            remaining = int(hrec.get('remainingQuantity', 0))
            if remaining <= 0:
                continue

            norm_sym = _normalize_symbol(raw_sym)
            entry_time = min(agg[norm_sym]['buy_ts']) if agg[norm_sym]['buy_ts'] else None

            holdings.append({
                "symbol": raw_sym,               # keep original symbol for reference
                "normalized_symbol": norm_sym,   # optional, useful for debugging
                "quantity": remaining,
                "average_price": float(hrec.get('costPrice', 0)),
                "current_value": float(hrec.get('marketVal', 0)),
                "unrealized_pnl": float(hrec.get('pl', 0)),
                "entry_time": entry_time
            })

        # Closed positions (remainingQuantity == 0 and original quantity > 0)
        closed = []
        for hrec in holdings_raw:
            raw_sym = hrec.get('symbol')
            if not raw_sym:
                continue
            remaining = int(hrec.get('remainingQuantity', 0))
            original_qty = int(hrec.get('quantity', 0))
            if remaining != 0 or original_qty <= 0:
                continue

            norm_sym = _normalize_symbol(raw_sym)
            cost_price = float(hrec.get('costPrice', 0))

            # Compute sell price from aggregated sells (which now include cross-exchange trades)
            sell_data = agg.get(norm_sym)
            if not sell_data or sell_data['sell_qty'] == 0:
                continue  # no sell found – shouldn't happen if fully sold, but skip

            sell_price = sell_data['sell_val'] / sell_data['sell_qty']
            realised_pnl = (sell_price - cost_price) * original_qty
            exit_time = max(sell_data['sell_ts']) if sell_data['sell_ts'] else None

            closed.append({
                "symbol": raw_sym,
                "normalized_symbol": norm_sym,
                "quantity": original_qty,
                "entry_price": round(cost_price, 2),
                "exit_price": round(sell_price, 2),
                "realised_pnl": round(realised_pnl, 2),
                "exit_time": exit_time,
                "type": "delivery_sell"
            })

        return {"holdings": holdings, "closed_positions": closed}




    def get_positions(self) -> dict:
        """Get current positions from broker"""
        try:
            response = self.fyers.positions()
            
            if response and response.get('s') == 'ok':
                positions = {}
                net_positions = response.get('netPositions', [])
                if not net_positions:
                    logger.debug(f"ℹ️  No open positions")
                    return positions
                    
                for pos in net_positions:
                    symbol = pos.get('symbol', '')
                    if not symbol:
                        continue
                    try:
                        buy_avg = float(pos.get('buyAvg', 0))
                        sell_avg = float(pos.get('sellAvg', 0))
                        net_qty = int(pos.get('netQty', 0))
                        entry_price = buy_avg if net_qty > 0 else sell_avg
                        
                        positions[symbol] = {
                            "entry_price": entry_price,
                            "quantity": net_qty,
                            "capital_used": abs(net_qty * entry_price),
                            "raw": pos
                        }
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Could not parse position for {symbol}: {e}")
                        continue
                        
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
                if not order_list:
                    logger.debug(f"ℹ️  No open orders")
                    return orders
                    
                for order in order_list:
                    order_id = order.get('id') or order.get('orderId')
                    if order_id is None:
                        continue
                    try:
                        orders[order_id] = {
                            "status": str(order.get("status", "UNKNOWN")),
                            "filled_quantity": int(order.get("filledQty", 0)),
                            "average_price": float(order.get("avgPrice", 0)),
                            "symbol": str(order.get("symbol", "")),
                            "raw": order
                        }
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Could not parse order {order_id}: {e}")
                        continue
                        
                logger.debug(f"✅ Fetched {len(orders)} orders from broker")
                return orders
            else:
                logger.error(f"❌ Failed to fetch orders: {response}")
                return {}
        
        except Exception as e:
            logger.error(f"❌ Error fetching orders: {e}")
            return {}


    def get_his_candle_data(self, symbol="NSE:SBIN-EQ", fromdate='2023-10-10', todate='2023-10-15', interval="1"):
        """Get historical candle data from Fyers broker with rate‑limit retry."""
        max_retries =6
        base_delay = 1  # seconds

        for attempt in range(max_retries):
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

                logger.debug(f"Fetching candles: {symbol} | {fromdate} to {todate} (attempt {attempt+1}/{max_retries})")
                
                response = fyers_model.history(data=data)
                
                # Check if response indicates rate limit (429) or other error
                if response and response.get('s') == 'error' and response.get('code') == 429:
                    delay = base_delay * (2 ** attempt)  # exponential backoff
                    logger.warning(f"Rate limit reached. Retrying in {delay}s...")
                    time.sleep(delay)
                    continue  # retry
                
                # Normal success or other error that should not be retried
                if response is None or 'candles' not in response or not response.get('candles'):
                    logger.warning(f"No candle data for {symbol}")
                    return pd.DataFrame()
                
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
                # If it's the last attempt, return empty DataFrame
                if attempt == max_retries - 1:
                    return pd.DataFrame()
                time.sleep(base_delay)  # simple delay before retrying on exception

        return pd.DataFrame()  # fallback after all retries

    def get_his_candle_data_single_appemt(self, symbol="NSE:SBIN-EQ", fromdate='2023-10-10', todate='2023-10-15', interval="1"):
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
            
            if response is None or 'candles' not in response or not response.get('candles'):
                logger.warning(f"No candle data for {symbol}")
                return pd.DataFrame()  # Return empty DataFrame instead of None
            
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
            return pd.DataFrame()  # Return empty DataFrame instead of None

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
            response = self.fyers.quotes({"symbols": symbol})
            if response and response.get('s') == 'ok' and response.get('d') and len(response.get('d', [])) > 0:
                # Check if the specific symbol data within the response is valid
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

    def place_oco_order(self, symbol: str, qty: int, side: str, entry_price: float,
                       stop_loss: float, take_profit: float) -> dict:
        """
        Place an OCO (One-Cancels-Other) bracket order
        - Entry order (BUY/SELL)
        - Stop-loss order (opposite side)
        - Take-profit order (opposite side)
        
        Returns dict with 'parent', 'sl_order_id', 'tp_order_id'
        """
        try:
            logger.info(f"📊 Placing OCO bracket for {symbol}: Entry={entry_price}, SL={stop_loss}, TP={take_profit}")
            
            side_int = 1 if side.upper() == "BUY" else -1
            
            # 1. Place entry order (LIMIT at entry_price)
            entry_order_data = {
                "symbol": symbol,
                "qty": qty,
                "type": 1,  # LIMIT
                "side": side_int,
                "productType": "INTRADAY",
                "limitPrice": entry_price,
                "stopPrice": 0,
                "validity": "DAY",
                "disclosedQty": 0,
                "offlineOrder": False,
                "stopLoss": 0,
                "takeProfit": 0
            }
            
            entry_response = self.fyers.place_order(data=entry_order_data)
            if not entry_response or entry_response.get('s') != 'ok':
                logger.error(f"❌ Entry order failed: {entry_response}")
                return {'parent': None, 'sl_order_id': None, 'tp_order_id': None}
            
            entry_order_id = entry_response.get('id', '')
            logger.info(f"✅ Entry order placed: {entry_order_id}")
            
            # 2. Place SL order (STOP_LOSS - market sell at SL price)
            sl_order_data = {
                "symbol": symbol,
                "qty": qty,
                "type": 2,  # MARKET (triggered by stop_price)
                "side": -side_int,  # opposite side
                "productType": "INTRADAY",
                "limitPrice": 0,
                "stopPrice": stop_loss,  # Trigger price
                "validity": "DAY",
                "disclosedQty": 0,
                "offlineOrder": False,
                "stopLoss": 0,
                "takeProfit": 0
            }
            
            sl_response = self.fyers.place_order(data=sl_order_data)
            if not sl_response or sl_response.get('s') != 'ok':
                logger.warning(f"⚠️  SL order failed: {sl_response}")
                sl_order_id = None
            else:
                sl_order_id = sl_response.get('id', '')
                logger.info(f"✅ SL order placed: {sl_order_id}")
            
            # 3. Place TP order (TAKE_PROFIT - market sell/buy at TP price)
            tp_order_data = {
                "symbol": symbol,
                "qty": qty,
                "type": 2,  # MARKET (triggered by stop_price)
                "side": -side_int,  # opposite side
                "productType": "INTRADAY",
                "limitPrice": 0,
                "stopPrice": take_profit,  # Trigger price
                "validity": "DAY",
                "disclosedQty": 0,
                "offlineOrder": False,
                "stopLoss": 0,
                "takeProfit": 0
            }
            
            tp_response = self.fyers.place_order(data=tp_order_data)
            if not tp_response or tp_response.get('s') != 'ok':
                logger.warning(f"⚠️  TP order failed: {tp_response}")
                tp_order_id = None
            else:
                tp_order_id = tp_response.get('id', '')
                logger.info(f"✅ TP order placed: {tp_order_id}")
            
            return {
                'parent': entry_order_id,
                'sl_order_id': sl_order_id,
                'tp_order_id': tp_order_id
            }
            
        except Exception as e:
            logger.error(f"❌ Error placing OCO bracket: {e}")
            return {'parent': None, 'sl_order_id': None, 'tp_order_id': None}

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
        """Place a true OCO with BO (Bracket Order) product type"""
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
            
            # Add 'parent' key manually so test suite doesn't crash
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
        """
        Place complete swing trading OCO in sequence (Fyers-specific, abstracted for future brokers):
        1. Place MARKET entry order (CNC)
        2. Poll until filled
        3. Place GTT OCO (SL + TP)
        
        Returns: {'s': 'ok'/'error', 'entry_order_id': '...', 'entry_filled': T/F, 
                  'gtt_placed': T/F, 'message': '...'}
        """
        try:
            import traceback
            is_buy = side.upper() == "BUY"
            
            # Validate SL/TP levels
            if is_buy:
                if not (sl_price < entry_price < tp_price):
                    raise ValueError(f"BUY: SL({sl_price}) < Entry({entry_price}) < TP({tp_price})")
            else:
                if not (sl_price > entry_price > tp_price):
                    raise ValueError(f"SELL: SL({sl_price}) > Entry({entry_price}) > TP({tp_price})")
            
            # Tick rounding
            tick = 0.1
            round_tick = lambda p: round(p / tick) * tick
            
            # STEP 1: Place MARKET entry order (CNC product)
            entry_data = {
                "symbol": symbol,
                "qty": qty,
                "type": 2,
                "side": 1 if is_buy else -1,
                "productType": "CNC",
                "limitPrice": 0,
                "validity": "DAY",
                "offlineOrder": False,
                "stopLoss": 0,
                "takeProfit": 0
            }
            
            entry_res = self.fyers.place_order(data=entry_data)
            
            if not entry_res or entry_res.get('s') != 'ok':
                logger.error(f"❌ Entry order failed for {symbol}: {entry_res}")
                return {
                    's': 'error',
                    'entry_order_id': None,
                    'entry_filled': False,
                    'gtt_placed': False,
                    'message': 'Entry order placement failed'
                }
            
            entry_order_id = entry_res.get('id', '')
            logger.info(f"📝 Entry order placed: {entry_order_id} | Waiting for fill...")
            
            # STEP 2: Poll for entry fill (Fyers status codes)
            entry_filled = self._wait_for_entry_fill(entry_order_id, max_wait_seconds=30)
            
            if not entry_filled:
                logger.error(f"❌ Entry order {entry_order_id} did not fill")
                return {
                    's': 'error',
                    'entry_order_id': entry_order_id,
                    'entry_filled': False,
                    'gtt_placed': False,
                    'message': f'Entry did not fill'
                }
            
            logger.info(f"✅ Entry order FILLED: {entry_order_id}")
            
            # STEP 3: Place GTT OCO (after entry confirmation)
            exit_side = -1 if is_buy else 1
            sl_round = round_tick(sl_price)
            tp_round = round_tick(tp_price)
            
            if is_buy:
                leg1_price, leg1_trigger = tp_round, tp_round
                leg2_price, leg2_trigger = sl_round, sl_round
            else:
                leg1_price, leg1_trigger = sl_round, sl_round
                leg2_price, leg2_trigger = tp_round, tp_round
            
            gtt_data = {
                "side": exit_side,
                "symbol": symbol,
                "productType": "CNC",
                "orderInfo": {
                    "leg1": {"price": leg1_price, "triggerPrice": leg1_trigger, "qty": qty},
                    "leg2": {"price": leg2_price, "triggerPrice": leg2_trigger, "qty": qty}
                }
            }
            
            gtt_res = self.fyers.place_gtt_order(data=gtt_data)
            gtt_placed = gtt_res and gtt_res.get('s') == 'ok'
            
            if not gtt_placed:
                logger.warning(f"⚠️ GTT placement failed for {symbol}: {gtt_res}")
            else:
                logger.info(f"✅ GTT OCO confirmed for {symbol}")
            
            return {
                's': 'ok',
                'entry_order_id': entry_order_id,
                'entry_filled': True,
                'gtt_placed': gtt_placed,
                'message': 'Entry filled' + (' + GTT placed' if gtt_placed else ' (GTT failed)')
            }
            
        except Exception as e:
            logger.error(f"❌ Swing OCO error: {e}")
            traceback.print_exc()
            return {
                's': 'error',
                'entry_order_id': None,
                'entry_filled': False,
                'gtt_placed': False,
                'message': str(e)
            }
    
    def _wait_for_entry_fill(self, order_id: str, max_wait_seconds: int = 30) -> bool:
        """Internal: Poll Fyers order until filled. Status codes: 1=CANCELLED, 2=FILLED, 5=REJECTED, 6=PENDING, 7=EXPIRED"""
        logger.info(f"⏳ Polling order {order_id} for fill (max {max_wait_seconds}s)...")
        start_time = time.time()
        
        while time.time() - start_time < max_wait_seconds:
            try:
                orders = self.fyers.orderbook()
                if not orders or orders.get('s') != 'ok':
                    time.sleep(1)
                    continue
                
                order_list = orders.get('orderBook', orders.get('orders', []))
                order = None
                
                for o in order_list:
                    if o.get('id') == order_id or o.get('orderId') == order_id:
                        order = o
                        break
                
                if not order:
                    time.sleep(1)
                    continue
                
                status_code = order.get('status')
                filled_qty = order.get('filledQty', 0)
                total_qty = order.get('qty', 0)
                
                if status_code == 2:
                    logger.info(f"✅ Order {order_id} FILLED: {filled_qty}/{total_qty}")
                    return True
                elif filled_qty > 0:
                    logger.info(f"✅ Order {order_id} PARTIAL FILL: {filled_qty}/{total_qty}")
                    return True
                elif status_code in [5, 7, 1]:
                    logger.error(f"❌ Order {order_id} failed (status: {status_code})")
                    return False
                
                time.sleep(1)
            
            except Exception as e:
                logger.debug(f"Poll error: {e}")
        
        logger.warning(f"⏱️ Order {order_id} PENDING after {max_wait_seconds}s")
        return False
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


    # ltp = quotes['d'][0]['v']['lp'] if quotes and 'd' else 500
    # entry_price = ltp
    # sl_price = round(entry_price * 0.9991, 2)
    # tp_price = round(entry_price * 1.0009, 2)
    # result = api.place_swing_oco(symbol_test, 1, "BUY", entry_price, sl_price, tp_price)


    print("\n✅ Test suite finished.")






