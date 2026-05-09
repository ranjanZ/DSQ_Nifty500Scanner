"""
Order Management System for Live Trading
Handles order placement, modification, and tracking
"""

import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
import pytz

from src.utils.fyers.fyers_broker import fyers_API


logger = logging.getLogger("OrderManager")


class OrderType(Enum):
    """Order types"""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class OrderSide(Enum):
    """Order sides"""
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(Enum):
    """Order statuses"""
    PENDING = "PENDING"
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


@dataclass
class Order:
    """Represents a trading order"""
    symbol: str
    side: OrderSide
    quantity: int
    order_type: OrderType
    price: float = 0
    stop_price: float = 0
    status: OrderStatus = OrderStatus.PENDING
    order_id: str = None
    filled_quantity: int = 0
    average_price: float = 0
    created_time: datetime = None
    modified_time: datetime = None
    executed_time: datetime = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.created_time is None:
            self.created_time = datetime.now(pytz.timezone('Asia/Kolkata'))
        if self.metadata is None:
            self.metadata = {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert order to dictionary"""
        data = asdict(self)
        data['side'] = self.side.value
        data['order_type'] = self.order_type.value
        data['status'] = self.status.value
        data['created_time'] = self.created_time.isoformat() if self.created_time else None
        data['modified_time'] = self.modified_time.isoformat() if self.modified_time else None
        data['executed_time'] = self.executed_time.isoformat() if self.executed_time else None
        return data


class OrderManager:
    """Manages order placement and tracking"""
    
    def __init__(self, broker: fyers_API = None):
        """
        Initialize order manager
        
        Args:
            broker: Fyers broker API instance
        """
        self.broker = broker or fyers_API()
        
        # Order tracking
        self.orders: Dict[str, Order] = {}
        self.order_counter = 0
        
        logger.info("OrderManager initialized")
    
    def create_order(self, symbol: str, side: str, quantity: int, 
                    order_type: str, price: float = 0, 
                    stop_price: float = 0, metadata: Dict = None) -> Order:
        """
        Create a new order
        
        Args:
            symbol: Trading symbol
            side: "BUY" or "SELL"
            quantity: Order quantity
            order_type: "MARKET", "LIMIT", "STOP", or "STOP_LIMIT"
            price: Price for limit orders
            stop_price: Stop price for stop orders
            metadata: Additional metadata
        
        Returns:
            Order object
        """
        try:
            order = Order(
                symbol=symbol,
                side=OrderSide[side.upper()],
                quantity=quantity,
                order_type=OrderType[order_type.upper()],
                price=price,
                stop_price=stop_price,
                metadata=metadata or {}
            )
            
            logger.info(f"Created order: {side} {quantity} {symbol} @{price}")
            return order
        
        except Exception as e:
            logger.error(f"Error creating order: {e}")
            raise
    
    def place_order(self, order: Order) -> bool:
        """
        Place an order with the broker
        
        Args:
            order: Order object
        
        Returns:
            True if order placed successfully
        """
        try:
            # Generate order ID
            self.order_counter += 1
            order.order_id = f"ORD_{self.order_counter}_{int(datetime.now().timestamp())}"
            
            # Store order
            self.orders[order.order_id] = order
            order.status = OrderStatus.OPEN
            
            logger.info(f"Order placed: {order.order_id} - {order.side.value} {order.quantity} {order.symbol}")
            
            # In production, place order with broker
            # response = self.broker.place_order(order=order)
            # if response.get('success'):
            #     order.status = OrderStatus.OPEN
            #     return True
            
            return True
        
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            order.status = OrderStatus.REJECTED
            return False
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order"""
        try:
            if order_id not in self.orders:
                logger.warning(f"Order not found: {order_id}")
                return False
            
            order = self.orders[order_id]
            
            if order.status in [OrderStatus.FILLED, OrderStatus.CANCELLED]:
                logger.warning(f"Cannot cancel order {order_id} with status {order.status.value}")
                return False
            
            order.status = OrderStatus.CANCELLED
            order.modified_time = datetime.now(pytz.timezone('Asia/Kolkata'))
            
            logger.info(f"Order cancelled: {order_id}")
            
            # In production, cancel with broker
            # response = self.broker.cancel_order(order_id=order_id)
            
            return True
        
        except Exception as e:
            logger.error(f"Error cancelling order: {e}")
            return False
    
    def modify_order(self, order_id: str, quantity: int = None, 
                    price: float = None, stop_price: float = None) -> bool:
        """Modify an order"""
        try:
            if order_id not in self.orders:
                logger.warning(f"Order not found: {order_id}")
                return False
            
            order = self.orders[order_id]
            
            if order.status not in [OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED]:
                logger.warning(f"Cannot modify order {order_id} with status {order.status.value}")
                return False
            
            # Update order parameters
            if quantity is not None:
                order.quantity = quantity
            if price is not None and price > 0:
                order.price = price
            if stop_price is not None and stop_price > 0:
                order.stop_price = stop_price
            
            order.modified_time = datetime.now(pytz.timezone('Asia/Kolkata'))
            
            logger.info(f"Order modified: {order_id}")
            
            # In production, modify with broker
            # response = self.broker.modify_order(order=order)
            
            return True
        
        except Exception as e:
            logger.error(f"Error modifying order: {e}")
            return False
    
    def get_order(self, order_id: str) -> Optional[Order]:
        """Get order details"""
        return self.orders.get(order_id)
    
    def get_orders(self, symbol: str = None, status: str = None) -> List[Order]:
        """Get orders by symbol and/or status"""
        orders = list(self.orders.values())
        
        if symbol:
            orders = [o for o in orders if o.symbol == symbol]
        
        if status:
            try:
                status_enum = OrderStatus[status.upper()]
                orders = [o for o in orders if o.status == status_enum]
            except KeyError:
                pass
        
        return orders
    
    def update_order_status(self, order_id: str, status: str, 
                          filled_qty: int = None, avg_price: float = None):
        """Update order status"""
        try:
            if order_id not in self.orders:
                return False
            
            order = self.orders[order_id]
            order.status = OrderStatus[status.upper()]
            
            if filled_qty is not None:
                order.filled_quantity = filled_qty
            
            if avg_price is not None:
                order.average_price = avg_price
            
            if order.status == OrderStatus.FILLED:
                order.executed_time = datetime.now(pytz.timezone('Asia/Kolkata'))
            
            logger.info(f"Order {order_id} status updated: {status}")
            return True
        
        except Exception as e:
            logger.error(f"Error updating order status: {e}")
            return False
    
    def get_pending_orders(self) -> List[Order]:
        """Get all pending orders"""
        return [o for o in self.orders.values() 
                if o.status in [OrderStatus.PENDING, OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED]]
    
    def get_filled_orders(self) -> List[Order]:
        """Get all filled orders"""
        return [o for o in self.orders.values() if o.status == OrderStatus.FILLED]
    
    def print_orders_summary(self, symbol: str = None):
        """Print summary of orders"""
        orders = self.get_orders(symbol=symbol)
        
        logger.info("=" * 80)
        logger.info("ORDER SUMMARY")
        logger.info("=" * 80)
        
        for order in orders:
            logger.info(f"ID: {order.order_id}")
            logger.info(f"  Symbol: {order.symbol}")
            logger.info(f"  Side: {order.side.value}")
            logger.info(f"  Quantity: {order.quantity}")
            logger.info(f"  Filled: {order.filled_quantity}")
            logger.info(f"  Type: {order.order_type.value}")
            logger.info(f"  Price: {order.price}")
            logger.info(f"  Status: {order.status.value}")
            logger.info(f"  Created: {order.created_time}")
            logger.info("-" * 80)
        
        logger.info(f"Total Orders: {len(orders)}")
        logger.info("=" * 80)
