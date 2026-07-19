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