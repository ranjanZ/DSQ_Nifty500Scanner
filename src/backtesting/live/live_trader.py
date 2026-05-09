"""
Live Trading Engine for Fyers Broker
Runs trading strategies during Indian market hours (9:15 AM - 3:20 PM IST)
"""

import os
import sys
import time
import logging
import yaml
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
import pandas as pd
import pytz
from threading import Thread, Event
import traceback

from src.utils.fyers.fyers_broker import fyers_API
from src.strategy.strategy_base import TradingStrategy
from src.strategy.rsi_w_strategy import RSIWPatternStrategy
from src.utils.telegram_api import send_telegram_message


# Setup Logging
def setup_logging(log_file: str = "logs/live_trading.log"):
    """Configure logging for live trading"""
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    
    logger = logging.getLogger("LiveTrader")
    logger.setLevel(logging.INFO)
    
    # File handler
    fh = logging.FileHandler(log_file)
    fh.setLevel(logging.INFO)
    
    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    
    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    
    logger.addHandler(fh)
    logger.addHandler(ch)
    
    return logger


logger = setup_logging()


@dataclass
class Position:
    """Represents an active trading position"""
    symbol: str
    entry_price: float
    entry_time: datetime
    quantity: int
    capital_used: float
    entry_signal: str
    target_price: float
    stop_loss_price: float
    highest_price: float = 0
    order_id: str = None
    status: str = "OPEN"  # OPEN, CLOSED, STOPPED_OUT
    exit_price: float = None
    exit_time: datetime = None
    pnl: float = None
    pnl_pct: float = None


class PortfolioManager:
    """Manages positions and portfolio metrics"""
    
    def __init__(self, initial_capital: float):
        self.initial_capital = initial_capital
        self.available_capital = initial_capital
        self.positions: Dict[str, Position] = {}
        self.closed_positions: List[Position] = []
        self.total_pnl = 0
        self.total_pnl_pct = 0
        
    def add_position(self, position: Position):
        """Add a new position"""
        if position.symbol in self.positions:
            logger.warning(f"Position for {position.symbol} already exists")
            return False
            
        if position.capital_used > self.available_capital:
            logger.error(f"Insufficient capital for {position.symbol}")
            return False
            
        self.positions[position.symbol] = position
        self.available_capital -= position.capital_used
        logger.info(f"Added position: {position.symbol} @{position.entry_price} | Capital used: {position.capital_used}")
        return True
    
    def close_position(self, symbol: str, exit_price: float, exit_time: datetime) -> Optional[Position]:
        """Close a position"""
        if symbol not in self.positions:
            logger.warning(f"No position found for {symbol}")
            return None
            
        position = self.positions[symbol]
        position.exit_price = exit_price
        position.exit_time = exit_time
        position.status = "CLOSED"
        
        # Calculate P&L
        pnl = (exit_price - position.entry_price) * position.quantity
        pnl_pct = ((exit_price - position.entry_price) / position.entry_price) * 100
        
        position.pnl = pnl
        position.pnl_pct = pnl_pct
        
        self.total_pnl += pnl
        self.available_capital += position.capital_used + pnl
        
        del self.positions[symbol]
        self.closed_positions.append(position)
        
        logger.info(f"Closed {symbol} @{exit_price} | P&L: {pnl:.2f} ({pnl_pct:.2f}%)")
        return position
    
    def get_portfolio_stats(self) -> Dict[str, Any]:
        """Get current portfolio statistics"""
        total_value = self.available_capital
        active_capital = 0
        active_pnl = 0
        
        for pos in self.positions.values():
            pos_value = pos.entry_price * pos.quantity
            active_capital += pos_value
            active_pnl += (pos.highest_price - pos.entry_price) * pos.quantity
            total_value += pos_value
        
        return {
            "initial_capital": self.initial_capital,
            "available_capital": self.available_capital,
            "active_capital": active_capital,
            "active_pnl": active_pnl,
            "closed_pnl": self.total_pnl,
            "total_value": total_value,
            "total_return_pct": ((total_value - self.initial_capital) / self.initial_capital) * 100,
            "num_open_positions": len(self.positions),
            "num_closed_positions": len(self.closed_positions)
        }


class LiveTrader:
    """Main live trading engine for Indian market hours"""
    
    def __init__(self, config_path: str = "config/live_trading_config.yaml"):
        """Initialize Live Trader"""
        self.config = self._load_config(config_path)
        self.trading_config = self.config['live_trading']
        
        # Initialize components
        self.broker = fyers_API()
        self.strategy = self._create_strategy()
        self.portfolio = PortfolioManager(self.trading_config['initial_capital'])
        
        # Timezone
        self.tz = pytz.timezone(self.trading_config['timezone'])
        
        # Trading state
        self.market_open = False
        self.trading_active_flag = Event()
        self.stop_flag = Event()
        
        logger.info("Live Trader initialized")
        
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Load configuration from YAML file"""
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        logger.info(f"Configuration loaded from {config_path}")
        return config
    
    def _create_strategy(self) -> TradingStrategy:
        """Create trading strategy"""
        strategy_type = self.trading_config['strategy_type']
        strategy_params = self.trading_config.get('strategy_params', {})
        
        if strategy_type == "RSI_W_Pattern":
            return RSIWPatternStrategy(params=strategy_params)
        else:
            raise ValueError(f"Unknown strategy type: {strategy_type}")
    
    def is_market_open(self) -> bool:
        """Check if market is currently open"""
        now = datetime.now(self.tz)
        
        # Market closed on weekends
        if now.weekday() >= 5:  # Saturday=5, Sunday=6
            return False
        
        market_open = datetime.strptime(
            self.trading_config['market_open'], "%H:%M"
        ).time()
        market_close = datetime.strptime(
            self.trading_config['market_close'], "%H:%M"
        ).time()
        
        return market_open <= now.time() <= market_close
    
    def get_historical_data(self, symbol: str, days_back: int = 30) -> Optional[pd.DataFrame]:
        """Fetch historical data for strategy analysis"""
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            past_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
            
            data = self.broker.get_his_candle_data(
                symbol=symbol,
                fromdate=past_date,
                todate=today,
                interval="1"  # 1 minute interval
            )
            
            if data is None or data.empty:
                return None
                
            return data
            
        except Exception as e:
            logger.error(f"Error fetching data for {symbol}: {e}")
            return None
    
    def generate_trading_signals(self, symbols: List[str]) -> Dict[str, Any]:
        """Generate trading signals for given symbols"""
        signals = {}
        
        for symbol in symbols:
            try:
                data = self.get_historical_data(symbol, days_back=30)
                
                if data is None or len(data) < 20:
                    continue
                
                # Generate signals
                signal_data = self.strategy.generate_signals(data)
                
                if signal_data is not None and not signal_data.empty:
                    latest_signal = signal_data.iloc[-1]
                    
                    if latest_signal.get('signal', 0) != 0:
                        signals[symbol] = {
                            'signal': latest_signal['signal'],
                            'price': latest_signal.get('close', 0),
                            'strength': latest_signal.get('signal_strength', 0),
                            'indicators': dict(latest_signal)
                        }
                        logger.info(f"Signal found for {symbol}: {latest_signal['signal']}")
                
            except Exception as e:
                logger.error(f"Error generating signal for {symbol}: {e}")
                continue
        
        return signals
    
    def place_buy_order(self, symbol: str, quantity: int, current_price: float, signal_info: Dict) -> bool:
        """Place a buy order"""
        try:
            if symbol in self.portfolio.positions:
                logger.warning(f"Position already exists for {symbol}")
                return False
            
            if quantity * current_price > self.portfolio.available_capital:
                logger.warning(f"Insufficient capital for {symbol}")
                return False
            
            # Calculate stop loss and target
            stop_loss = current_price * (1 - self.trading_config['stop_loss_pct'])
            target = current_price * (1 + self.trading_config['target_profit_pct'])
            
            # Create position
            position = Position(
                symbol=symbol,
                entry_price=current_price,
                entry_time=datetime.now(self.tz),
                quantity=quantity,
                capital_used=quantity * current_price,
                entry_signal=str(signal_info),
                target_price=target,
                stop_loss_price=stop_loss,
                highest_price=current_price
            )
            
            # Add to portfolio
            if self.portfolio.add_position(position):
                message = f"🟢 BUY: {symbol}\nPrice: {current_price}\nQty: {quantity}\nTarget: {target:.2f}\nStopLoss: {stop_loss:.2f}"
                self._send_notification(message)
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error placing buy order for {symbol}: {e}")
            return False
    
    def check_exit_signals(self):
        """Check for exit signals on open positions"""
        try:
            positions_to_close = []
            
            for symbol, position in list(self.portfolio.positions.items()):
                try:
                    data = self.get_historical_data(symbol, days_back=5)
                    
                    if data is None or data.empty:
                        continue
                    
                    current_price = data.iloc[-1]['close']
                    
                    # Update highest price
                    if current_price > position.highest_price:
                        position.highest_price = current_price
                    
                    # Check stop loss
                    if current_price <= position.stop_loss_price:
                        positions_to_close.append((symbol, current_price, "STOP_LOSS"))
                        logger.info(f"Stop loss hit for {symbol}")
                    
                    # Check target
                    elif current_price >= position.target_price:
                        positions_to_close.append((symbol, current_price, "TARGET_HIT"))
                        logger.info(f"Target hit for {symbol}")
                    
                    # Check trailing stop
                    trailing_stop = position.highest_price * (1 - self.trading_config['trailing_stop_pct'])
                    if current_price <= trailing_stop:
                        positions_to_close.append((symbol, current_price, "TRAILING_STOP"))
                        logger.info(f"Trailing stop triggered for {symbol}")
                
                except Exception as e:
                    logger.error(f"Error checking exit signals for {symbol}: {e}")
            
            # Close positions
            for symbol, exit_price, exit_reason in positions_to_close:
                if symbol in self.portfolio.positions:
                    self.portfolio.close_position(symbol, exit_price, datetime.now(self.tz))
                    message = f"🔴 SELL: {symbol}\nPrice: {exit_price}\nReason: {exit_reason}"
                    self._send_notification(message)
        
        except Exception as e:
            logger.error(f"Error in exit signal check: {e}")
    
    def _send_notification(self, message: str):
        """Send notification via Telegram"""
        try:
            if self.trading_config.get('enable_telegram'):
                chat_id = self.trading_config['telegram_chat_id']
                bot_token = self.trading_config['telegram_bot_token']
                
                if chat_id and bot_token and chat_id != "YOUR_CHAT_ID":
                    send_telegram_message(chat_id, bot_token, message)
        except Exception as e:
            logger.debug(f"Could not send telegram: {e}")
    
    def print_portfolio_status(self):
        """Print current portfolio status"""
        stats = self.portfolio.get_portfolio_stats()
        
        logger.info("=" * 60)
        logger.info("PORTFOLIO STATUS")
        logger.info("=" * 60)
        logger.info(f"Initial Capital: ${stats['initial_capital']:.2f}")
        logger.info(f"Available Capital: ${stats['available_capital']:.2f}")
        logger.info(f"Active Capital: ${stats['active_capital']:.2f}")
        logger.info(f"Active P&L: ${stats['active_pnl']:.2f}")
        logger.info(f"Closed P&L: ${stats['closed_pnl']:.2f}")
        logger.info(f"Total Portfolio Value: ${stats['total_value']:.2f}")
        logger.info(f"Total Return: {stats['total_return_pct']:.2f}%")
        logger.info(f"Open Positions: {stats['num_open_positions']}")
        logger.info(f"Closed Positions: {stats['num_closed_positions']}")
        logger.info("=" * 60)
    
    def run_trading_loop(self):
        """Main trading loop"""
        logger.info("Starting trading loop")
        scan_interval = self.trading_config['data_refresh_interval']
        last_scan_time = 0
        
        while not self.stop_flag.is_set():
            try:
                current_time = time.time()
                
                # Check market status
                if not self.is_market_open():
                    if self.market_open:
                        logger.info("Market closed")
                        self.print_portfolio_status()
                        self.market_open = False
                    time.sleep(30)
                    continue
                
                if not self.market_open:
                    logger.info("Market opened")
                    self.market_open = True
                
                # Scan for new signals
                if current_time - last_scan_time >= scan_interval:
                    try:
                        # Get watchlist symbols
                        watchlist = self.trading_config['watchlist']
                        num_scans = self.trading_config['scan_symbols']
                        
                        # Placeholder: Get symbols from config
                        # In production, load from stock_list.yaml
                        test_symbols = [
                            "NSE:SBIN-EQ",
                            "NSE:INFY-EQ",
                            "NSE:ITC-EQ",
                            "NSE:LT-EQ",
                            "NSE:MARUTI-EQ",
                        ]
                        
                        # Generate signals
                        signals = self.generate_trading_signals(test_symbols[:num_scans])
                        
                        # Place buy orders for buy signals
                        for symbol, signal_info in signals.items():
                            if signal_info['signal'] == 1 and len(self.portfolio.positions) < self.trading_config['max_positions']:
                                price = signal_info['price']
                                quantity = int(self.trading_config['max_position_size'] / price)
                                if quantity > 0:
                                    self.place_buy_order(symbol, quantity, price, signal_info)
                        
                        last_scan_time = current_time
                    
                    except Exception as e:
                        logger.error(f"Error in signal generation: {e}")
                        traceback.print_exc()
                
                # Check exit signals every minute
                self.check_exit_signals()
                
                # Sleep before next check
                time.sleep(5)
            
            except KeyboardInterrupt:
                logger.info("Trading loop interrupted by user")
                break
            except Exception as e:
                logger.error(f"Error in trading loop: {e}")
                traceback.print_exc()
                time.sleep(10)
        
        logger.info("Trading loop stopped")
        self.print_portfolio_status()
    
    def start_trading(self):
        """Start the live trading system"""
        logger.info("Starting Live Trading System")
        
        try:
            # Run trading loop
            self.run_trading_loop()
        
        except Exception as e:
            logger.error(f"Error in live trading: {e}")
            traceback.print_exc()
        
        finally:
            logger.info("Live Trading System stopped")
            self.print_portfolio_status()
    
    def stop_trading(self):
        """Stop the trading system"""
        logger.info("Stopping trading system...")
        self.stop_flag.set()


def main():
    """Main entry point"""
    try:
        trader = LiveTrader(config_path="config/live_trading_config.yaml")
        trader.start_trading()
    except KeyboardInterrupt:
        logger.info("Trading interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    main()
