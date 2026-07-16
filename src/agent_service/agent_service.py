"""
Agent Service - Telegram bot integration
Handles notifications and interactive commands
"""

import os
import sys
import logging
import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class AgentService:
    """Service for Telegram bot interactions"""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        self.bot = None
        self.is_running = False
        
        # Services to interact with
        self.trading_service = None
        self.strategy_service = None
        self.backtest_service = None
    
    def initialize(self) -> bool:
        """Initialize the Telegram bot"""
        if not self.bot_token:
            logger.warning("TELEGRAM_BOT_TOKEN not found in environment")
            return False
        
        try:
            from telebot import TeleBot
            self.bot = TeleBot(self.bot_token)
            self._setup_handlers()
            logger.info("Telegram bot initialized successfully")
            return True
        except ImportError:
            logger.error("telebot library not installed. Run: pip install pyTelegramBotAPI")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize bot: {e}")
            return False
    
    def _setup_handlers(self):
        """Setup command handlers"""
        
        @self.bot.message_handler(commands=['start'])
        def send_welcome(message):
            self.bot.reply_to(message, 
                '👋 Trading Bot Here!\n\n'
                'Available commands:\n'
                '/status - Get trading status\n'
                '/positions - Current positions\n'
                '/help - Show help')
        
        @self.bot.message_handler(commands=['help'])
        def send_help(message):
            help_text = (
                '📊 *Trading Bot Commands*\n\n'
                '/start - Start the bot\n'
                '/status - Get current trading status\n'
                '/positions - View open positions\n'
                '/balance - Check account balance\n'
                '/pnl - View P&L summary\n'
                '/help - Show this help message\n\n'
                '_Built for Indian Stock Market_'
            )
            self.bot.reply_to(message, help_text, parse_mode='Markdown')
        
        @self.bot.message_handler(commands=['status'])
        def send_status(message):
            if self.trading_service:
                status = self.trading_service.get_status()
                text = (
                    f'📈 *Trading Status*\n\n'
                    f'Running: {status.get("is_running", False)}\n'
                    f'Positions: {status.get("positions_count", 0)}\n'
                    f'Orders: {status.get("orders_count", 0)}\n'
                    f'Market Open: {status.get("market_open", False)}'
                )
                self.bot.reply_to(message, text, parse_mode='Markdown')
            else:
                self.bot.reply_to(message, 'Trading service not connected')
        
        @self.bot.message_handler(commands=['positions'])
        def send_positions(message):
            if self.trading_service:
                positions = self.trading_service.positions
                if positions:
                    text = '📊 *Current Positions*\n\n'
                    for symbol, pos in positions.items():
                        text += f'{symbol}: Qty={pos.get("quantity", 0)}\n'
                    self.bot.reply_to(message, text, parse_mode='Markdown')
                else:
                    self.bot.reply_to(message, 'No open positions')
            else:
                self.bot.reply_to(message, 'Trading service not connected')
    
    def start_polling(self):
        """Start the bot polling loop"""
        if not self.bot:
            logger.error("Bot not initialized")
            return
        
        logger.info("Starting Telegram bot polling...")
        self.is_running = True
        
        try:
            self.bot.polling(non_stop=True)
        except Exception as e:
            logger.error(f"Polling error: {e}")
            self.is_running = False
    
    def stop_polling(self):
        """Stop the bot polling"""
        logger.info("Stopping Telegram bot...")
        self.is_running = False
        
        if self.bot:
            try:
                self.bot.stop_polling()
            except Exception as e:
                logger.error(f"Error stopping bot: {e}")
    
    def send_notification(self, message: str, parse_mode: str = None):
        """Send a notification message"""
        if not self.bot or not self.chat_id:
            logger.warning("Cannot send notification: bot or chat_id not configured")
            return False
        
        try:
            self.bot.send_message(self.chat_id, message, parse_mode=parse_mode)
            logger.info(f"Notification sent: {message[:50]}...")
            return True
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")
            return False
    
    def send_trade_alert(self, action: str, symbol: str, qty: int, 
                        price: float = 0.0):
        """Send a trade alert notification"""
        emoji = "🟢" if action == "BUY" else "🔴"
        message = (
            f'{emoji} *Trade Alert*\n\n'
            f'Action: {action}\n'
            f'Symbol: {symbol}\n'
            f'Quantity: {qty}\n'
            f'Price: ₹{price:.2f}'
        )
        return self.send_notification(message, parse_mode='Markdown')
    
    def send_pnl_update(self, pnl: float, pnl_pct: float):
        """Send P&L update notification"""
        emoji = "📈" if pnl >= 0 else "📉"
        message = (
            f'{emoji} *P&L Update*\n\n'
            f'Profit/Loss: ₹{pnl:.2f}\n'
            f'Return: {pnl_pct:.2f}%'
        )
        return self.send_notification(message, parse_mode='Markdown')
    
    def set_trading_service(self, service):
        """Set the trading service reference"""
        self.trading_service = service
    
    def set_strategy_service(self, service):
        """Set the strategy service reference"""
        self.strategy_service = service
    
    def set_backtest_service(self, service):
        """Set the backtest service reference"""
        self.backtest_service = service


def run_test():
    """Test function for agent service"""
    print("Testing Agent Service...")
    
    service = AgentService()
    print(f"Bot token configured: {'Yes' if service.bot_token else 'No'}")
    print(f"Chat ID configured: {'Yes' if service.chat_id else 'No'}")
    
    # Test initialization (will fail without valid token)
    if service.initialize():
        print("✓ Bot initialized successfully")
    else:
        print("✗ Bot initialization failed (expected if no token)")
    
    # Test notification methods (won't actually send without valid bot)
    print("\nTesting notification methods:")
    print("  - send_notification: method exists")
    print("  - send_trade_alert: method exists")
    print("  - send_pnl_update: method exists")
    
    print("\nAgent Service test complete!")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        run_test()
    else:
        print("Agent Service Module")
        print("Usage: python -m src.agent_service.agent_service test")
        run_test()
