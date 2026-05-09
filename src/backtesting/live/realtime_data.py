"""
Real-time Market Data Handler for Fyers
Handles live price updates and streaming data via WebSocket
"""

import logging
import json
from typing import Dict, List, Callable, Any, Optional
from datetime import datetime
import pytz
from threading import Thread, Lock
import time

from fyers_apiv3.FyersWebsocket import data_ws
from src.utils.fyers.fyers_auth import access_token, client_id


logger = logging.getLogger("RealtimeDataHandler")


class RealtimeDataHandler:
    """Handles real-time market data streams from Fyers"""
    
    def __init__(self, symbols: List[str] = None):
        """
        Initialize real-time data handler
        
        Args:
            symbols: List of symbols to subscribe for real-time data
        """
        self.symbols = symbols or []
        self.access_token = access_token
        self.client_id = client_id
        
        # Data storage
        self.price_data: Dict[str, Dict[str, Any]] = {}
        self.data_lock = Lock()
        
        # WebSocket
        self.websocket = None
        self.connected = False
        
        # Callbacks
        self.on_price_update_callbacks: List[Callable] = []
        self.on_connect_callbacks: List[Callable] = []
        self.on_error_callbacks: List[Callable] = []
        
        logger.info("RealtimeDataHandler initialized")
    
    def add_symbol(self, symbol: str):
        """Add symbol to subscription"""
        if symbol not in self.symbols:
            self.symbols.append(symbol)
            if self.connected:
                self._subscribe([symbol])
    
    def remove_symbol(self, symbol: str):
        """Remove symbol from subscription"""
        if symbol in self.symbols:
            self.symbols.remove(symbol)
            if self.connected:
                self._unsubscribe([symbol])
    
    def register_on_price_update(self, callback: Callable):
        """Register callback for price updates"""
        self.on_price_update_callbacks.append(callback)
    
    def register_on_connect(self, callback: Callable):
        """Register callback for connection events"""
        self.on_connect_callbacks.append(callback)
    
    def register_on_error(self, callback: Callable):
        """Register callback for error events"""
        self.on_error_callbacks.append(callback)
    
    def _on_open(self, ws):
        """Handle WebSocket open"""
        logger.info("WebSocket connected")
        self.connected = True
        
        # Subscribe to symbols
        self._subscribe(self.symbols)
        
        # Call callbacks
        for callback in self.on_connect_callbacks:
            try:
                callback(self)
            except Exception as e:
                logger.error(f"Error in connect callback: {e}")
    
    def _on_message(self, ws, message):
        """Handle WebSocket message"""
        try:
            data = json.loads(message)
            
            # Update price data
            with self.data_lock:
                for item in data:
                    if 'symbol' in item:
                        symbol = item['symbol']
                        self.price_data[symbol] = {
                            'symbol': symbol,
                            'price': item.get('ltp', 0),
                            'bid': item.get('bid', 0),
                            'ask': item.get('ask', 0),
                            'volume': item.get('volume', 0),
                            'timestamp': datetime.now(pytz.timezone('Asia/Kolkata')),
                            'raw_data': item
                        }
            
            # Call callbacks
            for callback in self.on_price_update_callbacks:
                try:
                    callback(data)
                except Exception as e:
                    logger.error(f"Error in price update callback: {e}")
        
        except Exception as e:
            logger.error(f"Error processing message: {e}")
    
    def _on_error(self, ws, error):
        """Handle WebSocket error"""
        logger.error(f"WebSocket error: {error}")
        
        # Call callbacks
        for callback in self.on_error_callbacks:
            try:
                callback(error)
            except Exception as e:
                logger.error(f"Error in error callback: {e}")
    
    def _on_close(self, ws, close_status_code, close_msg):
        """Handle WebSocket close"""
        logger.info("WebSocket closed")
        self.connected = False
    
    def _subscribe(self, symbols: List[str]):
        """Subscribe to symbols"""
        try:
            if not self.websocket:
                return
            
            data = {
                "type": "subscribe",
                "symbols": symbols
            }
            
            self.websocket.send(json.dumps(data))
            logger.info(f"Subscribed to {len(symbols)} symbols")
        
        except Exception as e:
            logger.error(f"Error subscribing to symbols: {e}")
    
    def _unsubscribe(self, symbols: List[str]):
        """Unsubscribe from symbols"""
        try:
            if not self.websocket:
                return
            
            data = {
                "type": "unsubscribe",
                "symbols": symbols
            }
            
            self.websocket.send(json.dumps(data))
            logger.info(f"Unsubscribed from {len(symbols)} symbols")
        
        except Exception as e:
            logger.error(f"Error unsubscribing from symbols: {e}")
    
    def connect(self):
        """Connect to WebSocket"""
        try:
            logger.info("Connecting to WebSocket...")
            
            # Note: Fyers WebSocket implementation details
            # This is a simplified version - actual implementation depends on Fyers API v3
            self.websocket = data_ws.FyersDataSocket(
                access_token=self.access_token,
                log_path="logs/"
            )
            
            self.websocket.on_open = self._on_open
            self.websocket.on_message = self._on_message
            self.websocket.on_error = self._on_error
            self.websocket.on_close = self._on_close
            
            # Start connection in background thread
            Thread(target=self.websocket.connect, daemon=True).start()
            
            logger.info("WebSocket connection initiated")
            return True
        
        except Exception as e:
            logger.error(f"Error connecting to WebSocket: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from WebSocket"""
        try:
            if self.websocket:
                self.websocket.close()
                self.connected = False
                logger.info("WebSocket disconnected")
        
        except Exception as e:
            logger.error(f"Error disconnecting: {e}")
    
    def get_price(self, symbol: str) -> Optional[float]:
        """Get latest price for symbol"""
        with self.data_lock:
            if symbol in self.price_data:
                return self.price_data[symbol]['price']
        return None
    
    def get_price_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get all price data for symbol"""
        with self.data_lock:
            if symbol in self.price_data:
                return self.price_data[symbol].copy()
        return None
    
    def get_all_prices(self) -> Dict[str, Dict[str, Any]]:
        """Get all price data"""
        with self.data_lock:
            return {symbol: price_data.copy() 
                    for symbol, price_data in self.price_data.items()}
    
    def wait_for_data(self, symbol: str, timeout: int = 10) -> bool:
        """Wait for price data to arrive"""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            with self.data_lock:
                if symbol in self.price_data:
                    return True
            
            time.sleep(0.1)
        
        logger.warning(f"Timeout waiting for data for {symbol}")
        return False


class MockRealtimeDataHandler(RealtimeDataHandler):
    """Mock implementation for testing without live data"""
    
    def __init__(self, symbols: List[str] = None):
        """Initialize mock data handler"""
        super().__init__(symbols)
        self.mock_prices = {}
        logger.info("MockRealtimeDataHandler initialized (testing mode)")
    
    def set_mock_price(self, symbol: str, price: float):
        """Set mock price for testing"""
        self.mock_prices[symbol] = price
        
        # Simulate data update
        data = [{
            'symbol': symbol,
            'ltp': price,
            'bid': price * 0.999,
            'ask': price * 1.001,
            'volume': 1000
        }]
        
        self._on_message(None, json.dumps(data))
    
    def connect(self):
        """Connect (mock)"""
        logger.info("Mock WebSocket connected")
        self.connected = True
        
        # Call callbacks
        for callback in self.on_connect_callbacks:
            try:
                callback(self)
            except Exception as e:
                logger.error(f"Error in connect callback: {e}")
        
        return True
    
    def disconnect(self):
        """Disconnect (mock)"""
        logger.info("Mock WebSocket disconnected")
        self.connected = False
