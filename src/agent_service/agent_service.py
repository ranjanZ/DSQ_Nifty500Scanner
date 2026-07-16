"""
Agent Service - Telegram integration for trading notifications and commands
"""

import os
import sys
import logging
from typing import Optional, Dict, Any
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class AgentService:
    """Telegram bot service for trading interactions"""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.bot_token = config.get('telegram_bot_token') or os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id = config.get('telegram_chat_id') or os.getenv('TELEGRAM_CHAT_ID')
        
        self.bot = None
        self.connected = False
        
        self.logger = logging.getLogger("AgentService")
    
    def connect(self) -> bool:
        """Connect to Telegram Bot API"""
        try:
            import requests
            
            if not self.bot_token:
                self.logger.error("Telegram bot token not configured")
                return False
            
            # Test connection
            url = f"https://api.telegram.org/bot{self.bot_token}/getMe"
            response = requests.get(url)
            
            if response.status_code == 200:
                result = response.json()
                if result.get('ok'):
                    self.connected = True
                    self.logger.info(f"✅ Connected to Telegram as @{result['result']['username']}")
                    return True
            
            self.logger.error(f"❌ Telegram connection failed: {response.text}")
            return False
            
        except Exception as e:
            self.logger.error(f"❌ Error connecting to Telegram: {e}")
            return False
    
    def send_message(self, message: str, parse_mode: str = "HTML") -> bool:
        """Send a message to configured chat"""
        if not self.connected:
            self.logger.warning("Not connected to Telegram")
            return False
        
        try:
            import requests
            
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            data = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': parse_mode
            }
            
            response = requests.post(url, data=data)
            
            if response.status_code == 200:
                result = response.json()
                if result.get('ok'):
                    self.logger.debug(f"✅ Message sent")
                    return True
            
            self.logger.error(f"❌ Message failed: {response.text}")
            return False
            
        except Exception as e:
            self.logger.error(f"❌ Error sending message: {e}")
            return False
    
    def send_trade_notification(self, action: str, symbol: str, price: float, 
                                qty: int, pnl: float = None):
        """Send trade notification"""
        emoji = "🟢" if action == "BUY" else "🔴" if action == "SELL" else "⚪"
        
        message = f"""
{emoji} <b>Trade Alert</b>

<b>Action:</b> {action}
<b>Symbol:</b> {symbol}
<b>Price:</b> ₹{price:.2f}
<b>Quantity:</b> {qty}
<b>Value:</b> ₹{price * qty:,.2f}
"""
        
        if pnl is not None:
            pnl_emoji = "📈" if pnl > 0 else "📉" if pnl < 0 else "➖"
            message += f"\n{pnl_emoji} <b>P&L:</b> {pnl_emoji} ₹{pnl:.2f} ({pnl*100:.2f}%)"
        
        self.send_message(message)
    
    def send_daily_summary(self, summary: Dict[str, Any]):
        """Send daily trading summary"""
        message = f"""
📊 <b>Daily Trading Summary</b>

<b>Date:</b> {summary.get('date', 'N/A')}
<b>Total Trades:</b> {summary.get('total_trades', 0)}
<b>Wins:</b> {summary.get('wins', 0)}
<b>Losses:</b> {summary.get('losses', 0)}
<b>P&L:</b> ₹{summary.get('total_pnl', 0):,.2f}
<b>Win Rate:</b> {summary.get('win_rate', 0):.1f}%
"""
        self.send_message(message)
    
    def send_alert(self, title: str, message_text: str):
        """Send alert message"""
        message = f"🚨 <b>{title}</b>\n\n{message_text}"
        self.send_message(message)
    
    def disconnect(self):
        """Disconnect from Telegram"""
        self.connected = False
        self.logger.info("Disconnected from Telegram")


def run_test():
    """Test agent service"""
    print("Testing Agent Service (Telegram)")
    print("=" * 50)
    
    service = AgentService()
    
    if service.connect():
        print("✅ Connected to Telegram")
        
        # Send test message
        if service.send_message("🤖 Trading Bot Test Message"):
            print("✅ Test message sent")
        
        # Send sample trade notification
        service.send_trade_notification("BUY", "SBIN", 750.50, 100)
        
        service.disconnect()
        print("\n✅ Test completed")
    else:
        print("❌ Connection failed")
        print("Note: Make sure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set in .env")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        run_test()
    else:
        print("Agent Service (Telegram Integration)")
        print("Run with 'test' argument to test: python agent_service.py test")
