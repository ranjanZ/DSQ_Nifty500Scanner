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
from datetime import datetime
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import base class
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from broker_base import BrokerBase, register_broker

# Fyers imports
try:
    from fyers_apiv3 import fyersModel
    from src.utils.fyers.fyers_auth import access_token, client_id, fyers
except ImportError as e:
    logging.warning(f"Fyers SDK not available: {e}")
    fyersModel = None
    access_token = None
    client_id = None
    fyers = None

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
        
        # Get credentials with fallback hierarchy:
        # 1. Config dict argument
        # 2. Environment variable
        # 3. Imported from auth module (if available)
        # 4. Default placeholder for testing
        self.access_token = (
            config_dict.get('access_token') or 
            os.getenv('FYERS_ACCESS_TOKEN') or 
            access_token or 
            'demo_access_token_for_testing'
        )
        self.client_id = (
            config_dict.get('client_id') or 
            os.getenv('FYERS_CLIENT_ID') or 
            client_id or 
            'demo_client_id'
        )
        self.fyers = fyers
        self.cur_path = os.path.dirname(os.path.abspath(__file__))
        
        # Only try to initialize SDK if we have real-looking credentials
        if self.access_token and self.access_token not in ['default_access_token', 'demo_access_token_for_testing']:
            try:
                self._init_fyers_instance()
            except Exception as e:
                logger.warning(f"Could not initialize Fyers SDK: {e}")
        else:
            logger.info("Running in demo mode with default credentials")
        
    def connect(self) -> bool:
        """Connect to Fyers API"""
        try:
            if not self.fyers:
                self.logger.warning("Fyers SDK not initialized (demo mode). Simulating connection...")
                # In demo mode, simulate a successful connection for testing
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
                self.logger.error(f"❌ Connection failed: {response}")
                return False
        except Exception as e:
            self.logger.error(f"❌ Error connecting to Fyers: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from Fyers API"""
        self.connected = False
        self.logger.info("Disconnected from Fyers API")
    
    def get_historical_data(self, symbol: str, from_date: str, to_date: str, interval: str = "1") -> Optional[pd.DataFrame]:
        """Fetch historical candle data"""
        if not self.connected:
            self.logger.error("Not connected to broker")
            return None
        
        max_retries = 6
        base_delay = 1
        
        for attempt in range(max_retries):
            try:
                fyers_model = fyersModel.FyersModel(
                    client_id=self.client_id,
                    is_async=False,
                    token=self.access_token,
                    log_path=os.path.join(self.cur_path, "logs/")
                )
                
                data = {
                    "symbol": symbol,
                    "resolution": interval,
                    "date_format": 1,
                    "range_from": from_date,
                    "range_to": to_date,
                    "cont_flag": "1"
                }
                
                response = fyers_model.history(data=data)
                
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
                
                df['time'] = df['time'].apply(pd.Timestamp, unit='s', tzinfo=pytz.timezone('Asia/Kolkata'))
                df['time'] = df['time'].apply(pd.Timestamp.isoformat)
                
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
                # Demo mode: return simulated price
                import random
                simulated_price = round(random.uniform(100, 2000), 2)
                self.logger.info(f"Demo LTP for {symbol}: {simulated_price}")
                return simulated_price
                
            response = self.fyers.quotes({"symbols": symbol})
            if response and response.get('s') == 'ok' and response.get('d') and len(response.get('d', [])) > 0:
                if response['d'][0]['v'].get('s') == 'error':
                    return 0.0
                return float(response['d'][0]['v']['lp'])
            return 0.0
        except Exception as e:
            self.logger.error(f"❌ Error fetching LTP for {symbol}: {e}")
            return 0.0
    
    def place_order(self, order_params: Dict[str, Any]) -> Dict[str, Any]:
        """Place an order"""
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
                # Demo mode: return empty positions
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
                # Demo mode: return simulated funds
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
            return {'success': False, 'error': str(e)}


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
        
        broker.disconnect()
        print("✅ Tests completed")
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
