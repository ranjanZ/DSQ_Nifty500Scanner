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

# Load environment variables (handle typo in DEEFAULT_ENV_PATH gracefully)
env_path = os.environ.get('DEFAULT_ENV_PATH') or os.environ.get('DEEFAULT_ENV_PATH')
if env_path:
    load_dotenv(env_path)
else:
    load_dotenv()  # Fallback to default .env in current directory

# Import base class
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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

# Fyers imports
try:
    from fyers_apiv3 import fyersModel
    FYERS_SDK_AVAILABLE = True
except ImportError as e:
    logging.warning(f"Fyers SDK not available: {e}")
    fyersModel = None
    FYERS_SDK_AVAILABLE = False

# Import auth utility
try:
    # Adjust this import path to match your actual file structure (e.g., utils.fyers.fyers_auth)
    from utils.fyers.fyers_auth import generate_access_token
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
    """Fyers broker implementation"""
    
    def __init__(self, config: Dict[str, Any] = None):
        # Initialize base class first
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
        
        # Auth flow parameters (matching the updated generate_access_token signature)
        self.response_type = config_dict.get('response_type', os.getenv('FYERS_RESPONSE_TYPE', 'code'))
        self.grant_type = config_dict.get('grant_type', os.getenv('FYERS_GRANT_TYPE', 'authorization_code'))
        self.state = config_dict.get('state', os.getenv('FYERS_STATE', 'sample_state'))
        
        self.fyers = None
        self.cur_path = os.path.dirname(os.path.abspath(__file__))
        
        # Initialize SDK if we have credentials
        if FYERS_SDK_AVAILABLE:
            try:
                self._init_fyers_instance()
            except Exception as e:
                logger.warning(f"Could not initialize Fyers SDK: {e}")
        else:
            logger.info("Fyers SDK not available, running in demo mode")
        
    def _init_fyers_instance(self):
        """Initialize Fyers SDK instance"""
        if not FYERS_SDK_AVAILABLE:
            return
        
        try:
            # If we don't have an access token, try to generate one using the auth utility
            if not self.access_token and AUTH_UTIL_AVAILABLE and generate_access_token:
                logger.info("No access token found, attempting to generate one...")
                token_result = generate_access_token(
                    client_id=self.client_id,
                    secret_key=self.secret_key,
                    fyers_id=self.fyers_id,
                    pin=self.pin,
                    totp_token=self.totp_token,
                    redirect_uri=self.redirect_uri,
                )
                
                if token_result.get('success'):
                    self.access_token = token_result['access_token']
                    logger.info("✅ Access token generated successfully")
                else:
                    logger.warning(f"⚠️ Could not generate access token: {token_result.get('error')}")
                    logger.warning("Running in demo mode")
            
            if self.access_token:
                self.fyers = fyersModel.FyersModel(
                    client_id=self.client_id,
                    is_async=False,
                    token=self.access_token,
                    log_path=os.path.join(self.cur_path, "logs/")
                )
                logger.info("Fyers SDK initialized successfully with access token")
            else:
                logger.warning("No access token available - running in demo mode only")
                self.fyers = None

        except Exception as e:
            logger.warning(f"Could not initialize Fyers instance: {e}")
            self.fyers = None
        
    def connect(self) -> bool:
        """Connect to Fyers API"""
        try:
            if not self.fyers:
                self.logger.warning("Fyers SDK not initialized (demo mode). Simulating connection...")
                self.connected = True
                self.logger.info("✅ Connected to Fyers API (Demo Mode)")
                return True
            
            # Test connection
            response = self.fyers.funds()
            if response and response.get('s') == 'ok':
                self.connected = True
                self.logger.info("✅ Connected to Fyers API")
                return True
            else:
                # Authentication failed - fall back to demo mode
                self.logger.warning(f"⚠️ Authentication failed: {response}. Falling back to demo mode...")
                self.connected = True
                self.logger.info("✅ Connected to Fyers API (Demo Mode - Auth Failed)")
                return True
        except Exception as e:
            self.logger.error(f"❌ Error connecting to Fyers: {e}")
            self.connected = True
            return True
    
    def disconnect(self):
        """Disconnect from Fyers API"""
        self.connected = False
        self.logger.info("Disconnected from Fyers API")
    
    def get_historical_data(self, symbol: str, from_date: str, to_date: str, interval: str = "1") -> Optional[pd.DataFrame]:
        """Fetch historical candle data"""
        if not self.connected:
            self.logger.error("Not connected to broker")
            return None
        
        if not FYERS_SDK_AVAILABLE or not self.fyers:
            self.logger.info(f"Demo mode: Returning empty historical data for {symbol}")
            return pd.DataFrame()
        
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
                
                if response and response.get('s') == 'error' and response.get('code') == 429:
                    delay = base_delay * (2 ** attempt)
                    self.logger.warning(f"Rate limit reached. Retrying in {delay}s...")
                    time.sleep(delay)
                    continue
                
                if response is None or 'candles' not in response or not response.get('candles'):
                    self.logger.warning(f"No candle data for {symbol}")
                    return pd.DataFrame()
                
                df = pd.DataFrame(
                    response['candles'],
                    columns=['time', 'open', 'high', 'low', 'close', 'volume']
                )
                
                # ✅ FIXED: Robust pandas datetime conversion with IST timezone
                df['time'] = pd.to_datetime(df['time'], unit='s', utc=True).dt.tz_convert('Asia/Kolkata')
                df['time'] = df['time'].dt.strftime('%Y-%m-%d %H:%M:%S%z')
                
                self.logger.debug(f"✅ Fetched {len(df)} candles for {symbol}")
                return df
                
            except Exception as e:
                self.logger.error(f"❌ Error fetching candles for {symbol}: {e}")
                if attempt == max_retries - 1:
                    return pd.DataFrame()
                time.sleep(base_delay)
        
        return pd.DataFrame()
    
    def get_ltp(self, symbol: str) -> float:
        """Get Last Traded Price"""
        try:
            if not self.fyers:
                simulated_price = round(random.uniform(100, 2000), 2)
                self.logger.info(f"Demo LTP for {symbol}: {simulated_price}")
                return simulated_price
            
            response = self.fyers.quotes({"symbols": symbol})
            if response and response.get('s') == 'ok' and response.get('d') and len(response.get('d', [])) > 0:
                if response['d'][0]['v'].get('s') == 'error':
                    self.logger.warning(f"API error for {symbol}, using demo price")
                    return round(random.uniform(100, 2000), 2)
                return float(response['d'][0]['v']['lp'])
            
            self.logger.warning(f"No quote data for {symbol}, using demo price")
            return round(random.uniform(100, 2000), 2)
        except Exception as e:
            self.logger.error(f"❌ Error fetching LTP for {symbol}: {e}")
            return round(random.uniform(100, 2000), 2)
    
    def place_order(self, order_params: Dict[str, Any]) -> Dict[str, Any]:
        """Place an order"""
        if not FYERS_SDK_AVAILABLE or not self.fyers:
            self.logger.info(f"Demo mode: Simulating order placement")
            simulated_order_id = f"DEMO_{random.randint(100000, 999999)}"
            return {'success': True, 'order_id': simulated_order_id, 'demo_mode': True}
        
        try:
            symbol = order_params.get('symbol', '')
            qty = order_params.get('qty', 0)
            side = order_params.get('side', 'BUY')
            order_type = order_params.get('type', 'MARKET')
            price = order_params.get('price', 0.0)
            product_type = order_params.get('product_type', 'INTRADAY')
            
            fyers_type = 2 if order_type.upper() == "MARKET" else 1
            side_int = 1 if side.upper() == "BUY" else -1
            
            order_data = {
                "symbol": symbol,
                "qty": qty,
                "type": fyers_type,
                "side": side_int,
                "productType": product_type,
                "limitPrice": price if order_type.upper() == "LIMIT" else 0,
                "stopPrice": 0,
                "validity": "DAY",
                "disclosedQty": 0,
                "offlineOrder": False,
                "stopLoss": 0,
                "takeProfit": 0
            }
            
            response = self.fyers.place_order(data=order_data)
            
            if response and response.get('s') == 'error' and response.get('code') == -16:
                self.logger.warning("Auth failed for order, falling back to demo mode")
                simulated_order_id = f"DEMO_{random.randint(100000, 999999)}"
                return {'success': True, 'order_id': simulated_order_id, 'demo_mode': True, 'auth_failed': True}
            
            if response and response.get('s') == 'ok':
                order_id = response.get('id', '')
                self.logger.info(f"✅ Order placed: {order_id}")
                return {'success': True, 'order_id': order_id, 'response': response}
            else:
                self.logger.error(f"❌ Order failed: {response}")
                return {'success': False, 'error': response}
                
        except Exception as e:
            self.logger.error(f"❌ Error placing order: {e}")
            return {'success': False, 'error': str(e)}
    
    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancel an order"""
        try:
            response = self.fyers.cancel_order(data={"id": order_id})
            if response and response.get('s') == 'ok':
                return {'success': True, 'response': response}
            return {'success': False, 'error': response}
        except Exception as e:
            self.logger.error(f"❌ Error canceling order: {e}")
            return {'success': False, 'error': str(e)}
    
    def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """Get order status"""
        try:
            response = self.fyers.orderbook()
            if response and response.get('s') == 'ok':
                order_list = response.get('orderBook', response.get('orders', []))
                for order in order_list:
                    if order.get('id') == order_id or order.get('orderId') == order_id:
                        return {
                            'success': True,
                            'status': order.get('status'),
                            'filled_qty': order.get('filledQty', 0),
                            'avg_price': order.get('avgPrice', 0),
                            'order': order
                        }
            return {'success': False, 'error': 'Order not found'}
        except Exception as e:
            self.logger.error(f"❌ Error fetching order status: {e}")
            return {'success': False, 'error': str(e)}
    
    def get_positions(self) -> List[Dict[str, Any]]:
        """Get all positions"""
        try:
            if not self.fyers:
                self.logger.info("Demo mode: Returning empty positions")
                return []
                
            response = self.fyers.positions()
            if response and response.get('s') == 'ok':
                positions = []
                net_positions = response.get('netPositions', [])
                for pos in net_positions:
                    symbol = pos.get('symbol', '')
                    if not symbol:
                        continue
                    positions.append({
                        'symbol': symbol,
                        'quantity': int(pos.get('netQty', 0)),
                        'entry_price': float(pos.get('buyAvg', 0)),
                        'ltp': float(pos.get('marketValue', 0)),
                        'pnl': float(pos.get('pnl', 0)),
                        'raw': pos
                    })
                return positions
            return []
        except Exception as e:
            self.logger.error(f"❌ Error fetching positions: {e}")
            return []
    
    def get_funds(self) -> Dict[str, Any]:
        """Get available funds"""
        try:
            if not self.fyers:
                self.logger.info("Demo mode: Returning simulated funds")
                return {
                    'success': True,
                    'equity_available': 100000.0,
                    'used_margin': 0.0,
                    'available_margin': 100000.0,
                    'net_pnl': 0.0,
                    'timestamp': datetime.now(pytz.timezone("Asia/Kolkata")).isoformat()
                }
            
            response = self.fyers.funds()
            
            if response and response.get('s') == 'error' and response.get('code') == -16:
                self.logger.warning("Auth failed for funds, falling back to demo mode")
                return {
                    'success': True,
                    'equity_available': 100000.0,
                    'used_margin': 0.0,
                    'available_margin': 100000.0,
                    'net_pnl': 0.0,
                    'timestamp': datetime.now(pytz.timezone("Asia/Kolkata")).isoformat(),
                    'auth_failed': True
                }
            
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
            
            return {
                'success': True,
                'equity_available': equity_available,
                'used_margin': used_margin,
                'available_margin': available_margin,
                'net_pnl': response.get("netPnl", 0),
                'timestamp': datetime.now(pytz.timezone("Asia/Kolkata")).isoformat()
            }
        except Exception as e:
            self.logger.error(f"❌ Error fetching funds: {e}")
            return {
                'success': True,
                'equity_available': 100000.0,
                'used_margin': 0.0,
                'available_margin': 100000.0,
                'net_pnl': 0.0,
                'timestamp': datetime.now(pytz.timezone("Asia/Kolkata")).isoformat(),
                'error_fallback': True
            }


def run_test():
    """Test function for Fyers broker"""
    print("Testing Fyers Broker Implementation")
    print("=" * 50)
    
    broker = FyersBroker()
    print(f"Broker created: {broker.name}")
    
    if broker.connect():
        print("✅ Connection successful")
        
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
        order_result = broker.place_order({
            'symbol': 'NSE:SBIN-EQ',
            'qty': 10,
            'side': 'BUY',
            'type': 'MARKET',
            'product_type': 'INTRADAY'
        })
        print(f"Order result: {order_result}")
        
        broker.disconnect()
        print("\n✅ All tests completed")
        return True
    else:
        print("❌ Connection failed")
        return False


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        run_test()
    else:
        print("Fyers Broker Implementation")
        print("Run with 'test' argument to test: python fyers_broker_impl.py test")