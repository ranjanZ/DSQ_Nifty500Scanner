"""
Broker Synchronization
Syncs trading state with the Fyers broker
"""

import logging
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
import pytz

from src.utils.fyers.fyers_broker import fyers_API
from src.live_trading.state_manager import StateManager, PositionState, OrderState

logger = logging.getLogger("BrokerSync")


class BrokerSync:
    """Synchronizes state with broker and handles reconciliation"""
    
    def __init__(self, broker: fyers_API = None, state_manager: StateManager = None):
        """
        Initialize broker sync
        
        Args:
            broker: Fyers broker API instance
            state_manager: State manager instance
        """
        self.broker = broker or fyers_API()
        self.state_manager = state_manager or StateManager()
        self.tz = pytz.timezone('Asia/Kolkata')
        
        logger.info("BrokerSync initialized")
    
    def get_broker_positions(self) -> Dict[str, Any]:
        """Get positions from broker"""
        try:
            logger.debug("Fetching positions from broker")
            positions = self.broker.get_positions()
            return positions
        except Exception as e:
            logger.error(f"Error getting broker positions: {e}")
            return {}
    
    def get_broker_orders(self) -> Dict[str, Any]:
        """Get orders from broker"""
        try:
            logger.debug("Fetching orders from broker")
            orders = self.broker.get_orders()
            return orders
        except Exception as e:
            logger.error(f"Error getting broker orders: {e}")
            return {}
    
    def sync_positions(self) -> Tuple[bool, Dict[str, Any]]:
        """
        Synchronize positions with broker
        
        Returns:
            Tuple of (success, changes_dict)
        """
        try:
            logger.info("Starting position synchronization")
            
            broker_positions = self.get_broker_positions()
            local_positions = self.state_manager.get_all_positions()
            
            changes = {
                'added': [],
                'updated': [],
                'removed': [],
                'conflicts': []
            }
            
            # Check for positions in broker but not in local state
            for symbol, broker_pos in broker_positions.items():
                if symbol not in local_positions:
                    logger.warning(f"Position found in broker but not in local state: {symbol}")
                    changes['added'].append(symbol)
                    
                    # Add missing position
                    pos_state = PositionState(
                        symbol=symbol,
                        entry_price=broker_pos.get('entry_price', 0),
                        entry_time=datetime.now(self.tz).isoformat(),
                        quantity=broker_pos.get('quantity', 0),
                        capital_used=broker_pos.get('capital_used', 0),
                        entry_signal="RECOVERED",
                        target_price=broker_pos.get('target_price', 0),
                        stop_loss_price=broker_pos.get('stop_loss_price', 0)
                    )
                    self.state_manager.add_position(pos_state)
            
            # Check for positions in local state but not in broker
            for symbol, local_pos in local_positions.items():
                if symbol not in broker_positions:
                    logger.warning(f"Position found in local state but not in broker: {symbol}")
                    changes['removed'].append(symbol)
                    
                    # Mark as closed or investigate
                    self.state_manager.remove_position(symbol)
            
            # Update existing positions
            for symbol, broker_pos in broker_positions.items():
                if symbol in local_positions:
                    local_pos = local_positions[symbol]
                    
                    # Check for differences
                    if (local_pos.quantity != broker_pos.get('quantity', 0) or
                        abs(local_pos.entry_price - broker_pos.get('entry_price', 0)) > 0.01):
                        
                        logger.warning(f"Position mismatch: {symbol}")
                        changes['conflicts'].append(symbol)
                        
                        # Update with broker data
                        updates = {
                            'quantity': broker_pos.get('quantity', local_pos.quantity),
                            'entry_price': broker_pos.get('entry_price', local_pos.entry_price)
                        }
                        self.state_manager.update_position(symbol, updates)
                        changes['updated'].append(symbol)
            
            logger.info(f"Position sync completed: {changes}")
            return True, changes
        
        except Exception as e:
            logger.error(f"Error syncing positions: {e}")
            return False, {'error': str(e)}
    
    def sync_orders(self) -> Tuple[bool, Dict[str, Any]]:
        """
        Synchronize orders with broker
        
        Returns:
            Tuple of (success, changes_dict)
        """
        try:
            logger.info("Starting order synchronization")
            
            broker_orders = self.get_broker_orders()
            local_orders = self.state_manager.get_all_orders()
            
            changes = {
                'filled': [],
                'cancelled': [],
                'pending': [],
                'conflicts': []
            }
            
            # Update order status from broker
            for order_id, broker_order in broker_orders.items():
                if order_id in local_orders:
                    local_order = local_orders[order_id]
                    broker_status = broker_order.get('status', 'UNKNOWN')
                    
                    # Check for status changes
                    if local_order.status != broker_status:
                        logger.info(f"Order status changed: {order_id} - {broker_status}")
                        
                        changes[broker_status.lower()].append(order_id)
                        
                        # Update order state
                        updates = {
                            'status': broker_status,
                            'filled_quantity': broker_order.get('filled_quantity', 0),
                            'average_price': broker_order.get('average_price', 0)
                        }
                        self.state_manager.update_order(order_id, updates)
            
            # Check for missing orders
            for order_id in local_orders:
                if order_id not in broker_orders:
                    logger.warning(f"Order in local state but not in broker: {order_id}")
                    changes['conflicts'].append(order_id)
            
            logger.info(f"Order sync completed: {changes}")
            return True, changes
        
        except Exception as e:
            logger.error(f"Error syncing orders: {e}")
            return False, {'error': str(e)}
    def sync_account_balance(self) -> Dict[str, Any]:
        """
        Fetch latest account balance from broker and return it.
        The balance is not stored persistently; it can be saved in the state manager
        if needed, or cached in self._balance for later use.
        """
        try:
            balance = self.broker.get_funds()
            if balance:
                # Cache the balance inside the instance for quick access
                self._balance = balance
                logger.info(f"Account balance synced: Equity Available={balance.get('equity_available', 0)}")
                return {"success": True, "balance": balance}
            return {"success": False, "error": "No balance data returned"}
        except Exception as e:
            logger.error(f"Error syncing account balance: {e}")
            return {"success": False, "error": str(e)}



    def full_sync(self) -> Dict[str, Any]:
        """
        Perform full synchronization with broker
        
        Returns:
            Dictionary with sync results
        """
        try:
            logger.info("Starting full synchronization")
            
            result = {
                'timestamp': datetime.now(self.tz).isoformat(),
                'positions': {},
                'orders': {},
                'success': True
            }
            
            # Sync positions
            pos_success, pos_changes = self.sync_positions()
            result['positions'] = pos_changes
            result['success'] = result['success'] and pos_success
            
            # Sync orders
            ord_success, ord_changes = self.sync_orders()
            result['orders'] = ord_changes
            result['success'] = result['success'] and ord_success
            balance_result = self.sync_account_balance()
            result['balance'] = balance_result
            result['success'] = result['success'] and balance_result.get('success', True)

            
            logger.info(f"Full sync completed: {'SUCCESS' if result['success'] else 'FAILED'}")
            return result
        
        except Exception as e:
            logger.error(f"Error in full sync: {e}")
            return {
                'success': False,
                'error': str(e),
                'timestamp': datetime.now(self.tz).isoformat()
            }
    
    def reconcile_position(self, symbol: str) -> Tuple[bool, str]:
        """
        Reconcile a specific position
        
        Returns:
            Tuple of (matches, message)
        """
        try:
            broker_positions = self.get_broker_positions()
            local_pos = self.state_manager.get_position(symbol)
            
            if symbol not in broker_positions:
                if local_pos is None:
                    return True, "Position not in broker (as expected)"
                else:
                    return False, f"Position in local state but not in broker: {symbol}"
            
            if local_pos is None:
                return False, f"Position in broker but not in local state: {symbol}"
            
            broker_pos = broker_positions[symbol]
            
            # Compare key fields
            qty_match = local_pos.quantity == broker_pos.get('quantity', 0)
            price_match = abs(local_pos.entry_price - broker_pos.get('entry_price', 0)) < 0.01
            
            if qty_match and price_match:
                return True, "Position reconciled successfully"
            else:
                msg = "Position mismatch:"
                if not qty_match:
                    msg += f" Qty local={local_pos.quantity} broker={broker_pos.get('quantity', 0)};"
                if not price_match:
                    msg += f" Price local={local_pos.entry_price} broker={broker_pos.get('entry_price', 0)}"
                
                return False, msg
        
        except Exception as e:
            logger.error(f"Error reconciling position {symbol}: {e}")
            return False, str(e)
    
    def get_sync_status(self) -> Dict[str, Any]:
        """Get current synchronization status"""
        try:
            session_summary = self.state_manager.get_session_summary()
            broker_positions = self.get_broker_positions()
            broker_orders = self.get_broker_orders()

            # session_summary fields are already integers, not lists
            local_positions_count = session_summary.get('open_positions', 0)
            local_orders_count = session_summary.get('total_orders', 0)

            # Optionally fetch balance and include it
            balance = self.broker.get_funds()

            status = {
                'timestamp': datetime.now(self.tz).isoformat(),
                'local_positions': local_positions_count,
                'broker_positions': len(broker_positions),
                'local_orders': local_orders_count,
                'broker_orders': len(broker_orders),
                'balance': balance,
                'synced': local_positions_count == len(broker_positions)
            }
            return status
        except Exception as e:
            logger.error(f"Error getting sync status: {e}")
            return {'error': str(e), 'synced': False}
    

# ----------------------------------------------------------------------
# Direct execution block for testing / manual sync
# ----------------------------------------------------------------------
if __name__ == "__main__":
    # Set up logging so we can see what's happening
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger("BrokerSync")
    
    print("=" * 60)
    print("Starting Broker Synchronization Test")
    print("=" * 60)
    
    # Initialise with actual broker connection (no mock)
    # The fyers_API() will use credentials from your environment/config.
    # Make sure your FYERS_APP_ID, FYERS_SECRET, FYERS_REDIRECT_URI, 
    # and access token are set correctly in your environment or .env file.
    sync = BrokerSync()
    
    # 1. Show current status before sync
    print("\n>>> Current Sync Status (before sync):")
    status_before = sync.get_sync_status()
    for k, v in status_before.items():
        print(f"  {k}: {v}")
    
    # 2. Perform full synchronization
    print("\n>>> Performing Full Sync...")
    result = sync.full_sync()
    print("Sync Result:")
    print(f"  Success: {result.get('success')}")
    print(f"  Timestamp: {result.get('timestamp')}")
    if 'error' in result:
        print(f"  Error: {result['error']}")
    else:
        print("  Position changes:")
        pos = result.get('positions', {})
        for change_type, symbols in pos.items():
            if symbols:
                print(f"    {change_type}: {symbols}")
        print("  Order changes:")
        ord = result.get('orders', {})
        for change_type, order_ids in ord.items():
            if order_ids:
                print(f"    {change_type}: {order_ids}")
    

    print("\n>>> Account Balance:")
    balance = sync.sync_account_balance()
    if balance.get('success'):
        for k, v in balance['balance'].items():
            print(f"  {k}: {v}")
    else:
        print(f"  Error: {balance.get('error')}")


    # 3. Show status after sync
    print("\n>>> Status After Sync:")
    status_after = sync.get_sync_status()
    for k, v in status_after.items():
        print(f"  {k}: {v}")
    
    # 4. Optional: reconcile a particular symbol
    # Replace with a symbol you actually trade if you want to test
    test_symbol = "NSE:NIFTY50-INDEX"
    print(f"\n>>> Reconciling position for {test_symbol}:")
    match, msg = sync.reconcile_position(test_symbol)
    print(f"  Match: {match}")
    print(f"  Message: {msg}")
    
    print("\n" + "=" * 60)
    print("Synchronization test completed.")