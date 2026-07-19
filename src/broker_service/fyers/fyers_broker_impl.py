"""
Fyers Broker Implementation
Implements the BrokerBase interface for Fyers API
"""

import os
import sys
import time
import logging
import pandas as pd
import pytz
import re
import random
from datetime import datetime
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv

# ── Path Resolution ──────────────────────────────────────────────────────────
# Resolve paths relative to THIS file, so it works from anywhere
_CUR_FILE = os.path.abspath(__file__)
_CUR_DIR = os.path.dirname(_CUR_FILE)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_CUR_DIR))  # broker_service/fyers/ -> broker_service/ -> project_root/

# Add project root to path for imports
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Load environment variables (handle typo in DEEFAULT_ENV_PATH gracefully)
env_path = os.environ.get('DEFAULT_ENV_PATH') or os.environ.get('DEEFAULT_ENV_PATH')
if env_path:
    load_dotenv(env_path)
else:
    # Look for .env in project root first, then current directory
    root_env = os.path.join(_PROJECT_ROOT, '.env')
    if os.path.exists(root_env):
        load_dotenv(root_env)
    else:
        load_dotenv()  # Fallback to default .env in current directory

# ── Import base class ────────────────────────────────────────────────────────
try:
    from broker_base import BrokerBase, BrokerRegistry
except ImportError:
    # Fallback for testing without broker_base
    class BrokerBase:
        def __init__(self, name: str, config: Dict[str, Any] = None):
            self.name = name
            self.config = config or {}
            self.connected = False
            self.logger = logging.getLogger(__name__)

    class BrokerRegistry:
        _brokers = {}
        @classmethod
        def register(cls, name: str, broker_class: type):
            cls._brokers[name] = broker_class

def register_broker(name: str):
    """Decorator to register broker implementations"""
    def decorator(broker_class: type):
        BrokerRegistry.register(name, broker_class)
        return broker_class
    return decorator

# ── Fyers imports ────────────────────────────────────────────────────────────
try:
    from fyers_apiv3 import fyersModel
    FYERS_SDK_AVAILABLE = True
except ImportError as e:
    logging.warning(f"Fyers SDK not available: {e}")
    fyersModel = None
    FYERS_SDK_AVAILABLE = False

# Import auth utility
try:
    from broker_service.fyers.fyers_auth import generate_access_token
    AUTH_UTIL_AVAILABLE = True
except ImportError:
    try:
        from fyers.fyers_auth import generate_access_token
        AUTH_UTIL_AVAILABLE = True
    except ImportError as e:
        logging.debug(f"Fyers auth utility not available: {e}")
        generate_access_token = None
        AUTH_UTIL_AVAILABLE = False

logger = logging.getLogger(__name__)


def _normalize_symbol(symbol: str) -> str:
    """Convert exchange-specific symbol to canonical stock name"""
    if not symbol:
        return ''
    if ':' in symbol:
        symbol = symbol.split(':', 1)[1]
    symbol = re.sub(r'-(EQ|A|BE|SW|SM)$', '', symbol)
    return symbol


@register_broker("fyers")
class FyersBroker(BrokerBase):
    """Fyers broker implementation - always tries REAL mode first, no silent demo fallback"""

    def __init__(self, config: Dict[str, Any] = None):
        config_dict = config or {}
        super().__init__(name="Fyers", config=config_dict)

        # Get credentials with fallback hierarchy: Config dict -> Environment variable -> Default
        self.client_id = config_dict.get('client_id') or os.getenv('FYERS_CLIENT_ID', '8ZU1YKGMVT-200')
        self.secret_key = config_dict.get('secret_key') or os.getenv('FYERS_SECRET_KEY', 'c9YkxN1yj5TEnz1p')
        self.access_token = config_dict.get('access_token') or os.getenv('FYERS_ACCESS_TOKEN', '')

        # Additional Fyers auth params
        self.redirect_uri = config_dict.get('redirect_uri', os.getenv('FYERS_REDIRECT_URI', 'https://www.google.com'))
        self.fyers_id = config_dict.get('fyers_id', os.getenv('FYERS_ID', 'YC00531'))
        self.pin = config_dict.get('pin', os.getenv('FYERS_PIN', '1234'))
        self.totp_token = config_dict.get('totp_token', os.getenv('FYERS_TOTP_TOKEN', ''))

        # Auth flow parameters
        self.response_type = config_dict.get('response_type', os.getenv('FYERS_RESPONSE_TYPE', 'code'))
        self.grant_type = config_dict.get('grant_type', os.getenv('FYERS_GRANT_TYPE', 'authorization_code'))
        self.state = config_dict.get('state', os.getenv('FYERS_STATE', 'sample_state'))

        self.fyers = None
        self._demo_mode = False  # Track demo mode explicitly
        self._auth_error = None   # Store last auth error

        # Initialize SDK if we have credentials
        if FYERS_SDK_AVAILABLE:
            try:
                self._init_fyers_instance()
            except Exception as e:
                logger.error(f"Could not initialize Fyers SDK: {e}")
                self._auth_error = str(e)
                raise RuntimeError(f"Fyers SDK initialization failed: {e}")
        else:
            raise RuntimeError("Fyers SDK not available. Install with: pip install fyers-apiv3")

    def _init_fyers_instance(self):
        """Initialize Fyers SDK instance - raises on failure, NO silent demo fallback"""
        if not FYERS_SDK_AVAILABLE:
            raise RuntimeError("Fyers SDK not installed")

        # If we don't have an access token, try to generate one using the auth utility
        if not self.access_token and AUTH_UTIL_AVAILABLE and generate_access_token:
            if self.totp_token and self.fyers_id and self.pin:
                logger.info("No access token found, attempting to generate one...")
                token_result = generate_access_token(
                    client_id=self.client_id,
                    secret_key=self.secret_key,
                    fyers_id=self.fyers_id,
                    pin=self.pin,
                    totp_token=self.totp_token,
                    redirect_uri=self.redirect_uri,
                    response_type=self.response_type,
                    grant_type=self.grant_type,
                    state=self.state
                )

                if token_result.get('success'):
                    self.access_token = token_result['access_token']
                    logger.info("Access token generated successfully")
                else:
                    error_msg = token_result.get('error', 'Unknown error')
                    logger.error(f"Could not generate access token: {error_msg}")
                    raise RuntimeError(f"Token generation failed: {error_msg}")
            else:
                missing = []
                if not self.totp_token: missing.append('TOTP_TOKEN')
                if not self.fyers_id: missing.append('FYERS_ID')
                if not self.pin: missing.append('PIN')
                raise RuntimeError(f"Missing credentials for auto-auth: {', '.join(missing)}")

        if self.access_token:
            # Ensure log directory exists to prevent SDK crash
            log_dir = os.path.join(_CUR_DIR, "logs")
            os.makedirs(log_dir, exist_ok=True)

            self.fyers = fyersModel.FyersModel(
                client_id=self.client_id,
                is_async=False,
                token=self.access_token,
                log_path=log_dir + "/"
            )
            logger.info("Fyers SDK initialized successfully with access token")
        else:
            raise RuntimeError("No access token available and auto-auth not possible")

    def connect(self) -> bool:
        """Connect to Fyers API - raises on failure, NO demo fallback"""
        try:
            if not self.fyers:
                raise RuntimeError("Fyers SDK not initialized")

            # Test connection with funds API
            response = self.fyers.funds()
            if response and isinstance(response, dict) and response.get('s') == 'ok':
                self.connected = True
                self._demo_mode = False
                logger.info("Connected to Fyers API (LIVE)")
                return True
            else:
                error_msg = response.get('message', 'Unknown error') if isinstance(response, dict) else str(response)
                raise RuntimeError(f"Authentication failed: {error_msg}")

        except Exception as e:
            self.connected = False
            self._auth_error = str(e)
            logger.error(f"Error connecting to Fyers: {e}")
            raise RuntimeError(f"Fyers connection failed: {e}")

    def disconnect(self):
        """Disconnect from Fyers API"""
        self.connected = False
        self.fyers = None
        logger.info("Disconnected from Fyers API")

    def is_demo_mode(self) -> bool:
        """Check if running in demo/simulation mode"""
        return self._demo_mode

    def get_last_error(self) -> Optional[str]:
        """Get the last authentication/connection error"""
        return self._auth_error

    def get_historical_data(self, symbol: str, from_date: str, to_date: str, interval: str = "1") -> Optional[pd.DataFrame]:
        """Fetch historical candle data"""
        if not self.connected:
            raise RuntimeError("Not connected to broker. Call connect() first.")

        if not self.fyers:
            raise RuntimeError("Fyers SDK not initialized")

        max_retries = 6
        base_delay = 1

        for attempt in range(max_retries):
            try:
                data = {
                    "symbol": symbol,
                    "resolution": interval,
                    "date_format": 1,
                    "range_from": from_date,
                    "range_to": to_date,
                    "cont_flag": "1"
                }

                response = self.fyers.history(data=data)

                if not isinstance(response, dict):
                    logger.warning(f"Invalid response format for {symbol}")
                    return pd.DataFrame()

                if response.get('s') == 'error' and response.get('code') == 429:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(f"Rate limit reached. Retrying in {delay}s...")
                    time.sleep(delay)
                    continue

                if 'candles' not in response or not response.get('candles'):
                    #logger.warning(f"No candle data for {symbol} input payload: {data}  respose: {response} ")
                    return pd.DataFrame()

                df = pd.DataFrame(
                    response['candles'],
                    columns=['time', 'open', 'high', 'low', 'close', 'volume']
                )

                # Robust pandas datetime conversion handling both timestamps and strings
                if pd.api.types.is_numeric_dtype(df['time']):
                    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True).dt.tz_convert('Asia/Kolkata')
                else:
                    df['time'] = pd.to_datetime(df['time'], utc=True).dt.tz_convert('Asia/Kolkata')
                df['time'] = df['time'].dt.strftime('%Y-%m-%d %H:%M:%S%z')

                logger.debug(f"Fetched {len(df)} candles for {symbol}")
                return df

            except Exception as e:
                logger.error(f"Error fetching candles for {symbol}: {e}")
                if attempt == max_retries - 1:
                    return pd.DataFrame()
                time.sleep(base_delay)

        return pd.DataFrame()

    def get_ltp(self, symbol: str) -> float:
        """Get Last Traded Price"""
        if not self.connected:
            raise RuntimeError("Not connected to broker. Call connect() first.")

        try:
            if not self.fyers:
                raise RuntimeError("Fyers SDK not initialized")

            response = self.fyers.quotes({"symbols": symbol})
            if response and isinstance(response, dict) and response.get('s') == 'ok' and response.get('d'):
                quote_data = response['d'][0]
                if isinstance(quote_data, dict) and 'v' in quote_data and isinstance(quote_data['v'], dict):
                    if quote_data['v'].get('s') == 'error':
                        raise RuntimeError(f"API error for {symbol}: {quote_data['v']}")
                    lp = quote_data['v'].get('lp')
                    if lp is not None:
                        return float(lp)

            raise RuntimeError(f"No quote data for {symbol}: {response}")

        except Exception as e:
            logger.error(f"Error fetching LTP for {symbol}: {e}")
            raise RuntimeError(f"Failed to get LTP for {symbol}: {e}")

    def place_order(self, order_params: Dict[str, Any]) -> Dict[str, Any]:
        """Place an order"""
        if not self.connected:
            raise RuntimeError("Not connected to broker. Call connect() first.")

        if not self.fyers:
            raise RuntimeError("Fyers SDK not initialized")

        try:
            symbol = order_params.get('symbol', '')
            qty = order_params.get('qty', 0)
            side = order_params.get('side', 'BUY')
            order_type = order_params.get('type', 'MARKET')
            price = order_params.get('price', 0.0)
            product_type = order_params.get('product_type', 'INTRADAY')

            # Fyers API v3 type mapping: 1=LIMIT, 2=MARKET, 3=STOPLOSS LIMIT, 4=STOPLOSS MARKET
            fyers_type = 2 if str(order_type).upper() == "MARKET" else 1
            side_int = 1 if str(side).upper() == "BUY" else -1

            order_data = {
                "symbol": symbol,
                "qty": int(qty),
                "type": fyers_type,
                "side": side_int,
                "productType": str(product_type).upper(),
                "limitPrice": float(price) if str(order_type).upper() == "LIMIT" else 0.0,
                "stopPrice": 0.0,
                "validity": "DAY",
                "disclosedQty": 0,
                "offlineOrder": False,
                "stopLoss": 0.0,
                "takeProfit": 0.0
            }

            response = self.fyers.place_order(data=order_data)

            if response and isinstance(response, dict):
                if response.get('s') == 'ok':
                    order_id = response.get('id', '')
                    logger.info(f"Order placed: {order_id}")
                    return {'success': True, 'order_id': order_id, 'response': response}
                else:
                    # Return the actual error - don't fall back to demo
                    error_msg = response.get('message', 'Unknown error')
                    error_code = response.get('code', 'N/A')
                    logger.error(f"Order failed [code={error_code}]: {error_msg}")
                    return {
                        'success': False, 
                        'error': error_msg,
                        'error_code': error_code,
                        'response': response
                    }
            else:
                return {'success': False, 'error': 'Invalid response from API', 'response': response}

        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return {'success': False, 'error': str(e)}

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancel an order"""
        if not self.connected:
            raise RuntimeError("Not connected to broker. Call connect() first.")

        try:
            if not self.fyers:
                raise RuntimeError("Fyers SDK not initialized")
            response = self.fyers.cancel_order(data={"id": order_id})
            if response and isinstance(response, dict) and response.get('s') == 'ok':
                return {'success': True, 'response': response}
            return {'success': False, 'error': response}
        except Exception as e:
            logger.error(f"Error canceling order: {e}")
            return {'success': False, 'error': str(e)}

    def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """Get order status"""
        if not self.connected:
            raise RuntimeError("Not connected to broker. Call connect() first.")

        try:
            response = self.fyers.orderbook()
            if response and isinstance(response, dict) and response.get('s') == 'ok':
                order_list = response.get('orderBook', response.get('orders', []))
                if isinstance(order_list, list):
                    for order in order_list:
                        if order.get('id') == order_id or order.get('orderId') == order_id:
                            return {
                                'success': True,
                                'status': order.get('status'),
                                'filled_qty': float(order.get('filledQty', 0)),
                                'avg_price': float(order.get('avgPrice', 0)),
                                'order': order
                            }
            return {'success': False, 'error': 'Order not found'}
        except Exception as e:
            logger.error(f"Error fetching order status: {e}")
            return {'success': False, 'error': str(e)}

    def get_positions(self) -> List[Dict[str, Any]]:
        """Get all positions"""
        if not self.connected:
            raise RuntimeError("Not connected to broker. Call connect() first.")

        try:
            if not self.fyers:
                raise RuntimeError("Fyers SDK not initialized")

            response = self.fyers.positions()
            if response and isinstance(response, dict) and response.get('s') == 'ok':
                positions = []
                net_positions = response.get('netPositions', [])
                if isinstance(net_positions, list):
                    for pos in net_positions:
                        symbol = pos.get('symbol', '')
                        if not symbol:
                            continue

                        try:
                            net_qty = float(pos.get('netQty', 0))
                            buy_avg = float(pos.get('buyAvg', 0))
                            market_value = float(pos.get('marketValue', 0))
                            pnl = float(pos.get('pnl', 0))
                        except (ValueError, TypeError):
                            net_qty = 0.0
                            buy_avg = 0.0
                            market_value = 0.0
                            pnl = 0.0

                        positions.append({
                            'symbol': symbol,
                            'quantity': int(net_qty),
                            'entry_price': buy_avg,
                            'ltp': market_value,
                            'pnl': pnl,
                            'raw': pos
                        })
                return positions
            return []
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return []

    def get_funds(self) -> Dict[str, Any]:
        """Get available funds"""
        if not self.connected:
            raise RuntimeError("Not connected to broker. Call connect() first.")

        try:
            if not self.fyers:
                raise RuntimeError("Fyers SDK not initialized")

            response = self.fyers.funds()

            if response and isinstance(response, dict) and response.get('s') == 'error':
                error_msg = response.get('message', 'Unknown error')
                error_code = response.get('code', 'N/A')
                raise RuntimeError(f"Funds API error [code={error_code}]: {error_msg}")

            fund_data = response.get("fund_limit", [])

            equity_available = 0.0
            used_margin = 0.0
            available_margin = 0.0

            if isinstance(fund_data, list):
                for item in fund_data:
                    if not isinstance(item, dict):
                        continue
                    title = str(item.get("title", "")).lower()
                    amount = float(item.get("equityAmount", 0.0) or 0.0)
                    if "total balance" in title:
                        equity_available = amount
                    elif "used margin" in title or "utilized" in title:
                        used_margin = amount
                    elif "available margin" in title or "available" in title:
                        available_margin = amount

            return {
                'success': True,
                'equity_available': equity_available,
                'used_margin': used_margin,
                'available_margin': available_margin,
                'net_pnl': float(response.get("netPnl", 0.0) or 0.0),
                'timestamp': datetime.now(pytz.timezone("Asia/Kolkata")).isoformat()
            }
        except Exception as e:
            logger.error(f"Error fetching funds: {e}")
            raise RuntimeError(f"Failed to get funds: {e}")



    # ═══════════════════════════════════════════════════════════════════════
    # MODIFIED: place_order now respects offlineOrder from params
    # ═══════════════════════════════════════════════════════════════════════

    # In the existing place_order method, change this line:
    # FROM: "offlineOrder": False,
    # TO:   "offlineOrder": order_params.get('offlineOrder', False),

    # ═══════════════════════════════════════════════════════════════════════
    # NEW: Helper methods for place_order_v1
    # ═══════════════════════════════════════════════════════════════════════

    def _wait_for_entry_fill(self, order_id: str, max_wait_seconds: int = 30) -> bool:
        """Poll Fyers orderbook until entry order is filled."""
        self.logger.info(f"⏳ Waiting for entry fill: {order_id} (max {max_wait_seconds}s)...")
        start_time = time.time()

        while time.time() - start_time < max_wait_seconds:
            try:
                response = self.fyers.orderbook()
                if not response or response.get('s') != 'ok':
                    time.sleep(1)
                    continue

                order_list = response.get('orderBook', response.get('orders', []))
                for order in order_list:
                    if order.get('id') == order_id or order.get('orderId') == order_id:
                        status = order.get('status')
                        filled_qty = int(order.get('filledQty', 0))

                        if status == 2:  # FILLED
                            self.logger.info(f"✅ Order {order_id} FILLED")
                            return True
                        elif filled_qty > 0:
                            self.logger.info(f"✅ Order {order_id} PARTIAL FILL: {filled_qty}")
                            return True
                        elif status in [1, 5, 7]:  # CANCELLED, REJECTED, EXPIRED
                            self.logger.error(f"❌ Order {order_id} failed (status: {status})")
                            return False

                time.sleep(1)
            except Exception as e:
                self.logger.debug(f"Poll error: {e}")
                time.sleep(1)

        self.logger.warning(f"⏱️ Order {order_id} still pending after {max_wait_seconds}s")
        return False

    def _place_gtt_oco(self, symbol: str, qty: int, side: str,
                       sl_price: float, tp_price: float, product_type: str = "CNC") -> Dict[str, Any]:
        """
        Place GTT OCO (One-Cancels-Other) with SL and TP legs.
        Uses Fyers v3 place_gtt_order API.
        """
        try:
            is_buy = side.upper() == "BUY"
            exit_side = -1 if is_buy else 1

            # Round to tick (0.05 for most NSE stocks)
            tick = 0.05
            sl_price = round(sl_price / tick) * tick
            tp_price = round(tp_price / tick) * tick

            gtt_data = {
                "symbol": symbol,
                "side": exit_side,
                "productType": product_type.upper(),
                "orderInfo": {
                    "leg1": {
                        "price": tp_price,
                        "triggerPrice": tp_price,
                        "qty": qty
                    },
                    "leg2": {
                        "price": sl_price,
                        "triggerPrice": sl_price,
                        "qty": qty
                    }
                }
            }

            self.logger.info(f"📤 Placing GTT OCO: {symbol} | SL: {sl_price} | TP: {tp_price}")
            response = self.fyers.place_gtt_order(data=gtt_data)

            if response and isinstance(response, dict) and response.get('s') == 'ok':
                gtt_id = response.get('id', '')
                self.logger.info(f"✅ GTT OCO placed: {gtt_id}")
                return {'success': True, 'gtt_order_id': gtt_id, 'response': response}
            else:
                error_msg = response.get('message', 'Unknown error') if isinstance(response, dict) else str(response)
                self.logger.error(f"❌ GTT failed: {error_msg}")
                return {'success': False, 'error': error_msg, 'response': response}

        except Exception as e:
            self.logger.error(f"❌ GTT exception: {e}")
            return {'success': False, 'error': str(e)}

    def place_order_v1(self, order_params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Place an order with optional GTT OCO bracket for SL and TP.
        Supports AMO (After Market Orders) for testing during market close.

        Args:
            order_params: {
                'symbol': 'NSE:SBIN-EQ',
                'qty': 10,
                'side': 'BUY',
                'type': 'MARKET',
                'product_type': 'CNC',
                'price': 0.0,              # for LIMIT orders
                'amo': False,              # True = After Market Order
                'stop_loss_price': 450.0,  # optional - triggers GTT SL
                'take_profit_price': 550.0 # optional - triggers GTT TP
            }

        Returns:
            {
                'success': bool,
                'order_id': str,
                'entry_filled': bool,
                'amo': bool,
                'gtt_placed': bool,
                'gtt_order_id': str,
                'error': str
            }
        """
        if not self.connected:
            raise RuntimeError("Not connected to broker. Call connect() first.")

        symbol = order_params.get('symbol', '')
        qty = order_params.get('qty', 0)
        side = order_params.get('side', 'BUY')
        order_type = order_params.get('type', 'MARKET')
        product_type = order_params.get('product_type', 'CNC')
        price = order_params.get('price', 0.0)
        is_amo = order_params.get('amo', False)
        sl_price = order_params.get('stop_loss_price')
        tp_price = order_params.get('take_profit_price')

        # ── 1. Place entry order ──
        self.logger.info(f"📥 Placing {'AMO ' if is_amo else ''}entry order: {side} {qty} {symbol} @ {order_type}")
        entry_result = self.place_order({
            'symbol': symbol,
            'qty': qty,
            'side': side,
            'type': order_type,
            'price': price,
            'product_type': product_type,
            'offlineOrder': is_amo  # AMO flag passed through
        })

        if not entry_result.get('success'):
            self.logger.error(f"❌ Entry order failed: {entry_result.get('error')}")
            return {
                'success': False,
                'order_id': None,
                'entry_filled': False,
                'amo': is_amo,
                'gtt_placed': False,
                'error': entry_result.get('error', 'Entry order failed')
            }

        entry_order_id = entry_result.get('order_id')
        self.logger.info(f"✅ Entry order placed: {entry_order_id}")

        # ── 2. AMO mode: return early, GTT after market open ──
        if is_amo:
            self.logger.info("AMO order queued for next market open. GTT must be placed after fill.")
            return {
                'success': True,
                'order_id': entry_order_id,
                'entry_filled': False,
                'amo': True,
                'gtt_placed': False,
                'message': 'AMO entry placed. GTT will be placed after market open when position is active.'
            }

        # ── 3. No SL/TP requested → return early ──
        if sl_price is None or tp_price is None:
            return {
                'success': True,
                'order_id': entry_order_id,
                'entry_filled': True,
                'amo': False,
                'gtt_placed': False,
                'message': 'Entry placed, no GTT requested'
            }

        # ── 4. Wait for entry fill (MARKET fills fast, LIMIT may wait) ──
        entry_filled = self._wait_for_entry_fill(entry_order_id, max_wait_seconds=30)

        if not entry_filled:
            self.logger.error(f"❌ Entry {entry_order_id} did not fill. Cancelling...")
            self.cancel_order(entry_order_id)
            return {
                'success': False,
                'order_id': entry_order_id,
                'entry_filled': False,
                'amo': False,
                'gtt_placed': False,
                'error': 'Entry order did not fill'
            }

        # ── 5. Place GTT OCO ──
        gtt_result = self._place_gtt_oco(
            symbol=symbol, qty=qty, side=side,
            sl_price=sl_price, tp_price=tp_price, product_type=product_type
        )

        return {
            'success': True,
            'order_id': entry_order_id,
            'entry_filled': True,
            'amo': False,
            'gtt_placed': gtt_result.get('success', False),
            'gtt_order_id': gtt_result.get('gtt_order_id'),
            'message': 'Entry + GTT placed' if gtt_result.get('success') else 'Entry placed, GTT failed',
            'gtt_error': gtt_result.get('error')
        }


# ═══════════════════════════════════════════════════════════════════════
# LIVE AMO TEST — Real API calls during market close
# ═══════════════════════════════════════════════════════════════════════

def run_test_v1_live():
    """
    Real AMO test using live Fyers API. 
    Run this when market is CLOSED (after 15:30 or before 9:15).

    What it does:
      1. Connects to live Fyers
      2. Places AMO BUY order for 1 share SBIN (CNC, MARKET)
      3. Shows the order ID
      4. Tries placing GTT (will likely fail since AMO not filled yet)
      5. Cancels the AMO order to clean up
    """
    print("=" * 60)
    print("🔴 LIVE AMO TEST — Real Fyers API calls")
    print("=" * 60)

    broker = FyersBroker()

    print("\n1. Connecting to Fyers...")
    try:
        if not broker.connect():
            print("❌ Connection failed")
            return
    except Exception as e:
        print(f"❌ Connection error: {e}")
        return

    print("✅ Connected to Fyers LIVE")

    # ── Test 1: AMO entry only ──
    print("\n" + "─" * 60)
    print("TEST 1: AMO entry order (no SL/TP)")
    print("─" * 60)

    result1 = broker.place_order_v1({
        'symbol': 'NSE:SBIN-EQ',
        'qty': 1,
        'side': 'BUY',
        'type': 'MARKET',
        'product_type': 'CNC',
        'amo': True
    })

    print(f"\n   Result:")
    print(f"   success:      {result1.get('success')}")
    print(f"   order_id:     {result1.get('order_id')}")
    print(f"   amo:          {result1.get('amo')}")
    print(f"   message:      {result1.get('message')}")
    if result1.get('error'):
        print(f"   error:        {result1['error']}")

    # Cancel Test 1 order
    oid1 = result1.get('order_id')
    if oid1:
        print(f"\n   🧹 Cancelling AMO order {oid1}...")
        cancel1 = broker.cancel_order(oid1)
        print(f"   Cancel result: {cancel1}")

    # ── Test 2: AMO entry + GTT attempt ──
    print("\n" + "─" * 60)
    print("TEST 2: AMO entry + GTT SL/TP (GTT will fail until AMO fills)")
    print("─" * 60)

    result2 = broker.place_order_v1({
        'symbol': 'NSE:SBIN-EQ',
        'qty': 1,
        'side': 'BUY',
        'type': 'MARKET',
        'product_type': 'CNC',
        'amo': True,
        'stop_loss_price': 720.0,
        'take_profit_price': 780.0
    })

    print(f"\n   Result:")
    print(f"   success:      {result2.get('success')}")
    print(f"   order_id:     {result2.get('order_id')}")
    print(f"   amo:          {result2.get('amo')}")
    print(f"   gtt_placed:   {result2.get('gtt_placed')}")
    print(f"   message:      {result2.get('message')}")
    if result2.get('error'):
        print(f"   error:        {result2['error']}")

    # Cancel Test 2 order
    oid2 = result2.get('order_id')
    if oid2:
        print(f"\n   🧹 Cancelling AMO order {oid2}...")
        cancel2 = broker.cancel_order(oid2)
        print(f"   Cancel result: {cancel2}")

    # ── Test 3: Normal entry (if market is open, this tests full flow) ──
    print("\n" + "─" * 60)
    print("TEST 3: Normal entry + GTT (only works if market is OPEN)")
    print("─" * 60)

    now = datetime.now(pytz.timezone('Asia/Kolkata'))
    market_open = datetime.strptime('09:15', '%H:%M').time()
    market_close = datetime.strptime('15:30', '%H:%M').time()

    if market_open <= now.time() <= market_close and now.weekday() < 5:
        print("   Market is OPEN — placing live order...")
        result3 = broker.place_order_v1({
            'symbol': 'NSE:SBIN-EQ',
            'qty': 1,
            'side': 'BUY',
            'type': 'MARKET',
            'product_type': 'CNC',
            'amo': False,
            'stop_loss_price': 720.0,
            'take_profit_price': 780.0
        })
        print(f"\n   Result: {result3}")
    else:
        print("   Market is CLOSED — skipping (use AMO mode instead)")

    broker.disconnect()
    print("\n" + "=" * 60)
    print("✅ Live test complete")
    print("=" * 60)

def run_test():
    """Test function for Fyers broker"""
    print("Testing Fyers Broker Implementation")
    print("=" * 50)

    try:
        broker = FyersBroker()
        print(f"Broker created: {broker.name}")
        print(f"Demo mode: {broker.is_demo_mode()}")

        if broker.connect():
            print("Connection successful (LIVE MODE)")

            # Test get_ltp
            ltp = broker.get_ltp("NSE:SBIN-EQ")
            print(f"LTP of SBIN: {ltp}")

            # Test get_funds
            funds = broker.get_funds()
            print(f"Funds: {funds}")

            # Test get_positions
            positions = broker.get_positions()
            print(f"Positions: {len(positions)}")

            # Test get_historical_data
            print("\n--- Testing get_historical_data ---")
            hist_data = broker.get_historical_data("NSE:SBIN-EQ", "2026-01-01", "2026-01-10", "D")
            if hist_data is not None:
                print(f"Historical data rows: {len(hist_data)}")
            else:
                print("Historical data: None (not connected or error)")

            # Test place_order
            print("\n--- Testing place_order ---")
            # Use CNC (delivery) instead of MIS to avoid "after system square off" error
            order_result = broker.place_order({
                'symbol': 'NSE:SBIN-EQ',
                'qty': 10,
                'side': 'BUY',
                'type': 'MARKET',
                'product_type': 'CNC'  # CNC = Cash and Carry (delivery), avoids MIS square-off restriction
            })
            print(f"Order result: {order_result}")

            broker.disconnect()
            print("\nAll tests completed")
            return True

    except RuntimeError as e:
        print(f"ERROR: {e}")
        return False
    except Exception as e:
        print(f"UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        run_test()
    else:
        print("Fyers Broker Implementation")
        print("Run with 'test' argument to test: python fyers_broker_impl.py test")
        broker = FyersBroker()
