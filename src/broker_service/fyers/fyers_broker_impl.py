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
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.broker_service.broker_base import BrokerBase
from fyers_apiv3 import fyersModel
from fyers_apiv3.FyersWebsocket import data_ws

load_dotenv()

logger = logging.getLogger(__name__)


class FyersBroker(BrokerBase):
    """Fyers broker implementation"""
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        self.name = "Fyers"
        self.client_id = os.getenv("FYERS_CLIENT_ID", "")
        self.secret_key = os.getenv("FYERS_SECRET_KEY", "")
        self.redirect_uri = os.getenv("FYERS_REDIRECT_URI", "https://www.google.com")
        self.access_token = os.getenv("FYERS_ACCESS_TOKEN", "")
        
        self.fyers = None
        self.tz = pytz.timezone("Asia/Kolkata")
        
    def connect(self) -> bool:
        """Connect to Fyers API"""
        try:
            if not self.client_id:
                logger.error("FYERS_CLIENT_ID not found in environment variables")
                return False
            
            # Initialize Fyers model
            self.fyers = fyersModel.FyersModel(
                client_id=self.client_id,
                is_async=False,
                token=self.access_token,
                log_path="logs/"
            )
            
            self.connected = True
            logger.info(f"Connected to Fyers broker")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to Fyers: {e}")
            self.connected = False
            return False
    
    def disconnect(self):
        """Disconnect from Fyers API"""
        self.fyers = None
        self.connected = False
        logger.info("Disconnected from Fyers broker")
    
    def validate_credentials(self) -> bool:
        """Validate Fyers credentials"""
        if not self.client_id or not self.secret_key:
            return False
        
        try:
            # Try to get holdings to validate credentials
            response = self.fyers.holdings()
            return response.get('s') == 'ok'
        except Exception as e:
            logger.error(f"Credential validation failed: {e}")
            return False
    
    def place_order(self, symbol: str, qty: int, side: str, 
                    type: str = "MARKET", price: float = 0.0, 
                    product_type: str = "INTRADAY") -> Optional[str]:
        """Place an order with Fyers"""
        if not self.connected:
            logger.error("Not connected to broker")
            return None
        
        try:
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
                "stopLoss": 0,
                "takeProfit": 0
            }
            
            logger.info(f"Placing {side} order: {symbol} | Qty: {qty} | Type: {type}")
            response = self.fyers.place_order(data=order_data)
            
            if response and response.get('s') == 'ok':
                order_id = response.get('id', '')
                logger.info(f"Order placed successfully: {order_id}")
                return order_id
            else:
                logger.error(f"Order failed: {response}")
                return None
                
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return None
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order"""
        if not self.connected:
            logger.error("Not connected to broker")
            return False
        
        try:
            response = self.fyers.cancel_order(data={"id": order_id})
            if response and response.get('s') == 'ok':
                logger.info(f"Order cancelled: {order_id}")
                return True
            else:
                logger.error(f"Failed to cancel order: {response}")
                return False
        except Exception as e:
            logger.error(f"Error cancelling order: {e}")
            return False
    
    def get_positions(self) -> Dict[str, Any]:
        """Get current positions"""
        if not self.connected:
            return {}
        
        try:
            response = self.fyers.positions()
            if response and response.get('s') == 'ok':
                positions = {}
                net_positions = response.get('netPositions', [])
                
                for pos in net_positions:
                    symbol = pos.get('symbol', '')
                    if not symbol:
                        continue
                    
                    net_qty = int(pos.get('netQty', 0))
                    buy_avg = float(pos.get('buyAvg', 0))
                    sell_avg = float(pos.get('sellAvg', 0))
                    
                    entry_price = buy_avg if net_qty > 0 else sell_avg
                    
                    positions[symbol] = {
                        "entry_price": entry_price,
                        "quantity": net_qty,
                        "capital_used": abs(net_qty * entry_price),
                        "raw": pos
                    }
                
                logger.info(f"Fetched {len(positions)} positions")
                return positions
            else:
                logger.error(f"Failed to fetch positions: {response}")
                return {}
                
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return {}
    
    def get_orders(self) -> Dict[str, Any]:
        """Get current orders"""
        if not self.connected:
            return {}
        
        try:
            response = self.fyers.orderbook()
            if response and response.get('s') == 'ok':
                orders = {}
                order_list = response.get('orderBook', [])
                
                for order in order_list:
                    order_id = order.get('id') or order.get('orderId')
                    if order_id is None:
                        continue
                    
                    orders[order_id] = {
                        "status": str(order.get("status", "UNKNOWN")),
                        "filled_quantity": int(order.get("filledQty", 0)),
                        "average_price": float(order.get("avgPrice", 0)),
                        "symbol": str(order.get("symbol", "")),
                        "raw": order
                    }
                
                logger.info(f"Fetched {len(orders)} orders")
                return orders
            else:
                logger.error(f"Failed to fetch orders: {response}")
                return {}
                
        except Exception as e:
            logger.error(f"Error fetching orders: {e}")
            return {}
    
    def get_holdings(self) -> Dict[str, Any]:
        """Get current holdings"""
        if not self.connected:
            return {}
        
        try:
            response = self.fyers.holdings()
            if response and response.get('s') == 'ok':
                holdings = response.get('holdings', [])
                logger.info(f"Fetched {len(holdings)} holdings")
                return {"holdings": holdings}
            else:
                logger.error(f"Failed to fetch holdings: {response}")
                return {}
                
        except Exception as e:
            logger.error(f"Error fetching holdings: {e}")
            return {}
    
    def get_historical_data(self, symbol: str, from_date: str, 
                           to_date: str, interval: str = "1") -> pd.DataFrame:
        """Get historical candle data from Fyers"""
        if not self.connected:
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
                
                logger.debug(f"Fetching candles: {symbol} | {from_date} to {to_date}")
                response = self.fyers.history(data=data)
                
                # Check for rate limit
                if response and response.get('s') == 'error' and response.get('code') == 429:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(f"Rate limit reached. Retrying in {delay}s...")
                    time.sleep(delay)
                    continue
                
                if response is None or 'candles' not in response or not response.get('candles'):
                    logger.warning(f"No candle data for {symbol}")
                    return pd.DataFrame()
                
                df = pd.DataFrame(
                    response['candles'],
                    columns=['time', 'open', 'high', 'low', 'close', 'volume']
                )
                
                df['time'] = df['time'].apply(pd.Timestamp, unit='s', tzinfo=self.tz)
                df['time'] = df['time'].apply(pd.Timestamp.isoformat)
                
                logger.info(f"Fetched {len(df)} candles for {symbol}")
                return df
                
            except Exception as e:
                logger.error(f"Error fetching candles: {e}")
                if attempt == max_retries - 1:
                    return pd.DataFrame()
                time.sleep(base_delay)
        
        return pd.DataFrame()
    
    def get_quotes(self, symbols: List[str]) -> Dict[str, Any]:
        """Get real-time quotes for symbols"""
        if not self.connected:
            return {}
        
        try:
            # Fyers quote format: NSE:RELIANCE-EQ
            quote_symbols = [f"NSE:{sym}-EQ" if ':' not in sym else sym for sym in symbols]
            response = self.fyers.get_quotes(data={"symbols": ",".join(quote_symbols)})
            
            if response and response.get('s') == 'ok':
                quotes = response.get('d', {})
                logger.info(f"Fetched quotes for {len(quotes)} symbols")
                return quotes
            else:
                logger.error(f"Failed to fetch quotes: {response}")
                return {}
                
        except Exception as e:
            logger.error(f"Error fetching quotes: {e}")
            return {}


def run_test():
    """Test function for Fyers broker"""
    print("Testing Fyers Broker...")
    
    broker = FyersBroker()
    print(f"Broker name: {broker.name}")
    print(f"Client ID configured: {'Yes' if broker.client_id else 'No'}")
    
    # Test connection (will fail without valid credentials)
    if broker.connect():
        print("✓ Connected successfully")
        broker.disconnect()
    else:
        print("✗ Connection failed (expected if no credentials)")
    
    print("Fyers broker test complete!")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        run_test()
    else:
        print("Fyers Broker Implementation")
        print("Usage: python -m src.broker_service.fyers.fyers_broker_impl test")
        run_test()
